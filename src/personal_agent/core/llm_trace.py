from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from openai import OpenAI

from .config import OpenAIConfig
from .logging_utils import log_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LlmTraceResult:
    content: str
    model: str
    latency_ms: float
    prompt_name: str
    prompt_version: str
    raw_response: Any = None


def traced_chat_completion(
    config: OpenAIConfig,
    *,
    prompt_name: str,
    prompt_version: str = "v1",
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0,
    max_tokens: int = 500,
    response_format: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    upload_inputs_outputs: bool = False,
) -> LlmTraceResult:
    runner = _traced_chat_completion if upload_inputs_outputs else _chat_completion_impl
    return runner(
        config,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        metadata=metadata or {},
    )


def log_llm_parse(
    *,
    prompt_name: str,
    prompt_version: str = "v1",
    model: str,
    parse_ok: bool,
    parse_schema: str = "",
    parse_error: str = "",
    latency_ms: float | None = None,
) -> None:
    log_event(
        logger,
        logging.INFO if parse_ok else logging.WARNING,
        "llm.parse",
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        model=model,
        parse_schema=parse_schema or None,
        parse_ok=parse_ok,
        parse_error=parse_error[:500] if parse_error else None,
        latency_ms=latency_ms,
    )


def _traceable(fn):
    try:
        from langsmith import traceable
    except Exception:
        return fn
    return traceable(name="llm.chat_completion", run_type="llm")(fn)


@_traceable
def _traced_chat_completion(
    config: OpenAIConfig,
    *,
    prompt_name: str,
    prompt_version: str,
    messages: list[dict[str, str]],
    model: str | None,
    temperature: float,
    max_tokens: int,
    response_format: dict[str, object] | None,
    metadata: dict[str, object],
) -> LlmTraceResult:
    return _chat_completion_impl(
        config,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        metadata=metadata,
    )


def _chat_completion_impl(
    config: OpenAIConfig,
    *,
    prompt_name: str,
    prompt_version: str,
    messages: list[dict[str, str]],
    model: str | None,
    temperature: float,
    max_tokens: int,
    response_format: dict[str, object] | None,
    metadata: dict[str, object],
) -> LlmTraceResult:
    resolved_model = model or config.small_model or config.model
    start = perf_counter()
    client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
    )
    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    response = client.chat.completions.create(**kwargs)
    latency_ms = round((perf_counter() - start) * 1000, 2)
    content = (response.choices[0].message.content or "").strip()
    log_event(
        logger,
        logging.INFO,
        "llm.call",
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        model=resolved_model,
        latency_ms=latency_ms,
        response_chars=len(content),
        **metadata,
    )
    return LlmTraceResult(
        content=content,
        model=resolved_model,
        latency_ms=latency_ms,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        raw_response=response,
    )
