"""Content guard: prompt-injection neutralization, PII redaction, output moderation.

This is the content-quality/safety counterpart to ``policy/engine.py`` (which
governs *actions*). It follows the same Protocol + heuristic-implementation
shape as the answer verifier and rerankers, leaving room for an LLM/moderation
backend later.

Default behavior is **sanitize**: neutralize injection markers and redact PII,
then let the content through. ``block`` is opt-in and only fires on high-confidence
malicious input. ``log_only`` reports categories without changing content.
"""

from __future__ import annotations

from typing import Protocol

from personal_agent.guardrails.models import GuardVerdict
from personal_agent.guardrails.patterns import (
    INJECTION_PATTERNS,
    INJECTION_PLACEHOLDER,
    PII_PATTERNS,
    pii_placeholder,
)

# Two or more distinct injection markers ⇒ treat as high-confidence malicious.
_HIGH_CONFIDENCE_INJECTION_HITS = 2


class ContentGuard(Protocol):
    """Guards user input, model output, and untrusted retrieved content."""

    def check_input(self, text: str) -> GuardVerdict: ...

    def check_output(self, text: str) -> GuardVerdict: ...

    def sanitize_untrusted(self, text: str) -> GuardVerdict: ...


class HeuristicContentGuard:
    """Regex-based content guard. Stateless and cheap; safe as a process singleton."""

    def __init__(
        self,
        *,
        mode: str = "sanitize",
        redact_pii: bool = True,
    ) -> None:
        self._mode = mode if mode in ("sanitize", "block", "log_only") else "sanitize"
        self._redact_pii = redact_pii

    # -- public API ---------------------------------------------------------

    def check_input(self, text: str) -> GuardVerdict:
        """Guard user-supplied input before it reaches any LLM."""
        if not text:
            return GuardVerdict(action="allow", text=text)
        categories: list[str] = []
        out = text

        injection_hits = self._injection_hits(text)
        if injection_hits:
            categories.append("prompt_injection")
            if self._mode == "block" and injection_hits >= _HIGH_CONFIDENCE_INJECTION_HITS:
                return GuardVerdict(
                    action="block",
                    text="[输入被安全策略拦截]",
                    categories=("prompt_injection",),
                    reason=f"检测到 {injection_hits} 处疑似提示注入指令。",
                    audit_required=True,
                )
            out = self._neutralize_injection(out)

        if self._redact_pii:
            out, pii_categories = self._redact(out)
            categories.extend(pii_categories)

        return self._finalize(text, out, categories)

    def check_output(self, text: str) -> GuardVerdict:
        """Guard the final user-facing answer (PII redaction)."""
        if not text or not self._redact_pii:
            return GuardVerdict(action="allow", text=text)
        out, categories = self._redact(text)
        return self._finalize(text, out, categories)

    def sanitize_untrusted(self, text: str) -> GuardVerdict:
        """Neutralize injection markers in untrusted retrieved content (never blocks)."""
        if not text:
            return GuardVerdict(action="allow", text=text)
        if not self._injection_hits(text):
            return GuardVerdict(action="allow", text=text)
        out = self._neutralize_injection(text)
        if out == text:
            return GuardVerdict(action="allow", text=text)
        return GuardVerdict(
            action="sanitize",
            text=out,
            categories=("untrusted_injection",),
            reason="中和了检索内容中的疑似注入指令。",
            audit_required=True,
        )

    # -- internals ----------------------------------------------------------

    def _injection_hits(self, text: str) -> int:
        return sum(1 for pattern in INJECTION_PATTERNS if pattern.search(text))

    def _neutralize_injection(self, text: str) -> str:
        out = text
        for pattern in INJECTION_PATTERNS:
            out = pattern.sub(INJECTION_PLACEHOLDER, out)
        return out

    def _redact(self, text: str) -> tuple[str, list[str]]:
        out = text
        found: list[str] = []
        for category, pattern in PII_PATTERNS:
            if pattern.search(out):
                out = pattern.sub(pii_placeholder(category), out)
                found.append(f"pii:{category}")
        return out, found

    def _finalize(self, original: str, transformed: str, categories: list[str]) -> GuardVerdict:
        if not categories:
            return GuardVerdict(action="allow", text=original)
        if self._mode == "log_only":
            # Report categories but leave content untouched (observation phase).
            return GuardVerdict(
                action="allow",
                text=original,
                categories=tuple(categories),
                audit_required=True,
            )
        return GuardVerdict(
            action="sanitize",
            text=transformed,
            categories=tuple(categories),
            reason="；".join(sorted(set(categories))),
            audit_required=True,
        )


class NoopContentGuard:
    """Disabled guard: everything is allowed unchanged."""

    def check_input(self, text: str) -> GuardVerdict:
        return GuardVerdict(action="allow", text=text)

    def check_output(self, text: str) -> GuardVerdict:
        return GuardVerdict(action="allow", text=text)

    def sanitize_untrusted(self, text: str) -> GuardVerdict:
        return GuardVerdict(action="allow", text=text)


__all__ = ["ContentGuard", "HeuristicContentGuard", "NoopContentGuard"]
