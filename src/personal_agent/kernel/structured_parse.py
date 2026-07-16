"""Unified structured-output guardrail: parse + repair + validate + telemetry.

One place that turns a raw model string into a validated Pydantic object. Before
this, query_planner / replanner / rerankers / react helpers / thread-summary each
hand-rolled ``json.loads`` + fence stripping + truncation repair + ``log_llm_parse``
in slightly different ways, plus three separate "unwrap the model's JSON" helpers
(``_repair_truncated_json``, ``_extract_json_object``, ``strip_json_fence``).

Callers now do::

    res = parse_structured(raw, MyModel, operation="x", model_name=model)
    if not res.ok:
        ...fallback...
    value = res.value

The JSON-unwrap primitives (:func:`extract_json_object`, :func:`repair_truncated_json`,
:func:`load_json_lenient`) live here as the single implementation.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from personal_agent.kernel.llm_schemas import strip_json_fence
from personal_agent.kernel.llm_trace import log_llm_parse

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCED_OBJECT = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", flags=re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class StructuredParseResult(Generic[T]):
    """Outcome of one structured parse. ``value`` is set only when ``ok``."""

    ok: bool
    value: T | None
    error: str | None
    raw: str


def extract_json_object(text: str) -> str | None:
    """Pull a JSON object out of prose: a ```json fenced block, else outermost ``{...}``."""
    fenced = _FENCED_OBJECT.search(text)
    if fenced:
        return fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1].strip()
    return None


def repair_truncated_json(raw: str) -> str:
    """Best-effort close of JSON truncated by ``max_tokens`` (balance quotes/brackets)."""
    stripped = raw.rstrip()
    open_braces = stripped.count("{") - stripped.count("}")
    open_brackets = stripped.count("[") - stripped.count("]")
    in_string = False
    escape_next = False
    for ch in stripped:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
    if in_string:
        stripped += '"'
    stripped += "]" * open_brackets
    stripped += "}" * open_braces
    return stripped


def load_json_lenient(content: str) -> object:
    """Strip fences, then parse; on failure try an embedded object and truncation repair.

    Raises ``json.JSONDecodeError``/``ValueError`` when nothing parses.
    """
    text = strip_json_fence(content or "").strip()
    if not text:
        raise ValueError("empty content")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        extracted = extract_json_object(text)
        if extracted is not None:
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                text = extracted
        return json.loads(repair_truncated_json(text))


def parse_structured(
    content: str,
    model: type[T],
    *,
    operation: str,
    version: str = "v1",
    model_name: str = "",
    latency_ms: float | None = None,
) -> StructuredParseResult[T]:
    """Parse ``content`` into a validated ``model`` instance, emitting uniform telemetry.

    Never raises on bad model output — returns ``ok=False`` with the error so each
    caller keeps its own functional fallback. Programming errors in the model class
    itself still surface normally.
    """
    schema = model.__name__
    try:
        data = load_json_lenient(content)
        value = model.model_validate(data)
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
        log_llm_parse(
            prompt_name=operation,
            prompt_version=version,
            model=model_name,
            parse_schema=schema,
            parse_ok=False,
            parse_error=str(exc),
            latency_ms=latency_ms,
        )
        return StructuredParseResult(ok=False, value=None, error=str(exc), raw=content)
    log_llm_parse(
        prompt_name=operation,
        prompt_version=version,
        model=model_name,
        parse_schema=schema,
        parse_ok=True,
        latency_ms=latency_ms,
    )
    return StructuredParseResult(ok=True, value=value, error=None, raw=content)


__all__ = [
    "StructuredParseResult",
    "extract_json_object",
    "load_json_lenient",
    "parse_structured",
    "repair_truncated_json",
]
