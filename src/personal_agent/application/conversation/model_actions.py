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

from pydantic import ValidationError

from personal_agent.capabilities.contracts.model import (
    ModelActionDefinition,
    ModelActionInvocation,
    ModelActionKind,
    StructuredOutputFailure,
    StructuredOutputFailureCode,
)
from personal_agent.kernel.llm_schemas import model_tool_wire_name, strictify_schema

from .models import (
    AgentDelegationProposal,
    ContinueTurnProposal,
    EffectiveCapabilities,
    ToolCallProposal,
    WorkingPlanProposal,
)

_WORKING_PLAN_TARGET = "working_plan"
_FINALIZE_TARGET = "prepare_final"
_SAFE_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_RUNTIME_FIELD_NAMES = frozenset({
    "action_id",
    "agent_id",
    "arguments",
    "kind",
})


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


def _wrapped_schema(
    field_name: str,
    nested_schema: dict[str, Any],
    other_properties: dict[str, Any],
) -> dict[str, Any]:
    """Embed one Pydantic schema while keeping its root-local references valid."""
    nested = deepcopy(nested_schema)
    definitions = nested.pop("$defs", None)
    legacy_definitions = nested.pop("definitions", None)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            field_name: nested,
            **deepcopy(other_properties),
        },
    }
    if isinstance(definitions, dict):
        schema["$defs"] = definitions
    if isinstance(legacy_definitions, dict):
        schema["definitions"] = legacy_definitions
    return strictify_schema(schema)


def _tool_action_schema(
    input_schema: dict[str, Any],
) -> dict[str, Any]:
    return _wrapped_schema(
        "arguments",
        input_schema,
        {},
    )


def _working_plan_action_schema() -> dict[str, Any]:
    schema = deepcopy(WorkingPlanProposal.model_json_schema())
    schema["properties"].update({
        "wait_for_user": {"type": "boolean"},
        "message": {"type": "string", "maxLength": 4_000},
    })
    return strictify_schema(schema)


def _finalize_action_schema() -> dict[str, Any]:
    return strictify_schema({"type": "object", "properties": {}})


