"""Typed model ports and OpenAI-compatible adapters.

The ``StructuredModelClient`` port is the only LLM dependency application code
is allowed to hold. Provider/model structured-output capabilities are selected
at composition time: ``StrictJsonSchemaAdapter`` uses
native strict ``json_schema`` while ``JsonObjectStructuredAdapter`` uses JSON
mode plus the same Pydantic contract in the prompt. Application code is unaware
of that transport distinction.

The adapter owns only Provider calls, extraction, and one bounded repair of a
malformed Provider protocol response. It never authorizes an action or invents
Application semantics. Structured tracing and usage recording remain decorator
responsibilities; the adapter emits only local diagnostics for repair boundaries.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from queue import Empty, Queue
from threading import Thread
from time import perf_counter, sleep
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from openai import APIError, APIStatusError, ContentFilterFinishReasonError, OpenAI
from pydantic import BaseModel

from personal_agent.capabilities.contracts.model import (
    PROVIDER_DIAGNOSTIC_MAX_CHARS,
    ModelInvocationUnavailable,
    ProviderFailureDiagnostics,
    StructuredModelClient,
    StructuredModelRequest,
    StructuredModelResponse,
    StructuredOutputFailure,
    StructuredOutputT,
)
from personal_agent.infra.model_response import (
    _aggregate_usage,
    _extract_action_invocations,
    _require_chat_choices,
    _structured_chat_message,
    _sum_usage,
    _usage,
)
from personal_agent.kernel.config_models import (
    LangSmithConfig,
    OpenAIConfig,
    StructuredConfig,
)
from personal_agent.kernel.llm_schemas import structured_response_format
from personal_agent.kernel.llm_telemetry import record_llm_usage
from personal_agent.kernel.logging_utils import log_event
from personal_agent.kernel.prompts import get_prompt
from personal_agent.kernel.structured_parse import parse_structured

logger = logging.getLogger(__name__)


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


class OpenAIModelClient:
    """OpenAI-compatible SDK calls and bounded protocol repair.

    Concrete adapters build structured requests. Response normalization lives
    in ``model_response``; this adapter applies typed validation and owns text,
    native action and streaming transport. It emits local repair diagnostics;
    tracing and usage recording are owned by the observability decorators.
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
            if request.max_tokens is not None:
                kwargs["max_completion_tokens"] = request.max_tokens
            if request.reasoning_effort is not None:
                kwargs["reasoning_effort"] = request.reasoning_effort
        else:
            kwargs["temperature"] = request.temperature
            if request.max_tokens is not None:
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
        kwargs.update(stream=True, stream_options={"include_usage": True})
        return self._create_chat_completion(client, request.operation, kwargs)

    def _provider_unavailable(
        self,
        operation: str,
        exc: Exception,
    ) -> ModelInvocationUnavailable:
        status_code = getattr(exc, "status_code", None)
        retryable = (
            status_code in {408, 409, 429} or status_code is None or status_code >= 500
        )
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
            diagnostics=self._provider_diagnostics(exc),
        )

    def _provider_diagnostics(
        self, exc: Exception
    ) -> ProviderFailureDiagnostics | None:
        body = getattr(exc, "body", None)
        envelope = body if isinstance(body, dict) else {}
        detail = envelope.get("error", envelope)
        detail = detail if isinstance(detail, dict) else {}
        response = getattr(exc, "response", None)
        headers = response.headers if response is not None else {}

        def clean(value: object) -> str | None:
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                return None
            text = str(value)
            if self._config.api_key:
                text = text.replace(self._config.api_key, "[redacted]")
            text = re.sub(r"(?i)\bBearer\s+[^\s\"',;]+", "Bearer [redacted]", text)
            text = re.sub(r"\b(?:sk|tp)-[A-Za-z0-9_-]{8,}", "[redacted]", text)
            text = re.sub(r"https?://[^\s<>\"']+", "[url redacted]", text)
            text = re.sub(
                r"(?i)\b(api[_-]?key|access[_-]?token|authorization|cookie|password|secret)"
                r"\b[\"']?\s*[:=]\s*[\"']?[^\s,;\"']+",
                r"\1=[redacted]",
                text,
            )
            text = re.sub(r"[\x00-\x1f\x7f]", " ", text).strip()
            return text[:PROVIDER_DIAGNOSTIC_MAX_CHARS] or None

        diagnostics = ProviderFailureDiagnostics(
            error_code=clean(detail.get("code")),
            error_type=clean(detail.get("type")),
            message=clean(detail.get("message")),
            request_id=clean(
                getattr(exc, "request_id", None)
                or envelope.get("request_id")
                or headers.get("x-request-id")
            ),
            retry_after=clean(headers.get("retry-after")),
        )
        return diagnostics if diagnostics.model_dump(exclude_none=True) else None

    def _create_chat_completion(
        self,
        client: OpenAI,
        operation: str,
        kwargs: dict[str, Any],
    ) -> Any:
        def invoke() -> Any:
            if kwargs.get("stream"):
                stream_kwargs = {key: value for key, value in kwargs.items() if key != "stream"}
                with client.chat.completions.stream(**stream_kwargs) as stream:
                    return stream.get_final_completion()
            return client.chat.completions.create(**kwargs)

        try:
            return _run_with_deadline(
                invoke,
                client=client,
                operation=operation,
                timeout_seconds=self._config.timeout_seconds,
            )
        except ContentFilterFinishReasonError as exc:
            raise ModelInvocationUnavailable(
                operation, "provider_rejected", model=self._resolved_model,
                provider_host=urlparse(self._config.base_url or "").hostname,
                retryable=False,
                diagnostics=ProviderFailureDiagnostics(error_type="content_filter"),
            ) from exc
        except (APIStatusError, APIError) as exc:
            raise self._provider_unavailable(operation, exc) from exc

    # -- complete-response entrypoint ----------------------------------

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
        retry_errors: list[str] = []
        try:
            for repair in range(request.max_output_repairs + 1):
                chat_request = self._structured_chat_request(
                    request,
                    schema,
                    parse_error=retry_errors[-1] if retry_errors else None,
                )
                response = self._create_structured_completion(client, chat_request)
                responses.append(response)
                content, parsed, parse_error = self._parse_typed_response(
                    request,
                    response,
                    latency_ms=round((perf_counter() - start) * 1000, 2),
                )
                if parse_error is None:
                    usage = _aggregate_usage(responses)
                    return StructuredModelResponse(
                        value=parsed,
                        model=getattr(response, "model", None) or self._resolved_model,
                        latency_ms=round((perf_counter() - start) * 1000, 2),
                        content=content,
                        input_tokens=usage.get("input_tokens"),
                        output_tokens=usage.get("output_tokens"),
                        total_tokens=usage.get("total_tokens"),
                        raw_response=response,
                        retry_attempts=len(responses) - 1,
                        retry_errors=retry_errors,
                    )
                if repair == request.max_output_repairs:
                    raise StructuredOutputFailure(request.operation, parse_error)
                retry_errors.append(parse_error)
                log_event(
                    logger,
                    logging.WARNING,
                    "llm.structured_schema_repair",
                    operation=request.operation,
                    version=request.version,
                    parse_error=parse_error[:500],
                )
        except (StructuredOutputFailure, ModelInvocationUnavailable) as exc:
            if responses:
                usage = _aggregate_usage(responses)
                if isinstance(exc, ModelInvocationUnavailable):
                    # The failed transport did not provide complete usage.
                    usage.pop("input_tokens", None)
                    usage.pop("output_tokens", None)
                exc.response = StructuredModelResponse(
                    value=None,
                    model=getattr(responses[-1], "model", None) or self._resolved_model,
                    latency_ms=round((perf_counter() - start) * 1000, 2),
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    total_tokens=usage.get("total_tokens"),
                    raw_response=responses[-1],
                    retry_attempts=len(responses)
                    - 1
                    + int(isinstance(exc, ModelInvocationUnavailable)),
                    retry_errors=retry_errors,
                )
            raise
        raise AssertionError("structured repair loop must return or raise")

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
        responses: list[Any] = []
        chat_request = request
        repair_errors: list[str] = []
        protocol_failure: StructuredOutputFailure | None = None
        action_invocations = ()
        for attempt in range(2):
            try:
                response = self._create_chat_completion(
                    client,
                    request.operation,
                    self._chat_kwargs(chat_request),
                )
            except ModelInvocationUnavailable as exc:
                if responses:
                    exc.response = StructuredModelResponse(
                        value=None,
                        model=getattr(responses[-1], "model", None)
                        or self._resolved_model,
                        latency_ms=round((perf_counter() - start) * 1000, 2),
                        total_tokens=_aggregate_usage(responses).get("total_tokens"),
                        retry_attempts=attempt,
                        retry_errors=repair_errors,
                    )
                raise
            responses.append(response)
            message = _require_chat_choices(response)[0].message
            try:
                action_invocations = (
                    _extract_action_invocations(message, chat_request)
                    if request.kind == "tool_calling"
                    else ()
                )
                break
            except StructuredOutputFailure as exc:
                if not (
                    attempt == 0
                    and request.kind == "tool_calling"
                    and request.action_choice == "required"
                    and exc.reason_code
                    in (
                        "provider_action_missing",
                        "provider_action_arguments_invalid_json",
                    )
                ):
                    protocol_failure = exc
                    break
                repair_errors.append(exc.reason_code)
                repair_prompt = get_prompt("action.repair.system")
                log_event(
                    logger,
                    logging.WARNING,
                    "llm.action_protocol_repair",
                    operation=request.operation,
                    version=request.version,
                    reason_code=exc.reason_code,
                    repair_prompt_name=repair_prompt.name,
                    repair_prompt_version=repair_prompt.version,
                )
                rejected_calls = [
                    call if isinstance(call, dict) else call.model_dump(mode="json")
                    for call in (getattr(message, "tool_calls", None) or [])
                ]
                chat_request = replace(
                    request,
                    metadata={
                        **request.metadata,
                        "action_prompt_name": repair_prompt.name,
                        "action_prompt_version": repair_prompt.version,
                    },
                    messages=[
                        {
                            "role": "system",
                            "content": repair_prompt.render(
                                validation_feedback=json.dumps(
                                    {
                                        "reason_code": exc.reason_code,
                                        "rejected_content": message.content,
                                        "rejected_calls": rejected_calls,
                                    },
                                    ensure_ascii=False,
                                ),
                            ),
                        },
                        *request.messages,
                    ],
                )
        response = responses[-1]
        message = _require_chat_choices(response)[0].message
        latency_ms = round((perf_counter() - start) * 1000, 2)
        content = (message.content or "").strip()
        usage = _aggregate_usage(responses)
        result = StructuredModelResponse(
            value=(
                None
                if action_invocations or protocol_failure is not None
                else self._default_value(request)
            ),
            model=getattr(response, "model", None) or self._resolved_model,
            latency_ms=latency_ms,
            content=content,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw_response=response,
            action_invocations=action_invocations,
            retry_attempts=len(repair_errors),
            retry_errors=repair_errors,
        )
        if protocol_failure is not None:
            protocol_failure.response = result
            raise protocol_failure
        return result


