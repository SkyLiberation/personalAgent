"""Typed model ports and OpenAI-compatible adapters.

The port (``StructuredModelClient`` / ``StreamingModelClient``) is the only LLM
dependency application code is allowed to hold. Provider/model structured-output
capabilities are selected at composition time: ``StrictJsonSchemaAdapter`` uses
native strict ``json_schema`` while ``JsonObjectStructuredAdapter`` uses JSON
mode plus the same Pydantic contract in the prompt. Application code is unaware
of that transport distinction.

The adapter is **pure**: it only performs the API call and extracts
content / typed action invocations / usage / latency. No tracing (langsmith spans,
``record_llm_usage``, ``log_event``) lives inside it — that is the job of the
``ObservedStructuredModelClient`` decorator, applied at composition time. This
keeps the call logic decoupled from observability concerns and lets tracing be
added, removed or swapped without touching the adapter.
"""

from __future__ import annotations

import json
import logging
from queue import Empty, Queue
from threading import Thread
from dataclasses import replace
from time import perf_counter, sleep
from types import SimpleNamespace
from typing import Any, Callable, Iterator, Protocol
from urllib.parse import urlparse

from openai import APIError, APIStatusError, OpenAI
from pydantic import BaseModel
from personal_agent.capabilities.contracts.model import (
    ModelActionInvocation,
    StreamChunk,
    StreamingModelClient,
    StructuredModelClient,
    StructuredModelRequest,
    StructuredModelResponse,
    ModelInvocationUnavailable,
    StructuredOutputFailure,
    StructuredOutputT,
)

from personal_agent.kernel.structured_parse import load_json_lenient, parse_structured
from personal_agent.kernel.config_models import LangSmithConfig, OpenAIConfig, StructuredConfig
from personal_agent.kernel.llm_schemas import structured_response_format
from personal_agent.kernel.llm_telemetry import record_llm_usage
from personal_agent.kernel.logging_utils import log_event

logger = logging.getLogger(__name__)


class _EmptyNestedCompletionError(RuntimeError):
    """A provider accepted the request but returned no nested completion."""


class ModelCallDeadlineExceeded(ModelInvocationUnavailable, TimeoutError):
    """A provider call exceeded its configured wall-clock deadline."""

    def __init__(self, message: str, *, operation: str | None = None) -> None:
        self.message = message
        super().__init__(
            operation or "model_call",
            "provider_timeout",
            retryable=True,
        )
        self.args = (message,)


def _close_provider_client(client: OpenAI) -> None:
    close = getattr(client, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        logger.debug("failed to close timed-out model provider client", exc_info=True)


def _run_with_deadline(
    call: Callable[[], Any],
    *,
    client: OpenAI,
    operation: str,
    timeout_seconds: float,
) -> Any:
    """Bound total provider time, including endpoints that drip response bytes.

    httpx timeouts limit individual connect/read/write/pool operations. They do
    not cap total response time, so a broken endpoint can keep a request alive
    indefinitely by sending one chunk before each read timeout. The adapter owns
    this transport fact and enforces the configured deadline around the complete
    SDK call.
    """
    outcomes: Queue[tuple[bool, Any]] = Queue(maxsize=1)

    def invoke() -> None:
        try:
            outcomes.put((True, call()))
        except BaseException as exc:
            outcomes.put((False, exc))

    worker = Thread(
        target=invoke,
        name=f"model-provider-{operation}",
        daemon=True,
    )
    worker.start()
    try:
        succeeded, value = outcomes.get(timeout=timeout_seconds)
    except Empty as exc:
        Thread(
            target=_close_provider_client,
            args=(client,),
            name=f"model-provider-cancel-{operation}",
            daemon=True,
        ).start()
        raise ModelCallDeadlineExceeded(
            f"{operation} provider call exceeded {timeout_seconds:g}s wall-clock deadline",
            operation=operation,
        ) from exc
    if succeeded:
        return value
    raise value


def _is_reasoning_model(model: str) -> bool:
    name = model.lower()
    return (
        name.startswith("gpt-5")
        or name.startswith("o1")
        or name.startswith("o3")
        or name.startswith("mimo")
    )


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
    return values


def _aggregate_usage(responses: list[Any]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for response in responses:
        for key, value in _usage(response).items():
            totals[key] = totals.get(key, 0) + value
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
    raise RuntimeError("invalid provider response: missing structured completion content")


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
    return (
        object_type.startswith("chat.completion")
        and "choices" in value
    )


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
        raise RuntimeError("invalid provider response: missing streamed completion content")
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))],
        model=model,
        usage=usage,
    )


