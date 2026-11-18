"""How much of one action observation may enter the model context.

The loop's token ceiling cannot own this. ``LoopBudgetPolicy.max_total_tokens``
is consulted against *committed* usage at the top of a turn, so a single
oversized tool return inside a turn has already been sent by the time the
ceiling is next read. E21 measured one read at 1,940,197 payload characters and
776,720 committed tokens against a declared 32,000 ceiling.

Initial tool receipts use a byte budget and a contiguous text prefix.
Explicit read windows use a separate character budget.
"""

from __future__ import annotations

import json
from typing import Any

MAX_TOOL_OBSERVATION_BYTES = 50 * 1024
"""UTF-8 JSON ceiling for an initial tool receipt and its preview."""

MAX_OBSERVATION_PAYLOAD_CHARS = 20_000
"""Character ceiling for explicit reads and searches over stored results."""

def serialized_length(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str))


def serialized_utf8_size(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))


def fit_observation_preview(
    payload: dict[str, Any], text: str, *, previously_omitted: int | None = None,
) -> dict[str, Any]:
    """Fill the receipt's remaining byte budget with a verbatim prefix."""
    if serialized_utf8_size(payload) > MAX_TOOL_OBSERVATION_BYTES:
        payload = {key: value for key, value in payload.items()
                   if key in {"ok", "error_kind", "status", "retrieval", "observation_excerpt_removed"}}
    fitted = {**payload, "observation_excerpt": ""}
    fitted.pop("observation_excerpt_removed", None)
    total_chars = len(text) + previously_omitted if previously_omitted is not None else None
    if total_chars is not None:
        fitted["observation_excerpt_omitted_chars"] = 0
    available_bytes = MAX_TOOL_OBSERVATION_BYTES - serialized_utf8_size(fitted)
    if available_bytes <= 0 or not text:
        return payload

    lower, upper = 0, min(len(text), available_bytes)
    while lower < upper:
        end = (lower + upper + 1) // 2
        excerpt_bytes = serialized_utf8_size(text[:end]) - 2  # empty JSON string already counted
        if total_chars is not None:
            excerpt_bytes += len(str(total_chars - end)) - 1
        if excerpt_bytes <= available_bytes:
            lower = end
        else:
            upper = end - 1
    if not lower:
        return payload
    fitted["observation_excerpt"] = text[:lower]
    if total_chars is not None:
        fitted["observation_excerpt_omitted_chars"] = total_chars - lower
    return fitted


def _longest_string(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        candidates = [_longest_string(item) for item in value.values()]
    elif isinstance(value, (list, tuple)):
        candidates = [_longest_string(item) for item in value]
    else:
        return None
    found = [item for item in candidates if item is not None]
    return max(found, key=len) if found else None


def select_offload_text(
    payload: dict[str, Any], *, max_chars: int = MAX_OBSERVATION_PAYLOAD_CHARS
) -> str:
    """The text a re-read of this payload pages over.

    Escaping is the whole problem. A JSON dump of a payload whose size comes from
    one long string turns every newline in that string into a two-character
    escape, so ``splitlines`` sees the entire body as a single line: a keyword
    window returns that one line, bounding cuts its middle out again, and the
    fact the model was paging toward is unreachable at any offset. So when one
    string leaf is itself larger than a whole observation, that string is
    offloaded raw and its line numbers are the source's own.

    Otherwise the size comes from the payload's shape rather than any one string,
    no source line numbering exists to preserve, and the serialization is what
    pages.
    """

    longest = _longest_string(payload)
    if longest is not None and len(longest) > max_chars:
        return longest
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
