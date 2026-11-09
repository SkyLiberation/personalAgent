"""Conversation model actions over the provider-neutral model Port.

The capability projection remains the visibility owner. This module materializes
that already-filtered projection as exact provider actions and decodes selected
wire actions back into existing Application proposals. It does not authorize or
execute anything.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from functools import partial
import json
import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from personal_agent.application.artifacts.models import CreateArtifact
from personal_agent.capabilities.contracts.model import (
    ModelActionDefinition,
    ModelActionInvocation,
    ModelActionKind,
    StructuredOutputFailure,
    StructuredModelResponse,
    StructuredOutputFailureCode,
)
from personal_agent.kernel.contracts.resource import ResourceRef
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
)
from .goal_models import (
    AnalysisGoal, GOAL_PENDING_ACTION_REJECTED, GoalMaintenanceInvocation,
    GoalReadInvocation, ReadCurrentGoalArguments, RetainGoalArguments, SubmitGoalDraftArguments,
)
from .tool_requests import (
    CREATE_ARTIFACT_ACTION,
    PATCH_ARTIFACT_ACTION,
    ArtifactPatchArguments,
    decode_artifact_write_arguments,
)

_WORKING_PLAN_TARGET = "working_plan"
CLARIFICATION_TOOL = "control_request_clarification"
TEST_MODE_DISABLED_TOOLS = frozenset({CLARIFICATION_TOOL})
_SAFE_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_RUNTIME_FIELD_NAMES = frozenset(
    {
        "action_id",
        "agent_id",
        "arguments",
        "kind",
    }
)


def goal_action_definition(prompts: PromptCatalog, *, verification_enabled: bool = True,
                           has_goal: bool = False, draft_refs: tuple[ResourceRef, ...] = ()) -> ModelActionDefinition:
    name = "conversation.goal.submit_description" if has_goal else "conversation.goal.description"
    schema = (SubmitGoalDraftArguments if has_goal else AnalysisGoal).model_json_schema()
    if has_goal and draft_refs:
        schema["properties"]["resource_id"]["enum"] = [ref.resource_id for ref in draft_refs]
    return ModelActionDefinition(name="maintain_goal", kind="maintain_goal",
        target_name="submit_goal_draft" if has_goal else "maintain_goal",
        description=prompts.get(name if verification_enabled else name + "_unverified").template,
        input_schema=schema, strict=False)


def goal_retain_action_definition(prompts: PromptCatalog, *, verification_enabled: bool = True) -> ModelActionDefinition:
    return ModelActionDefinition(name="retain_goal", kind="maintain_goal", target_name="retain_goal",
        description=prompts.get("conversation.goal.retain_description" if verification_enabled
                                else "conversation.goal.retain_description_unverified").template,
        input_schema=RetainGoalArguments.model_json_schema(), strict=False)


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


def _working_plan_action_schema() -> dict[str, Any]:
    schema = deepcopy(WorkingPlanProposal.model_json_schema())
    schema["properties"]["wait_for_user"] = {"type": "boolean", "default": False}
    # Optional business fields keep their declared defaults; Runtime does not
    # infer waiting intent or new step identities from omitted values.
    return schema


def _artifact_write_definitions(prompts: PromptCatalog) -> tuple[ModelActionDefinition, ...]:
    return (
        ModelActionDefinition(
            name=CREATE_ARTIFACT_ACTION,
            kind="tool",
            target_name="write_artifact",
            description=prompts.get("artifact.create_action.description").template,
            input_schema=_schema_without_fields(CreateArtifact.model_json_schema(), frozenset({"operation"})),
        ),
        ModelActionDefinition(
            name=PATCH_ARTIFACT_ACTION,
            kind="tool",
            target_name="write_artifact",
            description=prompts.get("artifact.patch_action.description").template,
            input_schema=strictify_schema(ArtifactPatchArguments.model_json_schema()),
        ),
    )


def build_model_action_definitions(
    capabilities: EffectiveCapabilities,
    *,
    experiment_run: bool = False,
    answer_actions: tuple[ModelActionDefinition, ...] = (),
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> tuple[ModelActionDefinition, ...]:
    """Project visible business operations and typed control actions."""
    definitions: list[ModelActionDefinition] = []
    for capability in capabilities.tools:
        if capability.name == "write_artifact":
            definitions.extend(_artifact_write_definitions(prompts))
            continue
        definitions.append(
            ModelActionDefinition(
                name=_wire_name("tool", capability.name),
                kind="tool",
                target_name=capability.name,
                description=prompts.render(
                    "conversation.model_action.tool_description", description=prompts.localize_metadata(capability.description),
                ),
                input_schema=(strictify_schema(capability.input_schema)
                              if capability.strict else deepcopy(capability.input_schema)),
                strict=capability.strict,
            )
        )
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
            input_schema=_working_plan_action_schema(),
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


def model_visible_capability_policy_json(
    capabilities: EffectiveCapabilities,
    *,
    definitions: tuple[ModelActionDefinition, ...] | None = None,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> str:
    """Serialize policy metadata without duplicating action descriptions or schemas."""
    current = (
        definitions
        if definitions is not None
        else build_model_action_definitions(capabilities, prompts=prompts)
    )
    agent_names = {item.target_name: item.name for item in current if item.kind == "agent"}
    tools = {item.name: item for item in capabilities.tools}
    tool_policies = []
    for action in current:
        if action.kind != "tool":
            continue
        tool = tools[action.target_name]
        tool_policies.append({
            "name": action.name,
            "capability_id": tool.name,
            "read_only": tool.read_only,
            "planning_safe": tool.planning_safe,
            "safely_retryable": tool.safely_retryable,
            "emits_verified_artifact": tool.emits_verified_artifact,
        })
    return json.dumps(
        {
            "tools": tool_policies,
            "agents": [
                {
                    "name": agent_names[item.agent_id],
                    "agent_id": item.agent_id,
                    "task_types": item.task_types,
                    "allowed_operations": item.allowed_operations,
                }
                for item in capabilities.agents
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


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
    """Locate invalid fields inside a nullable value without choosing a union branch."""
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


def _wire_payload(
    invocation: ModelActionInvocation,
    definition: ModelActionDefinition,
    *,
    prompts: PromptCatalog,
    reveal_invalid_action_field_names: bool,
) -> dict[str, Any]:
    errors = tuple(
        detail
        for error in Draft202012Validator(definition.input_schema).iter_errors(invocation.arguments)
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
    return invocation.arguments


def decode_model_action_invocations(
    invocations: tuple[ModelActionInvocation, ...],
    definitions: tuple[ModelActionDefinition, ...],
    *,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
    reveal_invalid_action_field_names: bool = False,
) -> ContinueTurnProposal | AnswerResultInvocation | ClarificationInvocation:
    """Decode provider actions without authorizing, repairing, or executing them."""
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

    unknown_names = [item.name for item in invocations if item.name not in by_name]
    if unknown_names:
        raise StructuredOutputFailure(
            "agent_interaction_turn",
            f"unknown model action {unknown_names[0]!r}",
            reason_code="provider_action_unknown",
            action_name=unknown_names[0],
        )
    clarification = next((item for item in invocations if by_name[item.name].kind == "request_clarification"), None)
    if clarification is not None and len(invocations) != 1:
        raise _payload_failure(action_name=clarification.name, action_kind="request_clarification",
            reason="clarification must be submitted alone; the batch was not executed",
            field_paths=(), error_types=())
    answer_calls = [item for item in invocations if by_name[item.name].kind == "answer_result"]
    goal_calls = [item for item in invocations if by_name[item.name].kind in ("maintain_goal", "read_current_goal")]
    if goal_calls and len(invocations) != 1:
        raise StructuredOutputFailure(
            "agent_interaction_turn", "goal operations require an exclusive invocation; the batch was not executed",
            reason_code="provider_action_goal_payload_invalid", action_name=goal_calls[0].name,
            action_kind=by_name[goal_calls[0].name].kind)
    if answer_calls and len(invocations) != 1:
        raise StructuredOutputFailure(
            "agent_interaction_turn", "提交、修订和研究操作必须独占本轮；整批动作未执行。",
            reason_code="provider_action_answer_result_payload_invalid", action_kind="answer_result",
        )
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
                if definition.target_name == "retain_goal":
                    RetainGoalArguments.model_validate(payload)
                    goal = None
                elif definition.target_name == "submit_goal_draft":
                    goal = SubmitGoalDraftArguments.model_validate(payload)
                else:
                    goal = AnalysisGoal.model_validate(payload)
                return ContinueTurnProposal(goal_maintenance=GoalMaintenanceInvocation(
                    call_id=invocation.call_id, arguments=goal))
            if definition.kind == "read_current_goal":
                return ContinueTurnProposal(goal_read=GoalReadInvocation(
                    call_id=invocation.call_id, arguments=ReadCurrentGoalArguments.model_validate(payload)))
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
                if definition.target_name == "write_artifact":
                    payload = decode_artifact_write_arguments(definition.name, payload).model_dump(mode="json")
                actions.append(
                    ToolCallProposal(
                        action_id=invocation.call_id,
                        tool_name=definition.target_name,
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
    )


__all__ = [
    "build_model_action_definitions",
    "decode_model_action_invocations",
    "model_visible_capability_policy_json",
]


def provider_action_feedback(
    error: StructuredOutputFailure, response: StructuredModelResponse, *, prompts: PromptCatalog,
    goal_maintenance_actions: tuple[str, ...] | None = None,
) -> DecisionFeedback:
    read_error = error.action_kind == "read_current_goal" or error.action_name == "read_current_goal"
    retain_error = error.action_name == "retain_goal"
    goal_error = read_error or error.action_kind == "maintain_goal" or error.action_name == "maintain_goal"
    message = prompts.get("conversation.action_protocol_rejected").template
    repair = prompts.get("conversation.action_protocol_repair").template
    reason_code = error.reason_code
    if error.reason_code == "provider_action_unknown" and error.action_name:
        message = prompts.render("conversation.action_unavailable", action_name=error.action_name)
        if goal_maintenance_actions is not None:
            reason_code = GOAL_PENDING_ACTION_REJECTED
            repair = prompts.render("conversation.goal.pending_action_repair",
                                    actions=", ".join(goal_maintenance_actions))
    elif goal_error:
        message = prompts.render("conversation.goal.rejected", reason_code=error.reason_code,
            details_json=json.dumps({"field_paths": error.field_paths, "error_types": error.error_types}))
        repair = prompts.get("conversation.goal.read_repair" if read_error else
                             "conversation.goal.retain_repair" if retain_error else "conversation.goal.repair").template
    elif error.action_kind == "request_clarification":
        repair = prompts.get("conversation.clarification.repair").template
    if error.repair_hints:
        remaining_repair = (repair,) if goal_error or len(error.repair_hints) < len(error.field_paths) else ()
        repair = "\n".join((*error.repair_hints, *remaining_repair))
    return DecisionFeedback(
        action_id="provider_action_protocol",
        action_name=error.action_name or "provider_action_protocol",
        reason_code=reason_code,
        action_diagnostics=tuple(
            ActionProtocolDiagnostic(field_path=path, error_type=kind)
            for path, kind in zip(error.field_paths, error.error_types, strict=True)
        ),
        rejected_action_invocations=response.action_invocations,
        message=message,
        repairable_fields=("action_calls",),
        immutable_fields=("messages", "inputs"),
        required_repair=repair,
    )
