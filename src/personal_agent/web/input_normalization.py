"""Central input normalization for the HTTP transport edge.

Previously each entry route did its own ``text.strip()``. This is the one seam
that normalizes user-supplied entry text before it enters the agent, so the
behavior is consistent and there is a single place for the content guard
(prompt-injection / PII) to hook in later.
"""

from __future__ import annotations

import unicodedata


def normalize_entry_text(text: str | None) -> str:
    """Normalize raw entry text: NFC, strip control chars, trim edges.

    Newlines and tabs are preserved; other control characters (category ``C``)
    are dropped to avoid hidden/zero-width payloads.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text)
    cleaned = "".join(
        ch
        for ch in normalized
        if ch in ("\n", "\t") or unicodedata.category(ch)[0] != "C"
    )
    return cleaned.strip()


__all__ = ["normalize_entry_text"]
