"""Typed model ports and OpenAI-compatible adapters.

The ``StructuredModelClient`` port is the only LLM dependency application code
is allowed to hold. Provider/model structured-output capabilities are selected
at composition time: ``StrictJsonSchemaAdapter`` uses
native strict ``json_schema`` while ``JsonObjectStructuredAdapter`` uses JSON
mode plus the same Pydantic contract in the prompt. Application code is unaware
of that transport distinction.

The adapter owns only Provider calls, extraction, and request-bounded repair of a
malformed Provider protocol response. It never authorizes an action or invents
Application semantics. Structured tracing and usage recording remain decorator
responsibilities; the adapter emits only local diagnostics for repair boundaries.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from queue import Empty, Queue
from threading import Thread
from time import perf_counter, sleep
from typing import Any, Callable, Iterable, Protocol
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from langchain_core.utils.function_calling import convert_to_openai_tool
from openai import APIError, APIStatusError, APITimeoutError, OpenAI
from openai.lib.streaming.chat import ChatCompletionStreamState
from openai.types.chat import ChatCompletionChunk
from pydantic import BaseModel, ValidationError

from personal_agent.capabilities.contracts.model import (
    ModelActionDefinition,
    ModelActionInvocation,
    ModelInvocationContinuation,
    ModelResponseRecord,
    ModelResponseSink,
    ModelStreamProtocolFailure,
    ModelToolExchange,
    ModelToolResult,
    ModelCapacityRefused,
    ModelInvocationUnavailable,
    ProviderFailureDiagnostics,
    StructuredModelClient,
    StructuredModelRequest,
    StructuredModelResponse,
    StructuredOutputFailure,
    StructuredOutputT,
)
from personal_agent.infra.model_response import (
    _restore_provider_response,
    _extract_action_invocations,
    _require_chat_choices,
    _structured_chat_message,
    _sum_usage,
    _usage,
)
from personal_agent.infra.model_capacity import check_model_capacity
from personal_agent.infra.model_transport import (
    clean_provider_diagnostic,
    model_http_client,
    model_transport_snapshot,
    provider_exception_chain,
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


@dataclass(frozen=True, slots=True)
class _ProviderCompletion:
    payload: Any
    stream_protocol_failures: tuple[ModelStreamProtocolFailure, ...] = ()


def _aggregate_chat_chunks(chunks: Iterable[ChatCompletionChunk]) -> _ProviderCompletion:
    """Keep role structural on SDK consumption copies and retain sticky errors."""
    state = ChatCompletionStreamState(response_format={"type": "text"}, input_tools=[])
    first_roles: dict[int, str] = {}
    seen_choices: set[int] = set()
    failures: dict[int, ModelStreamProtocolFailure] = {}
    legal_roles = frozenset({"developer", "system", "user", "assistant", "tool"})
    for chunk in chunks:
        if chunk.object != "chat.completion.chunk":
            continue
        choices = []
        copied = False
        for choice in chunk.choices:
            index = choice.index
            seen_choices.add(index)
            role = choice.delta.role
            if role is None:
                choices.append(choice)
                continue
            role_json = json.dumps(role, ensure_ascii=False, separators=(",", ":"))
            first_role = first_roles.get(index)
            if first_role is None:
                first_roles[index] = role_json
            valid = isinstance(role, str) and role in legal_roles
            if index not in failures:
                if not valid:
                    failures[index] = ModelStreamProtocolFailure(
                        choice_index=index, reason="role_invalid",
                        observed_role_values_json=(role_json,),
                    )
                elif first_role is not None and first_role != role_json:
                    failures[index] = ModelStreamProtocolFailure(
                        choice_index=index, reason="role_conflict",
                        observed_role_values_json=(first_role, role_json),
                    )
            if valid and first_role == role_json:
                delta = choice.delta.model_copy(update={"role": None})
                delta.model_fields_set.discard("role")
                choices.append(choice.model_copy(update={"delta": delta}))
                copied = True
            else:
                choices.append(choice)
        consumed = chunk.model_copy(update={"choices": choices}) if copied else chunk
        # Use the same SDK state/events as ChatCompletionStream, after changing
        # only the repeated role field on this consumption copy.
        for _ in state.handle_chunk(consumed):
            pass
    for index in sorted(seen_choices):
        if index not in first_roles:
            failures.setdefault(index, ModelStreamProtocolFailure(
                choice_index=index, reason="role_missing",
            ))
    return _ProviderCompletion(
        payload=state.current_completion_snapshot,
        stream_protocol_failures=tuple(failures[index] for index in sorted(failures)),
    )


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
        or name.startswith("minimax-")
    )


def _report_usage_to_run_tree(
    response: StructuredModelResponse[Any],
    continuation: ModelInvocationContinuation | None = None,
) -> None:
    previous_ids = {
        record.attempt_id for record in continuation.response_records
    } if continuation else set()
    if response.response_records:
        usage = _sum_usage([
            {name: value for name in ("input_tokens", "output_tokens", "total_tokens")
             if (value := getattr(record, name)) is not None}
            for record in response.response_records if record.attempt_id not in previous_ids
        ])
    else:
        usage = {name: value for name in ("input_tokens", "output_tokens", "total_tokens")
                 if (value := getattr(response, name)) is not None}
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

    @property
    def _provider_host(self) -> str:
        # Match the SDK endpoint resolution before any protocol binding. The
        # response's model name may be a resolved snapshot of our request alias.
        endpoint = self._config.base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        return urlparse(endpoint).hostname or ""

    def _client(self) -> OpenAI:
        return OpenAI(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
            max_retries=0,
            http_client=model_http_client(api_key=self._config.api_key, timeout=self._config.timeout_seconds),
        )

    def _chat_kwargs(
        self,
        request: StructuredModelRequest[Any],
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        model = self._resolved_model
        messages = list(request.messages)
        host = self._provider_host
        for exchange in request.model_history:
            if exchange.assistant.provider_host != host or exchange.assistant.model != model:
                raise ModelCapacityRefused(request.operation, "capacity_profile_mismatch")
            messages.append(exchange.assistant.payload)
            messages.extend({"role": "tool", "tool_call_id": result.call_id, "content": result.content}
                            for result in exchange.results)
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
        if _is_reasoning_model(model):
            if request.max_tokens is not None:
                kwargs["max_completion_tokens"] = request.max_tokens
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
                        "strict": definition.strict,
                    },
                }
                for definition in request.action_definitions
            ]
            if request.action_choice is not None:
                kwargs["tool_choice"] = request.action_choice
        config_extra = getattr(self._config, "extra_body", None) or {}
        merged_extra = {**config_extra, **(request.extra_body or {})}
        configured_effort = merged_extra.pop("reasoning_effort", None)
        if request.reasoning_effort is not None:
            kwargs["reasoning_effort"] = request.reasoning_effort
        elif configured_effort is not None:
            kwargs["reasoning_effort"] = configured_effort
        if merged_extra:
            kwargs["extra_body"] = merged_extra
        if request.kind == "tool_calling" and urlparse(self._config.base_url or "").hostname in {
            "api.xiaomimimo.com", "token-plan-cn.xiaomimimo.com",
        }:
            kwargs.update(stream=True, stream_options={"include_usage": True}, tool_choice="auto")
        if (
            request.kind == "tool_calling"
            and request.action_choice == "required"
            and urlparse(self._config.base_url or "").hostname == "api.deepseek.com"
            and merged_extra.get("thinking") != {"type": "disabled"}
        ):
            # DeepSeek thinking rejects forced choice. The original required
            # request still owns action validation and bounded protocol repair.
            kwargs["tool_choice"] = "auto"
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
        *,
        before_send: Callable[[], None] | None = None,
    ) -> _ProviderCompletion:
        kwargs = self._chat_kwargs(request)
        kwargs.update(stream=True, stream_options={"include_usage": True})
        return self._create_chat_completion(
            client, request.operation, kwargs, before_send=before_send
        )

    def _provider_unavailable(
        self,
        operation: str,
        exc: Exception,
    ) -> ModelInvocationUnavailable:
        status_code = getattr(exc, "status_code", None)
        retryable = (
            status_code in {408, 409, 429} or status_code is None or status_code >= 500
        )
        category = "provider_transport"
        if isinstance(exc, (APITimeoutError, httpx.TimeoutException)):
            category = "provider_timeout"
        elif status_code is not None and status_code < 500:
            category = "provider_rejected"
        return ModelInvocationUnavailable(
            operation,
            category,
            model=self._resolved_model,
            provider_host=self._provider_host,
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
            return clean_provider_diagnostic(value, self._config.api_key)

        transport = model_transport_snapshot(exc)
        diagnostics = ProviderFailureDiagnostics(
            error_code=clean(detail.get("code")),
            error_type=clean(detail.get("type")),
            message=clean(detail.get("message")),
            request_id=clean(
                getattr(exc, "request_id", None)
                or envelope.get("request_id")
                or headers.get("x-request-id")
                or (transport.provider_request_id if transport else None)
            ),
            retry_after=clean(headers.get("retry-after") or (transport.retry_after if transport else None)),
            exception_chain=provider_exception_chain(exc, self._config.api_key),
            transport=transport,
        )
        return diagnostics if diagnostics.model_dump(exclude_none=True, exclude_defaults=True) else None

    def _create_chat_completion(
        self,
        client: OpenAI,
        operation: str,
        kwargs: dict[str, Any],
        *,
        before_send: Callable[[], None] | None = None,
    ) -> _ProviderCompletion:
        capacity = self._config.capacity
        if capacity is not None:
            try:
                check = check_model_capacity(
                    operation=operation,
                    provider_host=urlparse(str(client.base_url)).hostname or "",
                    model=self._resolved_model,
                    kwargs=kwargs,
                    capacity=capacity,
                )
            except ModelCapacityRefused as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    "llm.capacity.refused",
                    operation=operation,
                    reason_code=exc.reason_code,
                    capacity_check=exc.check.model_dump(mode="json")
                    if exc.check
                    else None,
                )
                raise
            log_event(
                logger,
                logging.INFO,
                "llm.capacity.accepted",
                capacity_check=check.model_dump(mode="json"),
            )

        # Application owns budget/deadline admission for a new paid request.
        # Keep it outside provider exception translation and the worker thread.
        if before_send is not None:
            try:
                before_send()
            except Exception as exc:
                exc.model_before_send_failed = True
                raise

        def invoke() -> _ProviderCompletion:
            if kwargs.get("stream"):
                # Collect every complete response before local Schema or finish
                # validation. SDK get_final_completion rejects content_filter
                # before handing us the original; its local rich parser can
                # also fail before the terminal usage chunk arrives.
                with client.chat.completions.create(**kwargs) as raw_stream:
                    return _aggregate_chat_chunks(raw_stream)
            return _ProviderCompletion(payload=client.chat.completions.create(**kwargs))

        try:
            return _run_with_deadline(
                invoke,
                client=client,
                operation=operation,
                timeout_seconds=self._config.timeout_seconds,
            )
        except (APIStatusError, APIError, httpx.TransportError) as exc:
            raise self._provider_unavailable(operation, exc) from exc

    # -- complete-response entrypoint ----------------------------------

    def generate(
        self,
        request: StructuredModelRequest[StructuredOutputT],
        *,
        response_sink: ModelResponseSink | None = None,
        continuation: ModelInvocationContinuation | None = None,
        before_send: Callable[[], None] | None = None,
    ) -> StructuredModelResponse[StructuredOutputT]:
        invocation = continuation or ModelInvocationContinuation.for_request(
            request, invocation_id=uuid4().hex
        )
        invocation.validate_request(request)
        for record in invocation.response_records:
            if (
                record.provider_host != self._provider_host
                or record.requested_model != self._resolved_model
            ):
                raise ValueError("model continuation provider binding mismatch")
        records = list(invocation.response_records)
        errors: list[str] = []
        exchanges: list[ModelToolExchange] = []
        try:
            if request.kind == "structured":
                return self._generate_structured(
                    request, invocation, records, errors, exchanges, response_sink,
                    before_send,
                )
            return self._generate_chat(
                request, invocation, records, errors, exchanges, response_sink,
                before_send,
            )
        except Exception as exc:
            # Recording failures are local errors and keep their original type.
            # Completed originals remain available even when no decode happened.
            if records:
                exc.response = self._response(
                    request, records, retry_errors=errors,
                    protocol_exchanges=exchanges,
                )
            raise

    def _receive_response(
        self,
        request: StructuredModelRequest[Any],
        chat_request: StructuredModelRequest[Any],
        invocation: ModelInvocationContinuation,
        records: list[ModelResponseRecord],
        response_sink: ModelResponseSink | None,
        before_send: Callable[[], None] | None,
        *,
        structured: bool,
    ) -> Any:
        client = self._client()
        started = perf_counter()
        if structured:
            completion = self._create_structured_completion(
                client, chat_request, before_send=before_send
            )
        else:
            completion = self._create_chat_completion(
                client, request.operation, self._chat_kwargs(chat_request),
                before_send=before_send,
            )
        response = completion.payload
        if isinstance(response, BaseModel):
            payload = response.model_dump(mode="json", exclude_unset=True)
        else:
            payload = response
        record = ModelResponseRecord.from_payload_json(
            invocation_id=invocation.invocation_id,
            attempt_id=uuid4().hex,
            operation=request.operation,
            request_digest=invocation.request_digest,
            context_projection_ref=request.context_projection_ref,
            provider_host=self._provider_host,
            requested_model=self._resolved_model,
            payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            latency_ms=round((perf_counter() - started) * 1000, 2),
            stream_protocol_failures=completion.stream_protocol_failures,
        )
        records.append(record)
        if response_sink is not None:
            try:
                response_sink(record)
            except Exception as exc:
                exc.model_response_recording_failed = True
                raise
        return response

    def _response(
        self,
        request: StructuredModelRequest[Any],
        records: list[ModelResponseRecord],
        *,
        value: Any = None,
        content: str | None = None,
        action_invocations: tuple[ModelActionInvocation, ...] = (),
        retry_errors: list[str] | None = None,
        protocol_exchanges: list[ModelToolExchange] | None = None,
    ) -> StructuredModelResponse[Any]:
        if content is None:
            raw = records[-1].raw_response if records else None
            choices = raw.get("choices") if isinstance(raw, dict) else None
            message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
            body = message.get("content") if isinstance(message, dict) else None
            content = body if isinstance(body, str) else ""
        return StructuredModelResponse(
            value=value,
            model=records[-1].model if records else self._resolved_model,
            latency_ms=0,
            content=content,
            response_records=tuple(records),
            action_invocations=action_invocations,
            assistant_message=records[-1].assistant_message if records else None,
            retry_attempts=max(0, len(records) - 1),
            retry_errors=list(retry_errors or []),
            protocol_exchanges=tuple(protocol_exchanges or ()),
        )

    def _check_complete_response(
        self, request: StructuredModelRequest[Any], response: Any,
        *, stream_protocol_failures: tuple[ModelStreamProtocolFailure, ...] = (),
    ) -> None:
        try:
            choices = _require_chat_choices(response)
        except (AttributeError, RuntimeError) as exc:
            raise StructuredOutputFailure(
                request.operation, str(exc)
            ) from exc
        if any(getattr(choice, "finish_reason", None) == "content_filter"
               for choice in choices):
            raise ModelInvocationUnavailable(
                request.operation, "provider_rejected",
                model=self._resolved_model, provider_host=self._provider_host,
                retryable=False,
                diagnostics=ProviderFailureDiagnostics(error_type="content_filter"),
                provider_response_complete=True,
            )
        if any(getattr(choice, "finish_reason", None) == "length"
               for choice in choices):
            raise StructuredOutputFailure(
                request.operation,
                "provider response was truncated (finish_reason=length)",
            )
        if any(not getattr(choice, "finish_reason", None) for choice in choices):
            raise StructuredOutputFailure(
                request.operation,
                "provider response is incomplete: missing terminal finish_reason",
            )
        if any(getattr(choice, "message", None) is None for choice in choices):
            raise StructuredOutputFailure(
                request.operation, "invalid provider response: missing assistant message"
            )
        if stream_protocol_failures:
            first = stream_protocol_failures[0]
            raise StructuredOutputFailure(
                request.operation,
                f"provider stream role protocol failed at choice {first.choice_index}: {first.reason}",
            )
        if any(getattr(choice.message, "role", None) != "assistant" for choice in choices):
            raise StructuredOutputFailure(
                request.operation, "provider response requires the original assistant role"
            )

    def _generate_structured(
        self,
        request: StructuredModelRequest[StructuredOutputT],
        invocation: ModelInvocationContinuation,
        records: list[ModelResponseRecord],
        errors: list[str],
        exchanges: list[ModelToolExchange],
        response_sink: ModelResponseSink | None,
        before_send: Callable[[], None] | None,
    ) -> StructuredModelResponse[StructuredOutputT]:
        schema = request.output_type.model_json_schema()
        native = request.output_transport == "native_tool"
        output_definition: ModelActionDefinition | None = None
        if native:
            output_definition = ModelActionDefinition(
                name="structured_output", kind="tool",
                target_name=request.operation,
                description="返回当前任务要求的完整结构化结果。",
                input_schema=convert_to_openai_tool(
                    request.output_type, strict=False
                )["function"]["parameters"],
                strict=False,
            )
            chat_request = replace(
                request, kind="tool_calling", output_transport=None,
                action_choice="required",
                action_definitions=(output_definition,),
            )
        elif request.output_transport == "prompted_json":
            instruction, prompt_metadata = _schema_instruction(schema, parse_error=None)
            chat_request = replace(
                request, kind="text", output_transport=None, response_format=None,
                messages=[instruction, *request.messages],
                metadata={**request.metadata, **prompt_metadata},
            )
        else:
            chat_request = self._structured_chat_request(
                request, schema, parse_error=None
            )
        for repair in range(request.max_output_repairs + 1):
            if repair < len(records):
                response = _restore_provider_response(records[repair])
            else:
                if request.output_transport == "prompted_json":
                    for extra in (self._config.extra_body, request.extra_body):
                        if extra and {"tools", "tool_choice", "response_format"}.intersection(extra):
                            raise ValueError("prompted JSON cannot use tool or response format extra_body fields")
                response = self._receive_response(
                    request, chat_request, invocation, records, response_sink,
                    before_send,
                    structured=True,
                )
            # The sink has already committed this complete original.
            try:
                self._check_complete_response(
                    request, response,
                    stream_protocol_failures=records[repair].stream_protocol_failures,
                )
                if native:
                    content, parsed, parse_error = self._parse_native_output(
                        request, response
                    )
                else:
                    content, parsed, parse_error = self._parse_typed_response(
                        request, response, latency_ms=records[repair].latency_ms
                    )
            except StructuredOutputFailure as exc:
                if not native:
                    raise
                content, parsed, parse_error = "", None, str(exc)
            if parse_error is None:
                if repair != len(records) - 1:
                    raise ValueError("model continuation contains responses after valid output")
                return self._response(
                    request, records, value=parsed, content=content,
                    retry_errors=errors, protocol_exchanges=exchanges,
                )
            if repair == request.max_output_repairs:
                raise StructuredOutputFailure(request.operation, parse_error)
            errors.append(parse_error)
            chat_request, exchange = self._structured_repair_request(
                chat_request, schema, parse_error, records[repair],
                output_definition=output_definition,
            )
            if exchange is not None:
                exchanges.append(exchange)
            if repair >= len(invocation.response_records):
                log_event(
                    logger, logging.WARNING, "llm.structured_schema_repair",
                    operation=request.operation, version=request.version,
                    parse_error=parse_error[:500],
                )
        raise AssertionError("structured repair loop must return or raise")

    def _structured_repair_request(
        self,
        request: StructuredModelRequest[StructuredOutputT],
        schema: dict[str, Any],
        parse_error: str,
        record: ModelResponseRecord,
        *,
        output_definition: ModelActionDefinition | None = None,
    ) -> tuple[StructuredModelRequest[StructuredOutputT], ModelToolExchange | None]:
        if output_definition is not None:
            if request.action_definitions != (output_definition,):
                raise ValueError("native output repair declaration mismatch")
            instruction, prompt_metadata = _native_output_repair_instruction(
                output_definition, parse_error
            )
        else:
            instruction, prompt_metadata = _schema_repair_instruction(schema, parse_error)
        assistant = record.assistant_message
        exchange = None
        messages = list(request.messages)
        history = request.model_history
        if assistant is not None and assistant.call_ids:
            exchange = ModelToolExchange(
                assistant=assistant,
                results=tuple(
                    ModelToolResult(call_id=call_id, content=instruction["content"])
                    for call_id in assistant.call_ids
                ),
            )
            history = (*history, exchange)
        else:
            if assistant is not None:
                messages.append(assistant.payload)
            else:
                messages.append({
                    "role": "user",
                    "content": json.dumps(
                        {"材料类型": "先前未通过协议校验的模型原始输出，仅作待修复数据",
                         "原始输出": record.raw_response},
                        ensure_ascii=False, separators=(",", ":"),
                    ),
                })
            messages.append(instruction)
        return replace(
            request, messages=messages, model_history=history,
            metadata={**request.metadata, **prompt_metadata},
        ), exchange

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

    def _parse_native_output(
        self,
        request: StructuredModelRequest[StructuredOutputT],
        response: Any,
    ) -> tuple[str, StructuredOutputT | None, str | None]:
        try:
            message = _require_chat_choices(response)[0].message
            calls = _extract_action_invocations(message, request)
            if len(calls) != 1 or calls[0].name != "structured_output":
                raise StructuredOutputFailure(
                    request.operation, "provider must return the single declared output tool"
                )
            content = json.dumps(calls[0].arguments, ensure_ascii=False)
            return content, request.output_type.model_validate(calls[0].arguments), None
        except (StructuredOutputFailure, ValidationError, AttributeError, RuntimeError) as exc:
            return "", None, str(exc)

    def _parse_typed_response(
        self,
        request: StructuredModelRequest[StructuredOutputT],
        response: Any,
        *,
        latency_ms: float,
    ) -> tuple[str, StructuredOutputT | None, str | None]:
        prompted_json = request.output_transport == "prompted_json"
        try:
            message = (
                _require_chat_choices(response)[0].message
                if prompted_json else _structured_chat_message(response)
            )
        except Exception as exc:
            return "", None, str(exc)
        if prompted_json:
            calls = getattr(message, "tool_calls", None)
            if calls is not None and (not isinstance(calls, list) or calls):
                return "", None, "prompted JSON response must not include tool calls"
            content = getattr(message, "content", None)
            if not isinstance(content, str):
                return "", None, "provider returned non-string prompted JSON content"
        else:
            content = (message.content or "").strip()
        if not content.strip():
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
        if request.output_type is BaseModel and not prompted_json:
            return content, self._default_value(request), None
        parse_result = parse_structured(
            content, request.output_type,
            operation=request.operation, version=request.version,
            model_name=getattr(response, "model", None) or self._resolved_model,
            latency_ms=latency_ms,
            allow_json_repair=not prompted_json,
        )
        if not parse_result.ok:
            return content, None, parse_result.error or "invalid structured response"
        return content, parse_result.value, None

    def _generate_chat(
        self,
        request: StructuredModelRequest[StructuredOutputT],
        invocation: ModelInvocationContinuation,
        records: list[ModelResponseRecord],
        errors: list[str],
        exchanges: list[ModelToolExchange],
        response_sink: ModelResponseSink | None,
        before_send: Callable[[], None] | None,
    ) -> StructuredModelResponse[StructuredOutputT]:
        chat_request = request
        for repair in range(request.max_output_repairs + 1):
            if repair < len(records):
                response = _restore_provider_response(records[repair])
            else:
                response = self._receive_response(
                    request, chat_request, invocation, records, response_sink,
                    before_send,
                    structured=False,
                )
            self._check_complete_response(
                request, response,
                stream_protocol_failures=records[repair].stream_protocol_failures,
            )
            message = _require_chat_choices(response)[0].message
            assistant = records[repair].assistant_message
            try:
                actions = (
                    _extract_action_invocations(message, chat_request)
                    if request.kind == "tool_calling" else ()
                )
                if request.kind == "tool_calling" and assistant is None:
                    raise StructuredOutputFailure(
                        request.operation, "provider returned an invalid native assistant message"
                    )
            except StructuredOutputFailure as exc:
                if not (
                    repair < request.max_output_repairs
                    and request.kind == "tool_calling"
                    and request.action_choice == "required"
                    and exc.reason_code in {
                        "provider_action_missing",
                        "provider_action_arguments_invalid_json",
                    }
                ):
                    raise
                errors.append(exc.reason_code)
                repair_prompt = get_prompt("action.repair.system")
                repair_content = repair_prompt.render(validation_feedback=json.dumps(
                    {"reason_code": exc.reason_code,
                     "rejected_output": records[repair].raw_response},
                    ensure_ascii=False,
                ))
                if assistant is None:
                    # A missing/duplicate call ID has no legal native pairing.
                    # Application owns that repair; never fabricate a call ID.
                    raise
                exchange = ModelToolExchange(
                    assistant=assistant,
                    results=tuple(
                        ModelToolResult(call_id=call_id, content=repair_content)
                        for call_id in assistant.call_ids
                    ),
                )
                exchanges.append(exchange)
                chat_request = replace(
                    request,
                    messages=[{"role": "system", "content": repair_content}, *request.messages],
                    model_history=(*request.model_history, *exchanges),
                    metadata={**request.metadata,
                              "action_prompt_name": repair_prompt.name,
                              "action_prompt_version": repair_prompt.version},
                )
                continue
            if repair != len(records) - 1:
                raise ValueError("model continuation contains responses after valid output")
            return self._response(
                request, records,
                value=None if actions else self._default_value(request),
                content=assistant.visible_text if assistant is not None else None,
                action_invocations=actions, retry_errors=errors,
                protocol_exchanges=exchanges,
            )
        raise AssertionError("chat repair loop must return or raise")


def _native_output_repair_instruction(
    output_definition: ModelActionDefinition,
    parse_error: str,
) -> tuple[dict[str, str], dict[str, str]]:
    prompt = get_prompt("structured.native_tool.repair.system")
    return (
        {
            "role": "system",
            "content": prompt.render(
                output_tool_name=output_definition.name,
                validation_feedback=parse_error[:2000],
            ),
        },
        {
            "structured_prompt_name": prompt.name,
            "structured_prompt_version": prompt.version,
        },
    )


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


def _schema_instruction(
    schema: dict[str, Any],
    *,
    parse_error: str | None,
) -> tuple[dict[str, str], dict[str, str]]:
    if parse_error is not None:
        return _schema_repair_instruction(schema, parse_error)
    prompt = get_prompt("structured.system")
    return (
        {
            "role": "system",
            "content": prompt.render(
                output_schema=json.dumps(
                    schema, ensure_ascii=False, separators=(",", ":"),
                ),
            ),
        },
        {"structured_prompt_name": prompt.name, "structured_prompt_version": prompt.version},
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
        instruction, prompt_metadata = _schema_instruction(schema, parse_error=parse_error)
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
        *,
        response_sink: ModelResponseSink | None = None,
        continuation: ModelInvocationContinuation | None = None,
        before_send: Callable[[], None] | None = None,
    ) -> StructuredModelResponse[StructuredOutputT]:
        current = continuation or ModelInvocationContinuation.for_request(
            request, invocation_id=uuid4().hex
        )
        current.validate_request(request)
        retry_errors: list[str] = []

        def aggregate(
            response: StructuredModelResponse[Any], technical_retries: int
        ) -> StructuredModelResponse[Any]:
            return replace(
                response,
                retry_attempts=response.retry_attempts + technical_retries,
                retry_errors=[*retry_errors, *response.retry_errors],
            )

        for attempt in range(self._max_retries + 1):
            try:
                response = self._delegate.generate(
                    request, response_sink=response_sink, continuation=current,
                    before_send=before_send,
                )
                return aggregate(response, attempt)
            except Exception as exc:
                observed = getattr(exc, "response", None)
                if observed is not None and observed.response_records:
                    current = current.model_copy(update={
                        "response_records": observed.response_records,
                    })
                if attempt >= self._max_retries or not _is_retryable_model_error(exc):
                    if observed is None and current.response_records:
                        observed = StructuredModelResponse(
                            value=None, model=current.response_records[-1].model,
                            latency_ms=0, response_records=current.response_records,
                        )
                    if observed is not None:
                        exc.response = aggregate(observed, attempt)
                    if retry_errors:
                        log_event(
                            logger, logging.WARNING, "llm.retry.exhausted",
                            prompt_name=request.operation,
                            prompt_version=request.version, attempts=attempt + 1,
                            retry_errors=retry_errors + [str(exc)[:240]],
                            provider_diagnostics=(
                                exc.diagnostics.model_dump(exclude_none=True)
                                if isinstance(exc, ModelInvocationUnavailable)
                                and exc.diagnostics else None
                            ),
                        )
                    raise
                retry_errors.append(str(exc)[:240])
                delay = self._backoff_seconds * (2**attempt)
                log_event(
                    logger, logging.WARNING, "llm.retry.scheduled",
                    prompt_name=request.operation, prompt_version=request.version,
                    attempt=attempt + 1, max_retries=self._max_retries,
                    retry_delay_seconds=round(delay, 3),
                    retry_error=retry_errors[-1],
                    provider_diagnostics=(
                        exc.diagnostics.model_dump(exclude_none=True)
                        if isinstance(exc, ModelInvocationUnavailable)
                        and exc.diagnostics else None
                    ),
                )
                if delay > 0:
                    sleep(delay)


def _is_retryable_model_error(exc: Exception) -> bool:
    if (
        isinstance(exc, StructuredOutputFailure)
        or getattr(exc, "model_response_recording_failed", False)
        or getattr(exc, "model_before_send_failed", False)
    ):
        return False
    if isinstance(exc, ModelCapacityRefused):
        return False
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
            "output_transport": request.output_transport,
            "max_output_repairs": request.max_output_repairs,
            "output_type": request.output_type.__name__ if request.kind == "structured" else None,
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
            "output_transport": request.output_transport,
            "max_output_repairs": request.max_output_repairs,
            "messages": request.messages,
            "output_type": request.output_type.__name__ if request.kind == "structured" else None,
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
        *,
        response_sink: ModelResponseSink | None = None,
        continuation: ModelInvocationContinuation | None = None,
        before_send: Callable[[], None] | None = None,
    ) -> StructuredModelResponse[StructuredOutputT]:
        response = None
        try:
            response = self._delegate.generate(
                request, response_sink=response_sink, continuation=continuation,
                before_send=before_send,
            )
        except Exception as exc:
            response = getattr(exc, "response", None)
            raise
        finally:
            if response is not None:
                previous_ids = {
                    record.attempt_id for record in continuation.response_records
                } if continuation else set()
                if response.response_records:
                    for record in response.response_records:
                        if record.attempt_id not in previous_ids:
                            record_llm_usage(
                                latency_ms=record.latency_ms,
                                input_tokens=record.input_tokens,
                                output_tokens=record.output_tokens,
                                total_tokens=record.total_tokens,
                            )
                else:
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
        *,
        response_sink: ModelResponseSink | None = None,
        continuation: ModelInvocationContinuation | None = None,
        before_send: Callable[[], None] | None = None,
    ) -> StructuredModelResponse[StructuredOutputT]:
        trace_options: dict[str, Any] = {}
        try:
            from langsmith import traceable

            traced = traceable(
                name="llm.structured_response",
                run_type="llm",
                process_inputs=self._payload_policy.inputs,
                process_outputs=self._payload_policy.outputs,
            )(self._delegate.generate)
            trace_options["langsmith_extra"] = {
                "name": f"llm.{request.operation}",
                "metadata": {
                    "prompt_name": request.operation,
                    "prompt_version": request.version,
                    "output_type": request.output_type.__name__ if request.kind == "structured" else None,
                },
            }
        except Exception:
            traced = self._delegate.generate

        try:
            response = traced(
                request,
                response_sink=response_sink,
                continuation=continuation,
                before_send=before_send,
                **trace_options,
            )
            _report_usage_to_run_tree(response, continuation)
            log_event(
                logger,
                logging.INFO,
                "llm.parse",
                prompt_name=request.operation,
                prompt_version=request.version,
                model=response.model,
                parse_schema=request.output_type.__name__ if request.kind == "structured" else None,
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
                parse_schema=request.output_type.__name__ if request.kind == "structured" else None,
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
