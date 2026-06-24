"""Guardrail decision model.

Mirrors the policy layer's ``PolicyDecision`` shape: a headline action plus the
material the caller needs to honor it. A guard never raises — it returns a
verdict whose ``text`` is the (possibly transformed) content to use downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

GuardAction = Literal["allow", "sanitize", "block"]


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    """Outcome of one content-guard evaluation.

    - ``allow``: content is clean (or ``log_only`` mode) — use ``text`` as-is.
    - ``sanitize``: content was transformed (injection neutralized / PII redacted)
      — use ``text``, which differs from the input.
    - ``block``: high-confidence malicious — caller should refuse; ``text`` holds a
      safe placeholder.
    """

    action: GuardAction
    text: str
    categories: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""
    audit_required: bool = False

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    @property
    def blocked(self) -> bool:
        return self.action == "block"

    @property
    def changed(self) -> bool:
        return self.action != "allow"


__all__ = ["GuardAction", "GuardVerdict"]
