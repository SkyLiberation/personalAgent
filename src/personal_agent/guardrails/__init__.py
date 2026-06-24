"""Content guardrails: prompt-injection defense, PII redaction, output moderation.

The content guard is constructed once from ``settings.guardrails`` and exposed
through a process-wide accessor so the three integration seams — entry input
normalization, final-answer assembly, and untrusted web-evidence conversion —
can reach it without threading a dependency through nodes that take no context
(``_node_normalize_entry`` / ``_node_finalize_entry_result`` / ``web_results_to_evidence``).

Until ``configure_guardrails`` runs, :func:`get_content_guard` returns a default
sanitize-mode guard, so imports in tests and scripts behave sensibly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from personal_agent.guardrails.engine import ContentGuard, HeuristicContentGuard, NoopContentGuard
from personal_agent.guardrails.models import GuardAction, GuardVerdict

if TYPE_CHECKING:
    from personal_agent.kernel.config_models import GuardrailsConfig

_DEFAULT_GUARD: ContentGuard = HeuristicContentGuard()
_GUARD: ContentGuard = _DEFAULT_GUARD


def build_content_guard(config: "GuardrailsConfig") -> ContentGuard:
    """Construct a content guard from configuration."""
    if not config.enabled:
        return NoopContentGuard()
    return HeuristicContentGuard(mode=config.mode, redact_pii=config.redact_pii)


def configure_guardrails(config: "GuardrailsConfig") -> ContentGuard:
    """Install the process-wide content guard from settings; returns it."""
    global _GUARD
    _GUARD = build_content_guard(config)
    return _GUARD


def get_content_guard() -> ContentGuard:
    """Return the currently configured content guard (sanitize-mode default)."""
    return _GUARD


__all__ = [
    "ContentGuard",
    "GuardAction",
    "GuardVerdict",
    "HeuristicContentGuard",
    "NoopContentGuard",
    "build_content_guard",
    "configure_guardrails",
    "get_content_guard",
]
