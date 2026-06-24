from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any
from urllib.parse import urlparse

from langchain_core.tools import BaseTool

# Tool governance/result contracts now live in the kernel so the infra and
# governance layers can share them without importing the tools package. They are
# re-exported here to keep ``personal_agent.tools.base`` the import site for the
# behavioral helpers that operate on a LangChain ``BaseTool``.
from personal_agent.kernel.contracts.tool import (
    RiskLevel,
    SideEffectType,
    ToolArtifact,
    ToolError,
    ToolErrorKind,
    ToolExposure,
    ToolGovernance,
    ToolInvocationEvent,
)


def host_allowed(host: str, allowed_domains: tuple[str, ...]) -> bool:
    """Return whether host matches an exact or subdomain allow-list entry."""
    normalized_host = host.lower().strip(".")
    for allowed in allowed_domains:
        suffix = allowed.lower().strip().lstrip(".")
        if suffix and (normalized_host == suffix or normalized_host.endswith("." + suffix)):
            return True
    return False


def url_allowed(url: str, allowed_domains: tuple[str, ...]) -> bool:
    """Return whether a URL is allowed by the domain allow-list.

    An empty allow-list means unrestricted access for the caller.
    """
    if not allowed_domains:
        return True
    host = (urlparse(url).hostname or "").lower()
    return bool(host and host_allowed(host, allowed_domains))


def governance_extras(
    *,
    exposure: ToolExposure = "public_agent",
    risk_level: RiskLevel = "low",
    requires_confirmation: bool = False,
    side_effects: tuple[SideEffectType, ...] = ("none",),
    permission_scope: str = "agent:tool",
    idempotency_key_required: bool = False,
    rollback_supported: bool = False,
    audit_required: bool = True,
    timeout_seconds: float | None = 30.0,
    max_retries: int = 0,
    retry_backoff_seconds: float = 0.2,
    rate_limit_per_minute: int | None = None,
    allowed_domains: tuple[str, ...] = (),
) -> dict[str, Any]:
    governance = ToolGovernance(
        exposure=exposure,
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
        side_effects=side_effects,
        permission_scope=permission_scope,
        idempotency_key_required=idempotency_key_required,
        rollback_supported=rollback_supported,
        audit_required=audit_required,
        timeout_seconds=timeout_seconds,
        max_retries=max(0, max_retries),
        retry_backoff_seconds=max(0.0, retry_backoff_seconds),
        rate_limit_per_minute=rate_limit_per_minute,
        allowed_domains=allowed_domains,
    )
    payload = asdict(governance)
    payload["side_effects"] = list(governance.side_effects)
    payload["allowed_domains"] = list(governance.allowed_domains)
    return {"governance": payload}


def tool_success(data: Any = None, evidence: list | None = None) -> ToolArtifact:
    return ToolArtifact(ok=True, data=data, error=None, evidence=evidence or [])


def tool_failure(error: str, *, error_kind: ToolErrorKind = "unrecoverable") -> ToolArtifact:
    return ToolArtifact(ok=False, data=None, error=error, error_kind=error_kind, evidence=[])


def _artifact_from(outcome: ToolArtifact | dict[str, Any]) -> ToolArtifact:
    if isinstance(outcome, ToolArtifact):
        return outcome
    return ToolArtifact.model_validate(outcome)


def tool_response(outcome: ToolArtifact | dict[str, Any]) -> tuple[str, ToolArtifact]:
    artifact = _artifact_from(outcome)
    content = (
        json.dumps(artifact.data, ensure_ascii=False, default=str)
        if artifact.ok
        else str(artifact.error or "工具执行失败。")
    )
    return content, artifact


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
    allowed_domains = payload.get("allowed_domains", ())
    if isinstance(allowed_domains, list):
        allowed_domains = tuple(allowed_domains)
    return ToolGovernance(
        exposure=payload.get("exposure", "public_agent"),
        risk_level=payload.get("risk_level", "low"),
        requires_confirmation=bool(payload.get("requires_confirmation", False)),
        side_effects=side_effects,
        permission_scope=str(payload.get("permission_scope", "agent:tool")),
        idempotency_key_required=bool(payload.get("idempotency_key_required", False)),
        rollback_supported=bool(payload.get("rollback_supported", False)),
        audit_required=bool(payload.get("audit_required", True)),
        timeout_seconds=payload.get("timeout_seconds", 30.0),
        max_retries=max(0, int(payload.get("max_retries", 0))),
        retry_backoff_seconds=max(0.0, float(payload.get("retry_backoff_seconds", 0.2))),
        rate_limit_per_minute=payload.get("rate_limit_per_minute"),
        allowed_domains=allowed_domains,
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
    run_id: str | None = None,
    user_id: str | None = None,
    latency_ms: float | None = None,
    langsmith_run_id: str | None = None,
    attempts: int = 1,
    timed_out: bool = False,
    rate_limited: bool = False,
) -> ToolInvocationEvent:
    governance = tool_governance(tool)
    artifact = _artifact_from(output)
    return ToolInvocationEvent(
        thread_id=thread_id,
        run_id=run_id,
        user_id=user_id,
        tool_name=tool.name,
        tool_call_id=tool_call_id,
        step_id=step_id,
        execution_mode=execution_mode,
        input=input,
        output=artifact,
        artifact_ok=artifact.ok,
        error=artifact.error,
        evidence=artifact.evidence,
        confirmed=bool(input.get("confirmed")),
        latency_ms=latency_ms,
        langsmith_run_id=langsmith_run_id,
        attempts=attempts,
        timed_out=timed_out,
        rate_limited=rate_limited,
        risk_level=governance.risk_level,
        exposure=governance.exposure,
        requires_confirmation=governance.requires_confirmation,
        side_effects=list(governance.side_effects),
        permission_scope=governance.permission_scope,
        side_effect_id=input.get("idempotency_key"),
        idempotency_key_required=governance.idempotency_key_required,
        rollback_supported=governance.rollback_supported,
        audit_required=governance.audit_required,
        timeout_seconds=governance.timeout_seconds,
        max_retries=governance.max_retries,
        rate_limit_per_minute=governance.rate_limit_per_minute,
    )


__all__ = [
    "RiskLevel",
    "SideEffectType",
    "ToolExposure",
    "ToolErrorKind",
    "ToolError",
    "ToolGovernance",
    "ToolArtifact",
    "ToolInvocationEvent",
    "host_allowed",
    "url_allowed",
    "governance_extras",
    "tool_success",
    "tool_failure",
    "tool_response",
    "tool_schema",
    "tool_governance",
    "tool_invocation_event",
]
