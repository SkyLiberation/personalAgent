"""Conversation model actions over the provider-neutral model Port.

The capability projection remains the visibility owner. This module materializes
that already-filtered projection as exact provider actions and decodes selected
wire actions back into existing Application proposals. It does not authorize or
execute anything.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
import json
import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.validators import validator_for
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from personal_agent.application.artifacts.models import CreateArtifact
from personal_agent.application.bash_execution.models import BASH_TEMP_DIR, BashArgs, BashShellArgs
from personal_agent.application.bash_execution.workspace_edit import workspace_edit_command, workspace_read_command
from personal_agent.application.text_edit import LiteralTextEdit
from personal_agent.capabilities.contracts.model import (
    ModelActionDefinition,
    ModelActionInvocation,
    ModelActionKind,
    StructuredOutputFailure,
    StructuredOutputFailureCode,
)
from personal_agent.kernel.decimal_integer import read_decimal_integer
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
from personal_agent.kernel.llm_schemas import model_tool_wire_name, strictify_schema

from .models import (
    AgentDelegationProposal,
    ActionProtocolDiagnostic,
    ClarificationInvocation,
    DecisionFeedback,
    ContinueTurnProposal,
    AnswerResultInvocation,
    EffectiveCapabilities,
    RequestClarificationArguments,
    ToolCallProposal,
    WorkingPlanProposal,
    WorkingPlanStepProposal,
)
from .goal_models import (
    SUBMIT_GOAL_PATCH, GoalMaintenanceInvocation, GoalPatchProposal,
    GoalReadInvocation, ReadCurrentGoalArguments,
)
from .tool_requests import (
    CREATE_ARTIFACT_ACTION,
    EDIT_ACTION,
    READ_FILE_ACTION,
    WriteArtifactArgs,
    decode_edit_arguments,
)
from .file_reading import ReadFileArguments

_WORKING_PLAN_TARGET = "working_plan"
CLARIFICATION_TOOL = "control_request_clarification"
TEST_MODE_DISABLED_TOOLS = frozenset({CLARIFICATION_TOOL})
_MODEL_INTEGER_MAX_DIGITS = 18
_SAFE_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_RUNTIME_FIELD_NAMES = frozenset(
    {
        "action_id",
        "agent_id",
        "arguments",
        "kind",
    }
)


def decode_bash_call(function: dict[str, str], *, prompts: PromptCatalog) -> BashArgs:
    """Reconstruct a rejected Bash request from its original native call."""
    if function["name"] == EDIT_ACTION:
        edit = LiteralTextEdit.model_validate_json(function["arguments"])
        return workspace_edit_command(edit, prompts=prompts)
    if function["name"] == READ_FILE_ACTION:
        read = ReadFileArguments.model_validate_json(function["arguments"])
        return workspace_read_command(**read.model_dump(), prompts=prompts)
    return BashArgs.model_validate_json(function["arguments"], context=prompts)


def goal_action_definition(prompts: PromptCatalog, *, verification_enabled: bool = True) -> ModelActionDefinition:
    acceptance = prompts.get(
        "conversation.goal.admission.verified" if verification_enabled else "conversation.goal.admission.deterministic"
    ).template
    return ModelActionDefinition(name=SUBMIT_GOAL_PATCH, kind="maintain_goal",
        target_name="maintain_goal",
        description=prompts.render("conversation.goal.description", acceptance=acceptance),
        input_schema=GoalPatchProposal.tool_schema(), strict=False)


def goal_read_action_definition(prompts: PromptCatalog) -> ModelActionDefinition:
    return ModelActionDefinition(name="read_current_goal", kind="read_current_goal", target_name="read_current_goal",
        description=prompts.get("conversation.goal.read_description").template,
        input_schema=ReadCurrentGoalArguments.model_json_schema(), strict=False)


def project_test_mode_tools(definitions: tuple[ModelActionDefinition, ...], *,
                            enabled: bool) -> tuple[ModelActionDefinition, ...]:
    if not enabled:
        return definitions
    return tuple(action for action in definitions if action.name not in TEST_MODE_DISABLED_TOOLS)


def _wire_name(prefix: str, target_name: str) -> str:
    return model_tool_wire_name(f"{prefix}_{target_name}")


def _schema_without_fields(
    schema: dict[str, Any],
    excluded: frozenset[str],
) -> dict[str, Any]:
    projected = deepcopy(schema)
    properties = projected.get("properties")
    if isinstance(properties, dict):
        for field_name in excluded:
            properties.pop(field_name, None)
    required = projected.get("required")
    if isinstance(required, list):
        projected["required"] = [
            field_name for field_name in required if field_name not in excluded
        ]
    return strictify_schema(projected)


def _working_plan_action_schema(*, bind_goal_items: bool) -> dict[str, Any]:
    schema = deepcopy(WorkingPlanProposal.model_json_schema())
    if not bind_goal_items:
        step_schema = schema["$defs"][WorkingPlanStepProposal.__name__]
        del step_schema["properties"]["goal_item_ids"]
    schema["properties"]["wait_for_user"] = {
        "type": "boolean", "default": False,
        "description": "Return the plan to the user and pause for review before executing business actions.",
    }
    # Optional business fields keep their declared defaults; Runtime does not
    # infer waiting intent or new step identities from omitted values.
    return schema


def _create_artifact_definition(prompts: PromptCatalog) -> ModelActionDefinition:
    return ModelActionDefinition(
        name=CREATE_ARTIFACT_ACTION,
        kind="tool",
        target_name="write_artifact",
        description=prompts.get("artifact.create_action.description").template,
        input_schema=_schema_without_fields(CreateArtifact.model_json_schema(), frozenset({"operation"})),
    )


def _edit_definition(
    *, artifact: bool, workspace: bool, prompts: PromptCatalog,
) -> ModelActionDefinition:
    schema = LiteralTextEdit.model_json_schema()
    roots = []
    if artifact:
        roots.append("artifacts/")
    if workspace:
        roots.append(f"{BASH_TEMP_DIR}/")
    schema["properties"]["file_path"]["pattern"] = (
        f"^(?:{'|'.join(re.escape(root) for root in roots)})[^\\x00-\\x1f]+$"
    )
    for name, field in schema["properties"].items():
        field["description"] = prompts.get(f"artifact.edit_action.field.{name}").template
    description = prompts.render("artifact.edit_action.description", paths=", ".join(roots))
    if workspace:
        description += " " + prompts.get("artifact.edit_action.workspace_guard").template
    return ModelActionDefinition(
        name=EDIT_ACTION,
        kind="tool",
        target_name="write_artifact" if artifact else "bash",
        description=description,
        input_schema=schema,
        strict=False,
    )


def build_model_action_definitions(
    capabilities: EffectiveCapabilities,
    *,
    experiment_run: bool = False,
    answer_actions: tuple[ModelActionDefinition, ...] = (),
    task_workspace: bool = False,
    bind_goal_items: bool = True,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> tuple[ModelActionDefinition, ...]:
    """Project visible business operations and typed control actions."""
    definitions: list[ModelActionDefinition] = []
    names = {capability.name for capability in capabilities.tools}
    draft_edit = "write_artifact" in names
    workspace_edit = task_workspace and {"bash", "read_file"} <= names
    for capability in capabilities.tools:
        if capability.name == "write_artifact":
            definitions.append(_create_artifact_definition(prompts))
            continue
        schema = (BashShellArgs.model_json_schema() if capability.name == "bash"
                  else deepcopy(capability.input_schema))
        description = prompts.localize_metadata(capability.description)
        if capability.name == "read_file":
            if workspace_edit:
                description += " " + prompts.get("artifact.edit_action.workspace_read").template
            else:
                schema["properties"]["file_path"]["pattern"] = rf"^(?!{BASH_TEMP_DIR}/)"
        definitions.append(
            ModelActionDefinition(
                name=_wire_name("tool", capability.name),
                kind="tool",
                target_name=capability.name,
                description=prompts.render(
                    "conversation.model_action.tool_description", description=description,
                ),
                input_schema=strictify_schema(schema) if capability.strict else schema,
                strict=capability.strict,
                model_integer_string_fields=capability.model_integer_string_fields,
            )
        )
    if draft_edit or workspace_edit:
        definitions.append(_edit_definition(artifact=draft_edit, workspace=workspace_edit, prompts=prompts))
    for capability in capabilities.agents:
        definitions.append(
            ModelActionDefinition(
                name=_wire_name("agent", capability.agent_id),
                kind="agent",
                target_name=capability.agent_id,
                description=prompts.render(
                    "conversation.model_action.agent_description", description=prompts.localize_metadata(capability.description),
                ),
                input_schema=_agent_action_schema(
                    AgentDelegationProposal.model_json_schema(),
                ),
            )
        )
    definitions.append(
        ModelActionDefinition(
            name=_wire_name("control", _WORKING_PLAN_TARGET),
            kind="working_plan",
            target_name=_WORKING_PLAN_TARGET,
            description=prompts.get("conversation.working_plan.description").render(),
            input_schema=_working_plan_action_schema(bind_goal_items=bind_goal_items),
            strict=False,
        )
    )
    definitions.append(ModelActionDefinition(name=CLARIFICATION_TOOL, kind="request_clarification",
        target_name="request_clarification", description=prompts.get("conversation.clarification.description").template,
        input_schema=RequestClarificationArguments.model_json_schema(), strict=False))
    definitions.extend(answer_actions)
    names = [definition.name for definition in definitions]
    if len(names) != len(set(names)):
        raise ValueError("model action wire-name collision")
    return tuple(definitions)


def _agent_action_schema(
    schema: dict[str, Any],
) -> dict[str, Any]:
    projected = _schema_without_fields(
        schema,
        frozenset({"kind", "action_id", "agent_id"}),
    )
    return projected


def model_visible_capability_policy(
    capabilities: EffectiveCapabilities,
    *,
    definitions: tuple[ModelActionDefinition, ...] | None = None,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> str:
    """Describe the constraints that affect selection of the declared actions."""
    current = definitions if definitions is not None else build_model_action_definitions(capabilities, prompts=prompts)
    agents = {item.agent_id: item for item in capabilities.agents}
    tools = {item.name: item for item in capabilities.tools}
    rules = []
    for action in current:
        if action.kind == "agent":
            agent = agents[action.target_name]
            rules.append(prompts.render("conversation.context.agent_policy", action_name=action.name,
                task_types=", ".join(agent.task_types), operations=", ".join(agent.allowed_operations)))
        elif action.kind == "tool":
            tool = tools[action.target_name]
            notes = [
                prompts.get(f"conversation.context.policy.{key}").template
                for key, applies in (
                    ("planning_safe", tool.planning_safe), ("may_write", not tool.read_only),
                    ("no_safe_retry", not tool.safely_retryable), ("verified_artifact", tool.emits_verified_artifact),
                ) if applies
            ]
            if notes:
                rules.append(prompts.render("conversation.context.tool_policy", action_name=action.name, notes=" · ".join(notes)))
    return "\n".join((prompts.get("conversation.context.declared_tools").template, *rules))


def _definition_map(
    definitions: tuple[ModelActionDefinition, ...],
) -> dict[str, ModelActionDefinition]:
    mapping = {definition.name: definition for definition in definitions}
    if len(mapping) != len(definitions):
        raise StructuredOutputFailure(
            "agent_interaction_turn",
            "model action definitions contain duplicate wire names",
            reason_code="provider_action_definition_invalid",
        )
    return mapping


def _payload_failure_code(
    action_kind: ModelActionKind,
) -> StructuredOutputFailureCode:
    return {
        "working_plan": "provider_action_working_plan_payload_invalid",
        "tool": "provider_action_tool_payload_invalid",
        "agent": "provider_action_agent_payload_invalid",
        "answer_result": "provider_action_answer_result_payload_invalid",
        "request_clarification": "provider_action_clarification_payload_invalid",
        "maintain_goal": "provider_action_goal_payload_invalid",
        "read_current_goal": "provider_action_goal_payload_invalid",
    }[action_kind]


def _declared_field_names(schema: dict[str, Any]) -> frozenset[str]:
    names = set(_RUNTIME_FIELD_NAMES)

    def collect(value: object) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                names.update(str(name) for name in properties)
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    collect(schema)
    return frozenset(names)


def _field_path(
    location: tuple[object, ...],
    *,
    declared_fields: frozenset[str],
    reveal_invalid_action_field_names: bool,
) -> str:
    path = "$"
    for part in location:
        if isinstance(part, int) and part >= 0:
            path += f"[{part}]"
        elif (
            isinstance(part, str)
            and _SAFE_FIELD_NAME.fullmatch(part)
            and (part in declared_fields or reveal_invalid_action_field_names)
        ):
            path += f".{part}"
        else:
            path += ".<unexpected>"
    return path


def _validation_diagnostics(
    error: ValidationError,
    *,
    definition: ModelActionDefinition,
    prefix: tuple[object, ...] = (),
    reveal_invalid_action_field_names: bool,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    declared_fields = _declared_field_names(definition.input_schema)
    field_paths: list[str] = []
    error_types: list[str] = []
    for issue in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = prefix + tuple(issue.get("loc", ()))
        field_paths.append(
            _field_path(
                location,
                declared_fields=declared_fields,
                reveal_invalid_action_field_names=(reveal_invalid_action_field_names),
            )
        )
        error_types.append(str(issue.get("type", "validation_error")))
    return tuple(field_paths), tuple(error_types)


def _payload_failure(
    *,
    action_name: str,
    action_kind: ModelActionKind,
    reason: str,
    field_paths: tuple[str, ...],
    error_types: tuple[str, ...],
    repair_hints: tuple[str, ...] = (),
) -> StructuredOutputFailure:
    return StructuredOutputFailure(
        "agent_interaction_turn",
        reason,
        reason_code=_payload_failure_code(action_kind),
        action_name=action_name,
        action_kind=action_kind,
        field_paths=field_paths,
        error_types=error_types,
        repair_hints=repair_hints,
    )


def _wire_schema_error_details(error: SchemaValidationError) -> tuple[SchemaValidationError, ...]:
    """Locate invalid fields for nullable values and explicitly selected union branches."""
    if error.validator == "oneOf" and isinstance(error.instance, dict):
        discriminator = error.schema.get("discriminator", {})
        tag = error.instance.get(discriminator.get("propertyName"))
        if isinstance(tag, str):
            reference = discriminator.get("mapping", {}).get(tag)
            if reference is not None:
                branch = next((index for index, schema in enumerate(error.validator_value)
                               if schema.get("$ref") == reference), None)
                if branch is not None:
                    details = tuple(detail for child in error.context if child.schema_path[0] == branch
                                    for detail in _wire_schema_error_details(child))
                    return details or (error,)
    alternatives = error.validator_value if error.validator == "anyOf" else ()
    if len(alternatives) != 2 or {"type": "null"} not in alternatives:
        return (error,)
    children = tuple(child for child in error.context
                     if not (child.validator == "type" and child.validator_value == "null"))
    return tuple(detail for child in children for detail in _wire_schema_error_details(child)) or (error,)


_JSON_TYPE_NAMES = {
    dict: "object",
    list: "array",
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    type(None): "null",
}


def _wire_type_repair(
    error: SchemaValidationError,
    field_path: str,
    *,
    describe_path: Callable[[tuple[object, ...]], str],
    prompts: PromptCatalog,
) -> str | None:
    if error.validator != "type":
        return None
    expected = error.validator_value
    actual = _JSON_TYPE_NAMES.get(type(error.instance))
    if actual is None:
        return None
    if expected == "integer":
        number = read_decimal_integer(error.instance, max_digits=_MODEL_INTEGER_MAX_DIGITS)
        if (
            number is not None
            and not {"$ref", "$dynamicRef", "allOf", "anyOf", "oneOf", "if", "not"}.intersection(error.schema)
            and Draft202012Validator(error.schema).is_valid(number)
        ):
            return prompts.render("conversation.action_integer_literal_repair", field_path=field_path,
                actual_value=json.dumps(error.instance), number=number)
    if expected == "array" and isinstance(error.instance, dict) and len(error.instance) == 1:
        member, value = next(iter(error.instance.items()))
        if isinstance(value, list):
            return prompts.render(
                "conversation.action_array_wrapper_repair",
                field_path=field_path,
                array_path=describe_path((*error.absolute_path, member)),
            )
    return prompts.render(
        "conversation.action_type_repair",
        field_path=field_path,
        expected=expected if isinstance(expected, str) else " / ".join(expected),
        actual=actual,
    )


def _read_tool_arguments(
    arguments: dict[str, Any], fields: tuple[str, ...],
) -> tuple[dict[str, Any], tuple[SchemaValidationError, ...]]:
    if not fields:
        return arguments, ()
    payload = dict(arguments)
    errors = []
    for field in fields:
        value = payload.get(field)
        number = read_decimal_integer(value, max_digits=_MODEL_INTEGER_MAX_DIGITS)
        if number is not None:
            payload[field] = number
        elif isinstance(value, float) and value.is_integer():
            # JSON Schema treats integral floats as integers. The opted-in reader
            # accepts the integer representation and the explicit string form.
            errors.append(SchemaValidationError(
                "tool argument requires an integer", validator="type",
                validator_value="integer", instance=value, path=(field,),
            ))
    return payload, tuple(errors)


def _wire_payload(
    invocation: ModelActionInvocation,
    definition: ModelActionDefinition,
    *,
    prompts: PromptCatalog,
    reveal_invalid_action_field_names: bool,
) -> dict[str, Any]:
    payload, reading_errors = _read_tool_arguments(invocation.arguments, definition.model_integer_string_fields)
    errors = reading_errors + tuple(
        detail
        for error in validator_for(definition.input_schema)(definition.input_schema).iter_errors(payload)
        for detail in _wire_schema_error_details(error)
    )
    if errors:
        describe_path = partial(
            _field_path,
            declared_fields=_declared_field_names(definition.input_schema),
            reveal_invalid_action_field_names=reveal_invalid_action_field_names,
        )
        diagnostics: list[tuple[str, str]] = []
        repair_hints: list[str] = []
        required_diagnostics: set[tuple[str, str]] = set()
        for error in errors:
            location = tuple(error.absolute_path)
            locations = (
                tuple(location + (name,) for name in error.validator_value
                      if name not in error.instance)
                if error.validator == "required" and isinstance(error.instance, dict)
                else (location,)
            )
            for missing_location in locations:
                diagnostic = (
                    describe_path(missing_location),
                    f"schema_{error.validator}",
                )
                if error.validator == "required":
                    if diagnostic in required_diagnostics:
                        continue
                    required_diagnostics.add(diagnostic)
                diagnostics.append(diagnostic)
                if hint := _wire_type_repair(error, diagnostic[0], describe_path=describe_path, prompts=prompts):
                    repair_hints.append(hint)
        raise _payload_failure(
            action_name=invocation.name,
            action_kind=definition.kind,
            reason="action payload does not match its declared wire schema",
            field_paths=tuple(path for path, _ in diagnostics),
            error_types=tuple(kind for _, kind in diagnostics),
            repair_hints=tuple(repair_hints),
        )
    return payload


def decode_model_action_invocations(
    invocations: tuple[ModelActionInvocation, ...],
    definitions: tuple[ModelActionDefinition, ...],
    *,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
    reveal_invalid_action_field_names: bool = False,
) -> ContinueTurnProposal | AnswerResultInvocation | ClarificationInvocation:
    """Read the declared wire representation and form proposals before admission."""
    if not invocations:
        raise StructuredOutputFailure(
            "agent_interaction_turn",
            "model returned no action invocation",
            reason_code="provider_action_missing",
        )
    by_name = _definition_map(definitions)
    if len({item.call_id for item in invocations}) != len(invocations):
        raise StructuredOutputFailure(
            "agent_interaction_turn",
            "model action invocations contain duplicate call IDs",
            reason_code="provider_action_call_id_duplicate",
        )

    if len(invocations) > 1:
        for kind in ("maintain_goal", "request_clarification", "answer_result"):
            exclusive = next((call for call in invocations
                              if call.name in by_name and by_name[call.name].kind == kind), None)
            if exclusive is not None:
                raise StructuredOutputFailure(
                    "agent_interaction_turn", "exclusive operation was mixed with other calls",
                    reason_code="provider_action_exclusive", action_name=exclusive.name, action_kind=kind,
                )
    unknown = next((item for item in invocations if item.name not in by_name), None)
    if unknown is not None:
        raise StructuredOutputFailure(
            "agent_interaction_turn",
            f"unknown model action {unknown.name!r}",
            reason_code="provider_action_unknown",
            action_name=unknown.name,
        )
    goal_read: GoalReadInvocation | None = None
    working_plan: WorkingPlanProposal | None = None
    wait_for_user = False
    working_plan_call_id = None
    actions: list[ToolCallProposal | AgentDelegationProposal] = []
    for invocation in invocations:
        definition = by_name[invocation.name]
        payload = _wire_payload(
            invocation,
            definition,
            prompts=prompts,
            reveal_invalid_action_field_names=reveal_invalid_action_field_names,
        )
        try:
            if definition.kind == "request_clarification":
                return ClarificationInvocation(call_id=invocation.call_id, **payload)
            if definition.kind == "maintain_goal":
                return ContinueTurnProposal(goal_maintenance=GoalMaintenanceInvocation(
                    call_id=invocation.call_id, arguments=GoalPatchProposal.model_validate(payload).to_patch()))
            if definition.kind == "read_current_goal":
                if goal_read is not None:
                    raise StructuredOutputFailure(
                        "agent_interaction_turn", "a model response may contain only one current-goal read",
                        reason_code="provider_action_goal_payload_invalid", action_name=invocation.name,
                        action_kind=definition.kind,
                        repair_hints=(prompts.get("conversation.goal.read_description").template,),
                    )
                goal_read = GoalReadInvocation(
                    call_id=invocation.call_id, arguments=ReadCurrentGoalArguments.model_validate(payload))
                continue
            if definition.kind == "answer_result":
                return AnswerResultInvocation(call_id=invocation.call_id,
                    operation=definition.target_name, arguments=payload)
            if definition.kind == "working_plan":
                if working_plan is not None:
                    raise StructuredOutputFailure(
                        "agent_interaction_turn",
                        "a model turn may contain at most one working-plan action",
                        reason_code="provider_action_multiple_working_plans",
                    )
                working_plan = WorkingPlanProposal.model_validate(
                    {
                        key: value
                        for key, value in payload.items()
                        if key != "wait_for_user"
                    }
                )
                working_plan_call_id = invocation.call_id
                wait_for_user = payload.get("wait_for_user", False)
                continue
            if definition.kind == "tool":
                target_name = definition.target_name
                if definition.name == EDIT_ACTION:
                    target_name, request = decode_edit_arguments(payload, prompts=prompts)
                    payload = request.model_dump(mode="json")
                elif definition.name == READ_FILE_ACTION and payload["file_path"].startswith(f"{BASH_TEMP_DIR}/"):
                    read = ReadFileArguments.model_validate(payload)
                    target_name = "bash"
                    payload = workspace_read_command(**read.model_dump(), prompts=prompts).model_dump(mode="json")
                elif definition.name == CREATE_ARTIFACT_ACTION:
                    payload = WriteArtifactArgs(
                        request=CreateArtifact.model_validate({**payload, "operation": "create"}),
                    ).model_dump(mode="json")
                actions.append(
                    ToolCallProposal(
                        action_id=invocation.call_id,
                        tool_name=target_name,
                        arguments=payload,
                    )
                )
                continue
            if definition.kind == "agent":
                actions.append(
                    AgentDelegationProposal.model_validate(
                        {
                            **payload,
                            "kind": "agent_delegation",
                            "action_id": invocation.call_id,
                            "agent_id": definition.target_name,
                        }
                    )
                )
                continue
            raise StructuredOutputFailure(
                "agent_interaction_turn",
                f"unsupported model action kind {definition.kind!r}",
                reason_code="provider_action_definition_invalid",
            )
        except ValidationError as exc:
            field_paths, error_types = _validation_diagnostics(
                exc,
                definition=definition,
                prefix=(),
                reveal_invalid_action_field_names=reveal_invalid_action_field_names,
            )
            raise _payload_failure(
                action_name=invocation.name,
                action_kind=definition.kind,
                reason=f"invalid {definition.kind} action payload",
                field_paths=field_paths,
                error_types=error_types,
            ) from None

    return ContinueTurnProposal(
        actions=tuple(actions),
        working_plan=working_plan,
        wait_for_user=wait_for_user,
        working_plan_call_id=working_plan_call_id,
        goal_read=goal_read,
    )


__all__ = [
    "build_model_action_definitions",
    "decode_model_action_invocations",
    "model_visible_capability_policy",
]


@dataclass(frozen=True, slots=True)
class PartiallyDecodedToolBatch:
    """Original call order with one proposal or rejection for each read."""

    calls: tuple[ToolCallProposal | DecisionFeedback, ...]

    @property
    def proposal(self) -> ContinueTurnProposal:
        return ContinueTurnProposal(
            actions=tuple(call for call in self.calls if isinstance(call, ToolCallProposal))
        )


def partially_decode_tool_batch(
    error: StructuredOutputFailure,
    invocations: tuple[ModelActionInvocation, ...],
    definitions: tuple[ModelActionDefinition, ...],
    capabilities: EffectiveCapabilities,
    *,
    prompts: PromptCatalog,
    reveal_invalid_action_field_names: bool,
) -> PartiallyDecodedToolBatch | None:
    """Recover independent reads after the batch envelope has passed validation."""
    if error.reason_code != "provider_action_tool_payload_invalid" or len(invocations) < 2:
        return None
    by_name = _definition_map(definitions)
    safe_tools = {
        tool.name for tool in capabilities.tools
        if tool.read_only and tool.safely_retryable and tool.planning_safe
    }
    calls: list[ToolCallProposal | DecisionFeedback] = []
    for invocation in invocations:
        definition = by_name[invocation.name]
        if definition.kind != "tool" or definition.target_name not in safe_tools:
            return None
        file_path = invocation.arguments.get("file_path")
        if (invocation.name == READ_FILE_ACTION and isinstance(file_path, str)
                and file_path.startswith(f"{BASH_TEMP_DIR}/")):
            # This wire name can route to the separately governed Bash executor.
            return None
        try:
            decoded = decode_model_action_invocations(
                (invocation,), (definition,), prompts=prompts,
                reveal_invalid_action_field_names=reveal_invalid_action_field_names,
            )
        except StructuredOutputFailure as failure:
            if failure.reason_code != "provider_action_tool_payload_invalid":
                return None
            calls.append(provider_action_feedback(
                failure, (invocation,), prompts=prompts, available_actions=(),
                rejected_call_id=invocation.call_id,
            ))
            continue
        assert isinstance(decoded, ContinueTurnProposal)
        action = decoded.actions[0]
        if not isinstance(action, ToolCallProposal) or action.tool_name not in safe_tools:
            return None
        calls.append(action)
    if not any(isinstance(call, ToolCallProposal) for call in calls):
        return None
    return PartiallyDecodedToolBatch(tuple(calls))


def provider_action_feedback(
    error: StructuredOutputFailure, invocations: tuple[ModelActionInvocation, ...], *, prompts: PromptCatalog,
    available_actions: tuple[str, ...],
    rejected_call_id: str | None = None,
) -> DecisionFeedback:
    read_error = error.action_kind == "read_current_goal" or error.action_name == "read_current_goal"
    goal_error = read_error or error.action_kind == "maintain_goal" or error.action_name == SUBMIT_GOAL_PATCH
    message = prompts.get("conversation.action_protocol_rejected" if rejected_call_id is None
                          else "conversation.tool_arguments_rejected").template
    repair = prompts.get("conversation.action_protocol_repair").template
    if error.reason_code == "provider_action_exclusive":
        message = prompts.get("conversation.action_exclusive_rejected").template
        repair = prompts.render("conversation.action_exclusive_repair", action_name=error.action_name)
    elif error.reason_code == "provider_action_unknown" and error.action_name:
        message = prompts.render("conversation.action_unavailable", action_name=error.action_name)
        if available_actions:
            repair = prompts.render("conversation.action_available_repair", actions=", ".join(available_actions))
    elif goal_error:
        message = prompts.render("conversation.goal.rejected", reason_code=error.reason_code,
            details_json=json.dumps({"field_paths": error.field_paths, "error_types": error.error_types}))
        repair = prompts.get("conversation.goal.read_repair" if read_error else "conversation.goal.repair").template
    elif error.action_kind == "request_clarification":
        repair = prompts.get("conversation.clarification.repair").template
    if error.repair_hints:
        remaining_repair = (repair,) if goal_error or len(error.repair_hints) < len(error.field_paths) else ()
        repair = "\n".join((*error.repair_hints, *remaining_repair))
    return DecisionFeedback(
        action_id=rejected_call_id if rejected_call_id is not None else "provider_action_protocol",
        action_name=error.action_name or "provider_action_protocol",
        reason_code=error.reason_code,
        action_diagnostics=tuple(
            ActionProtocolDiagnostic(field_path=path, error_type=kind)
            for path, kind in zip(error.field_paths, error.error_types, strict=True)
        ),
        rejected_action_invocations=invocations,
        message=message,
        repairable_fields=("action_calls",),
        immutable_fields=("messages", "inputs"),
        required_repair=repair,
    )