def _report_usage_to_run_tree(response: StructuredModelResponse[Any]) -> None:
    usage = {
        key: value
        for key, value in {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "total_tokens": response.total_tokens,
        }.items()
        if value is not None
    }
    if not usage:
        return
    try:
        from langsmith.run_helpers import get_current_run_tree

        run_tree = get_current_run_tree()
        if run_tree is not None:
            run_tree.set(usage_metadata=usage)
    except Exception:
        pass


def _extract_action_invocations(
    message: Any,
    request: StructuredModelRequest[Any],
) -> tuple[ModelActionInvocation, ...]:
    """Validate provider tool calls before they cross the model Port boundary."""
    tool_calls = getattr(message, "tool_calls", None) or []
    if not tool_calls:
        raise StructuredOutputFailure(
            request.operation,
            "provider returned no action call for a tool-calling request",
            reason_code="provider_action_missing",
        )
    known_names = {definition.name for definition in request.action_definitions}
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
        if name not in known_names:
            raise StructuredOutputFailure(
                request.operation,
                f"provider selected unknown model action {name!r}",
                reason_code="provider_action_unknown",
            )
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
        normalized.append(
            ModelActionInvocation(
                call_id=call_id,
                name=name,
                arguments=arguments,
            )
        )
    return tuple(normalized)


