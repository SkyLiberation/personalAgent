"""Policy engine input/decision models.

The policy layer is the single place that answers "is this action allowed, and
under what conditions?" for tools, memory access, and entry sources. It takes a
normalized ``PolicyInput`` and returns a ``PolicyDecision`` carrying an effect
plus the governance obligations (confirmation, escalation, audit) the caller
must honor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..tools.base import RiskLevel, SideEffectType
else:
    # Runtime aliases kept local so importing ``policy`` never pulls in the
    # ``tools`` package (which imports ``policy`` back — see the historical
    # memory→policy→tools cycle). These mirror ``tools.base`` exactly.
    RiskLevel = str
    SideEffectType = str

# allow                 执行放行
# deny                  拒绝执行（权限/前置条件不满足）
# require_confirmation   需要人工确认（HITL）后才能执行副作用
# require_escalation     超出当前主体授权，需要升级审批
PolicyEffect = Literal["allow", "deny", "require_confirmation", "require_escalation"]

# 被治理的动作类别。工具调用、记忆读写删、图谱同步、入口接入都走同一套决策。
PolicyAction = Literal[
    "tool_call",
    "memory_read",
    "memory_write",
    "memory_delete",
    "memory_graph_sync",
    "entry_access",
]


@dataclass(frozen=True, slots=True)
class PolicyInput:
    """Normalized request for a policy decision.

    Every consumer (tool gateway, memory facade, entry layer) builds one of
    these so the engine reasons over a single stable schema instead of each
    subsystem's bespoke arguments.
    """

    action: PolicyAction
    user_id: str | None = None
    session_id: str | None = None
    source_platform: str | None = None
    # 预留 workspace 维度（当前不引入业务 workspace 概念，默认 None）。
    workspace: str | None = None
    # 执行场景：deterministic | react | direct | memory | entry。
    execution_mode: str = "direct"

    # 工具/资源标识。
    tool_name: str | None = None
    resource: str | None = None

    # 工具治理快照（来自 ToolGovernance）。
    risk_level: RiskLevel = "low"
    requires_confirmation: bool = False
    side_effects: tuple[SideEffectType, ...] = ("none",)
    permission_scope: str = "agent:tool"

    # 调用方提供的上下文标志。
    confirmed: bool = False
    react_allowed_tools: frozenset[str] = frozenset()
    # 资源归属用户（用于记忆层 owner 校验）。
    resource_owner: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Result of a policy evaluation.

    ``effect`` is the headline verdict; the booleans are obligations the caller
    must enforce. ``reason``/``rule`` make "why allow / deny / confirm" auditable.
    """

    effect: PolicyEffect
    reason: str = ""
    rule: str = "default"
    audit_required: bool = True
    error_kind: str = "permission"
    obligations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def allowed(self) -> bool:
        """Whether the action may proceed to execution right now."""
        return self.effect == "allow"

    @property
    def needs_confirmation(self) -> bool:
        return self.effect == "require_confirmation"

    @property
    def needs_escalation(self) -> bool:
        return self.effect == "require_escalation"

    @classmethod
    def allow(cls, *, reason: str = "", rule: str = "default", audit_required: bool = True) -> "PolicyDecision":
        return cls(effect="allow", reason=reason, rule=rule, audit_required=audit_required)

    @classmethod
    def deny(
        cls,
        reason: str,
        *,
        rule: str = "default",
        error_kind: str = "permission",
        audit_required: bool = True,
    ) -> "PolicyDecision":
        return cls(
            effect="deny",
            reason=reason,
            rule=rule,
            error_kind=error_kind,
            audit_required=audit_required,
        )

    @classmethod
    def confirm(cls, reason: str, *, rule: str = "default") -> "PolicyDecision":
        return cls(effect="require_confirmation", reason=reason, rule=rule)

    @classmethod
    def escalate(cls, reason: str, *, rule: str = "default") -> "PolicyDecision":
        return cls(effect="require_escalation", reason=reason, rule=rule)


__all__ = [
    "PolicyAction",
    "PolicyDecision",
    "PolicyEffect",
    "PolicyInput",
]
