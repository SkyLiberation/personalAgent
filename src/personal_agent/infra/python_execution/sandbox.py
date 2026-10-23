"""Run one untrusted Python program in Docker, outside the production Runtime.

The result channels are captured stdout and stderr. Callers own their output
contracts; this runner confirms process termination and preserves actual bytes.
"""

from __future__ import annotations

from contextlib import closing

import hashlib
import json
import math
import shutil
import socket
import struct
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol
from pydantic import TypeAdapter

from personal_agent.application.python_execution.models import validate_python_filename

if TYPE_CHECKING:
    from docker.models.containers import Container


SandboxStatus = Literal["succeeded", "failed", "timed_out", "output_limit", "unknown"]
_API_TIMEOUT = 5
_API_VERSION = "1.44"
_POLL_SECONDS = 0.1
_READ_CHUNK = 64 * 1024
_COMMAND = ["python", "-I", "/inputs/program.py", "/inputs"]


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: float = 60
    memory_mb: int = 512
    cpus: float = 1.0
    pids_limit: int = 64
    stdout_bytes: int = 16 * 1024 * 1024
    stderr_bytes: int = 64 * 1024
    scratch_mb: int = 32

    def __post_init__(self) -> None:
        for name in ("timeout_seconds", "cpus"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a positive finite number")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        for name in (
            "memory_mb",
            "pids_limit",
            "stdout_bytes",
            "stderr_bytes",
            "scratch_mb",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if int(self.cpus * 1_000_000_000) < 1:
            raise ValueError("cpus is below Docker's nanocpu resolution")


@dataclass(frozen=True)
class SandboxResult:
    container_id: str
    status: SandboxStatus
    exit_code: int | None
    stdout: bytes
    stderr: str
    elapsed_seconds: float
    image_id: str
    stderr_raw: bytes = b""
    oom_killed: bool | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    output_available: bool = True
    elapsed_known: bool = True


@dataclass
class _JobRecord:
    container_name: str
    endpoint: str
    limits: SandboxLimits
    staging_directory: str
    input_sha256: dict[str, str]
    job_key: str | None = None
    container_id: str = ""
    image_id: str = ""
    phase: (
        Literal["prepared", "create_requested", "created", "start_requested", "started"]
        | SandboxStatus
    ) = "prepared"
    backend_state: str | None = None
    container_removed: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _ContainerState:
    status: str
    exit_code: int | None
    oom_killed: bool

    @property
    def terminal(self) -> bool:
        return self.status in {"exited", "dead"}


@dataclass(frozen=True)
class _SavedResult:
    container_id: str
    status: SandboxStatus
    exit_code: int | None
    elapsed_seconds: float
    image_id: str
    stdout_file: str
    stdout_bytes: int
    stdout_sha256: str
    stderr_file: str
    stderr_bytes: int
    backend_state: str | None
    errors: list[str]
    stderr_sha256: str = ""
    oom_killed: bool | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    output_available: bool = True


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:1024]}"


def _copy_input(source: Path, target: Path) -> str:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"input must be a regular, non-symlink file: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as reader, target.open("xb") as writer:
        while block := reader.read(1024 * 1024):
            digest.update(block)
            writer.write(block)
    target.chmod(0o444)
    return digest.hexdigest()


def _remove_staging(directory: Path) -> None:
    resolved = directory.resolve()
    if (
        directory.is_symlink()
        or resolved.parent != Path(tempfile.gettempdir()).resolve()
        or not resolved.name.startswith("retrieval-candidate-inputs-")
    ):
        raise RuntimeError("refusing to remove an unexpected staging directory")
    # Windows preserves the read-only bit even after the container is removed.
    for child in resolved.iterdir():
        if child.is_symlink() or not child.is_file():
            raise RuntimeError("unexpected entry in the flat input staging directory")
        child.chmod(0o600)
    shutil.rmtree(resolved)