class OpenAIModelClient:
    """Shared OpenAI-compatible Chat Completions adapter.

    Concrete structured-output adapters own request construction. This base owns
    only common SDK invocation, response normalization, typed validation, text /
    tool-calling requests and streaming.

    The adapter is **pure**: it only assembles kwargs, calls the SDK, extracts
    content / tool_calls / usage / latency, and returns structured objects. No
    tracing (langsmith spans, ``record_llm_usage``, ``log_event``) lives here —
    that is the job of ``ObservedStructuredModelClient`` /
    ``ObservedStreamingModelClient``, applied at composition time. This keeps
    the call logic decoupled from observability and lets tracing evolve without
    touching the adapter.

    ``config`` may be an ``OpenAIConfig`` or ``StructuredConfig`` (both expose
    ``api_key`` / ``base_url`` / ``timeout_seconds`` / ``max_retries``; the
    resolved model is ``model_override`` or ``config.model``). The SDK retry
    loop is disabled here: ``config.max_retries`` belongs to the typed-operation
    retry decorator assembled in the composition root. Keeping one retry owner
    prevents one configured budget from multiplying into nested provider
    requests. Streaming calls also fail closed because replaying a partially
    observed stream is not generally safe.
    """

    def __init__(
        self,
        config: OpenAIConfig | StructuredConfig,
        *,
        model_override: str | None = None,
    ) -> None:
        self._config = config
        self._model_override = model_override
        self._structured_streaming = False

    # -- shared helpers --------------------------------------------------

    @property
    def _resolved_model(self) -> str:
        return self._model_override or self._config.model

    def _client(self) -> OpenAI:
        return OpenAI(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
            max_retries=0,
        )

    def _chat_kwargs(
        self,
        request: StructuredModelRequest[Any],
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        model = self._resolved_model
        kwargs: dict[str, Any] = {"model": model, "messages": request.messages}
        if stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
        if _is_reasoning_model(model):
            kwargs["max_completion_tokens"] = request.max_tokens
            if request.reasoning_effort is not None:
                kwargs["reasoning_effort"] = request.reasoning_effort
        else:
            kwargs["temperature"] = request.temperature
            kwargs["max_tokens"] = request.max_tokens
        if request.kind == "text" and request.response_format is not None:
            kwargs["response_format"] = request.response_format
        if request.kind == "tool_calling":
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": definition.name,
                        "description": definition.description,
                        "parameters": definition.input_schema,
                        "strict": True,
                    },
                }
                for definition in request.action_definitions
            ]
            if request.action_choice is not None:
                kwargs["tool_choice"] = request.action_choice
        config_extra = getattr(self._config, "extra_body", None) or {}
        merged_extra = {**config_extra, **(request.extra_body or {})}
        if merged_extra:
            kwargs["extra_body"] = merged_extra
        return kwargs

    @staticmethod
    def _default_value(request: StructuredModelRequest[Any]) -> Any:
        try:
            return request.output_type()  # type: ignore[call-arg]
        except Exception:
            return None

    def _create_structured_completion(
        self,
        client: OpenAI,
        request: StructuredModelRequest[Any],
    ) -> Any:
        kwargs = self._chat_kwargs(request)
        if not self._structured_streaming:
            return self._create_chat_completion(client, request.operation, kwargs)
        streaming_kwargs = {
            **kwargs,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        try:
            return _run_with_deadline(
                lambda: _collect_streamed_chat_response(
                    client.chat.completions.create(**streaming_kwargs)
                ),
                client=client,
                operation=request.operation,
                timeout_seconds=self._config.timeout_seconds,
            )
        except (APIStatusError, APIError) as exc:
            raise self._provider_unavailable(request.operation, exc) from exc

    def _provider_unavailable(
        self,
        operation: str,
        exc: Exception,
    ) -> ModelInvocationUnavailable:
        status_code = getattr(exc, "status_code", None)
        retryable = status_code in {408, 409, 429} or status_code is None or status_code >= 500
        category = (
            "provider_rejected"
            if status_code is not None and status_code < 500
            else "provider_transport"
        )
        return ModelInvocationUnavailable(
            operation,
            category,
            model=self._resolved_model,
            provider_host=urlparse(self._config.base_url).hostname,
            status_code=status_code,
            retryable=retryable,
        )

    def _create_chat_completion(
        self,
        client: OpenAI,
        operation: str,
        kwargs: dict[str, Any],
    ) -> Any:
        try:
            return _run_with_deadline(
                lambda: client.chat.completions.create(**kwargs),
                client=client,
                operation=operation,
                timeout_seconds=self._config.timeout_seconds,
            )
        except (APIStatusError, APIError) as exc:
            raise self._provider_unavailable(operation, exc) from exc

    # -- unified non-streaming entrypoint -------------------------------

    def generate(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]:
        if request.kind == "structured":
            return self._generate_structured(request)
        return self._generate_chat(request)

    def _generate_structured(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]:
        start = perf_counter()
        client = self._client()
        schema = request.output_type.model_json_schema()
        responses: list[Any] = []
        chat_request = self._structured_chat_request(request, schema, parse_error=None)
        response = self._create_structured_completion(client, chat_request)
        responses.append(response)
        response = self._normalize_streaming_structured_response(
            client,
            chat_request,
            response,
            responses,
        )
        latency_ms = round((perf_counter() - start) * 1000, 2)
        content, parsed, parse_error = self._parse_typed_response(
            request,
            response,
            latency_ms=latency_ms,
        )
        if parse_error is not None:
            log_event(
                logger,
                logging.WARNING,
                "llm.structured_schema_repair",
                operation=request.operation,
                version=request.version,
                parse_error=parse_error[:500],
            )
            repair_request = self._structured_chat_request(
                request,
                schema,
                parse_error=parse_error,
            )
            response = self._create_structured_completion(client, repair_request)
            responses.append(response)
            response = self._normalize_streaming_structured_response(
                client,
                repair_request,
                response,
                responses,
            )
            latency_ms = round((perf_counter() - start) * 1000, 2)
            content, parsed, parse_error = self._parse_typed_response(
                request,
                response,
                latency_ms=latency_ms,
            )
            if parse_error is not None:
                raise StructuredOutputFailure(request.operation, parse_error)
        usage = _aggregate_usage(responses)
        return StructuredModelResponse(
            value=parsed,
            model=getattr(response, "model", None) or self._resolved_model,
            latency_ms=latency_ms,
            content=content,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw_response=response,
        )

    def _structured_chat_request(
        self,
        request: StructuredModelRequest[StructuredOutputT],
        schema: dict[str, Any],
        *,
        parse_error: str | None,
    ) -> StructuredModelRequest[StructuredOutputT]:
        raise RuntimeError(
            "structured requests require an explicit structured-output adapter"
        )

    def _normalize_streaming_structured_response(
        self,
        client: OpenAI,
        chat_request: StructuredModelRequest[StructuredOutputT],
        response: Any,
        responses: list[Any],
    ) -> Any:
        try:
            _structured_chat_message(response)
        except _EmptyNestedCompletionError:
            if self._structured_streaming or not _is_sse_payload(response):
                return response
            self._structured_streaming = True
            response = self._create_structured_completion(client, chat_request)
            responses.append(response)
        return response

    def _parse_typed_response(
        self,
        request: StructuredModelRequest[StructuredOutputT],
        response: Any,
        *,
        latency_ms: float,
    ) -> tuple[str, StructuredOutputT | None, str | None]:
        try:
            message = _structured_chat_message(response)
        except Exception as exc:
            return "", None, str(exc)
        content = (message.content or "").strip()
        if not content:
            choice = _require_chat_choices(response)[0]
            details: list[str] = []
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason:
                details.append(f"finish_reason={finish_reason}")
            output_tokens = _usage(response).get("output_tokens")
            if output_tokens is not None:
                details.append(f"output_tokens={output_tokens}")
            suffix = f" ({', '.join(details)})" if details else ""
            return "", None, "provider returned empty structured content" + suffix
        if request.output_type is BaseModel:
            return content, self._default_value(request), None
        parse_result = parse_structured(
            content,
            request.output_type,
            operation=request.operation,
            version=request.version,
            model_name=getattr(response, "model", None) or self._resolved_model,
            latency_ms=latency_ms,
        )
        if not parse_result.ok:
            return content, None, parse_result.error or "invalid structured response"
        return content, parse_result.value, None

    def _generate_chat(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]:
        start = perf_counter()
        client = self._client()
        response = self._create_chat_completion(
            client,
            request.operation,
            self._chat_kwargs(request),
        )
        latency_ms = round((perf_counter() - start) * 1000, 2)
        message = _require_chat_choices(response)[0].message
        content = (message.content or "").strip()
        action_invocations = (
            _extract_action_invocations(message, request)
            if request.kind == "tool_calling"
            else ()
        )
        usage = _usage(response)
        return StructuredModelResponse(
            value=self._default_value(request),
            model=getattr(response, "model", None) or self._resolved_model,
            latency_ms=latency_ms,
            content=content,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw_response=response,
            action_invocations=action_invocations,
        )

    # -- unified streaming entrypoint ------------------------------------

    def stream(
        self,
        request: StructuredModelRequest[Any],
    ) -> Iterator[StreamChunk]:
        client = self._client()
        stream = client.chat.completions.create(**self._chat_kwargs(request, stream=True))
        full_text = ""
        usage: dict[str, int] = {}
        for chunk in stream:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                for key, attr in (
                    ("input_tokens", "prompt_tokens"),
                    ("output_tokens", "completion_tokens"),
                    ("total_tokens", "total_tokens"),
                ):
                    value = getattr(chunk_usage, attr, None)
                    if isinstance(value, int):
                        usage[key] = value
            choices = getattr(chunk, "choices", None)
            delta = choices[0].delta.content if choices else ""
            if delta:
                full_text += delta
                yield StreamChunk(delta=delta, accumulated=full_text)
        if usage:
            yield StreamChunk(delta="", accumulated=full_text, usage=usage)


def _schema_repair_instruction(
    schema: dict[str, Any],
    parse_error: str,
) -> dict[str, str]:
    return {
        "role": "system",
        "content": (
            "Your previous structured response was rejected by the typed output contract. "
            "The validation feedback and schema are authoritative. Never repeat a value "
            "identified as invalid in the feedback. For literal or enum failures, use only "
            "a value explicitly listed by the contract. Do not relabel invalid behavior "
            "with an allowed value merely to pass validation; when the enclosing array item "
            "is optional and no allowed value preserves its semantics, omit that item. "
            "Author a complete new JSON object for the original request; do not explain, "
            "patch, or refer to the rejected response. Respect all mutually exclusive "
            "fields and return only JSON. Validation feedback:\n"
            + parse_error[:2000]
            + "\nOutput schema:\n"
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        ),
    }


class StrictJsonSchemaAdapter(OpenAIModelClient):
    """Structured-output adapter for native strict JSON Schema providers."""

    def _structured_chat_request(
        self,
        request: StructuredModelRequest[StructuredOutputT],
        schema: dict[str, Any],
        *,
        parse_error: str | None,
    ) -> StructuredModelRequest[StructuredOutputT]:
        messages = request.messages
        if parse_error is not None:
            messages = [_schema_repair_instruction(schema, parse_error), *messages]
        return replace(
            request,
            messages=messages,
            kind="text",
            response_format=structured_response_format(request.operation, schema),
        )


class JsonObjectStructuredAdapter(OpenAIModelClient):
    """Structured-output adapter for providers that only support JSON mode."""

    def _structured_chat_request(
        self,
        request: StructuredModelRequest[StructuredOutputT],
        schema: dict[str, Any],
        *,
        parse_error: str | None,
    ) -> StructuredModelRequest[StructuredOutputT]:
        if parse_error is None:
            instruction = {
                "role": "system",
                "content": (
                    "Return exactly one JSON object that conforms to the output schema below. "
                    "Do not add Markdown, explanation, or fields absent from the schema. "
                    "Do not omit required fields.\nOutput schema:\n"
                    + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
                ),
            }
        else:
            instruction = _schema_repair_instruction(schema, parse_error)
        return replace(
            request,
            messages=[instruction, *request.messages],
            kind="text",
            response_format={"type": "json_object"},
        )


class RetryingStructuredModelClient:
    """Decorator for retrying transient structured model failures.

    This is the sole retry owner at the model-port boundary. The OpenAI SDK
    transport retry is disabled by ``OpenAIModelClient``; this wrapper retries
    the whole typed operation after transient transport/server failures so
    parsing, usage recording, tracing, and application code stay uniform.
    """

    def __init__(
        self,
        delegate: StructuredModelClient,
        *,
        max_retries: int,
        backoff_seconds: float = 2.0,
    ) -> None:
        self._delegate = delegate
        self._max_retries = max(0, int(max_retries))
        self._backoff_seconds = max(0.0, float(backoff_seconds))

    def generate(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]:
        retry_errors: list[str] = []
        for attempt in range(self._max_retries + 1):
            try:
                response = self._delegate.generate(request)
                return replace(
                    response,
                    retry_attempts=attempt,
                    retry_errors=retry_errors,
                )
            except Exception as exc:
                if attempt >= self._max_retries or not _is_retryable_model_error(exc):
                    if retry_errors:
                        log_event(
                            logger,
                            logging.WARNING,
                            "llm.retry.exhausted",
                            prompt_name=request.operation,
                            prompt_version=request.version,
                            attempts=attempt + 1,
                            retry_errors=retry_errors + [str(exc)[:240]],
                        )
                    raise
                retry_errors.append(str(exc)[:240])
                delay = self._backoff_seconds * (2 ** attempt)
                log_event(
                    logger,
                    logging.WARNING,
                    "llm.retry.scheduled",
                    prompt_name=request.operation,
                    prompt_version=request.version,
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    retry_delay_seconds=round(delay, 3),
                    retry_error=retry_errors[-1],
                )
                if delay > 0:
                    sleep(delay)


def _is_retryable_model_error(exc: Exception) -> bool:
    if isinstance(exc, ModelInvocationUnavailable):
        return exc.retryable
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    retryable_names = (
        "apiconnectionerror",
        "apitimeouterror",
        "ratelimiterror",
        "internalservererror",
        "serviceunavailableerror",
        "timeout",
        "connection",
    )
    if any(token in name for token in retryable_names):
        return True
    retryable_messages = (
        "connection error",
        "connection reset",
        "connection aborted",
        "timeout",
        "timed out",
        "rate limit",
        "429",
        "500",
        "502",
        "503",
        "504",
        "temporarily unavailable",
        "service unavailable",
        "invalid provider response",
        "provider returned empty structured content",
    )
    return any(token in message for token in retryable_messages)


class TracePayloadPolicy(Protocol):
    """Controls which model-call payload is exposed to the trace backend."""

    def inputs(self, values: dict[str, Any]) -> dict[str, Any]: ...

    def outputs(
        self,
        response: StructuredModelResponse[Any],
    ) -> dict[str, Any]: ...


class RedactedTracePayloadPolicy:
    """Expose structural metrics while removing prompt and response bodies."""

    def inputs(self, values: dict[str, Any]) -> dict[str, Any]:
        request = values.get("request")
        if not isinstance(request, StructuredModelRequest):
            return {}
        messages = request.messages
        return {
            "operation": request.operation,
            "version": request.version,
            "kind": request.kind,
            "output_type": request.output_type.__name__,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "message_count": len(messages),
            "message_roles": [str(message.get("role", "")) for message in messages],
            "message_chars": sum(len(str(message.get("content", ""))) for message in messages),
            "action_names": [
                definition.name for definition in request.action_definitions
            ],
        }

    def outputs(
        self,
        response: StructuredModelResponse[Any],
    ) -> dict[str, Any]:
        return {
            "model": response.model,
            "latency_ms": response.latency_ms,
            "response_chars": len(response.content),
            "action_invocation_count": len(response.action_invocations),
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "total_tokens": response.total_tokens,
            "retry_attempts": response.retry_attempts,
            "retry_error_count": len(response.retry_errors),
        }


class FullTracePayloadPolicy:
    """Allow the trace backend to serialize the complete call boundary."""

    def inputs(self, values: dict[str, Any]) -> dict[str, Any]:
        request = values.get("request")
        if not isinstance(request, StructuredModelRequest):
            return values
        return {
            "operation": request.operation,
            "version": request.version,
            "kind": request.kind,
            "messages": request.messages,
            "output_type": request.output_type.__name__,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "action_definitions": [
                definition.model_dump(mode="json")
                for definition in request.action_definitions
            ] or None,
            "action_choice": request.action_choice,
            "response_format": request.response_format,
        }

    def outputs(
        self,
        response: StructuredModelResponse[Any],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "content": response.content,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "total_tokens": response.total_tokens,
            "retry_attempts": response.retry_attempts,
            "retry_errors": response.retry_errors,
        }
        if response.value is not None:
            out["value"] = response.value.model_dump(mode="json")
        if response.action_invocations:
            out["action_invocations"] = [
                invocation.model_dump(mode="json")
                for invocation in response.action_invocations
            ]
        return out


class UsageRecordingStructuredModelClient:
    """Decorator that records run-scoped LLM usage without LangSmith coupling."""

    def __init__(self, delegate: StructuredModelClient) -> None:
        self._delegate = delegate

    def generate(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]:
        response = self._delegate.generate(request)
        record_llm_usage(
            latency_ms=response.latency_ms,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            total_tokens=response.total_tokens,
        )
        return response


class ObservedStructuredModelClient:
    """Decorator adding tracing without changing application callers."""

    def __init__(
        self,
        delegate: StructuredModelClient,
        payload_policy: TracePayloadPolicy,
    ) -> None:
        self._delegate = delegate
        self._payload_policy = payload_policy

    def generate(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]:
        try:
            from langsmith import traceable

            traced = traceable(
                name="llm.structured_response",
                run_type="llm",
                process_inputs=self._payload_policy.inputs,
                process_outputs=self._payload_policy.outputs,
            )(self._delegate.generate)
        except Exception:
            traced = self._delegate.generate

        try:
            response = traced(
                request,
                langsmith_extra={
                    "name": f"llm.{request.operation}",
                    "metadata": {
                        "prompt_name": request.operation,
                        "prompt_version": request.version,
                        "output_type": request.output_type.__name__,
                    },
                },
            )
            _report_usage_to_run_tree(response)
            log_event(
                logger,
                logging.INFO,
                "llm.parse",
                prompt_name=request.operation,
                prompt_version=request.version,
                model=response.model,
                parse_schema=request.output_type.__name__,
                parse_ok=True,
                latency_ms=response.latency_ms,
                retry_attempts=response.retry_attempts,
                retry_error_count=len(response.retry_errors),
            )
            return response
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "llm.parse",
                prompt_name=request.operation,
                prompt_version=request.version,
                parse_schema=request.output_type.__name__,
                parse_ok=False,
                parse_error=str(exc)[:500],
            )
            raise


