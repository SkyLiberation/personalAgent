"""Risk predicates for the policy engine's ReAct autonomy guard."""

from __future__ import annotations

from collections.abc import Iterable

RiskLevel = str
SideEffectType = str

# 删除长期记忆、对外发送、不可逆动作：ReAct 自主执行中一律禁止的副作用。
# 普通写入不在此列——它另需满足 scoped allowed_tools、非 high risk、非 requires_confirmation。
BLOCKED_REACT_SIDE_EFFECTS: frozenset[str] = frozenset(
    {"delete_longterm", "send_external", "irreversible"}
)


def is_high_risk(risk_level: RiskLevel | None) -> bool:
    """Whether ``risk_level`` denotes the high-risk tier."""
    return risk_level == "high"


def has_blocked_react_effect(side_effects: Iterable[SideEffectType]) -> bool:
    """Whether any side effect is forbidden inside autonomous ReAct."""
    return bool(BLOCKED_REACT_SIDE_EFFECTS.intersection(side_effects))


def react_autonomy_blocked(
    *,
    risk_level: RiskLevel | None,
    requires_confirmation: bool,
    side_effects: Iterable[SideEffectType],
) -> bool:
    """Whether a tool may NOT run as an autonomous ReAct step.

    High risk, confirmation-gated, or a blocked side effect each disqualify it.
    Allowlist membership is enforced separately by the caller.
    """
    return bool(
        is_high_risk(risk_level)
        or requires_confirmation
        or has_blocked_react_effect(side_effects)
    )


__all__ = [
    "BLOCKED_REACT_SIDE_EFFECTS",
    "has_blocked_react_effect",
    "is_high_risk",
    "react_autonomy_blocked",
]
