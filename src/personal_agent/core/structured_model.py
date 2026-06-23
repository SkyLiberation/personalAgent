"""Typed structured-model port and infrastructure adapters."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Generic, Protocol, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from .config_models import LangSmithConfig, RouterConfig
from .llm_telemetry import record_llm_usage
from .logging_utils import log_event

logger = logging.getLogger(__name__)
StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StructuredModelRequest(Generic[StructuredOutputT]):
    """Provider-neutral request for one typed model response."""

    operation: str
    version: str
    messages: list[dict[str, str]]
    output_type: type[StructuredOutputT]
    temperature: float = 0
    max_tokens: int = 500


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


class StructuredModelClient(Protocol):
    """Application port for Pydantic-typed model calls."""

    def generate(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]: ...


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


class OpenAIResponsesModelClient:
    """OpenAI Responses API adapter for the structured-model port."""

    def __init__(self, config: RouterConfig) -> None:
        self._config = config

    def generate(
        self,
        request: StructuredModelRequest[StructuredOutputT],
    ) -> StructuredModelResponse[StructuredOutputT]:
        start = perf_counter()
        client = OpenAI(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
            max_retries=self._config.max_retries,
        )
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "input": request.messages,
            "text_format": request.output_type,
            "max_output_tokens": request.max_tokens,
        }
        if not _is_reasoning_model(self._config.model):
            kwargs["temperature"] = request.temperature
        if self._config.extra_body:
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
        record_llm_usage(
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        log_event(
            logger,
            logging.INFO,
            "llm.call",
            prompt_name=request.operation,
            prompt_version=request.version,
            model=self._config.model,
            latency_ms=latency_ms,
            response_chars=len(content),
            output_type=request.output_type.__name__,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        return StructuredModelResponse(
            value=parsed,
            model=getattr(response, "model", None) or self._config.model,
            latency_ms=latency_ms,
            content=content,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw_response=response,
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
            "output_type": request.output_type.__name__,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "message_count": len(messages),
            "message_roles": [str(message.get("role", "")) for message in messages],
            "message_chars": sum(len(str(message.get("content", ""))) for message in messages),
        }

    def outputs(
        self,
        response: StructuredModelResponse[Any],
    ) -> dict[str, Any]:
        return {
            "model": response.model,
            "latency_ms": response.latency_ms,
            "response_chars": len(response.content),
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
            "messages": request.messages,
            "output_type": request.output_type.__name__,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

    def outputs(
        self,
        response: StructuredModelResponse[Any],
    ) -> dict[str, Any]:
        return {
            "value": response.value.model_dump(mode="json"),
            "content": response.content,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "total_tokens": response.total_tokens,
        }


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


def build_structured_model_client(
    config: RouterConfig,
    observability: LangSmithConfig,
) -> StructuredModelClient | None:
    """Composition helper used at application startup."""
    if not (config.api_key and config.base_url and config.model):
        return None
    client: StructuredModelClient = OpenAIResponsesModelClient(config)
    if not observability.enabled:
        return client
    policy: TracePayloadPolicy = (
        FullTracePayloadPolicy()
        if observability.upload_inputs
        else RedactedTracePayloadPolicy()
    )
    return ObservedStructuredModelClient(client, policy)
