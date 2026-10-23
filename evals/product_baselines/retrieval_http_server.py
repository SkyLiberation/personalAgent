"""Observe real SDK requests without changing production app/model behavior."""
from __future__ import annotations

from functools import wraps
import json
import os
from pathlib import Path
from threading import Lock
from time import monotonic
from uuid import uuid4


def redact_payload(value):
    if isinstance(value, dict):
        return {key: "[redacted]" if str(key).lower() in {
            "api_key", "authorization", "password", "secret", "access_token", "cookie", "extra_headers",
        } else redact_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_payload(item) for item in value]
    return value


def install_sdk_observer(directory: Path) -> None:
    from personal_agent.infra.structured_model import OpenAIModelClient

    original = OpenAIModelClient._create_chat_completion
    lock = Lock()
    directory.mkdir(parents=True, exist_ok=True)

    @wraps(original)
    def observed_create(self, client, operation, kwargs):
        call_id = uuid4().hex
        # SDK call bodies contain model input, never Authorization headers.
        body = redact_payload(kwargs)
        request_path = directory / f"{call_id}.request.json"
        request_path.write_text(json.dumps(body, ensure_ascii=False, default=str), encoding="utf-8")
        started = monotonic()
        record = {"call_id": call_id, "completed": False}
        try:
            response = original(self, client, operation, kwargs)
            record.update(completed=True, response=response.model_dump(mode="json"))
            return response
        except BaseException as error:
            # Provider errors may contain URLs or headers; record type only.
            record["exception_type"] = type(error).__name__
            raise
        finally:
            record["wall_seconds"] = monotonic() - started
            with lock:
                (directory / f"{call_id}.response.json").write_text(
                    json.dumps(record, ensure_ascii=False, default=str), encoding="utf-8",
                )

    OpenAIModelClient._create_chat_completion = observed_create


def main() -> None:
    import uvicorn

    install_sdk_observer(Path(os.environ["RETRIEVAL_E2E_SDK_DIRECTORY"]))
    uvicorn.run("personal_agent.adapters.web.api:app", host="127.0.0.1",
                port=int(os.environ["RETRIEVAL_E2E_HTTP_PORT"]), log_level="info")


if __name__ == "__main__":
    main()
