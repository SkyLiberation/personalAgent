from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from openai import OpenAI

from .config import OpenAIConfig
from .logging_utils import log_event

logger = logging.getLogger(__name__)


def _is_reasoning_model(model: str | None) -> bool:
    """Whether ``model`` belongs to the gpt-5 reasoning family.

    These models reject a non-default ``temperature`` and use
    ``max_completion_tokens`` instead of ``max_tokens``.
    """
    name = (model or "").lower()
    return name.startswith("gpt-5") or name.startswith("o1") or name.startswith("o3")


@dataclass(frozen=True, slots=True)
class LlmTraceResult:
    content: str
    model: str
    latency_ms: float
    prompt_name: str
    prompt_version: str
    raw_response: Any = None
    tool_calls: list[dict[str, Any]] | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


def _extract_usage(response: Any) -> dict[str, int]:
    """Pull token counts from an OpenAI-style response, tolerating absences."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    counts: dict[str, int] = {}
    for key, attr in (
        ("input_tokens", "prompt_tokens"),
        ("output_tokens", "completion_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        value = getattr(usage, attr, None)
        if isinstance(value, int):
            counts[key] = value
    return counts


def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    tool_calls = getattr(message, "tool_calls", None) or []
    normalized: list[dict[str, Any]] = []
    for call in tool_calls:
        if isinstance(call, dict):
            normalized.append(call)
            continue
        function = getattr(call, "function", None)
        normalized.append({
            "id": getattr(call, "id", ""),
            "type": getattr(call, "type", "function"),
            "function": {
                "name": getattr(function, "name", ""),
                "arguments": getattr(function, "arguments", "{}"),
            },
        })
    return normalized


def _report_usage_to_run_tree(usage: dict[str, int]) -> None:
    """Attach token usage to the active LangSmith run so cost rolls up."""
    if not usage:
        return
    try:
        from langsmith.run_helpers import get_current_run_tree

        run_tree = get_current_run_tree()
        if run_tree is not None:
            run_tree.set(usage_metadata=usage)
    except Exception:  # pragma: no cover - tracing must never break the call
        pass


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
    tools: list[dict[str, object]] | None = None,
    tool_choice: str | dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    upload_inputs_outputs: bool = False,
    extra_body: dict[str, object] | None = None,
) -> LlmTraceResult:
    runner = _traced_chat_completion if upload_inputs_outputs else _redacted_traced_chat_completion
    return runner(
        config,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        tools=tools,
        tool_choice=tool_choice,
        metadata=metadata or {},
        extra_body=extra_body,
        langsmith_extra={
            "name": f"llm.{prompt_name}",
            "metadata": {
                "prompt_name": prompt_name,
                "prompt_version": prompt_version,
                "model": model or config.small_model or config.model,
                "upload_inputs_outputs": upload_inputs_outputs,
                **(metadata or {}),
            },
        },
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


def _redacted_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    messages = inputs.get("messages") or []
    message_count = len(messages) if isinstance(messages, list) else 0
    message_chars = 0
    roles: list[str] = []
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            roles.append(str(message.get("role") or ""))
            message_chars += len(str(message.get("content") or ""))
    return {
        "prompt_name": inputs.get("prompt_name"),
        "prompt_version": inputs.get("prompt_version"),
        "model": inputs.get("model") or getattr(inputs.get("config"), "small_model", None)
        or getattr(inputs.get("config"), "model", None),
        "temperature": inputs.get("temperature"),
        "max_tokens": inputs.get("max_tokens"),
        "response_format": inputs.get("response_format"),
        "tool_names": [
            str((tool.get("function") or {}).get("name"))
            for tool in (inputs.get("tools") or [])
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        ],
        "tool_choice": inputs.get("tool_choice"),
        "message_count": message_count,
        "message_roles": roles,
        "message_chars": message_chars,
        "metadata": inputs.get("metadata") or {},
    }


def _redacted_outputs(output: LlmTraceResult) -> dict[str, Any]:
    return {
        "prompt_name": output.prompt_name,
        "prompt_version": output.prompt_version,
        "model": output.model,
        "latency_ms": output.latency_ms,
        "response_chars": len(output.content or ""),
        "tool_call_count": len(output.tool_calls or []),
        "input_tokens": output.input_tokens,
        "output_tokens": output.output_tokens,
        "total_tokens": output.total_tokens,
    }


def _traceable_redacted(fn):
    try:
        from langsmith import traceable
    except Exception:
        return fn
    return traceable(
        name="llm.chat_completion",
        run_type="llm",
        process_inputs=_redacted_inputs,
        process_outputs=_redacted_outputs,
    )(fn)


@_traceable_redacted
def _redacted_traced_chat_completion(
    config: OpenAIConfig,
    *,
    prompt_name: str,
    prompt_version: str,
    messages: list[dict[str, str]],
    model: str | None,
    temperature: float,
    max_tokens: int,
    response_format: dict[str, object] | None,
    tools: list[dict[str, object]] | None,
    tool_choice: str | dict[str, object] | None,
    metadata: dict[str, object],
    langsmith_extra: dict[str, object] | None = None,
    extra_body: dict[str, object] | None = None,
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
        tools=tools,
        tool_choice=tool_choice,
        metadata=metadata,
        extra_body=extra_body,
    )


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
    tools: list[dict[str, object]] | None,
    tool_choice: str | dict[str, object] | None,
    metadata: dict[str, object],
    langsmith_extra: dict[str, object] | None = None,
    extra_body: dict[str, object] | None = None,
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
        tools=tools,
        tool_choice=tool_choice,
        metadata=metadata,
        extra_body=extra_body,
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
    tools: list[dict[str, object]] | None,
    tool_choice: str | dict[str, object] | None,
    metadata: dict[str, object],
    extra_body: dict[str, object] | None = None,
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
    }
    if _is_reasoning_model(resolved_model):
        # gpt-5 family rejects non-default temperature and renamed the token
        # cap to ``max_completion_tokens``. Omit temperature so the API uses
        # its only supported value (1).
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["temperature"] = temperature
        kwargs["max_tokens"] = max_tokens
    if response_format is not None:
        kwargs["response_format"] = response_format
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if extra_body:
        kwargs["extra_body"] = extra_body
    response = client.chat.completions.create(**kwargs)
    latency_ms = round((perf_counter() - start) * 1000, 2)
    message = response.choices[0].message
    content = (message.content or "").strip()
    tool_calls = _extract_tool_calls(message)
    usage = _extract_usage(response)
    _report_usage_to_run_tree(usage)
    log_event(
        logger,
        logging.INFO,
        "llm.call",
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        model=resolved_model,
        latency_ms=latency_ms,
        response_chars=len(content),
        tool_call_count=len(tool_calls),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        total_tokens=usage.get("total_tokens"),
        **metadata,
    )
    return LlmTraceResult(
        content=content,
        model=resolved_model,
        latency_ms=latency_ms,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        raw_response=response,
        tool_calls=tool_calls,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        total_tokens=usage.get("total_tokens"),
    )
