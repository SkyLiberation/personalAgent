from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Literal

from langchain_core.tools import BaseTool

RiskLevel = Literal["low", "medium", "high"]
SideEffectType = Literal[
    "none",
    "read_local",
    "external_network",
    "write_longterm",
    "delete_longterm",
    "send_external",
    "irreversible",
]


@dataclass(frozen=True, slots=True)
class ToolGovernance:
    risk_level: RiskLevel = "low"
    requires_confirmation: bool = False
    side_effects: tuple[SideEffectType, ...] = ("none",)
    permission_scope: str = "agent:tool"
    idempotency_key_required: bool = False
    rollback_supported: bool = False
    audit_required: bool = True


def governance_extras(
    *,
    risk_level: RiskLevel = "low",
    requires_confirmation: bool = False,
    side_effects: tuple[SideEffectType, ...] = ("none",),
    permission_scope: str = "agent:tool",
    idempotency_key_required: bool = False,
    rollback_supported: bool = False,
    audit_required: bool = True,
) -> dict[str, Any]:
    governance = ToolGovernance(
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
        side_effects=side_effects,
        permission_scope=permission_scope,
        idempotency_key_required=idempotency_key_required,
        rollback_supported=rollback_supported,
        audit_required=audit_required,
    )
    payload = asdict(governance)
    payload["side_effects"] = list(governance.side_effects)
    return {"governance": payload}


def tool_success(data: Any = None, evidence: list | None = None) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None, "evidence": evidence or []}


def tool_failure(error: str) -> dict[str, Any]:
    return {"ok": False, "data": None, "error": error, "evidence": []}


def tool_response(outcome: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    content = (
        json.dumps(outcome.get("data"), ensure_ascii=False, default=str)
        if outcome.get("ok")
        else str(outcome.get("error") or "工具执行失败。")
    )
    return content, outcome


def tool_schema(tool: BaseTool) -> dict[str, Any]:
    if tool.args_schema is None:
        return {}
    if isinstance(tool.args_schema, dict):
        return tool.args_schema
    return tool.args_schema.model_json_schema()


def tool_governance(tool: BaseTool) -> ToolGovernance:
    payload = (tool.extras or {}).get("governance")
    if not isinstance(payload, dict):
        raise ValueError(f"Tool {tool.name!r} is missing structured governance metadata.")
    side_effects = payload.get("side_effects", ("none",))
    if isinstance(side_effects, list):
        side_effects = tuple(side_effects)
    return ToolGovernance(
        risk_level=payload.get("risk_level", "low"),
        requires_confirmation=bool(payload.get("requires_confirmation", False)),
        side_effects=side_effects,
        permission_scope=str(payload.get("permission_scope", "agent:tool")),
        idempotency_key_required=bool(payload.get("idempotency_key_required", False)),
        rollback_supported=bool(payload.get("rollback_supported", False)),
        audit_required=bool(payload.get("audit_required", True)),
    )


def tool_invocation_event(
    tool: BaseTool,
    *,
    tool_call_id: str,
    input: dict[str, Any],
    output: dict[str, Any],
    execution_mode: str,
    step_id: str | None = None,
    thread_id: str | None = None,
    user_id: str | None = None,
    latency_ms: float | None = None,
    langsmith_run_id: str | None = None,
) -> dict[str, Any]:
    governance = tool_governance(tool)
    return {
        "thread_id": thread_id,
        "user_id": user_id,
        "tool_name": tool.name,
        "tool_call_id": tool_call_id,
        "step_id": step_id,
        "execution_mode": execution_mode,
        "input": input,
        "output": output,
        "artifact_ok": output.get("ok"),
        "error": output.get("error"),
        "evidence": output.get("evidence", []),
        "latency_ms": latency_ms,
        "langsmith_run_id": langsmith_run_id,
        "risk_level": governance.risk_level,
        "requires_confirmation": governance.requires_confirmation,
        "side_effects": list(governance.side_effects),
        "permission_scope": governance.permission_scope,
        "side_effect_id": input.get("idempotency_key"),
        "idempotency_key_required": governance.idempotency_key_required,
        "rollback_supported": governance.rollback_supported,
        "audit_required": governance.audit_required,
    }
