"""Dispatch and recover fresh Bash processes in an authorized Docker container."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
from threading import RLock
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, TypeAdapter

from personal_agent.application.bash_execution.models import (
    BashBackendOutcome,
    BashExecutionCommand,
    BashExecutionFact,
    BashExecutionProfile,
    Digest,
)
from personal_agent.application.bash_execution.ports import BashInputLoader
from personal_agent.application.bash_execution.workspace_edit import WORKSPACE_VERSION_ENV
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .run_container import BASH_USER, BashTurnContainers, BashWorkspaceUnavailable
from .sandbox import SandboxLimits, _OutputCapture, _POLL_SECONDS, _stop_and_confirm, _write_json

if TYPE_CHECKING:
    from docker import DockerClient
    from docker.models.containers import Container

logger = logging.getLogger(__name__)
_FILE_DIGEST = TypeAdapter(Digest)


class _Job(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command_digest: str
    # This field is part of the persisted Bash job and result records.
    run_key: str
    container_id: str
    exec_id: str
    expected_file_version: Digest | None = None


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job: _Job
    fact: BashExecutionFact
    stdout_digest: str
    stderr_digest: str


class DockerBashExecutionBackend:
    def __init__(
        self, *, endpoint: str, work_root: Path, profile: BashExecutionProfile,
        prompts: PromptCatalog = DEFAULT_PROMPTS,
    ) -> None:
        if not endpoint.startswith(("unix://", "npipe://", "tcp://", "http://", "https://")) or "@" in endpoint:
            raise ValueError("Bash执行器需要无内嵌凭证的显式Docker Engine端点")
        self._prompts = prompts
        self.work_root = work_root.resolve()
        self.profile = profile
        self.containers = BashTurnContainers(endpoint, self.work_root, profile, prompts=prompts)
        # The Conversation Journal serializes API owners across processes.
        # Also serialize actions dispatched concurrently by this Runtime.
        self._lock = RLock()

    def _root(self, command: BashExecutionCommand) -> Path:
        if (
            command.execution_scope.principal != self.profile.authorized_principal
            or command.deployment_digest != self.profile.deployment_digest
            or command.image_id != self.profile.image_id
            or (command.task_workspace is None) != (self.profile.task_workspace is None)
            or command.limits.timeout_seconds > self.profile.limits.timeout_seconds
            or command.limits.model_dump(exclude={"timeout_seconds"})
            != self.profile.limits.model_dump(exclude={"timeout_seconds"})
        ):
            raise PermissionError(self._prompts.render("bash_backend.deployment"))
        root = self.work_root / command.command_digest
        if any(path.is_symlink() for path in (root, *root.parents)):
            raise ValueError(self._prompts.render("bash_backend.directory_symlink"))
        return root

    def _snapshot(self, root: Path, command: BashExecutionCommand) -> None:
        path = root / "command.json"
        if path.is_file():
            if path.is_symlink() or BashExecutionCommand.model_validate_json(
                path.read_bytes(), context=self._prompts,
            ) != command:
                raise ValueError(self._prompts.render("bash_backend.job_command"))
        else:
            raise ValueError(self._prompts.render("bash_backend.job_command_missing"))

    def execute(
        self, command: BashExecutionCommand, load_input: BashInputLoader,
        *, run_deadline_at: datetime,
    ) -> BashBackendOutcome:
        root = self._root(command)
        if command.deadline_at > run_deadline_at:
            raise ValueError(self._prompts.render("bash_backend.deployment"))
        with self._lock:
            if (root / "command.json").exists():
                self._snapshot(root, command)
            else:
                root.mkdir(parents=True, exist_ok=True)
                if any(root.iterdir()):
                    raise ValueError(self._prompts.render("bash_backend.job_identity"))
                with (root / "command.json").open("x", encoding="utf-8") as stream:
                    stream.write(command.model_dump_json() + "\n")
            output = root / "execution"
            if output.exists():
                return self.reconcile(command)
            output.mkdir()
            key = self.containers.key(command.execution_scope)
            if command.deadline_at <= datetime.now(timezone.utc):
                return _unavailable(status="timed_out", error_code="deadline")
            try:
                with closing(self.containers.connect()) as client:
                    self._retire_unsettled(client, key)
                    container = (
                        self.containers.prepare_task(client, key, command, load_input)
                        if command.task_workspace is not None else
                        self.containers.prepare(client, key, run_deadline_at, command, load_input)
                    )
                    return self._execute_in(client, container, command, output, key)
            except BashWorkspaceUnavailable:
                return _unavailable(status="failed", error_code="workspace_unavailable")
            except Exception:
                logger.exception("Bash Docker dispatch failed for %s", command.command_digest)
                if (output / "job.json").is_file():
                    return self.reconcile(command)
                return _unavailable(status="failed", error_code="execution_failed")

    def _execute_in(
        self, client: DockerClient, container: Container, command: BashExecutionCommand, output: Path, key: str,
    ) -> BashBackendOutcome:
        remaining = (command.deadline_at - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return _unavailable(status="timed_out", error_code="deadline")
        start = time.monotonic()
        deadline = start + min(remaining, command.limits.timeout_seconds)
        file_action = command.workspace_file
        expected_version = (
            self.containers.observed_file_version(key, container.id, file_action.file_path)
            if file_action is not None and file_action.operation == "edit" else None
        )
        exec_id = client.api.exec_create(
            container.id,
            ["bash", "--noprofile", "--norc", f"{self.containers.inputs_path}/command.sh"],
            user=BASH_USER, workdir=f"{self.containers.workdir}/{command.workdir}",
            environment={WORKSPACE_VERSION_ENV: expected_version} if expected_version is not None else None,
        )["Id"]
        job = _Job(command_digest=command.command_digest, run_key=key, container_id=container.id, exec_id=exec_id,
                   expected_file_version=expected_version)
        _write_json(output / "job.json", job.model_dump(mode="json"))
        active = self.containers.active_record(key)
        _write_json(active, job.command_digest)
        if time.monotonic() >= deadline:
            outcome = BashBackendOutcome(
                execution=BashExecutionFact(
                    status="timed_out", container_id=job.container_id, image_id=command.image_id,
                    elapsed_seconds=time.monotonic() - start, output_available=False, error_code="deadline",
                ),
                stdout=b"", stderr=b"",
            )
            self._persist(output, job, outcome)
            active.unlink()
            return outcome
        capture = None
        oom_killed = None
        try:
            capture = _OutputCapture(
                client.api.exec_start(job.exec_id, socket=True),
                SandboxLimits(**command.limits.model_dump()),
            )
            capture.thread.start()
            status, exit_code = self._wait_for_exit(client, job, capture, deadline)
            idle = exit_code is not None and self.containers.idle(container)
            oom_killed = container.attrs["State"].get("OOMKilled") or None
            discarded = not idle or bool(oom_killed)
            if discarded:
                observed_exit, observed_oom = self._terminate(client, container, job)
                if exit_code is None:
                    exit_code = observed_exit
                oom_killed = oom_killed or observed_oom
        except BaseException:
            self.containers.discard(container)
            raise
        finally:
            if capture is not None and capture.thread.ident is not None:
                stdout, stderr, errors = capture.finish()
                if errors:
                    logger.warning("Bash Docker output capture %s: %s", job.exec_id, "; ".join(errors))
        if capture.overflow.is_set():
            if not discarded:
                self._terminate(client, container, job)
            status = "output_limit"
        elif oom_killed or (capture.failed.is_set() and status == "succeeded"):
            status = "failed"
        fact = BashExecutionFact(
            status=status, process_exit_code=exit_code, elapsed_seconds=time.monotonic() - start,
            container_id=job.container_id, image_id=command.image_id,
            oom_killed=oom_killed,
            stdout_truncated=capture.stdout_truncated, stderr_truncated=capture.stderr_truncated,
            output_available=not capture.failed.is_set(),
            error_code={
                "succeeded": None, "failed": "execution_failed",
                "timed_out": "deadline", "output_limit": "output_limit",
            }[status] if not oom_killed else "oom",
        )
        observed_version = None
        if file_action is not None:
            # The registered worker sends the version before the model-visible body.
            digest, _, stdout = stdout.partition(b"\n")
            if status == "succeeded" and not discarded:
                observed_version = _FILE_DIGEST.validate_python(digest.decode("ascii"))
        outcome = BashBackendOutcome(execution=fact, stdout=stdout, stderr=stderr)
        self._persist(output, job, outcome)
        if file_action is not None and observed_version is not None:
            self.containers.record_file_version(key, container.id, file_action.file_path, observed_version)
        active.unlink()
        return outcome

    def _terminate(self, client: DockerClient, container: Container, job: _Job) -> tuple[int | None, bool | None]:
        from docker.errors import APIError

        try:
            exec_state = client.api.exec_inspect(job.exec_id)
            exit_code = None if exec_state["Running"] else exec_state["ExitCode"]
        except APIError:
            # Docker can no longer inspect an Exec when its container stopped.
            # That makes the exit code unavailable, not cleanup optional.
            exit_code = None
        errors: list[str] = []
        state = _stop_and_confirm(container, errors, force=True)
        # Force removal also confirms absence when another process or the Turn
        # deadline stopped the original namespace before our inspect.
        self.containers.discard(container)
        return exit_code, True if state is not None and state.oom_killed else None

    @staticmethod
    def _persist(output: Path, job: _Job, outcome: BashBackendOutcome) -> None:
        (output / "stdout.json").write_bytes(outcome.stdout)
        (output / "stderr.log").write_bytes(outcome.stderr)
        result = _Result(
            job=job, fact=outcome.execution, stdout_digest=sha256(outcome.stdout).hexdigest(),
            stderr_digest=sha256(outcome.stderr).hexdigest(),
        )
        _write_json(output / "result.json", result.model_dump(mode="json"))

    def _retire_unsettled(self, client: DockerClient, key: str) -> None:
        active = self.containers.active_record(key)
        if not active.exists():
            return
        digest = json.loads(active.read_bytes())
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("无效的 Bash Run 待结算记录引用")
        output = self.work_root / digest / "execution"
        job = _Job.model_validate_json((output / "job.json").read_bytes())
        if job.command_digest != digest or job.run_key != key:
            raise ValueError(self._prompts.render("bash_backend.job_binding"))
        result = output / "result.json"
        if not result.is_file() or _Result.model_validate_json(result.read_bytes()).job != job:
            container = self.containers.lookup(client, key, identity=job.container_id)
            if container is not None:
                self.containers.discard(container)
        active.unlink()

    @staticmethod
    def _wait_for_exit(client: DockerClient, job: _Job, capture: _OutputCapture, deadline: float):
        while True:
            if capture.overflow.is_set():
                return "output_limit", None
            if capture.failed.is_set():
                return "failed", None
            if time.monotonic() >= deadline:
                return "timed_out", None
            state = client.api.exec_inspect(job.exec_id)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timed_out", None
            if not state["Running"] and (exit_code := state["ExitCode"]) is not None:
                return ("succeeded" if exit_code == 0 else "failed"), exit_code
            capture.overflow.wait(min(remaining, _POLL_SECONDS))

    def reconcile(self, command: BashExecutionCommand) -> BashBackendOutcome:
        root = self._root(command)
        with self._lock:
            if (root / "command.json").exists():
                self._snapshot(root, command)
            output = root / "execution"
            if not (output / "job.json").is_file():
                return _unavailable()
            job = _Job.model_validate_json((output / "job.json").read_bytes())
            key = self.containers.key(command.execution_scope)
            if job.command_digest != command.command_digest or job.run_key != key:
                raise ValueError(self._prompts.render("bash_backend.job_binding"))
            record = output / "result.json"
            if record.is_file():
                saved = _Result.model_validate_json(record.read_bytes())
                if (saved.job != job or saved.fact.container_id != job.container_id
                        or saved.fact.image_id != command.image_id):
                    raise ValueError(self._prompts.render("bash_recovery.capture_binding"))
                stdout_file, stderr_file = output / "stdout.json", output / "stderr.log"
                if not (stdout_file.is_file() and stderr_file.is_file()):
                    return BashBackendOutcome(
                        execution=saved.fact.model_copy(update={"output_available": False}), stdout=b"", stderr=b"",
                    )
                stdout, stderr = stdout_file.read_bytes(), stderr_file.read_bytes()
                if (len(stdout) > command.limits.stdout_bytes or len(stderr) > command.limits.stderr_bytes
                        or sha256(stdout).hexdigest() != saved.stdout_digest
                        or sha256(stderr).hexdigest() != saved.stderr_digest):
                    raise ValueError(self._prompts.render("bash_recovery.output_incomplete"))
                return BashBackendOutcome(execution=saved.fact, stdout=stdout, stderr=stderr)

            # The host may have crashed after starting this exec. Never start
            # another copy or stop a newer container with the same name.
            try:
                exit_code, oom_killed = None, None
                with closing(self.containers.connect()) as client:
                    container = self.containers.lookup(client, key, identity=job.container_id)
                    if container is not None:
                        exit_code, oom_killed = self._terminate(client, container, job)
            except Exception:
                logger.exception("Could not reconcile Bash exec %s", job.exec_id)
                return _unavailable()
            return BashBackendOutcome(
                execution=BashExecutionFact(
                    status="failed", process_exit_code=exit_code, oom_killed=oom_killed,
                    image_id=command.image_id, container_id=job.container_id, output_available=False,
                    error_code="output_unavailable",
                ),
                stdout=b"", stderr=b"",
            )

    def close_turn(self, scope: ExecutionScope) -> None:
        key = self.containers.key(scope)
        if not self.containers.expiry_record(key).exists():
            return
        with self._lock, closing(self.containers.connect()) as client:
            if self.profile.task_workspace is None:
                self.containers.close(client, key)
            elif self.containers.task_turn_owns_workspace(key, scope.execution_id):
                self._retire_unsettled(client, key)
                self.containers.close_task_turn(client, key)

    def close_task_workspace(self) -> None:
        if self.profile.task_workspace is None:
            return
        key = self.containers.task_key()
        if not self.containers.expiry_record(key).exists():
            return
        with self._lock, closing(self.containers.connect()) as client:
            self._retire_unsettled(client, key)
            self.containers.invalidate_task(client, key)

    def sweep_expired(self) -> None:
        if not self.containers.root.is_dir():
            return
        try:
            with closing(self.containers.connect()) as client:
                self.containers.sweep_expired(client)
        except Exception:
            logger.exception("Could not sweep expired Bash Run containers")


def _unavailable(*, status="unknown", error_code="backend_unknown") -> BashBackendOutcome:
    return BashBackendOutcome(
        execution=BashExecutionFact(status=status, output_available=False, error_code=error_code),
        stdout=b"", stderr=b"",
    )