class ObservedStreamingModelClient:
    """Tracing decorator for ``StreamingModelClient``.

    Wraps the pure adapter's ``stream`` in a langsmith span and records
    usage/latency after the stream completes. The adapter itself stays free of
    any tracing concern — this decorator is the only place streaming
    observability is wired.
    """

    def __init__(
        self,
        delegate: StreamingModelClient,
        observability: LangSmithConfig,
    ) -> None:
        self._delegate = delegate
        self._observability = observability

    def stream(self, request: StructuredModelRequest[Any]) -> Iterator[StreamChunk]:
        from personal_agent.kernel.langsmith_tracing import langsmith_llm_span, report_usage_metadata

        start = perf_counter()
        resolved_model = getattr(self._delegate, "_resolved_model", request.metadata.get("model", "unknown"))
        run_ctx = {
            "component": request.metadata.get("component", "stream"),
            "prompt_name": request.operation,
            "prompt_version": request.version,
            "model": resolved_model,
        }
        with langsmith_llm_span(
            self._observability,
            name=f"llm.{request.operation}.stream",
            metadata=run_ctx,
            tags=["llm", "stream", request.operation],
        ) as run:
            full_text = ""
            usage: dict[str, int] = {}
            for chunk in self._delegate.stream(request):
                full_text = chunk.accumulated
                if chunk.usage:
                    usage = chunk.usage
                yield chunk
            report_usage_metadata(run, usage)
            latency_ms = round((perf_counter() - start) * 1000, 2)
            record_llm_usage(
                latency_ms=latency_ms,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
            log_event(
                logger,
                logging.INFO,
                "llm.stream",
                prompt_name=request.operation,
                model=resolved_model,
                latency_ms=latency_ms,
                response_chars=len(full_text),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
            )


def build_structured_model_client(
    config: StructuredConfig,
    observability: LangSmithConfig,
) -> StructuredModelClient | None:
    """Select the configured provider/model structured-output capability."""
    if not (config.api_key and config.base_url and config.model):
        return None
    adapter: StructuredModelClient
    if config.output_transport == "json_object":
        adapter = JsonObjectStructuredAdapter(config)
    else:
        adapter = StrictJsonSchemaAdapter(config)
    client: StructuredModelClient = RetryingStructuredModelClient(
        adapter,
        max_retries=config.max_retries,
    )
    client = UsageRecordingStructuredModelClient(client)
    if observability.enabled:
        policy: TracePayloadPolicy = (
            FullTracePayloadPolicy()
            if observability.upload_inputs
            else RedactedTracePayloadPolicy()
        )
        client = ObservedStructuredModelClient(client, policy)
    from personal_agent.capabilities.model_resolution import GovernedModelClient
    return GovernedModelClient(client, provider="openai_compatible", model=config.model)


def build_chat_model_client(
    config: OpenAIConfig,
    observability: LangSmithConfig,
    *,
    model_override: str | None = None,
) -> StructuredModelClient | None:
    """Composition helper for Chat Completions (``tool_calling`` / ``text``)."""
    if not (config.api_key and config.base_url):
        return None
    client: StructuredModelClient = RetryingStructuredModelClient(
        OpenAIModelClient(config, model_override=model_override),
        max_retries=config.max_retries,
    )
    client = UsageRecordingStructuredModelClient(client)
    if observability.enabled:
        policy: TracePayloadPolicy = (
            FullTracePayloadPolicy()
            if observability.upload_inputs
            else RedactedTracePayloadPolicy()
        )
        client = ObservedStructuredModelClient(client, policy)
    from personal_agent.capabilities.model_resolution import GovernedModelClient
    return GovernedModelClient(
        client,
        provider="openai_compatible",
        model=model_override or config.model,
    )


def build_streaming_model_client(
    config: OpenAIConfig,
    observability: LangSmithConfig,
) -> StreamingModelClient | None:
    """Composition helper for streaming text generation."""
    if not (config.api_key and config.base_url):
        return None
    client: StreamingModelClient = OpenAIModelClient(config)
    observed: StreamingModelClient = (
        ObservedStreamingModelClient(client, observability)
        if observability.enabled else client
    )
    from personal_agent.capabilities.model_resolution import GovernedStreamingModelClient
    return GovernedStreamingModelClient(
        observed,
        provider="openai_compatible",
        model=config.model,
    )