def _stage_inputs(
    directory: Path, program: Path, inputs: Mapping[str, Path]
) -> dict[str, str]:
    names: set[str] = {"program.py", "input_manifest.json"}
    for name in inputs:
        validate_python_filename(name)
        if name.casefold() in names:
            raise ValueError(f"reserved or colliding input name: {name}")
        names.add(name.casefold())
    hashes = {"program.py": _copy_input(program, directory / "program.py")}
    for name, source in inputs.items():
        hashes[name] = _copy_input(source, directory / name)
    directory.chmod(0o755)
    return hashes


def _inspect(container: Container) -> _ContainerState:
    container.reload()
    raw = container.attrs.get("State")
    if not isinstance(raw, dict) or not isinstance(raw.get("Status"), str):
        raise RuntimeError("Docker inspect returned no valid State.Status")
    exit_code = raw.get("ExitCode")
    if exit_code is not None and type(exit_code) is not int:
        raise RuntimeError("Docker inspect returned an invalid ExitCode")
    oom = raw.get("OOMKilled", False)
    if type(oom) is not bool:
        raise RuntimeError("Docker inspect returned an invalid OOMKilled")
    return _ContainerState(raw["Status"], exit_code, oom)


def _stop_and_confirm(
    container: Container, errors: list[str], *, force: bool
) -> _ContainerState | None:
    """API acceptance or timeout never stands in for a terminal inspect."""
    try:
        if force:
            container.kill()
        else:
            container.stop(timeout=1)
    except Exception as exc:
        errors.append("stop request: " + _error_text(exc))
    try:
        state = _inspect(container)
        if state.terminal:
            return state
    except Exception as exc:
        errors.append("inspect after stop: " + _error_text(exc))
    try:
        container.kill()
    except Exception as exc:
        errors.append("kill request: " + _error_text(exc))
    try:
        state = _inspect(container)
        if state.terminal:
            return state
        errors.append(f"container is still {state.status} after termination requests")
    except Exception as exc:
        errors.append("final inspect: " + _error_text(exc))
    return None


class _AttachChannel(Protocol):
    def close(self) -> None: ...


class _OutputCapture:
    """One Docker multiplexed stream, two independent byte budgets."""

    def __init__(self, channel: _AttachChannel, limits: SandboxLimits) -> None:
        from docker.utils.socket import read

        self.channel = channel
        self.limits = limits
        self.lock = threading.Lock()
        self.overflow = threading.Event()
        self.failed = threading.Event()
        self.closing = threading.Event()
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.stdout_truncated = False
        self.stderr_truncated = False
        self.errors: list[str] = []
        # The pinned SDK handles Unix/TCP poll and Windows pipe EOF; reading the
        # raw SocketIO directly would turn five seconds of silence into failure.
        self.read: Callable[[int], bytes] = lambda size: read(channel, size)
        self.thread = threading.Thread(
            target=self._consume, name="retrieval-candidate-output", daemon=True
        )

    def _read_exactly(self, size: int, *, allow_eof: bool = False) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            block = self.read(size - len(chunks))
            if block is None:
                continue
            if not block:
                if allow_eof and not chunks:
                    return b""
                raise RuntimeError("truncated Docker output frame")
            chunks.extend(block)
        return bytes(chunks)

    def _consume(self) -> None:
        try:
            while header := self._read_exactly(8, allow_eof=True):
                stream, size = struct.unpack(">BxxxI", header)
                if stream not in (1, 2) or header[1:4] != b"\0\0\0":
                    raise RuntimeError("invalid Docker output stream frame")
                while size:
                    block = self._read_exactly(min(size, _READ_CHUNK))
                    size -= len(block)
                    with self.lock:
                        # Keep draining attach after overflow. Stopping reads can
                        # backpressure Docker's kill/inspect control requests.
                        target = self.stdout if stream == 1 else self.stderr
                        budget = (
                            self.limits.stdout_bytes
                            if stream == 1
                            else self.limits.stderr_bytes
                        )
                        available = budget - len(target)
                        target.extend(block[:available])
                        exceeded = len(block) > available
                        if exceeded:
                            if stream == 1:
                                self.stdout_truncated = True
                            else:
                                self.stderr_truncated = True
                    if exceeded:
                        self.overflow.set()
                        # The main thread exclusively owns kill and terminal
                        # confirmation; this thread only consumes output.
        except Exception as exc:
            if not self.closing.is_set():
                with self.lock:
                    self.errors.append("output reader: " + _error_text(exc))
                self.failed.set()

    def finish(self) -> tuple[bytes, bytes, list[str]]:
        self.thread.join(timeout=2)
        was_alive = self.thread.is_alive()
        if was_alive:
            self.failed.set()
            with self.lock:
                self.errors.append("output reader did not finish after container stop")
        self.closing.set()
        # Closing a SocketIO wrapper alone may leave its underlying recv blocked.
        underlying = getattr(self.channel, "_sock", self.channel)
        try:
            shutdown = getattr(underlying, "shutdown", None)
            if was_alive and callable(shutdown):
                shutdown(socket.SHUT_RDWR)
        except Exception as exc:
            with self.lock:
                self.errors.append("attach shutdown: " + _error_text(exc))
        try:
            self.channel.close()
        except Exception as exc:
            with self.lock:
                self.errors.append("attach close: " + _error_text(exc))
        self.thread.join(timeout=1)
        with self.lock:
            return bytes(self.stdout), bytes(self.stderr), list(self.errors)


