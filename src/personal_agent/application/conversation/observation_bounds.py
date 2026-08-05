"""How much of one action observation may enter the model context.

The loop's token ceiling cannot own this. ``LoopBudgetPolicy.max_total_tokens``
is consulted against *committed* usage at the top of a turn, so a single
oversized tool return inside a turn has already been sent by the time the
ceiling is next read. E21 measured one read at 1,940,197 payload characters and
776,720 committed tokens against a declared 32,000 ceiling.

Bounding here is paging, not summarising. The excerpt keeps head and tail,
states how much was dropped, and travels with a reference the model can read by
keyword or line range. Which part of the omitted text matters stays a model
decision; this module only decides how much fits.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

MAX_OBSERVATION_PAYLOAD_CHARS = 20_000
"""Serialized ceiling for one observation payload entering the context."""

_HEAD_RATIO = 0.2
_MIN_STRING_CHARS = 400
_OMISSION_TEMPLATE = "\n... [{omitted} characters omitted from the middle] ...\n"


@dataclass(frozen=True, slots=True)
class BoundedPayload:
    """A payload sized for the context, plus what bounding cost."""

    payload: dict[str, Any]
    omitted_chars: int
    original_chars: int

    @property
    def is_bounded(self) -> bool:
        return self.omitted_chars > 0


def serialized_length(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str))


def _bound_string(text: str, limit: int) -> tuple[str, int]:
    if len(text) <= limit:
        return text, 0
    head_chars = max(1, int(limit * _HEAD_RATIO))
    tail_chars = max(1, limit - head_chars)
    omitted = len(text) - head_chars - tail_chars
    marker = _OMISSION_TEMPLATE.format(omitted=omitted)
    return text[:head_chars] + marker + text[len(text) - tail_chars:], omitted


def _bound_value(value: Any, limit: int) -> tuple[Any, int]:
    if isinstance(value, str):
        return _bound_string(value, limit)
    if isinstance(value, dict):
        bounded: dict[str, Any] = {}
        omitted = 0
        for key, item in value.items():
            bounded[key], dropped = _bound_value(item, limit)
            omitted += dropped
        return bounded, omitted
    if isinstance(value, (list, tuple)):
        items: list[Any] = []
        omitted = 0
        for item in value:
            bounded_item, dropped = _bound_value(item, limit)
            items.append(bounded_item)
            omitted += dropped
        return items, omitted
    return value, 0


_SCALAR_KEY_CHARS = 200


def _bound_as_text(
    payload: dict[str, Any], max_chars: int, original_chars: int
) -> BoundedPayload:
    """Last resort for payloads whose size comes from their shape, not one string.

    Shrinking a per-string allowance cannot bound a payload built from thousands
    of medium strings, so the structure is given up and the whole serialization is
    paged as one excerpt. Small scalar keys are kept verbatim, because ``status``
    and ``ok`` are what the model reads first.
    """

    kept = {
        key: value
        for key, value in payload.items()
        if not isinstance(value, (dict, list, tuple))
        and serialized_length(value) <= _SCALAR_KEY_CHARS
    }
    kept["excerpt_is_serialized_text"] = True
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    budget = max(1, max_chars - serialized_length(kept) - _SCALAR_KEY_CHARS)
    # Escaping makes the serialized cost of an excerpt unpredictable, so shrink
    # until the whole payload is measured to fit rather than trusting an estimate.
    while True:
        excerpt, omitted = _bound_string(serialized, budget)
        kept["observation_excerpt"] = excerpt
        if serialized_length(kept) <= max_chars or budget <= 1:
            return BoundedPayload(
                payload=kept, omitted_chars=omitted, original_chars=original_chars
            )
        budget = max(1, budget - (serialized_length(kept) - max_chars) - 1)


def bound_observation_payload(
    payload: dict[str, Any],
    *,
    max_chars: int = MAX_OBSERVATION_PAYLOAD_CHARS,
) -> BoundedPayload:
    """Fit ``payload`` inside ``max_chars`` by paging its long strings.

    The per-string allowance shrinks until the whole serialized payload fits, so
    a payload whose size comes from many medium strings is bounded as reliably
    as one dominated by a single huge string.
    """

    original_chars = serialized_length(payload)
    if original_chars <= max_chars:
        return BoundedPayload(payload=payload, omitted_chars=0, original_chars=original_chars)
    limit = max_chars
    while True:
        bounded, omitted = _bound_value(payload, limit)
        if serialized_length(bounded) <= max_chars:
            return BoundedPayload(
                payload=bounded,
                omitted_chars=omitted,
                original_chars=original_chars,
            )
        if limit <= _MIN_STRING_CHARS:
            return _bound_as_text(payload, max_chars, original_chars)
        limit = max(_MIN_STRING_CHARS, limit // 2)


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


MAX_EXCERPT_LINES = 200
"""Lines returned by one re-read of an offloaded payload."""

_CONTEXT_BEFORE = 2
_CONTEXT_AFTER = 4
"""Lines kept around each keyword hit, as ``grep -C`` does.

