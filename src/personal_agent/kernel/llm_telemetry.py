"""Run-scoped LLM usage collection for evaluation and observability."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(slots=True)
class LlmUsageTotals:
    call_count: int = 0
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


_ACTIVE_USAGE: ContextVar[LlmUsageTotals | None] = ContextVar(
    "personal_agent_active_llm_usage",
    default=None,
)


def record_llm_usage(
    *,
    latency_ms: float = 0.0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
) -> None:
    totals = _ACTIVE_USAGE.get()
    if totals is None:
        return
    totals.call_count += 1
    totals.latency_ms += max(0.0, float(latency_ms))
    totals.input_tokens += max(0, int(input_tokens or 0))
    totals.output_tokens += max(0, int(output_tokens or 0))
    if total_tokens is not None:
        totals.total_tokens += max(0, int(total_tokens))
    else:
        totals.total_tokens += max(0, int(input_tokens or 0)) + max(
            0, int(output_tokens or 0)
        )


@contextmanager
def collect_llm_usage() -> Iterator[LlmUsageTotals]:
    totals = LlmUsageTotals()
    token = _ACTIVE_USAGE.set(totals)
    try:
        yield totals
    finally:
        _ACTIVE_USAGE.reset(token)