def _persist_result(
    output_dir: Path, result: SandboxResult, stderr: bytes, job: _JobRecord
) -> None:
    (output_dir / "stdout.json").write_bytes(result.stdout)
    (output_dir / "stderr.log").write_bytes(stderr)
    saved = _SavedResult(
        result.container_id,
        result.status,
        result.exit_code,
        result.elapsed_seconds,
        result.image_id,
        "stdout.json",
        len(result.stdout),
        hashlib.sha256(result.stdout).hexdigest(),
        "stderr.log",
        len(stderr),
        job.backend_state,
        list(job.errors),
        hashlib.sha256(stderr).hexdigest(),
        result.oom_killed,
        result.stdout_truncated,
        result.stderr_truncated,
        result.output_available,
    )
    _write_json(output_dir / "result.json", asdict(saved))
    _write_json(output_dir / "job.json", asdict(job))


def run_program(
    *,
    endpoint: str,
    image: str,
    program: Path,
    inputs: Mapping[str, Path],
    output_dir: Path,
    limits: SandboxLimits = SandboxLimits(),
    job_key: str | None = None,
    deadline_at: datetime | None = None,
    retain_jobs: bool = False,
) -> SandboxResult:
    """Execute exactly ``python -I /inputs/program.py /inputs`` once.

    ``inputs`` keys are exact flat filenames under ``/inputs``.
    Neither this API nor Docker pulls images.
    ``output_dir`` must be new or empty. Unknown jobs keep their container and
    staged inputs for reconciliation using the name/ID in ``job.json``.
    """
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("an explicit Docker Engine endpoint is required")
    if not endpoint.startswith(
        ("unix://", "npipe://", "tcp://", "http://", "https://")
    ):
        raise ValueError("unsupported explicit Docker Engine endpoint")
    if "@" in endpoint:
        raise ValueError("Docker endpoint must not contain embedded credentials")
    if not isinstance(image, str) or not image.strip():
        raise ValueError("an existing local candidate image is required")
    if not isinstance(limits, SandboxLimits):
        raise ValueError("limits must be SandboxLimits")
    if output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        if job_key is None:
            raise ValueError(f"output directory must be empty: {output_dir}")
        return _recover_program(
            endpoint=endpoint,
            image=image,
            program=program,
            inputs=inputs,
            output_dir=output_dir,
            job_key=job_key,
        )

    try:
        from docker import DockerClient
        from docker.types import LogConfig, Mount
    except ImportError as exc:
        raise RuntimeError(
            "install requirements-control.txt before candidate execution"
        ) from exc

    staging = Path(tempfile.mkdtemp(prefix="retrieval-candidate-inputs-"))
    try:
        hashes = _stage_inputs(staging, program, inputs)
    except BaseException:
        _remove_staging(staging)
        raise
    job = _JobRecord(
        container_name="retrieval-candidate-"
        + (job_key[:40] if job_key else uuid.uuid4().hex),
        endpoint=endpoint,
        limits=limits,
        staging_directory=str(staging),
        input_sha256=hashes,
        job_key=job_key,
    )
    _write_json(output_dir / "job.json", asdict(job))
    started = time.monotonic()
    client = None
    container = None
    capture = None
    state = None
    start_requested = False
    create_requested = False
    terminal_confirmed = False
    interrupted: BaseException | None = None
    status: SandboxStatus = "failed"
    stdout = stderr = b""
    try:
        # Fixed API avoids any constructor-time request before host proxy and
        # netrc discovery are disabled. The daemon must support this API version.
        client = DockerClient(
            base_url=endpoint, version=_API_VERSION, timeout=_API_TIMEOUT
        )
        client.api.trust_env = False
        local_image = client.images.get(image)
        job.image_id = local_image.id
        if local_image.attrs.get("Os") != "linux":
            raise ValueError("candidate image must use Linux isolation")
        if local_image.attrs.get("Config", {}).get("Volumes"):
            raise ValueError("candidate image must not declare writable volumes")
        _write_json(output_dir / "job.json", asdict(job))
        create_requested = True
        job.phase = "create_requested"
        _write_json(output_dir / "job.json", asdict(job))
        container = client.containers.create(
            image=job.image_id,
            command=_COMMAND,
            entrypoint=[],
            name=job.container_name,
            detach=True,
            stdin_open=False,
            tty=False,
            user="65534:65534",
            working_dir="/tmp",
            environment={"PYTHONDONTWRITEBYTECODE": "1", "HOME": "/tmp"},
            use_config_proxy=False,
            healthcheck={"test": ["NONE"]},
            mounts=[Mount("/inputs", str(staging), type="bind", read_only=True)],
            network_mode="none",
            read_only=True,
            privileged=False,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            mem_limit=limits.memory_mb * 1024 * 1024,
            memswap_limit=limits.memory_mb * 1024 * 1024,
            nano_cpus=int(limits.cpus * 1_000_000_000),
            pids_limit=limits.pids_limit,
            ipc_mode="none",
            auto_remove=False,
            restart_policy={"Name": "no"},
            tmpfs={
                "/tmp": f"rw,noexec,nosuid,nodev,size={limits.scratch_mb}m,mode=1777"
            },
            log_config=LogConfig(
                type="json-file", config={"max-size": "1m", "max-file": "1"}
            ),
            labels={
                "personal-agent.retrieval-experiment": job.container_name,
                "personal-agent.job": job_key or job.container_name,
                "personal-agent.inputs": hashlib.sha256(
                    json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            },
        )
        job.container_id = container.id
        job.phase = "created"
        # Persist the actual backend identity before any start request.
        _write_json(output_dir / "job.json", asdict(job))
        channel = container.attach_socket(
            params={"stdout": 1, "stderr": 1, "stream": 1, "logs": 0}
        )
        capture = _OutputCapture(channel, limits)
        capture.thread.start()
        started = time.monotonic()
        remaining = (
            min(
                limits.timeout_seconds,
                (deadline_at - datetime.now(timezone.utc)).total_seconds(),
            )
            if deadline_at
            else limits.timeout_seconds
        )
        if remaining <= 0:
            raise TimeoutError("原实验deadline已到，拒绝启动候选")
        deadline = started + remaining
        start_requested = True
        job.phase = "start_requested"
        _write_json(output_dir / "job.json", asdict(job))
        container.start()
        job.phase = "started"
        _write_json(output_dir / "job.json", asdict(job))
        while True:
            if capture.overflow.is_set():
                status = "output_limit"
                break
            if capture.failed.is_set():
                status = "failed"
                break
            if time.monotonic() >= deadline:
                status = "timed_out"
                break
            state = _inspect(container)
            if state.terminal:
                terminal_confirmed = True
                status = (
                    "succeeded"
                    if state.exit_code == 0 and not state.oom_killed
                    else "failed"
                )
                break
            capture.overflow.wait(
                timeout=min(_POLL_SECONDS, max(0, deadline - time.monotonic()))
            )
    except BaseException as exc:
        job.errors.append(_error_text(exc))
        if not isinstance(exc, Exception):
            interrupted = exc
        # A lost create response is reconciled by the original unique name;
        # it is never retried or followed by an implicit start.
        if container is None and create_requested and client is not None:
            try:
                recovered = client.containers.get(job.container_name)
                if (
                    recovered.attrs.get("Image") != job.image_id
                    or recovered.labels.get("personal-agent.retrieval-experiment")
                    != job.container_name
                ):
                    raise RuntimeError(
                        "container name reconciliation did not match frozen binding"
                    )
                container = recovered
                job.container_id = recovered.id
            except Exception as reconcile_error:
                job.errors.append(
                    "create reconciliation: " + _error_text(reconcile_error)
                )
        status = "unknown" if create_requested and container is None else "failed"
    finally:
        if container is not None and not terminal_confirmed:
            if start_requested:
                state = _stop_and_confirm(
                    container,
                    job.errors,
                    force=capture is not None and capture.overflow.is_set(),
                )
                terminal_confirmed = state is not None
            else:
                try:
                    state = _inspect(container)
                    # A never-started container has no candidate process to stop.
                    terminal_confirmed = state.terminal or state.status == "created"
                except Exception as exc:
                    job.errors.append("inspect before cleanup: " + _error_text(exc))
            if not terminal_confirmed:
                status = "unknown"
        if capture is not None:
            stdout, stderr, capture_errors = capture.finish()
            job.errors.extend(capture_errors)
            if status != "unknown":
                if capture.overflow.is_set():
                    status = "output_limit"
                elif capture.failed.is_set():
                    status = "failed"
        job.backend_state = state.status if state is not None else None
        job.phase = status
        result = SandboxResult(
            container_id=job.container_id,
            status=status,
            exit_code=state.exit_code if state is not None and state.terminal else None,
            stdout=stdout,
            stderr=stderr.decode("utf-8", errors="replace"),
            elapsed_seconds=time.monotonic() - started,
            image_id=job.image_id,
            stderr_raw=stderr,
            oom_killed=state.oom_killed if state is not None else None,
            stdout_truncated=capture.stdout_truncated if capture is not None else False,
            stderr_truncated=capture.stderr_truncated if capture is not None else False,
        )
        # If persistence fails, leave the backend identity and files for review.
        _persist_result(output_dir, result, stderr, job)
        if container is not None and terminal_confirmed and not retain_jobs:
            try:
                container.remove()
                job.container_removed = True
            except Exception as exc:
                job.errors.append("container cleanup: " + _error_text(exc))
        if (container is None and not create_requested) or job.container_removed:
            try:
                _remove_staging(staging)
            except Exception as exc:
                job.errors.append("input cleanup: " + _error_text(exc))
        _persist_result(output_dir, result, stderr, job)
        if client is not None:
            client.close()
    if interrupted is not None:
        raise interrupted
    return result


def _recover_program(
    *,
    endpoint: str,
    image: str,
    program: Path | None = None,
    inputs: Mapping[str, Path] | None = None,
    output_dir: Path,
    job_key: str,
    input_sha256: Mapping[str, str] | None = None,
) -> SandboxResult:
    """原候选完整输出可复用；失去capture的在途进程只确认停止，不重启。"""
    from docker import DockerClient

    record_path = output_dir / "job.json"
    if not record_path.is_file():
        raise RuntimeError("候选目录缺少原身份，禁止重新执行")
    raw = asdict(TypeAdapter(_JobRecord).validate_json(record_path.read_bytes()))
    expected_name = "retrieval-candidate-" + job_key[:40]
    if input_sha256 is not None:
        hashes = dict(input_sha256)
    else:
        if program is None or inputs is None:
            raise ValueError("恢复Python需要确切输入摘要或原件")
        hashes = {"program.py": hashlib.sha256(program.read_bytes()).hexdigest()}
        hashes.update(
            {
                name: hashlib.sha256(path.read_bytes()).hexdigest()
                for name, path in inputs.items()
            }
        )
    if (
        raw["container_name"] != expected_name
        or raw["image_id"] not in {"", image}
        or raw["job_key"] != job_key
        or raw["input_sha256"] != hashes
    ):
        raise ValueError("原候选身份与恢复请求不同")
    saved_path = output_dir / "result.json"
    if saved_path.is_file():
        saved = asdict(TypeAdapter(_SavedResult).validate_json(saved_path.read_bytes()))
        if (
            (
                saved["container_id"] != raw["container_id"]
                and not (saved["status"] == "unknown" and not saved["container_id"])
            )
            or saved["image_id"] != raw["image_id"]
            or saved["stdout_file"] != "stdout.json"
            or saved["stderr_file"] != "stderr.log"
            or saved["stdout_bytes"] < 0
            or saved["stderr_bytes"] < 0
            or saved["stdout_bytes"] > raw["limits"]["stdout_bytes"]
            or saved["stderr_bytes"] > raw["limits"]["stderr_bytes"]
        ):
            raise ValueError("原Python捕获与作业身份或限额不同")
        if saved["status"] != "unknown":
            if (
                not (output_dir / "stdout.json").is_file()
                or not (output_dir / "stderr.log").is_file()
            ):
                return SandboxResult(
                    saved["container_id"],
                    saved["status"],
                    saved["exit_code"],
                    b"",
                    "",
                    saved["elapsed_seconds"],
                    saved["image_id"],
                    oom_killed=saved["oom_killed"],
                    stdout_truncated=saved["stdout_truncated"],
                    stderr_truncated=saved["stderr_truncated"],
                    output_available=False,
                )
            stdout = (output_dir / "stdout.json").read_bytes()
            stderr_raw = (output_dir / "stderr.log").read_bytes()
            stderr = stderr_raw.decode("utf-8", errors="replace")
            if len(stdout) != saved["stdout_bytes"] or hashlib.sha256(
                stdout
            ).hexdigest() != saved.get("stdout_sha256"):
                raise ValueError("原候选输出不完整")
            if len(stderr_raw) != saved["stderr_bytes"] or (
                saved["stderr_sha256"]
                and hashlib.sha256(stderr_raw).hexdigest() != saved["stderr_sha256"]
            ):
                raise ValueError("原Python stderr捕获不完整")
            return SandboxResult(
                saved["container_id"],
                saved["status"],
                saved["exit_code"],
                stdout,
                stderr,
                saved["elapsed_seconds"],
                saved["image_id"],
                stderr_raw,
                saved["oom_killed"],
                saved["stdout_truncated"],
                saved["stderr_truncated"],
                saved["output_available"],
            )
    errors = []
    state = None
    with closing(
        DockerClient(base_url=endpoint, version=_API_VERSION, timeout=_API_TIMEOUT)
    ) as client:
        client.api.trust_env = False
        try:
            container = client.containers.get(expected_name)
            if (
                container.attrs.get("Image") != image
                or container.labels.get("personal-agent.retrieval-experiment")
                != expected_name
                or container.labels.get("personal-agent.job") != job_key
                or container.labels.get("personal-agent.inputs")
                != hashlib.sha256(
                    json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
            ):
                raise ValueError("原候选容器绑定不符")
            state = _stop_and_confirm(container, errors, force=True)
            raw["container_id"] = container.id
        except Exception as exc:
            errors.append(_error_text(exc))
    status = "failed" if state and state.terminal else "unknown"
    result = SandboxResult(
        raw.get("container_id", ""),
        status,
        state.exit_code if state else None,
        b"",
        "原候选完整输出不可恢复；未重启。",
        0,
        image,
        oom_killed=state.oom_killed if state else None,
        output_available=False,
        elapsed_known=False,
    )
    raw["phase"] = status
    raw["backend_state"] = state.status if state else None
    raw["errors"].extend(errors)
    _write_json(record_path, raw)
    return result