A bare matching line is rarely the answer. Searching a maintainer file for a
section name returns the section header, and what the goal needed sat three
lines under it; without context the model must guess a second call or answer
from the header. Context is what makes one search answer one question.
"""


@dataclass(frozen=True, slots=True)
class PayloadExcerpt:
    """A window into an offloaded payload, plus how to ask for the next one."""

    lines: tuple[tuple[int, str], ...]
    total_lines: int
    matched_lines: tuple[int, ...]
    next_start_line: int | None


def excerpt_payload_text(
    text: str,
    *,
    keyword: str = "",
    start_line: int = 1,
    max_lines: int = MAX_EXCERPT_LINES,
) -> PayloadExcerpt:
    """Return a 1-indexed line window of ``text``, optionally keyword-anchored.

    With a keyword, each hit is returned with the lines around it, wherever it
    sits in the payload — which is what makes a fact at 96% of a file reachable
    without paging through the first 96%, and what lets a section header answer a
    question about the lines under it. Without a keyword the window starts at
    ``start_line``. Selecting the keyword and deciding whether the window answered
    the goal stay with the model.
    """

    all_lines = text.splitlines()
    total = len(all_lines)
    last_hit: int | None = None
    if keyword:
        folded = keyword.casefold()
        matched = tuple(
            number for number, line in enumerate(all_lines, start=1) if folded in line.casefold()
        )
        chosen: list[int] = []
        for hit in (number for number in matched if number >= start_line):
            window = range(
                max(1, hit - _CONTEXT_BEFORE), min(total, hit + _CONTEXT_AFTER) + 1
            )
            addition = [number for number in window if number not in set(chosen)]
            if len(chosen) + len(addition) > max_lines and chosen:
                break
            chosen.extend(addition[: max_lines - len(chosen)])
            last_hit = hit
            if len(chosen) >= max_lines:
                break
        chosen.sort()
    else:
        matched = ()
        chosen = [
            number for number in range(max(1, start_line), total + 1)][:max_lines]
    lines = tuple((number, all_lines[number - 1]) for number in chosen)
    last = last_hit if keyword else (chosen[-1] if chosen else None)
    remaining = bool(matched) and any(number > (last or 0) for number in matched)
    if not keyword:
        remaining = last is not None and last < total
    return PayloadExcerpt(
        lines=lines,
        total_lines=total,
        matched_lines=matched,
        next_start_line=(last + 1) if (last is not None and remaining) else None,
    )


__all__ = [
    "MAX_EXCERPT_LINES",
    "MAX_OBSERVATION_PAYLOAD_CHARS",
    "BoundedPayload",
    "PayloadExcerpt",
    "bound_observation_payload",
    "excerpt_payload_text",
    "select_offload_text",
    "serialized_length",
]
