"""Typed model port and the single OpenAI adapter.

The port (``StructuredModelClient`` / ``StreamingModelClient``) is the only LLM
dependency application code is allowed to hold. ``OpenAIModelClient`` is the one
adapter that maps the port to the OpenAI API — it handles all three request
kinds (``structured`` via Chat Completions strict ``json_schema``,
``tool_calling`` / ``text`` via Chat Completions) plus streaming, in a single
high-cohesion class.

The adapter is **pure**: it only performs the API call and extracts
content / tool_calls / usage / latency. No tracing (langsmith spans,
``record_llm_usage``, ``log_event``) lives inside it — that is the job of the
``ObservedStructuredModelClient`` decorator, applied at composition time. This
keeps the call logic decoupled from observability concerns and lets tracing be
added, removed or swapped without touching the adapter.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from time import perf_counter, sleep
from typing import Any, Iterator, Protocol

from openai import OpenAI
from pydantic import BaseModel
from personal_agent.capabilities.contracts.model import (
    StreamChunk,
    StreamingModelClient,
    StructuredModelClient,
    StructuredModelRequest,
    StructuredModelResponse,
    StructuredOutputT,
)

from personal_agent.kernel.structured_parse import parse_structured
from personal_agent.kernel.config_models import LangSmithConfig, OpenAIConfig, StructuredConfig
from personal_agent.kernel.llm_schemas import structured_response_format
from personal_agent.kernel.llm_telemetry import record_llm_usage
from personal_agent.kernel.logging_utils import log_event

logger = logging.getLogger(__name__)
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

    - ``structured``  → Chat Completions with strict ``json_schema`` and Pydantic parse.
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

    ``config`` may be an ``OpenAIConfig`` or ``StructuredConfig`` (both expose
    ``api_key`` / ``base_url`` / ``timeout_seconds`` / ``max_retries``; the
    resolved model is ``model_override`` or ``config.model``).
    """

    def __init__(
        self,
        config: OpenAIConfig | StructuredConfig,
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
        response_format = request.response_format or structured_response_format(
            request.operation,
            schema,
        )
        chat_request = request.__class__(
            operation=request.operation,
            version=request.version,
            messages=request.messages,
            output_type=request.output_type,
            context_projection_ref=request.context_projection_ref,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            kind="text",
            response_format=response_format,
            extra_body=request.extra_body,
            metadata=request.metadata,
        )
        transport = "strict_json_schema"
        try:
            response = client.chat.completions.create(**self._chat_kwargs(chat_request))
        except Exception as exc:
            if not _response_format_unavailable(exc):
                raise
            # Transport compatibility only: the same model still authors the
            # same typed Proposal.  We change neither its semantic input nor
            # the output contract, merely fall back from provider-native JSON
            # Schema to JSON-object / plain-text transport and fail closed if
            # Pydantic cannot parse the returned object.
            response, transport = self._create_structured_transport_fallback(
                client,
                request,
                schema,
                primary_error=exc,
            )
        latency_ms = round((perf_counter() - start) * 1000, 2)
        message = response.choices[0].message
        content = (message.content or "").strip()
        if request.output_type is BaseModel:
            parsed = self._default_value(request)
        else:
            parse_result = parse_structured(
                content or "{}",
                request.output_type,
                operation=request.operation,
                version=request.version,
                model_name=getattr(response, "model", None) or self._resolved_model,
                latency_ms=latency_ms,
            )
            if not parse_result.ok and transport == "json_object":
                # Some OpenAI-compatible providers accept ``json_object`` but
                # reply with an empty or schema-incomplete object.  This is
                # still a transport failure, not permission to invent the
                # typed value. Retry once with the same model, messages, and
                # Pydantic contract but no response_format transport hint.
                response = self._create_plain_text_structured_transport(
                    client,
                    request,
                    schema,
                    primary_error=ValueError(parse_result.error or "invalid json_object response"),
                )
                transport = "plain_text_json"
                latency_ms = round((perf_counter() - start) * 1000, 2)
                message = response.choices[0].message
                content = (message.content or "").strip()
                parse_result = parse_structured(
                    content or "{}",
                    request.output_type,
                    operation=request.operation,
                    version=request.version,
                    model_name=getattr(response, "model", None) or self._resolved_model,
                    latency_ms=latency_ms,
                )
            if not parse_result.ok:
                # A schema-valid JSON transport can still violate a cross-field
                # Pydantic invariant (for example a ``clarify`` TaskAnalysis
                # that also contains Goals).  This is not a deterministic
                # repair: ask the same model to author a fresh value against
                # the exact same typed contract and report its validation
                # feedback.  If it remains invalid, fail closed.
                response = self._create_structured_schema_repair(
                    client,
                    request,
                    schema,
                    parse_error=parse_result.error or "invalid structured response",
                    response_format=(
                        response_format if transport == "strict_json_schema"
                        else ({"type": "json_object"} if transport == "json_object" else None)
                    ),
                )
                transport = f"{transport}_schema_repair"
                latency_ms = round((perf_counter() - start) * 1000, 2)
                message = response.choices[0].message
                content = (message.content or "").strip()
                parse_result = parse_structured(
                    content or "{}",
                    request.output_type,
                    operation=request.operation,
                    version=request.version,
                    model_name=getattr(response, "model", None) or self._resolved_model,
                    latency_ms=latency_ms,
                )
                if not parse_result.ok:
                    raise ValueError(f"{request.operation} structured parse failed: {parse_result.error}")
            parsed = parse_result.value
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

    def _create_structured_transport_fallback(
        self,
        client: OpenAI,
        request: StructuredModelRequest[StructuredOutputT],
        schema: dict[str, Any],
        *,
        primary_error: Exception,
    ) -> tuple[Any, str]:
        schema_instruction = {
            "role": "system",
            "content": (
                "Return only one JSON object that conforms exactly to this output schema. "
                "Do not add Markdown, explanation, or fields not in the schema.\n"
                + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            ),
        }
        messages = [*request.messages, schema_instruction]
        log_event(
            logger,
            logging.WARNING,
            "llm.structured_transport_fallback",
            operation=request.operation,
            version=request.version,
            primary_error=str(primary_error)[:240],
            fallback="json_object",
        )
        json_object_request = request.__class__(
            operation=request.operation,
            version=request.version,
            messages=messages,
            output_type=request.output_type,
            context_projection_ref=request.context_projection_ref,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            kind="text",
            response_format={"type": "json_object"},
            extra_body=request.extra_body,
            metadata=request.metadata,
        )
        try:
            return (
                client.chat.completions.create(**self._chat_kwargs(json_object_request)),
                "json_object",
            )
        except Exception as fallback_error:
            if not _response_format_unavailable(fallback_error):
                raise
            return (
                self._create_plain_text_structured_transport(
                    client,
                    request,
                    schema,
                    primary_error=fallback_error,
                ),
                "plain_text_json",
            )

    def _create_plain_text_structured_transport(
        self,
        client: OpenAI,
        request: StructuredModelRequest[StructuredOutputT],
        schema: dict[str, Any],
        *,
        primary_error: Exception,
    ) -> Any:
        schema_instruction = {
            "role": "system",
            "content": (
                "Return only one JSON object that conforms exactly to this output schema. "
                "Do not add Markdown, explanation, or fields not in the schema.\n"
                + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            ),
        }
        log_event(
            logger,
            logging.WARNING,
            "llm.structured_transport_fallback",
            operation=request.operation,
            version=request.version,
            primary_error=str(primary_error)[:240],
            fallback="plain_text_json",
        )
        plain_text_request = request.__class__(
            operation=request.operation,
            version=request.version,
            messages=[*request.messages, schema_instruction],
            output_type=request.output_type,
            context_projection_ref=request.context_projection_ref,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            kind="text",
            extra_body=request.extra_body,
            metadata=request.metadata,
        )
        return client.chat.completions.create(**self._chat_kwargs(plain_text_request))

    def _create_structured_schema_repair(
        self,
        client: OpenAI,
        request: StructuredModelRequest[StructuredOutputT],
        schema: dict[str, Any],
        *,
        parse_error: str,
        response_format: dict[str, Any] | None,
    ) -> Any:
        """Request a new model-authored value after typed output rejection.

        The prior bytes are intentionally not copied into the repair request:
        they are neither canonical facts nor a mutable state to be patched.
        Pydantic's contract error is the only feedback, and the returned value
        must independently satisfy the original schema.
        """
        log_event(
            logger,
            logging.WARNING,
            "llm.structured_schema_repair",
            operation=request.operation,
            version=request.version,
            parse_error=parse_error[:500],
        )
        repair_instruction = {
            "role": "system",
            "content": (
                "Your previous structured response was rejected by the typed output contract. "
                "Author a complete new JSON object for the original request; do not explain, patch, "
                "or refer to the rejected response. Respect all mutually exclusive fields and return "
                "only JSON. Validation feedback:\n"
                + parse_error[:2000]
                + "\nOutput schema:\n"
                + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            ),
        }
        repair_request = request.__class__(
            operation=request.operation,
            version=request.version,
            messages=[*request.messages, repair_instruction],
            output_type=request.output_type,
            context_projection_ref=request.context_projection_ref,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            kind="text",
            response_format=response_format,
            extra_body=request.extra_body,
            metadata=request.metadata,
        )
        return client.chat.completions.create(**self._chat_kwargs(repair_request))

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


class RetryingStructuredModelClient:
    """Decorator for retrying transient structured model failures.

    This sits at the model-port boundary rather than in callers. The OpenAI SDK
    may already retry inside one provider request, but this wrapper retries the
    whole typed operation after transient transport/server failures so parsing,
    usage recording, tracing, and application code stay uniform.
    """

    def __init__(
        self,
        delegate: StructuredModelClient,
        *,
        max_retries: int,
        backoff_seconds: float = 0.5,
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
    )
    return any(token in message for token in retryable_messages)


def _response_format_unavailable(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "response_format" in message
        and any(token in message for token in (
            "unavailable", "unsupported", "not supported", "invalid_request",
        ))
    )


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
            "retry_attempts": response.retry_attempts,
            "retry_errors": response.retry_errors,
        }
        if response.value is not None:
            out["value"] = response.value.model_dump(mode="json")
        if response.tool_calls:
            out["tool_calls"] = response.tool_calls
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
    """Composition helper for strict JSON-schema structured output."""
    if not (config.api_key and config.base_url and config.model):
        return None
    client: StructuredModelClient = RetryingStructuredModelClient(
        OpenAIModelClient(config),
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