def _schema_repair_instruction(
    schema: dict[str, Any],
    parse_error: str,
) -> tuple[dict[str, str], dict[str, str]]:
    prompt = get_prompt("structured.repair.system")
    return (
        {
            "role": "system",
            "content": prompt.render(
                validation_feedback=parse_error[:2000],
                output_schema=json.dumps(
                    schema,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        },
        {
            "structured_prompt_name": prompt.name,
            "structured_prompt_version": prompt.version,
        },
    )


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
        metadata = request.metadata
        if parse_error is not None:
            instruction, prompt_metadata = _schema_repair_instruction(
                schema,
                parse_error,
            )
            messages = [instruction, *messages]
            metadata = {**metadata, **prompt_metadata}
        return replace(
            request,
            messages=messages,
            metadata=metadata,
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
            prompt = get_prompt("structured.system")
            instruction = {
                "role": "system",
                "content": prompt.render(
                    output_schema=json.dumps(
                        schema,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
            }
            prompt_metadata = {
                "structured_prompt_name": prompt.name,
                "structured_prompt_version": prompt.version,
            }
        else:
            instruction, prompt_metadata = _schema_repair_instruction(
                schema,
                parse_error,
            )
        return replace(
            request,
            messages=[instruction, *request.messages],
            metadata={**request.metadata, **prompt_metadata},
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
        failed_responses: list[StructuredModelResponse[Any] | None] = []
        start = perf_counter()

        def aggregate(response: StructuredModelResponse) -> StructuredModelResponse:
            attempts = [*failed_responses, response]
            usage = _sum_usage(
                [
                    {
                        key: value
                        for key in ("input_tokens", "output_tokens", "total_tokens")
                        if (value := getattr(item, key, None)) is not None
                    }
                    for item in attempts
                ]
            )
            return replace(
                response,
                latency_ms=round((perf_counter() - start) * 1000, 2),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
                retry_attempts=response.retry_attempts
                + len(failed_responses)
                + sum(
                    item.retry_attempts for item in failed_responses if item is not None
                ),
                retry_errors=[*retry_errors, *response.retry_errors],
            )

        for attempt in range(self._max_retries + 1):
            try:
                response = self._delegate.generate(request)
                return aggregate(response)
            except Exception as exc:
                observed = (
                    exc.response
                    if isinstance(
                        exc, (StructuredOutputFailure, ModelInvocationUnavailable)
                    )
                    else None
                )
                if attempt >= self._max_retries or not _is_retryable_model_error(exc):
                    if isinstance(
                        exc, (StructuredOutputFailure, ModelInvocationUnavailable)
                    ):
                        if observed is None and any(
                            item is not None for item in failed_responses
                        ):
                            previous = next(
                                item
                                for item in reversed(failed_responses)
                                if item is not None
                            )
                            observed = StructuredModelResponse(
                                value=None, model=previous.model, latency_ms=0
                            )
                        if observed is not None:
                            exc.response = aggregate(observed)
                    if retry_errors:
                        log_event(
                            logger,
                            logging.WARNING,
                            "llm.retry.exhausted",
                            prompt_name=request.operation,
                            prompt_version=request.version,
                            attempts=attempt + 1,
                            retry_errors=retry_errors + [str(exc)[:240]],
                            provider_diagnostics=(
                                exc.diagnostics.model_dump(exclude_none=True)
                                if isinstance(exc, ModelInvocationUnavailable)
                                and exc.diagnostics
                                else None
                            ),
                        )
                    raise
                failed_responses.append(observed)
                if observed is not None:
                    retry_errors.extend(observed.retry_errors)
                retry_errors.append(str(exc)[:240])
                delay = self._backoff_seconds * (2**attempt)
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
                    provider_diagnostics=(
                        exc.diagnostics.model_dump(exclude_none=True)
                        if isinstance(exc, ModelInvocationUnavailable)
                        and exc.diagnostics
                        else None
                    ),
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
            "message_chars": sum(
                len(str(message.get("content", ""))) for message in messages
            ),
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
            ]
            or None,
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
        response = None
        try:
            response = self._delegate.generate(request)
        except (StructuredOutputFailure, ModelInvocationUnavailable) as exc:
            response = exc.response
            raise
        finally:
            if response is not None:
                record_llm_usage(
                    latency_ms=response.latency_ms,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    total_tokens=response.total_tokens,
                )
        assert response is not None
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