def build_model_action_definitions(
    capabilities: EffectiveCapabilities,
) -> tuple[ModelActionDefinition, ...]:
    """Project each visible capability exactly once plus typed control actions."""
    definitions: list[ModelActionDefinition] = []
    for capability in capabilities.tools:
        definitions.append(
            ModelActionDefinition(
                name=_wire_name("tool", capability.name),
                kind="tool",
                target_name=capability.name,
                description=(
                    f"Canonical capability: {capability.name}. {capability.description} "
                    "Pass only capability parameters inside arguments; working-plan "
                    "state is controlled separately."
                ),
                input_schema=_tool_action_schema(capability.input_schema),
            )
        )
    for capability in capabilities.agents:
        definitions.append(
            ModelActionDefinition(
                name=_wire_name("agent", capability.agent_id),
                kind="agent",
                target_name=capability.agent_id,
                description=(
                    f"Delegate one bounded sub-goal to agent {capability.agent_id}. "
                    f"{capability.description}"
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
            description=(
                "Propose or revise the user-visible working plan. This is a control "
                "action, not an executed tool."
            ),
            input_schema=_working_plan_action_schema(),
        )
    )
    definitions.append(
        ModelActionDefinition(
            name=_wire_name("control", _FINALIZE_TARGET),
            kind="finalize",
            target_name=_FINALIZE_TARGET,
            description=(
                "Request the exclusive typed FinalMessage phase after every "
                "compatible action in this response has completed. This control "
                "action carries no user-visible answer."
            ),
            input_schema=_finalize_action_schema(),
        )
    )
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
) -> str:
    """Serialize policy metadata without duplicating action descriptions or schemas."""
    return json.dumps(
        {
            "tools": [
                {
                    "name": item.name,
                    "read_only": item.read_only,
                    "planning_safe": item.planning_safe,
                    "safely_retryable": item.safely_retryable,
                    "emits_verified_artifact": item.emits_verified_artifact,
                }
                for item in capabilities.tools
            ],
            "agents": [
                {
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
        "finalize": "provider_action_finalize_payload_invalid",
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
            and (
                part in declared_fields
                or reveal_invalid_action_field_names
            )
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
                reveal_invalid_action_field_names=(
                    reveal_invalid_action_field_names
                ),
            )
        )
        error_types.append(str(issue.get("type", "validation_error")))
    return tuple(field_paths), tuple(error_types)


def _unexpected_field_paths(
    field_names: set[str],
    *,
    prefix: tuple[object, ...] = (),
    reveal_invalid_action_field_names: bool,
) -> tuple[str, ...]:
    return tuple(
        _field_path(
            prefix + (field_name,),
            declared_fields=frozenset(),
            reveal_invalid_action_field_names=(
                reveal_invalid_action_field_names
            ),
        )
        for field_name in sorted(field_names)
    )


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


def _reject_reserved_arguments(
    arguments: dict[str, Any],
    reserved: frozenset[str],
    *,
    action_name: str,
    action_kind: ModelActionKind,
) -> None:
    overlap = reserved.intersection(arguments)
    if overlap:
        field_paths = tuple(f"$.{name}" for name in sorted(overlap))
        raise _payload_failure(
            action_name=action_name,
            action_kind=action_kind,
            reason="model action asserted runtime-owned fields",
            field_paths=field_paths,
            error_types=("runtime_owned_field",) * len(field_paths),
        )


def decode_model_action_invocations(
    invocations: tuple[ModelActionInvocation, ...],
    definitions: tuple[ModelActionDefinition, ...],
    *,
    reveal_invalid_action_field_names: bool = False,
) -> ContinueTurnProposal:
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
        )
    working_plan: WorkingPlanProposal | None = None
    wait_for_user = False
    message = ""
    finalization_requested = False
    actions: list[ToolCallProposal | AgentDelegationProposal] = []
    for invocation in invocations:
        definition = by_name.get(invocation.name)
        if definition is None:
            raise StructuredOutputFailure(
                "agent_interaction_turn",
                f"unknown model action {invocation.name!r}",
                reason_code="provider_action_unknown",
            )
        try:
            if definition.kind == "finalize":
                if finalization_requested:
                    raise StructuredOutputFailure(
                        "agent_interaction_turn",
                        "a model turn may contain at most one finalization request",
                        reason_code="provider_action_definition_invalid",
                    )
                unexpected = set(invocation.arguments)
                if unexpected:
                    raise _payload_failure(
                        action_name=invocation.name,
                        action_kind="finalize",
                        reason="finalization request does not accept arguments",
                        field_paths=_unexpected_field_paths(
                            unexpected,
                            reveal_invalid_action_field_names=(
                                reveal_invalid_action_field_names
                            ),
                        ),
                        error_types=("extra_forbidden",) * len(unexpected),
                    )
                finalization_requested = True
                continue
            if definition.kind == "working_plan":
                if working_plan is not None:
                    raise StructuredOutputFailure(
                        "agent_interaction_turn",
                        "a model turn may contain at most one working-plan action",
                        reason_code="provider_action_multiple_working_plans",
                    )
                declared_fields = set(
                    definition.input_schema.get("properties", {})
                )
                unexpected = set(invocation.arguments).difference(declared_fields)
                if unexpected:
                    raise _payload_failure(
                        action_name=invocation.name,
                        action_kind="working_plan",
                        reason="working-plan action payload does not match its declared fields",
                        field_paths=_unexpected_field_paths(
                            unexpected,
                            reveal_invalid_action_field_names=(
                                reveal_invalid_action_field_names
                            ),
                        ),
                        error_types=("extra_forbidden",) * len(unexpected),
                    )
                plan_payload = {
                    key: value
                    for key, value in invocation.arguments.items()
                    if key not in {"wait_for_user", "message"}
                }
                try:
                    working_plan = WorkingPlanProposal.model_validate(plan_payload)
                except ValidationError as exc:
                    field_paths, error_types = _validation_diagnostics(
                        exc,
                        definition=definition,
                        reveal_invalid_action_field_names=(
                            reveal_invalid_action_field_names
                        ),
                    )
                    raise _payload_failure(
                        action_name=invocation.name,
                        action_kind="working_plan",
                        reason="invalid working-plan action payload",
                        field_paths=field_paths,
                        error_types=error_types,
                    ) from None
                wait_for_user = bool(invocation.arguments.get("wait_for_user", False))
                message = str(invocation.arguments.get("message", ""))
                continue
            if definition.kind == "tool":
                declared_fields = set(
                    definition.input_schema.get("properties", {})
                )
                unexpected = set(invocation.arguments).difference(declared_fields)
                tool_arguments = invocation.arguments.get("arguments")
                if unexpected or not isinstance(tool_arguments, dict):
                    arguments_present = "arguments" in invocation.arguments
                    field_paths = (
                        _unexpected_field_paths(
                            unexpected,
                            reveal_invalid_action_field_names=(
                                reveal_invalid_action_field_names
                            ),
                        )
                        + (() if isinstance(tool_arguments, dict) else ("$.arguments",))
                    )
                    error_types = (
                        ("extra_forbidden",) * len(unexpected)
                        + (
                            ()
                            if isinstance(tool_arguments, dict)
                            else (("dict_type",) if arguments_present else ("missing",))
                        )
                    )
                    raise _payload_failure(
                        action_name=invocation.name,
                        action_kind="tool",
                        reason="tool action payload does not match its wrapper",
                        field_paths=field_paths,
                        error_types=error_types,
                    )
                actions.append(
                    ToolCallProposal(
                        action_id=invocation.call_id,
                        tool_name=definition.target_name,
                        arguments=tool_arguments,
                    )
                )
                continue
            if definition.kind == "agent":
                _reject_reserved_arguments(
                    invocation.arguments,
                    frozenset({"kind", "action_id", "agent_id"}),
                    action_name=invocation.name,
                    action_kind="agent",
                )
                unexpected = set(invocation.arguments).difference(
                    definition.input_schema.get("properties", {})
                )
                if unexpected:
                    raise _payload_failure(
                        action_name=invocation.name,
                        action_kind="agent",
                        reason="agent action asserted undeclared fields",
                        field_paths=_unexpected_field_paths(
                            unexpected,
                            reveal_invalid_action_field_names=(
                                reveal_invalid_action_field_names
                            ),
                        ),
                        error_types=("extra_forbidden",) * len(unexpected),
                    )
                actions.append(
                    AgentDelegationProposal.model_validate({
                        **invocation.arguments,
                        "kind": "agent_delegation",
                        "action_id": invocation.call_id,
                        "agent_id": definition.target_name,
                    })
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
                reveal_invalid_action_field_names=(
                    reveal_invalid_action_field_names
                ),
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
        message=message,
        finalization_requested=finalization_requested,
    )


__all__ = [
    "build_model_action_definitions",
    "decode_model_action_invocations",
    "model_visible_capability_policy_json",
]
