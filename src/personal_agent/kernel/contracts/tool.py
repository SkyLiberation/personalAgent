"""Tool governance/result contracts (pure data, no behavior).

These types are the persistence- and policy-facing schema for tool execution.
They live in the kernel so the infra layer (audit stores) and the governance
layer (policy engine) can share them without importing the tools package. The
behavioral helpers that operate on a LangChain ``BaseTool`` stay in
``personal_agent.tools.base``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high"]
ToolExposure = Literal[
    "public_agent",
    "scoped_agent",
    "workflow_activity",
    "admin",
]
SideEffectType = Literal[
    "none",
    "read_local",
    "read_longterm",
    "external_network",
    "write_longterm",
    "delete_longterm",
    "send_external",
    "irreversible",
]

# 工具执行错误分类。Gateway 据此决定是否重试，并写入审计。
#   transient     瞬时错误（网络抖动、超时、上游 5xx）—— 可重试
#   invalid_param 参数错误（schema 通过但语义非法）—— 不可重试，应交还规划层修正
#   permission    权限/前置条件不满足（缺 key、无权访问、域名不允许）—— 不可重试
#   unrecoverable 业务确定性失败（资源不存在、已删除）—— 不可重试
ToolErrorKind = Literal["transient", "invalid_param", "permission", "unrecoverable"]

_RETRYABLE_ERROR_KINDS: frozenset[str] = frozenset({"transient"})


class ToolError(Exception):
    """业务工具抛出的分类异常。

    工具不再自己 ``try/except`` 吞掉异常返回 failure artifact，而是抛出带 ``kind``
    的 ``ToolError``，由 ``ToolGateway`` 统一决定重试、收敛为 artifact 和审计。
    """

    def __init__(self, message: str, *, kind: ToolErrorKind = "unrecoverable") -> None:
        super().__init__(message)
        self.message = message
        self.kind: ToolErrorKind = kind


@dataclass(frozen=True, slots=True)
class ToolGovernance:
    exposure: ToolExposure = "public_agent"
    risk_level: RiskLevel = "low"
    requires_confirmation: bool = False
    side_effects: tuple[SideEffectType, ...] = ("none",)
    permission_scope: str = "agent:tool"
    idempotency_key_required: bool = False
    rollback_supported: bool = False
    audit_required: bool = True
    timeout_seconds: float | None = 30.0
    max_retries: int = 0
    retry_backoff_seconds: float = 0.2
    rate_limit_per_minute: int | None = None
    # 外部网络工具的来源白名单（域名后缀匹配）。空元组表示该工具不做域名限制。
    allowed_domains: tuple[str, ...] = ()


class ToolArtifact(BaseModel):
    ok: bool
    data: Any = None
    error: str | None = None
    error_kind: ToolErrorKind | None = None
    evidence: list[Any] = Field(default_factory=list)


class ToolInvocationEvent(BaseModel):
    thread_id: str | None = None
    run_id: str | None = None
    user_id: str | None = None
    tool_name: str
    tool_call_id: str
    step_id: str | None = None
    execution_mode: str
    input: dict[str, Any]
    output: ToolArtifact
    artifact_ok: bool | None = None
    error: str | None = None
    error_kind: ToolErrorKind | None = None
    evidence: list[Any] = Field(default_factory=list)
    confirmed: bool = False
    latency_ms: float | None = None
    langsmith_run_id: str | None = None
    attempts: int = 1
    timed_out: bool = False
    rate_limited: bool = False
    risk_level: RiskLevel
    exposure: ToolExposure = "public_agent"
    requires_confirmation: bool
    side_effects: list[SideEffectType]
    permission_scope: str
    side_effect_id: str | None = None
    idempotency_key_required: bool = False
    rollback_supported: bool = False
    audit_required: bool = True
    timeout_seconds: float | None = None
    max_retries: int = 0
    rate_limit_per_minute: int | None = None


__all__ = [
    "RiskLevel",
    "ToolExposure",
    "SideEffectType",
    "ToolErrorKind",
    "ToolError",
    "ToolGovernance",
    "ToolArtifact",
    "ToolInvocationEvent",
]
