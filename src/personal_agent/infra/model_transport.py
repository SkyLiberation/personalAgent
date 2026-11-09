"""Minimized HTTPX observations for the OpenAI-compatible model adapter.

Hooks run on the actual request thread. State belongs to that HTTP Request,
including streaming consumption after Client.send returns; no global last call.
"""

from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any, Callable, Iterator
from uuid import uuid4

import httpx
from openai import APIConnectionError, DefaultHttpxClient

from personal_agent.capabilities.contracts.model import (
    PROVIDER_DIAGNOSTIC_MAX_CHARS,
    ModelTransportDiagnostics,
    ProviderExceptionFrame,
)
from personal_agent.kernel.logging_utils import log_event

logger = logging.getLogger(__name__)
_OBSERVATION_KEY = "personal_agent.model_transport"


def clean_provider_diagnostic(value: object, api_key: str = "") -> str | None:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    text = str(value)
    if api_key:
        text = text.replace(api_key, "[redacted]")
    text = re.sub(r"(?i)\bBearer\s+[^\s\"',;]+", "Bearer [redacted]", text)
    text = re.sub(r"\b(?:sk|tp)-[A-Za-z0-9_-]{8,}", "[redacted]", text)
    text = re.sub(r"https?://[^\s<>\"']+", "[url redacted]", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|authorization|cookie|password|secret)"
        r"\b[\"']?\s*[:=]\s*[\"']?[^\s,;\"']+",
        r"\1=[redacted]", text,
    )
    return re.sub(r"[\x00-\x1f\x7f]", " ", text).strip()[:PROVIDER_DIAGNOSTIC_MAX_CHARS] or None


def provider_exception_chain(error: BaseException, api_key: str = "") -> tuple[ProviderExceptionFrame, ...]:
    frames = []
    seen: set[int] = set()
    relation = "root"
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(frames) < 8:
        seen.add(id(current))
        # APIStatusError.__str__ includes arbitrary provider bodies. Only network
        # exceptions have messages here; error envelopes retain their whitelist.
        network_error = isinstance(current, (httpx.TransportError, APIConnectionError, OSError))
        network_error = network_error or type(current).__module__.startswith("httpcore")
        frames.append(ProviderExceptionFrame(
            relation=relation,
            exception_type=f"{type(current).__module__}.{type(current).__name__}",
            message=clean_provider_diagnostic(str(current), api_key) if network_error else None,
        ))
        if current.__cause__ is not None:
            current, relation = current.__cause__, "cause"
        elif not current.__suppress_context__:
            current, relation = current.__context__, "context"
        else:
            current = None
    return tuple(frames)


class _RequestObservation:
    def __init__(self, request: httpx.Request, api_key: str) -> None:
        self.started = perf_counter()
        self.api_key = api_key
        self.value = ModelTransportDiagnostics(attempt_id=uuid4().hex, provider_host=request.url.host,
                                               elapsed_seconds=0)
        self.exceptions: tuple[ProviderExceptionFrame, ...] = ()
        self.upstream_trace: Callable[[str, dict[str, Any]], None] | None = None

    def update(self, **fields: Any) -> None:
        self.value = ModelTransportDiagnostics.model_validate({**self.value.model_dump(), **fields})

    def snapshot(self) -> ModelTransportDiagnostics:
        return self.value.model_copy(update={"elapsed_seconds": perf_counter() - self.started})

    def emit(self, event: str) -> None:
        try:
            log_event(logger, logging.INFO, event, transport=self.snapshot().model_dump(exclude_none=True),
                      exception_chain=[frame.model_dump(exclude_none=True) for frame in self.exceptions] or None)
        except Exception:
            # Optional transport telemetry must not change model execution.
            pass

    def trace(self, name: str, fields: dict[str, Any]) -> None:
        try:
            # SSE consumers normally close the HTTP iterator after [DONE].
            # HTTPcore reports GeneratorExit via .failed; it is no remote fault.
            if name.endswith(".failed") and isinstance(fields.get("exception"), GeneratorExit):
                return
            self.update(phase=clean_provider_diagnostic(name, self.api_key))
            if name == "connection.connect_tcp.started":
                self.update(connect_host=clean_provider_diagnostic(fields.get("host"), self.api_key),
                            connect_port=fields.get("port"))
            if name.endswith(".failed") and isinstance(fields.get("exception"), BaseException):
                self.update(failure_phase=clean_provider_diagnostic(name, self.api_key))
                self.exceptions = provider_exception_chain(fields["exception"], self.api_key)
                self.emit("llm.http.failed")
        except Exception:
            pass


