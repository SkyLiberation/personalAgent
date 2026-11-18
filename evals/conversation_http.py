"""Shared production Web lifecycle and Conversation HTTP entry for public datasets."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from hashlib import file_digest
import json
import mimetypes
import os
from pathlib import Path, PurePath
import socket
import subprocess
import sys
from threading import Thread
from time import monotonic, sleep
from typing import Any, BinaryIO, TYPE_CHECKING
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import httpx
from pydantic import BaseModel

from personal_agent.adapters.web.routes.artifacts import ArtifactResourceView
from personal_agent.adapters.web.routes.conversation import ConversationTurnResumeRequest
from personal_agent.kernel.config_models import InteractionLoopConfig
from personal_agent.kernel.feature_flags import FeatureFlags

from .web_process import ActualWebProcess, record_server_process

if TYPE_CHECKING:
    from personal_agent.adapters.web.routes.conversation import ConversationTurnRequest, TurnId
    from personal_agent.kernel.config import Settings
    from personal_agent.kernel.config_models import OpenAIConfig, StructuredConfig
    from personal_agent.kernel.contracts.resource import ResourceRef


ROOT = Path(__file__).resolve().parents[1]
UNVERIFIED_FLOW = "unverified_flow_capture"
TURNS_PATH = "/api/conversation/turns"


def benchmark_feature_flags(flags: FeatureFlags) -> FeatureFlags:
    return flags.model_copy(update={"goal_verification": False, "answer_verification": False})


def request(base: str, path: str, payload: dict | None = None, *, timeout: float = 3) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        return json.load(response)


def local_attachments(paths: Iterable[Path], *, directory: Path) -> Iterator[tuple[PurePath, BinaryIO]]:
    for path in paths:
        with path.open("rb") as content:
            yield path.relative_to(directory), content


def upload_attachments(
    base: str, files: Iterable[tuple[PurePath, BinaryIO]], *, manifest: Path,
    user_id: str | None = None, api_key: str | None = None,
) -> tuple[ResourceRef, ...]:
    """Register byte-exact originals through the same public upload used by callers."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key is not None else None
    data = {"user_id": user_id} if user_id is not None else None
    records = []
    refs = []
    with httpx.Client(base_url=base, headers=headers, timeout=3600) as client:
        for path, content in files:
            digest = file_digest(content, "sha256").hexdigest()
            size = content.seek(0, 2)
            content.seek(0)
            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            response = client.post("/api/artifacts/upload", data=data, files={"file": (path.name, content, media_type)})
            response.raise_for_status()
            resource = ArtifactResourceView.model_validate_json(response.content).resource
            if resource.content_digest != digest or resource.size_bytes != size:
                raise ValueError(f"Artifact upload differs from source: {path.as_posix()}")
            records.append({"source_path": path.as_posix(), **resource.model_dump(mode="json")})
            refs.append(resource.resource_ref)
    manifest.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return tuple(dict.fromkeys(refs))


def submit_turn(
    base: str, body: ConversationTurnRequest, *, timeout: float, api_key: str | None = None,
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key is not None else None
    return httpx.post(
        base + TURNS_PATH, json=body.model_dump(mode="json"), headers=headers, timeout=timeout,
    )


def turn_path(turn_id: TurnId) -> str:
    return f"{TURNS_PATH}/{turn_id}"


def resume_turn(
    base: str, turn_id: TurnId, *, timeout: float, user_id: str | None = None, api_key: str | None = None,
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key is not None else None
    return httpx.post(
        base + turn_path(turn_id) + "/resume",
        json=ConversationTurnResumeRequest(user_id=user_id).model_dump(mode="json"),
        headers=headers, timeout=timeout,
    )


def wait_for_product(base: str, process: ActualWebProcess, timeout: float) -> bool:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            if request(base, "/api/health")["status"] == "ok":
                return True
        except URLError:
            sleep(0.2)
    raise RuntimeError("Product Web process did not become ready")


class WebModelSettings(BaseModel):
    model: str
    provider: str | None
    provider_host: str | None
    timeout_seconds: float
    max_retries: int

    @classmethod
    def from_config(cls, config: OpenAIConfig | StructuredConfig) -> WebModelSettings:
        return cls(
            model=config.model,
            provider=config.provider,
            provider_host=urlsplit(config.base_url or "").hostname,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
        )


class WebSettingsSnapshot(BaseModel):
    structured: WebModelSettings
    openai: WebModelSettings
    budget: InteractionLoopConfig
    feature_flags: FeatureFlags


def _record_web_settings(directory: Path, settings: Settings) -> None:
    snapshot = WebSettingsSnapshot(
        structured=WebModelSettings.from_config(settings.structured),
        openai=WebModelSettings.from_config(settings.openai),
        budget=settings.interaction_loop,
        feature_flags=settings.feature_flags,
    )
    (directory / "web-settings.json").write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")


def effective_structured_model(directory: Path) -> str:
    return WebSettingsSnapshot.model_validate_json((directory / "web-settings.json").read_bytes()).structured.model


@contextmanager
def product(
    output: Path, env: dict[str, str], *, sdk_directory: Path | None = None, log_name: str = "web.log",
) -> Iterator[tuple[str, ActualWebProcess]]:
    log_path = output / log_name
    port_file = output / "web.port"
    stop_signal = output / "stop-web"
    command = [sys.executable, "-B", "-X", "utf8", "-m", "evals.conversation_http", str(output)]
    if sdk_directory is not None:
        command.extend(("--sdk-directory", str(sdk_directory)))
    environment = {
        **env,
        "PYTHONUTF8": "1",
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONPATH": os.pathsep.join((str(ROOT), str(ROOT / "src"))),
    }
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        )
        actual = None
        try:
            deadline = monotonic() + 45
            while not port_file.exists():
                if process.poll() is not None or monotonic() >= deadline:
                    raise RuntimeError(f"Product Web process did not bind a port. See {log_path}.")
                sleep(0.05)
            actual = ActualWebProcess(process, output / "server-process.json")
            port = int(port_file.read_text(encoding="ascii"))
            yield f"http://127.0.0.1:{port}", actual
        finally:
            try:
                stop_signal.touch()
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                if actual is None and (output / "server-process.json").is_file():
                    actual = ActualWebProcess(process, output / "server-process.json")
                if actual is not None:
                    actual.stop(deadline=monotonic() + 5)
                else:
                    process.kill()
                    process.wait(timeout=5)
                raise RuntimeError("Product did not shut down gracefully") from None
            finally:
                if actual is not None:
                    try:
                        if actual.poll() is None:
                            actual.stop(deadline=monotonic() + 5)
                            raise RuntimeError("Product launcher exited before the Web process")
                    finally:
                        actual.close()


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sdk-directory", type=Path)
    args = parser.parse_args()
    record_server_process(args.output / "server-process.json")

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        port_file = args.output / "web.port"
        pending = port_file.with_suffix(".tmp")
        pending.write_text(str(port), encoding="ascii")
        pending.replace(port_file)
        if args.sdk_directory is not None:
            from .sdk_capture import install_acceptance_observer

            install_acceptance_observer(args.sdk_directory)
        from personal_agent.adapters.web.api import app

        _record_web_settings(args.output, app.state.context.settings)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port))

        def shutdown() -> None:
            while not (args.output / "stop-web").exists():
                sleep(0.1)
            server.should_exit = True

        Thread(target=shutdown, daemon=True).start()
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
