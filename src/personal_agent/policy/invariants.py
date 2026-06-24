"""Shared risk invariants — the single definition of what makes an action risky.

These predicates used to be re-encoded independently in three places:
- ``policy/engine.py`` (ReAct autonomy guard + high-risk confirmation gate),
- ``agent/workflow_validator.py`` (declaration-time spec invariants),
- ``agent/step_projection_validator.py`` (runtime step + intent rules).

Defense in depth is intentional — all three still check — but they must agree by
construction. Centralizing the *definitions* here means a change to "what is
high-risk" or "which side effects ReAct may never trigger" happens once.

Plain ``str`` aliases (mirroring ``policy/models.py``) are used instead of
importing ``tools.base`` so this module never pulls in the ``tools`` package and
re-triggers the historical memory -> policy -> tools import cycle.
"""

from __future__ import annotations

from collections.abc import Iterable

RiskLevel = str
SideEffectType = str

# 删除长期记忆、对外发送、不可逆动作：ReAct 自主执行中一律禁止的副作用。
# 普通写入不在此列——它另需满足 scoped allowed_tools、非 high risk、非 requires_confirmation。
BLOCKED_REACT_SIDE_EFFECTS: frozenset[str] = frozenset(
    {"delete_longterm", "send_external", "irreversible"}
)

# 长期删除副作用标记。
DELETE_LONGTERM: SideEffectType = "delete_longterm"


def is_high_risk(risk_level: RiskLevel | None) -> bool:
    """Whether ``risk_level`` denotes the high-risk tier."""
    return risk_level == "high"


def high_risk_requires_confirmation(
    risk_level: RiskLevel | None, requires_confirmation: bool
) -> bool:
    """The "high-risk ⇒ must require confirmation" invariant.

    Returns ``True`` when the invariant is **violated** (high risk but no
    confirmation), so callers can phrase their own localized message.
    """
    return is_high_risk(risk_level) and not requires_confirmation


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


def is_high_risk_side_effect_action(
    *,
    risk_level: RiskLevel | None,
    requires_confirmation: bool,
    side_effects: Iterable[SideEffectType],
) -> bool:
    """The triad the confirmation gate keys on: high + confirm-flagged + blocked effect."""
    return bool(
        requires_confirmation
        and is_high_risk(risk_level)
        and has_blocked_react_effect(side_effects)
    )


def carries_delete_longterm(side_effects: Iterable[SideEffectType]) -> bool:
    return DELETE_LONGTERM in set(side_effects)


def delete_longterm_violations(
    *,
    side_effects: Iterable[SideEffectType],
    risk_level: RiskLevel | None,
    requires_confirmation: bool,
    hitl_policy: str,
) -> tuple[str, ...]:
    """Return violated-constraint codes for a delete_longterm action.

    Empty tuple ⇒ the delete_longterm requirements (high risk + confirmation +
    a non-``none`` HITL policy) all hold, or the action does not delete longterm.
    Codes: ``"risk"``, ``"confirmation"``, ``"hitl"``. Callers map codes to their
    own messages.
    """
    if not carries_delete_longterm(side_effects):
        return ()
    codes: list[str] = []
    if not is_high_risk(risk_level):
        codes.append("risk")
    if not requires_confirmation:
        codes.append("confirmation")
    if hitl_policy == "none":
        codes.append("hitl")
    return tuple(codes)


__all__ = [
    "BLOCKED_REACT_SIDE_EFFECTS",
    "DELETE_LONGTERM",
    "carries_delete_longterm",
    "delete_longterm_violations",
    "has_blocked_react_effect",
    "high_risk_requires_confirmation",
    "is_high_risk",
    "is_high_risk_side_effect_action",
    "react_autonomy_blocked",
]