def model_transport_snapshot(source: object) -> ModelTransportDiagnostics | None:
    if isinstance(source, httpx.Request):
        observation = source.extensions.get(_OBSERVATION_KEY)
        return observation.snapshot() if isinstance(observation, _RequestObservation) else None
    # SDK connection errors can reference the original Request even after a
    # redirect. HTTPX's underlying failure identifies the actual failed Request.
    current = source
    seen: set[int] = set()
    snapshot = None
    while isinstance(current, BaseException) and id(current) not in seen and len(seen) < 8:
        seen.add(id(current))
        try:
            observed = model_transport_snapshot(getattr(current, "request", None))
            if observed is not None:
                snapshot = observed
        except RuntimeError:  # HTTPX errors may have no bound Request.
            pass
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return snapshot


class _ObservedBody(httpx.SyncByteStream):
    def __init__(self, inner: httpx.SyncByteStream, observation: _RequestObservation) -> None:
        self.inner, self.observation = inner, observation

    def __iter__(self) -> Iterator[bytes]:
        try:
            for chunk in self.inner:
                try:
                    if chunk:
                        value = self.observation.value
                        elapsed = perf_counter() - self.observation.started
                        self.observation.update(first_byte_seconds=value.first_byte_seconds if value.first_byte_seconds is not None else elapsed,
                                                last_byte_seconds=elapsed, body_bytes=value.body_bytes + len(chunk),
                                                body_chunks=value.body_chunks + 1)
                except Exception:
                    pass
                yield chunk
            try:
                self.observation.update(body_complete=True)
            except Exception:
                pass
        except BaseException as error:
            try:
                self.observation.exceptions = provider_exception_chain(error, self.observation.api_key)
            except Exception:
                pass
            raise

    def close(self) -> None:
        try:
            self.inner.close()
        finally:
            try:
                self.observation.update(closed=True)
                self.observation.emit("llm.http.body_closed")
            except Exception:
                pass


def model_http_client(*, api_key: str, timeout: float) -> httpx.Client:
    """Keep SDK defaults while explicitly installing request-local observers."""
    def request_hook(request: httpx.Request) -> None:
        try:
            previous = request.extensions.get(_OBSERVATION_KEY)
            previous_trace = previous.upstream_trace if isinstance(previous, _RequestObservation) else request.extensions.get("trace")
            observation = _RequestObservation(request, api_key)
            observation.upstream_trace = previous_trace if callable(previous_trace) else None
            request.extensions[_OBSERVATION_KEY] = observation

            def trace(name: str, fields: dict[str, Any]) -> None:
                observation.trace(name, fields)
                if observation.upstream_trace is not None:
                    observation.upstream_trace(name, fields)

            request.extensions["trace"] = trace
        except Exception:
            pass

    def response_hook(response: httpx.Response) -> None:
        observation = response.request.extensions.get(_OBSERVATION_KEY)
        if not isinstance(observation, _RequestObservation):
            return
        try:
            clean = lambda value: clean_provider_diagnostic(value, api_key)
            observation.update(status_code=response.status_code, headers_seconds=perf_counter() - observation.started,
                               content_type=clean(response.headers.get("content-type")),
                               content_length=clean(response.headers.get("content-length")),
                               transfer_encoding=clean(response.headers.get("transfer-encoding")),
                               content_encoding=clean(response.headers.get("content-encoding")),
                               provider_request_id=clean(response.headers.get("x-request-id")),
                               retry_after=clean(response.headers.get("retry-after")))
            network_stream = response.extensions.get("network_stream")
            if network_stream is not None:
                peer = network_stream.get_extra_info("server_addr")
                if isinstance(peer, tuple) and len(peer) >= 2:
                    observation.update(peer_host=clean(peer[0]), peer_port=peer[1])
        except Exception:
            pass
        response.stream = _ObservedBody(response.stream, observation)
        observation.emit("llm.http.headers")

    return DefaultHttpxClient(timeout=timeout, event_hooks={"request": [request_hook], "response": [response_hook]})
