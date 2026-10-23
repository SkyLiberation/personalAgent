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

from fastapi import FastAPI, HTTPException, Request

from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

from .retrieval_http_server import redact_payload


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
            record.update(response_received=True, status_code=response.status_code)
            return response
        except BaseException as error:
            record["exception_type"] = type(error).__name__
            raise
        finally:
            record["wall_seconds"] = monotonic() - started
            (directory / f"{send_id}.http.response.json").write_bytes(_json_bytes(record))

    @wraps(original_create)
    def observed_create(self, client, operation, kwargs):
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
            response = original_create(self, client, operation, kwargs)
            record.update(completed=True, response=response.model_dump(mode="json"))
            return response
        except BaseException as error:
            record["exception_type"] = type(error).__name__
            if hasattr(error, "reason_code"):
                record["reason_code"] = error.reason_code
            raise
        finally:
            record["wall_seconds"] = monotonic() - started
            (directory / f"{candidate_id}.candidate.response.json").write_bytes(_json_bytes(record))

    httpx.Client.send = observed_send
    OpenAIModelClient._create_chat_completion = observed_create


def main() -> None:
    observer_configuration = os.environ.get("RETRIEVAL_E2E_WRITE_AUDIT_CONFIGURATION")
    observer = None
    if observer_configuration is not None:
        from .retrieval_knowledge_write_audit import KnowledgeWriteObserver, WriteAuditConfiguration

        observer = KnowledgeWriteObserver(WriteAuditConfiguration.model_validate_json(
            Path(observer_configuration).read_bytes()))

    import uvicorn

    install_acceptance_observer(Path(os.environ["RETRIEVAL_E2E_SDK_DIRECTORY"]))
    fault_path = os.environ.get("RETRIEVAL_E2E_FAULT_CONFIGURATION")
    if fault_path is not None:
        from .retrieval_start_response_fault import (
            StartResponseFaultConfiguration,
            install_start_response_fault,
        )

        install_start_response_fault(
            StartResponseFaultConfiguration.model_validate_json(Path(fault_path).read_bytes())
        )
    app: FastAPI | str = "personal_agent.adapters.web.api:app"
    if observer is not None:
        from personal_agent.adapters.web.api import app as production_app

        def close_write_observer(request: Request):
            principal = AuthenticatedPrincipal.model_validate(getattr(request.state, "principal", None))
            if principal != observer.configuration.principal:
                raise HTTPException(status_code=403, detail="观察关闭主体不属于本次采集")
            return observer.close().model_dump(mode="json")

        production_app.add_api_route("/__retrieval_e2e_observer__/close", close_write_observer,
                                     methods=["POST"], include_in_schema=False)
        app = production_app
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ["RETRIEVAL_E2E_HTTP_PORT"]),
        log_level="info",
    )


if __name__ == "__main__":
    main()
