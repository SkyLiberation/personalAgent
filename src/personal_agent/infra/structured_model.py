"""Typed model port and the single OpenAI adapter.

The port (``StructuredModelClient`` / ``StreamingModelClient``) is the only LLM
dependency application code is allowed to hold. ``OpenAIModelClient`` is the one
adapter that maps the port to the OpenAI API — it handles all three request
kinds (``structured`` via Responses API, ``tool_calling`` / ``text`` via Chat
Completions) plus streaming, in a single high-cohesion class.

The adapter is **pure**: it only performs the API call and extracts
content / tool_calls / usage / latency. No tracing (langsmith spans,
``record_llm_usage``, ``log_event``) lives inside it — that is the job of the
``ObservedStructuredModelClient`` decorator, applied at composition time. This
keeps the call logic decoupled from observability concerns and lets tracing be
added, removed or swapped without touching the adapter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Generic, Iterator, Literal, Protocol, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from personal_agent.kernel.config_models import LangSmithConfig, OpenAIConfig, RouterConfig
from personal_agent.kernel.llm_telemetry import record_llm_usage
from personal_agent.kernel.logging_utils import log_event

logger = logging.getLogger(__name__)
StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)

ModelRequestKind = Literal["structured", "tool_calling", "text"]


@dataclass(frozen=True, slots=True)
class StructuredModelRequest(Generic[StructuredOutputT]):
    """Provider-neutral request for one typed model response.

    ``kind`` selects the transport:

    - ``structured`` (default): provider parses ``output_type`` (Responses API).
    - ``tool_calling``: Chat Completions with ``tools`` / ``tool_choice``;
      ``output_type`` may be ``BaseModel`` (unused, kept for typing).
    - ``text``: Chat Completions, optionally with ``response_format``.

    ``tools`` / ``tool_choice`` / ``response_format`` are ignored unless the
    matching ``kind`` is set. ``extra_body`` is forwarded to the provider.
    """

    operation: str
    version: str
    messages: list[dict[str, Any]]
    output_type: type[StructuredOutputT]
    temperature: float = 0
    max_tokens: int = 500
    kind: ModelRequestKind = "structured"
    tools: list[dict[str, object]] = field(default_factory=list)
    tool_choice: str | dict[str, object] | None = None
    response_format: dict[str, object] | None = None
    extra_body: dict[str, object] | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StructuredModelResponse(Generic[StructuredOutputT]):
    value: StructuredOutputT
    model: str
    latency_ms: float
    content: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw_response: Any = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class StreamChunk:
    """One delta from a streaming model response.

    ``usage`` is populated only on the final chunk (empty ``delta``) so the
    tracing observer can record token usage without intruding on the adapter.
    """

    delta: str
    accumulated: str
    usage: dict[str, int] | None = None


class StructuredModelClient(Protocol):
    """Application port for typed / tool-calling / text model calls."""

    def generate(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]: ...


class StreamingModelClient(Protocol):
    """Application port for streaming text generation (answer deltas)."""

    def stream(
        self,
        request: StructuredModelRequest[Any],
    ) -> Iterator[StreamChunk]: ...


def _is_reasoning_model(model: str) -> bool:
    name = model.lower()
    return name.startswith("gpt-5") or name.startswith("o1") or name.startswith("o3")


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


def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    """Pull normalized tool-call dicts off a Chat Completions message."""
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


class OpenAIModelClient:
    """The single OpenAI adapter for the model ports.

    One high-cohesion class covers every request kind:

    - ``structured``  → Responses API ``responses.parse`` with Pydantic ``output_type``.
    - ``tool_calling`` → Chat Completions with ``tools`` / ``tool_choice``;
      response carries native ``tool_calls``.
    - ``text``        → Chat Completions, optional ``response_format`` JSON-schema.
    - streaming        → ``stream()`` yields ``StreamChunk`` deltas + final usage.

    The adapter is **pure**: it only assembles kwargs, calls the SDK, extracts
    content / tool_calls / usage / latency, and returns structured objects. No
    tracing (langsmith spans, ``record_llm_usage``, ``log_event``) lives here —
    that is the job of ``ObservedStructuredModelClient`` /
    ``ObservedStreamingModelClient``, applied at composition time. This keeps
    the call logic decoupled from observability and lets tracing evolve without
    touching the adapter.

    ``config`` may be an ``OpenAIConfig`` or ``RouterConfig`` (both expose
    ``api_key`` / ``base_url`` / ``timeout_seconds`` / ``max_retries``; the
    resolved model is ``model_override`` or ``config.model``).
    """

    def __init__(
        self,
        config: OpenAIConfig | RouterConfig,
        *,
        model_override: str | None = None,
    ) -> None:
        self._config = config
        self._model_override = model_override

    # -- shared helpers --------------------------------------------------

    @property
    def _resolved_model(self) -> str:
        return self._model_override or self._config.model

    def _client(self) -> OpenAI:
        return OpenAI(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
            max_retries=self._config.max_retries,
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
        else:
            kwargs["temperature"] = request.temperature
            kwargs["max_tokens"] = request.max_tokens
        if request.kind == "text" and request.response_format is not None:
            kwargs["response_format"] = request.response_format
        if request.kind == "tool_calling":
            if request.tools:
                kwargs["tools"] = request.tools
            if request.tool_choice is not None:
                kwargs["tool_choice"] = request.tool_choice
        if request.extra_body:
            kwargs["extra_body"] = request.extra_body
        return kwargs

    @staticmethod
    def _default_value(request: StructuredModelRequest[Any]) -> Any:
        try:
            return request.output_type()  # type: ignore[call-arg]
        except Exception:
            return None

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
        kwargs: dict[str, Any] = {
            "model": self._resolved_model,
            "input": request.messages,
            "text_format": request.output_type,
            "max_output_tokens": request.max_tokens,
        }
        if not _is_reasoning_model(self._resolved_model):
            kwargs["temperature"] = request.temperature
        if getattr(self._config, "extra_body", None):
            kwargs["extra_body"] = self._config.extra_body
        response = client.responses.parse(**kwargs)
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError(
                f"Structured response did not contain {request.output_type.__name__}; "
                f"status={getattr(response, 'status', None)!r}"
            )
        latency_ms = round((perf_counter() - start) * 1000, 2)
        content = (getattr(response, "output_text", "") or "").strip()
        usage = _usage(response)
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

    def _generate_chat(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]:
        start = perf_counter()
        client = self._client()
        response = client.chat.completions.create(**self._chat_kwargs(request))
        latency_ms = round((perf_counter() - start) * 1000, 2)
        message = response.choices[0].message
        content = (message.content or "").strip()
        tool_calls = _extract_tool_calls(message)
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
            tool_calls=tool_calls,
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
            "tool_names": [
                str((tool.get("function") or {}).get("name"))
                for tool in (request.tools or [])
                if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
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
            "tool_call_count": len(response.tool_calls or []),
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "total_tokens": response.total_tokens,
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
            "tools": request.tools or None,
            "tool_choice": request.tool_choice,
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
        }
        if response.value is not None:
            out["value"] = response.value.model_dump(mode="json")
        if response.tool_calls:
            out["tool_calls"] = response.tool_calls
        return out


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
    config: RouterConfig,
    observability: LangSmithConfig,
) -> StructuredModelClient | None:
    """Composition helper for the Responses API (``structured`` kind)."""
    if not (config.api_key and config.base_url and config.model):
        return None
    client: StructuredModelClient = OpenAIModelClient(config)
    if not observability.enabled:
        return client
    policy: TracePayloadPolicy = (
        FullTracePayloadPolicy()
        if observability.upload_inputs
        else RedactedTracePayloadPolicy()
    )
    return ObservedStructuredModelClient(client, policy)


def build_chat_model_client(
    config: OpenAIConfig | RouterConfig,
    observability: LangSmithConfig,
    *,
    model_override: str | None = None,
) -> StructuredModelClient | None:
    """Composition helper for Chat Completions (``tool_calling`` / ``text``)."""
    if not (config.api_key and config.base_url):
        return None
    client: StructuredModelClient = OpenAIModelClient(config, model_override=model_override)
    if not observability.enabled:
        return client
    policy: TracePayloadPolicy = (
        FullTracePayloadPolicy()
        if observability.upload_inputs
        else RedactedTracePayloadPolicy()
    )
    return ObservedStructuredModelClient(client, policy)


def build_streaming_model_client(
    config: OpenAIConfig,
    observability: LangSmithConfig,
) -> StreamingModelClient | None:
    """Composition helper for streaming text generation."""
    if not (config.api_key and config.base_url):
        return None
    client: StreamingModelClient = OpenAIModelClient(config)
    if not observability.enabled:
        return client
    return ObservedStreamingModelClient(client, observability)
