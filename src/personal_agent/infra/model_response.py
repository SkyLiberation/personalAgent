"""Normalize provider responses into the existing typed model wire contracts.

This module owns response envelopes, streamed content, native action calls and
usage aggregation. SDK calls, deadlines, protocol repair and observability are
assembled by ``structured_model``; Application owns business admission.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

from personal_agent.capabilities.contracts.model import (
    ModelActionInvocation,
    StructuredModelRequest,
    StructuredOutputFailure,
)
from personal_agent.kernel.structured_parse import load_json_lenient


class _EmptyNestedCompletionError(RuntimeError):
    """A provider accepted the request but returned no nested completion."""


def _usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    values: dict[str, int] = {}
    for key, attrs in (
        ("input_tokens", ("input_tokens", "prompt_tokens")),
        ("output_tokens", ("output_tokens", "completion_tokens")),
        ("total_tokens", ("total_tokens",)),
    ):
        for attr in attrs:
            value = getattr(usage, attr, None)
            if isinstance(value, int):
                values[key] = value
                break
    if (
        "total_tokens" not in values
        and "input_tokens" in values
        and "output_tokens" in values
    ):
        values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
    return values


def _aggregate_usage(responses: list[Any]) -> dict[str, int]:
    return _sum_usage([_usage(response) for response in responses])


def _sum_usage(usages: list[dict[str, int]]) -> dict[str, int]:
    """Keep complete component totals and the known total-token lower bound."""
    totals: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        values = [usage[key] for usage in usages if key in usage]
        if values and (key == "total_tokens" or len(values) == len(usages)):
            totals[key] = sum(values)
    return totals


def _require_chat_choices(response: Any) -> Any:
    choices = getattr(response, "choices", None)
    if not choices:
        raise RuntimeError("invalid provider response: missing chat completion choices")
    return choices


def _structured_chat_message(response: Any) -> Any:
    """Normalize provider-native and direct structured-content transports."""
    choices = getattr(response, "choices", None)
    if choices:
        message = choices[0].message
        return SimpleNamespace(
            content=_unwrap_structured_content(getattr(message, "content", "")),
            tool_calls=getattr(message, "tool_calls", None) or [],
        )
    if isinstance(response, str) and response.strip():
        return SimpleNamespace(
            content=_unwrap_structured_content(response),
            tool_calls=[],
        )
    if isinstance(response, dict):
        raw_choices = response.get("choices")
        if isinstance(raw_choices, list) and raw_choices:
            message = raw_choices[0].get("message", {})
            if isinstance(message, dict):
                return SimpleNamespace(
                    content=_unwrap_structured_content(message.get("content")),
                    tool_calls=message.get("tool_calls") or [],
                )
        return SimpleNamespace(
            content=json.dumps(response, ensure_ascii=False),
            tool_calls=[],
        )
    raise RuntimeError(
        "invalid provider response: missing structured completion content"
    )


def _unwrap_structured_content(content: Any) -> str:
    """Unwrap OpenAI-compatible providers that nest a completion envelope."""
    if isinstance(content, dict):
        candidate = json.dumps(content, ensure_ascii=False)
    else:
        candidate = str(content or "").strip()
    for _ in range(6):
        if not candidate:
            return ""
        try:
            decoded = load_json_lenient(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            return candidate
        if isinstance(decoded, str):
            candidate = decoded.strip()
            continue
        if not _is_chat_completion_envelope(decoded):
            return candidate
        # Decision Ownership Taxonomy: provider transport normalization.
        # Envelope structure uniquely identifies the nested content field;
        # this branch does not create or repair any Proposal semantics.
        nested = _chat_completion_envelope_content(decoded)
        candidate = (
            json.dumps(nested, ensure_ascii=False)
            if isinstance(nested, dict)
            else str(nested).strip()
        )
    return candidate


def _is_chat_completion_envelope(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    object_type = str(value.get("object") or "")
    return object_type.startswith("chat.completion") and "choices" in value


def _chat_completion_envelope_content(envelope: dict[str, Any]) -> Any:
    choices: Any = envelope.get("choices")
    if isinstance(choices, str):
        try:
            choices = load_json_lenient(choices)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                "invalid provider response: nested chat completion choices are malformed"
            ) from exc
    if not isinstance(choices, list) or not choices:
        raise _EmptyNestedCompletionError(
            "invalid provider response: nested chat completion choices are missing"
        )
    choice = choices[0]
    if isinstance(choice, str):
        try:
            choice = load_json_lenient(choice)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                "invalid provider response: nested chat completion choice is malformed"
            ) from exc
    if not isinstance(choice, dict):
        raise RuntimeError(
            "invalid provider response: nested chat completion choice is invalid"
        )
    message: Any = choice.get("message") or choice.get("delta")
    if isinstance(message, str):
        try:
            message = load_json_lenient(message)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                "invalid provider response: nested chat completion message is malformed"
            ) from exc
    if isinstance(message, dict):
        nested = message.get("content")
        if nested is None:
            nested = message.get("parsed")
        if nested is not None:
            return nested
    if choice.get("text") is not None:
        return choice["text"]
    raise RuntimeError(
        "invalid provider response: nested chat completion content is missing"
    )


def _is_sse_payload(response: Any) -> bool:
    return isinstance(response, str) and response.lstrip().startswith("data:")


def _collect_streamed_chat_response(stream: Any) -> Any:
    content_parts: list[str] = []
    model = ""
    usage = None
    for chunk in stream:
        model = getattr(chunk, "model", None) or model
        usage = getattr(chunk, "usage", None) or usage
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None)
        if isinstance(content, str):
            content_parts.append(content)
    content = "".join(content_parts)
    if not content:
        raise RuntimeError(
            "invalid provider response: missing streamed completion content"
        )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))
        ],
        model=model,
        usage=usage,
    )


def _extract_action_invocations(
    message: Any,
    request: StructuredModelRequest[Any],
) -> tuple[ModelActionInvocation, ...]:
    """Normalize call structure; the Application owns declared-action admission."""
    tool_calls = getattr(message, "tool_calls", None) or []
    if not tool_calls:
        raise StructuredOutputFailure(
            request.operation,
            "provider returned no action call for a tool-calling request",
            reason_code="provider_action_missing",
        )
    seen_call_ids: set[str] = set()
    normalized: list[ModelActionInvocation] = []
    for call in tool_calls:
        if isinstance(call, dict):
            call_id = str(call.get("id") or "")
            call_type = str(call.get("type") or "function")
            function = call.get("function")
        else:
            call_id = str(getattr(call, "id", "") or "")
            call_type = str(getattr(call, "type", "function") or "function")
            function = getattr(call, "function", None)
        if call_type != "function":
            raise StructuredOutputFailure(
                request.operation,
                f"unsupported provider action type {call_type!r}",
                reason_code="provider_action_type_unsupported",
            )
        if not call_id or call_id in seen_call_ids:
            reason = "missing" if not call_id else "duplicate"
            raise StructuredOutputFailure(
                request.operation,
                f"provider action call_id is {reason}",
                reason_code=(
                    "provider_action_call_id_missing"
                    if not call_id
                    else "provider_action_call_id_duplicate"
                ),
            )
        seen_call_ids.add(call_id)
        if isinstance(function, dict):
            name = str(function.get("name") or "")
            raw_arguments = function.get("arguments", "{}")
        else:
            name = str(getattr(function, "name", "") or "")
            raw_arguments = getattr(function, "arguments", "{}")
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                raise StructuredOutputFailure(
                    request.operation,
                    f"model action {name!r} returned invalid JSON arguments",
                    reason_code="provider_action_arguments_invalid_json",
                ) from exc
        else:
            arguments = raw_arguments
        if not isinstance(arguments, dict):
            raise StructuredOutputFailure(
                request.operation,
                f"model action {name!r} arguments require an object",
                reason_code="provider_action_arguments_not_object",
            )
        try:
            invocation = ModelActionInvocation(
                call_id=call_id,
                name=name,
                arguments=arguments,
            )
        except ValidationError as exc:
            raise StructuredOutputFailure(
                request.operation,
                "provider action name does not satisfy the wire contract",
                reason_code="provider_action_unknown",
            ) from exc
        normalized.append(invocation)
    return tuple(normalized)
