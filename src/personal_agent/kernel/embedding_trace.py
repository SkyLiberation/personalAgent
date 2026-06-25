from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from openai import OpenAI

from personal_agent.kernel.logging_utils import log_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingTraceResult:
    vector: list[float]
    model: str
    latency_ms: float
    input_chars: int
    provider: str = "openai_compatible"
    raw_response: Any = None


def traced_embedding(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    text: str,
    timeout_seconds: float = 30.0,
    metadata: dict[str, object] | None = None,
    upload_inputs_outputs: bool = False,
) -> EmbeddingTraceResult:
    runner = _traced_embedding if upload_inputs_outputs else _embedding_impl
    return runner(
        api_key=api_key,
        base_url=base_url,
        model=model,
        text=text,
        timeout_seconds=timeout_seconds,
        metadata=metadata or {},
    )


def log_embedding_fallback(
    *,
    model: str,
    reason: str,
    provider: str,
    input_chars: int,
) -> None:
    log_event(
        logger,
        logging.WARNING,
        "embedding.fallback",
        model=model,
        provider=provider,
        reason=reason[:500],
        input_chars=input_chars,
    )


def log_local_embedding(
    *,
    model: str,
    input_chars: int,
    metadata: dict[str, object] | None = None,
) -> None:
    log_event(
        logger,
        logging.INFO,
        "embedding.local",
        model=model,
        provider="local",
        input_chars=input_chars,
        **(metadata or {}),
    )


def _traceable(fn):
    try:
        from langsmith import traceable
    except Exception:
        return fn
    return traceable(name="embedding.create", run_type="embedding")(fn)


@_traceable
def _traced_embedding(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    text: str,
    timeout_seconds: float,
    metadata: dict[str, object],
) -> EmbeddingTraceResult:
    return _embedding_impl(
        api_key=api_key,
        base_url=base_url,
        model=model,
        text=text,
        timeout_seconds=timeout_seconds,
        metadata=metadata,
    )


def _embedding_impl(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    text: str,
    timeout_seconds: float,
    metadata: dict[str, object],
) -> EmbeddingTraceResult:
    input_text = text[:8000]
    start = perf_counter()
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout_seconds,
    )
    response = client.embeddings.create(model=model, input=input_text)
    latency_ms = round((perf_counter() - start) * 1000, 2)
    vector = [float(value) for value in response.data[0].embedding]
    log_event(
        logger,
        logging.INFO,
        "embedding.call",
        model=model,
        provider="openai_compatible",
        latency_ms=latency_ms,
        input_chars=len(input_text),
        dimensions=len(vector),
        **metadata,
    )
    return EmbeddingTraceResult(
        vector=vector,
        model=model,
        latency_ms=latency_ms,
        input_chars=len(input_text),
        raw_response=response,
    )
