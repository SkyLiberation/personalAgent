"""Conversation model actions over the provider-neutral model Port.

The capability projection remains the visibility owner. This module materializes
that already-filtered projection as exact provider actions and decodes selected
wire actions back into existing Application proposals. It does not authorize or
execute anything.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from pydantic import ValidationError

from personal_agent.capabilities.contracts.model import (
    ModelActionDefinition,
    ModelActionInvocation,
    StructuredOutputFailure,
)
from personal_agent.kernel.llm_schemas import model_tool_wire_name, strictify_schema

from .models import (
    AgentDelegationProposal,
    ContinueTurnProposal,
    ConversationWorkingPlan,
    EffectiveCapabilities,
    FinalMessage,
    ToolCallProposal,
    WorkingPlanProposal,
)

_FINAL_TARGET = "final_message"
_WORKING_PLAN_TARGET = "working_plan"


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
    pending_plan_step_ids: tuple[str, ...],
) -> dict[str, Any]:
    plan_binding_schema = (
        {
            "plan_step_id": {
                "type": "string",
                "enum": list(pending_plan_step_ids),
                "description": "Bind to one current pending working-plan step.",
            }
        }
        if pending_plan_step_ids
        else {}
    )
    return _wrapped_schema(
        "arguments",
        input_schema,
        plan_binding_schema,
    )


def _working_plan_action_schema() -> dict[str, Any]:
    return _wrapped_schema(
        "working_plan",
        WorkingPlanProposal.model_json_schema(),
        {
            "wait_for_user": {"type": "boolean"},
            "message": {"type": "string", "maxLength": 4_000},
        },
    )


def build_model_action_definitions(
    capabilities: EffectiveCapabilities,
    *,
    working_plan: ConversationWorkingPlan | None = None,
) -> tuple[ModelActionDefinition, ...]:
    """Project each visible capability exactly once plus typed control actions."""
    pending_plan_step_ids = tuple(
        step.step_id
        for step in working_plan.steps
        if step.status == "pending"
    ) if working_plan is not None else ()
    definitions: list[ModelActionDefinition] = []
    for capability in capabilities.tools:
        definitions.append(
            ModelActionDefinition(
                name=_wire_name("tool", capability.name),
                kind="tool",
                target_name=capability.name,
                description=(
                    f"Canonical capability: {capability.name}. {capability.description} "
                    "Pass capability parameters inside arguments."
                    + (
                        " Bind this action to one declared pending plan_step_id."
                        if pending_plan_step_ids
                        else " No working-plan binding is available in this turn."
                    )
                ),
                input_schema=_tool_action_schema(
                    capability.input_schema,
                    pending_plan_step_ids,
                ),
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
                    pending_plan_step_ids,
                ),
            )
        )
    definitions.extend((
        ModelActionDefinition(
            name=_wire_name("control", _WORKING_PLAN_TARGET),
            kind="working_plan",
            target_name=_WORKING_PLAN_TARGET,
            description=(
                "Propose or revise the user-visible working plan. This is a control "
                "action, not an executed tool."
            ),
            input_schema=_working_plan_action_schema(),
        ),
        ModelActionDefinition(
            name=_wire_name("control", _FINAL_TARGET),
            kind="final",
            target_name=_FINAL_TARGET,
            description=(
                "Return the user-visible final answer, clarification, limitation, or "
                "failure. This is a completion proposal, not an executed tool."
            ),
            input_schema=_schema_without_fields(
                FinalMessage.model_json_schema(),
                frozenset({"kind"}),
            ),
        ),
    ))
    names = [definition.name for definition in definitions]
    if len(names) != len(set(names)):
        raise ValueError("model action wire-name collision")
    return tuple(definitions)


def _agent_action_schema(
    schema: dict[str, Any],
    pending_plan_step_ids: tuple[str, ...],
) -> dict[str, Any]:
    projected = _schema_without_fields(
        schema,
        frozenset({"kind", "action_id", "agent_id", "plan_step_id"}),
    )
    properties = projected["properties"]
    if pending_plan_step_ids:
        properties["plan_step_id"] = {
            "type": "string",
            "enum": list(pending_plan_step_ids),
            "description": "Bind to one current pending working-plan step.",
        }
        projected["required"].append("plan_step_id")
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


def _reject_reserved_arguments(
    arguments: dict[str, Any],
    reserved: frozenset[str],
    *,
    action_name: str,
) -> None:
    overlap = reserved.intersection(arguments)
    if overlap:
        names = ", ".join(sorted(overlap))
        raise StructuredOutputFailure(
            "agent_interaction_turn",
            f"model action {action_name!r} asserted runtime-owned fields: {names}",
            reason_code="provider_action_payload_invalid",
        )


def decode_model_action_invocations(
    invocations: tuple[ModelActionInvocation, ...],
    definitions: tuple[ModelActionDefinition, ...],
) -> ContinueTurnProposal | FinalMessage:
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
    final_invocations = [
        item for item in invocations if by_name[item.name].kind == "final"
    ]
    if final_invocations:
        if len(invocations) != 1:
            raise StructuredOutputFailure(
                "agent_interaction_turn",
                "final action must be the only action in a model turn",
                reason_code="provider_action_final_not_exclusive",
            )
        invocation = final_invocations[0]
        _reject_reserved_arguments(
            invocation.arguments,
            frozenset({"kind"}),
            action_name=invocation.name,
        )
        try:
            return FinalMessage.model_validate({
                **invocation.arguments,
                "kind": "final_message",
            })
        except ValidationError as exc:
            raise StructuredOutputFailure(
                "agent_interaction_turn",
                f"invalid final action payload: {exc}",
                reason_code="provider_action_payload_invalid",
            ) from exc

    working_plan: WorkingPlanProposal | None = None
    wait_for_user = False
    message = ""
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
            if definition.kind == "working_plan":
                if working_plan is not None:
                    raise StructuredOutputFailure(
                        "agent_interaction_turn",
                        "a model turn may contain at most one working-plan action",
                        reason_code="provider_action_multiple_working_plans",
                    )
                unexpected = set(invocation.arguments).difference(
                    {"working_plan", "wait_for_user", "message"}
                )
                if unexpected or "working_plan" not in invocation.arguments:
                    raise StructuredOutputFailure(
                        "agent_interaction_turn",
                        "working-plan action payload does not match its declared fields",
                        reason_code="provider_action_payload_invalid",
                    )
                working_plan = WorkingPlanProposal.model_validate(
                    invocation.arguments["working_plan"]
                )
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
                    raise StructuredOutputFailure(
                        "agent_interaction_turn",
                        f"tool action {invocation.name!r} payload does not match its wrapper",
                        reason_code="provider_action_payload_invalid",
                    )
                actions.append(
                    ToolCallProposal(
                        action_id=invocation.call_id,
                        tool_name=definition.target_name,
                        arguments=tool_arguments,
                        plan_step_id=invocation.arguments.get("plan_step_id"),
                    )
                )
                continue
            if definition.kind == "agent":
                _reject_reserved_arguments(
                    invocation.arguments,
                    frozenset({"kind", "action_id", "agent_id"}),
                    action_name=invocation.name,
                )
                unexpected = set(invocation.arguments).difference(
                    definition.input_schema.get("properties", {})
                )
                if unexpected:
                    names = ", ".join(sorted(unexpected))
                    raise StructuredOutputFailure(
                        "agent_interaction_turn",
                        f"agent action {invocation.name!r} asserted undeclared fields: {names}",
                        reason_code="provider_action_payload_invalid",
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
            raise StructuredOutputFailure(
                "agent_interaction_turn",
                f"invalid {definition.kind} action payload: {exc}",
                reason_code="provider_action_payload_invalid",
            ) from exc

    return ContinueTurnProposal(
        actions=tuple(actions),
        working_plan=working_plan,
        wait_for_user=wait_for_user,
        message=message,
    )


__all__ = [
    "build_model_action_definitions",
    "decode_model_action_invocations",
    "model_visible_capability_policy_json",
]
