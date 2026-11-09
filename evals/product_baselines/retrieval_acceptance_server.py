"""只读封存候选模型输入和实际 HTTP 发送；不改变生产请求或规则。"""

from __future__ import annotations

from functools import wraps
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Lock
from time import monotonic
from uuid import uuid4

if __name__ == "__main__":
    from .retrieval_capture_process import record_server_process

    record_server_process(Path(os.environ["RETRIEVAL_E2E_PROCESS_FILE"]))

def redact_payload(value):
    if isinstance(value, dict):
        return {key: "[redacted]" if str(key).lower() in {
            "api_key", "authorization", "password", "secret", "access_token", "cookie", "extra_headers",
        } else redact_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_payload(item) for item in value]
    return value


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def install_acceptance_observer(directory: Path) -> None:
    """Only Client.send records are physical requests; capacity refusals stay candidates.

    The provider deadline creates another thread, so a ContextVar would lose the
    association. Keep all candidate IDs per actual SDK HTTP client instead. An
    association can be plural after retries; the raw HTTP count stays exact.
    """
    import httpx

    from personal_agent.infra.structured_model import OpenAIModelClient
    from personal_agent.infra.model_transport import model_transport_snapshot, provider_exception_chain

    directory.mkdir(parents=True, exist_ok=False)
    original_create = OpenAIModelClient._create_chat_completion
    original_send = httpx.Client.send
    lock = Lock()
    candidate_ids: dict[httpx.Client, list[str]] = {}

    @wraps(original_send)
    def observed_send(http_client, request, *args, **kwargs):
        with lock:
            related = tuple(candidate_ids.get(http_client, ()))
        if not related:
            return original_send(http_client, request, *args, **kwargs)
        send_id = uuid4().hex
        record: dict[str, object] = {
            "send_id": send_id,
            "observation": "httpx_client_send_invoked",
            "candidate_ids_on_client": related,
            "provider_host": request.url.host,
            "method": request.method,
            "path": request.url.path,
            "response_received": False,
        }
        started = monotonic()
        transport_source = request
        try:
            body = request.content
            # JSON bytes are saved as sent; never include request headers.
            json.loads(body)
            record["request_body_sha256"] = sha256(body).hexdigest()
            record["request_body_bytes"] = len(body)
            (directory / f"{send_id}.http.request.json").write_bytes(body)
        except (ValueError, TypeError, RuntimeError) as error:
            record["body_observation_error"] = type(error).__name__
        try:
            response = original_send(http_client, request, *args, **kwargs)
            transport_source = response.request
            record.update(response_received=True, status_code=response.status_code)
            return response
        except BaseException as error:
            transport_source = error
            record["exception_type"] = type(error).__name__
            record["exception_chain"] = [frame.model_dump(exclude_none=True) for frame in
                                         provider_exception_chain(error, request.headers.get("authorization", "").removeprefix("Bearer "))]
            raise
        finally:
            transport = model_transport_snapshot(transport_source)
            if transport is not None:
                record["transport"] = transport.model_dump(exclude_none=True)
            record["wall_seconds"] = monotonic() - started
            (directory / f"{send_id}.http.response.json").write_bytes(_json_bytes(record))

    @wraps(original_create)
    def observed_create(self, client, operation, kwargs, *, before_send=None):
        candidate_id = uuid4().hex
        http_client = client._client
        with lock:
            candidate_ids.setdefault(http_client, []).append(candidate_id)
        record: dict[str, object] = {
            "candidate_id": candidate_id,
            "observation": "before_capacity_admission",
            "operation": operation,
            "completed": False,
        }
        started = monotonic()
        try:
            body = _json_bytes(redact_payload(kwargs))
            record["candidate_body_sha256"] = sha256(body).hexdigest()
            (directory / f"{candidate_id}.candidate.request.json").write_bytes(body)
        except (ValueError, TypeError) as error:
            record["body_observation_error"] = type(error).__name__
        try:
            completion = original_create(self, client, operation, kwargs, before_send=before_send)
            record.update(completed=True, response=completion.payload.model_dump(mode="json"))
            return completion
        except BaseException as error:
            record["exception_type"] = type(error).__name__
            diagnostics = getattr(error, "diagnostics", None)
            if diagnostics is not None:
                record["provider_diagnostics"] = diagnostics.model_dump(exclude_none=True)
            if hasattr(error, "reason_code"):
                record["reason_code"] = error.reason_code
            raise
        finally:
            record["wall_seconds"] = monotonic() - started
            (directory / f"{candidate_id}.candidate.response.json").write_bytes(_json_bytes(record))

    httpx.Client.send = observed_send
    OpenAIModelClient._create_chat_completion = observed_create


def main() -> None:
    import uvicorn

    install_acceptance_observer(Path(os.environ["RETRIEVAL_E2E_SDK_DIRECTORY"]))
    uvicorn.run(
        "personal_agent.adapters.web.api:app",
        host="127.0.0.1",
        port=int(os.environ["RETRIEVAL_E2E_HTTP_PORT"]),
        log_level="info",
    )


if __name__ == "__main__":
    main()
