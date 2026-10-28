"""Conversation model actions over the provider-neutral model Port.

The capability projection remains the visibility owner. This module materializes
that already-filtered projection as exact provider actions and decodes selected
wire actions back into existing Application proposals. It does not authorize or
execute anything.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from personal_agent.capabilities.contracts.model import (
    ModelActionDefinition,
    ModelActionInvocation,
    ModelActionKind,
    StructuredOutputFailure,
    StructuredOutputFailureCode,
)
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
from personal_agent.kernel.llm_schemas import model_tool_wire_name, strictify_schema

from .models import (
    AgentDelegationProposal,
    ContinueTurnProposal,
    AnswerResultInvocation,
    EffectiveCapabilities,
    ToolCallProposal,
    WorkingPlanProposal,
)

_WORKING_PLAN_TARGET = "working_plan"
_SAFE_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_RUNTIME_FIELD_NAMES = frozenset(
    {
        "action_id",
        "agent_id",
        "arguments",
        "kind",
    }
)


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


def build_model_action_definitions(
    capabilities: EffectiveCapabilities,
    *,
    experiment_run: bool = False,
    answer_actions: tuple[ModelActionDefinition, ...] = (),
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> tuple[ModelActionDefinition, ...]:
    """Project each visible capability exactly once plus typed control actions."""
    definitions: list[ModelActionDefinition] = []
    for capability in capabilities.tools:
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
    names = {(item.kind, item.target_name): item.name for item in current}
    return json.dumps(
        {
            "tools": [
                {
                    "name": names[("tool", item.name)],
                    "capability_id": item.name,
                    "read_only": item.read_only,
                    "planning_safe": item.planning_safe,
                    "safely_retryable": item.safely_retryable,
                    "emits_verified_artifact": item.emits_verified_artifact,
                }
                for item in capabilities.tools
            ],
            "agents": [
                {
                    "name": names[("agent", item.agent_id)],
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
) -> StructuredOutputFailure:
    return StructuredOutputFailure(
        "agent_interaction_turn",
        reason,
        reason_code=_payload_failure_code(action_kind),
        action_name=action_name,
        action_kind=action_kind,
        field_paths=field_paths,
        error_types=error_types,
    )


def _wire_payload(
    invocation: ModelActionInvocation,
    definition: ModelActionDefinition,
    *,
    reveal_invalid_action_field_names: bool,
) -> dict[str, Any]:
    errors = tuple(
        Draft202012Validator(definition.input_schema).iter_errors(invocation.arguments)
    )
    if errors:
        declared = _declared_field_names(definition.input_schema)
        diagnostics: list[tuple[str, str]] = []
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
                    _field_path(
                        missing_location,
                        declared_fields=declared,
                        reveal_invalid_action_field_names=reveal_invalid_action_field_names,
                    ),
                    f"schema_{error.validator}",
                )
                if error.validator == "required":
                    if diagnostic in required_diagnostics:
                        continue
                    required_diagnostics.add(diagnostic)
                diagnostics.append(diagnostic)
        raise _payload_failure(
            action_name=invocation.name,
            action_kind=definition.kind,
            reason="action payload does not match its declared wire schema",
            field_paths=tuple(path for path, _ in diagnostics),
            error_types=tuple(kind for _, kind in diagnostics),
        )
    return invocation.arguments


def decode_model_action_invocations(
    invocations: tuple[ModelActionInvocation, ...],
    definitions: tuple[ModelActionDefinition, ...],
    *,
    reveal_invalid_action_field_names: bool = False,
) -> ContinueTurnProposal | AnswerResultInvocation:
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
    answer_calls = [item for item in invocations if by_name[item.name].kind == "answer_result"]
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
            reveal_invalid_action_field_names=reveal_invalid_action_field_names,
        )
        try:
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
