"""Unified policy engine.

Consolidates the governance decisions that used to be scattered across the tool
gateway (``_validate_policy``), the ``delete_note`` tool (hardcoded confirmation)
and the memory facade (ad-hoc ``user_id`` checks) into one evaluator.

Rules are code-internal by default. A small set of programmable allow/deny
overrides (keyed by user / source / tool / scope) can be supplied at
construction so deployments can pin authorization without an external config
file or env parsing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from personal_agent.policy.invariants import (
    is_high_risk_side_effect_action,
    react_autonomy_blocked,
)
from personal_agent.policy.models import PolicyDecision, PolicyInput

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PolicyRules:
    """Programmable allow/deny overrides layered on top of code defaults.

    Each set holds opaque match keys. ``deny_*`` wins over ``allow_*``; an empty
    rule set means "defer entirely to the built-in defaults" (current behavior).
    """

    deny_users: frozenset[str] = field(default_factory=frozenset)
    allow_users: frozenset[str] = field(default_factory=frozenset)
    deny_sources: frozenset[str] = field(default_factory=frozenset)
    allow_sources: frozenset[str] = field(default_factory=frozenset)
    # 显式封禁的工具名。
    deny_tools: frozenset[str] = field(default_factory=frozenset)
    # 显式封禁的权限域（如 "memory:delete"）。
    deny_scopes: frozenset[str] = field(default_factory=frozenset)
    # 是否对所有高风险动作强制要求确认（默认开启）。
    require_confirmation_for_high_risk: bool = True

    @property
    def is_empty(self) -> bool:
        return not (
            self.deny_users
            or self.allow_users
            or self.deny_sources
            or self.allow_sources
            or self.deny_tools
            or self.deny_scopes
        )


class PolicyEngine:
    """Evaluate a ``PolicyInput`` into a ``PolicyDecision``.

    Evaluation order (first decisive verdict wins):

    1. Explicit deny overrides (user / source / tool / scope).
    2. ReAct autonomy guard — block high-risk / side-effecting tools.
    3. High-risk confirmation gate — unconfirmed high-risk side effects pause.
    4. Memory ownership — read/write/delete across user boundaries denied.
    5. Default allow.
    """

    def __init__(self, rules: PolicyRules | None = None) -> None:
        self._rules = rules or PolicyRules()

    @property
    def rules(self) -> PolicyRules:
        return self._rules

    def evaluate(self, request: PolicyInput) -> PolicyDecision:
        override = self._evaluate_overrides(request)
        if override is not None:
            return override

        if request.action == "tool_call":
            return self._evaluate_tool(request)
        if request.action in ("memory_read", "memory_write", "memory_delete", "memory_graph_sync"):
            return self._evaluate_memory(request)
        if request.action == "entry_access":
            return self._evaluate_entry(request)
        return PolicyDecision.allow(rule="default.unknown_action")

    # -- override layer -----------------------------------------------------

    def _evaluate_overrides(self, request: PolicyInput) -> PolicyDecision | None:
        rules = self._rules
        if request.user_id and request.user_id in rules.deny_users:
            return PolicyDecision.deny(
                f"用户 {request.user_id} 被策略禁止执行该动作。",
                rule="override.deny_user",
            )
        if request.source_platform and request.source_platform in rules.deny_sources:
            return PolicyDecision.deny(
                f"入口来源 {request.source_platform} 被策略禁止。",
                rule="override.deny_source",
            )
        if request.tool_name and request.tool_name in rules.deny_tools:
            return PolicyDecision.deny(
                f"工具 {request.tool_name} 被策略禁止调用。",
                rule="override.deny_tool",
            )
        if request.permission_scope and request.permission_scope in rules.deny_scopes:
            return PolicyDecision.deny(
                f"权限域 {request.permission_scope} 被策略禁止。",
                rule="override.deny_scope",
            )
        return None

    # -- tool decisions -----------------------------------------------------

    def _evaluate_tool(self, request: PolicyInput) -> PolicyDecision:
        if request.execution_mode == "react":
            react_block = self._evaluate_react_guard(request)
            if react_block is not None:
                return react_block

        # 高风险副作用动作：未确认则要求确认，已确认则放行交由 gateway 做幂等校验。
        if self._is_high_risk_side_effect(request):
            if not request.confirmed:
                return PolicyDecision.confirm(
                    f"工具 {request.tool_name} 为高风险操作，需用户确认后执行。",
                    rule="tool.high_risk_confirmation",
                )
            return PolicyDecision.allow(rule="tool.high_risk_confirmed")

        return PolicyDecision.allow(rule="tool.default")

    def _evaluate_react_guard(self, request: PolicyInput) -> PolicyDecision | None:
        if request.tool_name and request.tool_name not in request.react_allowed_tools:
            return PolicyDecision.deny(
                f"工具 {request.tool_name} 不在当前 ReAct 允许列表中。",
                rule="react.not_allowed",
            )
        if react_autonomy_blocked(
            risk_level=request.risk_level,
            requires_confirmation=request.requires_confirmation,
            side_effects=request.side_effects,
        ):
            return PolicyDecision.deny(
                f"工具 {request.tool_name} 不允许在 ReAct 自主执行中调用。",
                rule="react.blocked_side_effect",
            )
        return None

    def _is_high_risk_side_effect(self, request: PolicyInput) -> bool:
        if not self._rules.require_confirmation_for_high_risk:
            return False
        return is_high_risk_side_effect_action(
            risk_level=request.risk_level,
            requires_confirmation=request.requires_confirmation,
            side_effects=request.side_effects,
        )

    # -- memory decisions ---------------------------------------------------

    def _evaluate_memory(self, request: PolicyInput) -> PolicyDecision:
        owner = request.resource_owner
        subject = request.user_id
        if owner is not None and subject is not None and owner != subject:
            return PolicyDecision.deny(
                f"资源 {request.resource or ''} 不属于用户 {subject}。",
                rule="memory.owner_mismatch",
            )
        if request.action == "memory_delete" and not request.confirmed:
            return PolicyDecision.confirm(
                "删除长期记忆需要确认后执行。",
                rule="memory.delete_confirmation",
            )
        return PolicyDecision.allow(rule=f"memory.{request.action}")

    # -- entry decisions ----------------------------------------------------

    def _evaluate_entry(self, request: PolicyInput) -> PolicyDecision:
        rules = self._rules
        if rules.allow_sources and request.source_platform not in rules.allow_sources:
            return PolicyDecision.deny(
                f"入口来源 {request.source_platform} 不在允许列表中。",
                rule="entry.source_not_allowed",
            )
        if rules.allow_users and request.user_id not in rules.allow_users:
            return PolicyDecision.deny(
                f"用户 {request.user_id} 不在允许列表中。",
                rule="entry.user_not_allowed",
            )
        return PolicyDecision.allow(rule="entry.default")


__all__ = ["PolicyEngine", "PolicyRules"]
