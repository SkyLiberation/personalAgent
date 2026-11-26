"""Execute governed Bash calls through a native Linux bubblewrap sandbox."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import logging
import os
from pathlib import Path, PurePosixPath
from selectors import DefaultSelector, EVENT_READ
import shutil
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired
import sys
from threading import RLock
from time import monotonic
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from personal_agent.application.bash_execution.models import (
    BASH_DEFAULT_INPUTS_DIR,
    BASH_SHARED_INPUTS_DIR,
    BASH_TEMP_DIR,
    BashBackendOutcome,
    BashExecutionCommand,
    BashExecutionFact,
    BashExecutionProfile,
    Digest,
    ErrorCode,
    ProcessStatus,
)
from personal_agent.application.bash_execution.workspace_edit import WORKSPACE_VERSION_ENV
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .persistent import PersistentBash, stop_process
from .workspace import BashTaskFiles, BashWorkspaceUnavailable, publish_task_inputs, stage_inputs, write_record

if TYPE_CHECKING:
    from personal_agent.application.bash_execution.ports import BashInputLoader


logger = logging.getLogger(__name__)
_FILE_DIGEST = TypeAdapter(Digest)
_SettledStatus = Literal["succeeded", "failed", "timed_out", "output_limit"]


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command_digest: Digest
    fact: BashExecutionFact
    stdout_digest: Digest
    stderr_digest: Digest


class NativeBashExecutionBackend:
    def __init__(
        self, *, work_root: Path, profile: BashExecutionProfile,
        prompts: PromptCatalog = DEFAULT_PROMPTS,
    ) -> None:
        bwrap = shutil.which("bwrap")
        bash = shutil.which("bash")
        if sys.platform != "linux" or bwrap is None or bash is None:
            raise RuntimeError("Native Bash execution requires Linux with bubblewrap and Bash installed")
        self._bwrap = str(Path(bwrap).resolve(strict=True))
        self._bash = str(Path(bash).resolve(strict=True))
        self._prompts = prompts
        self.work_root = work_root.resolve()
        if self.work_root.parent == Path("/"):
            raise ValueError("The Agent's private data directory must be below the host root")
        self.profile = profile
        self.tasks = BashTaskFiles(self.work_root, profile)
        if profile.persistent_bash and profile.task_workspace is None:
            raise ValueError("Persistent Bash requires an authorized task workspace")
        self._persistent = PersistentBash() if profile.persistent_bash else None
        self._hidden = {self.work_root.parent, *(path.resolve() for path in profile.hidden_directories)}
        if Path("/") in self._hidden:
            raise ValueError("The host root cannot be a hidden Bash directory")
        self._shared = profile.workspace.host_path.resolve(strict=True) if profile.workspace else None
        if self._shared is not None:
            if not self._shared.is_dir():
                raise ValueError("The authorized Bash workspace must be a directory")
            if any(path.is_relative_to(self._shared) for path in self._hidden):
                raise ValueError("The authorized Bash workspace contains a hidden directory")
        self._lock = RLock()

    def _root(self, command: BashExecutionCommand) -> Path:
        if (
            command.execution_scope.principal != self.profile.authorized_principal
            or command.deployment_digest != self.profile.deployment_digest
            or (command.task_workspace is None) != (self.profile.task_workspace is None)
            or command.limits.timeout_seconds > self.profile.limits.timeout_seconds
            or command.limits.model_dump(exclude={"timeout_seconds"})
            != self.profile.limits.model_dump(exclude={"timeout_seconds"})
        ):
            raise PermissionError(self._prompts.render("bash_backend.deployment"))
        root = self.work_root / command.command_digest
        if root.is_symlink():
            raise ValueError(self._prompts.render("bash_backend.directory_symlink"))
        return root

    def _snapshot(self, root: Path, command: BashExecutionCommand) -> None:
        path = root / "command.json"
        if path.is_symlink() or BashExecutionCommand.model_validate_json(
            path.read_bytes(), context=self._prompts,
        ) != command:
            raise ValueError(self._prompts.render("bash_backend.job_command"))

    def execute(
        self, command: BashExecutionCommand, load_input: BashInputLoader,
        *, run_deadline_at: datetime,
    ) -> BashBackendOutcome:
        root = self._root(command)
        if command.deadline_at > run_deadline_at:
            raise ValueError(self._prompts.render("bash_backend.deployment"))
        with self._lock:
            root.mkdir(parents=True, exist_ok=True)
            try:
                with (root / "command.json").open("x", encoding="utf-8") as stream:
                    stream.write(command.model_dump_json())
            except FileExistsError:
                self._snapshot(root, command)
            output = root / "execution"
            try:
                output.mkdir()
            except FileExistsError:
                return self.reconcile(command)
            # Claim execution before launching. Parent death terminates the
            # namespace, and a missing settlement never authorizes a retry.
            inputs = root / "input"
            try:
                stage_inputs(inputs, command, load_input)
                scratch = self.tasks.prepare(command) if command.task_workspace is not None else None
                outcome = self._run(command, inputs, scratch)
            except BashWorkspaceUnavailable:
                outcome = _unavailable(status="failed", error_code="workspace_unavailable")
            except Exception:
                logger.exception("Native Bash dispatch failed for %s", command.command_digest)
                outcome = _unavailable(status="failed", error_code="execution_failed")
            finally:
                if inputs.is_dir():
                    shutil.rmtree(inputs)
            self._persist(output, command.command_digest, outcome)
            return outcome

    def _argv(self, inputs: Path, scratch: Path | None, *, relative_workdir: str) -> list[str]:
        workspace = self.profile.workspace
        input_root = BASH_SHARED_INPUTS_DIR if workspace else BASH_DEFAULT_INPUTS_DIR
        workdir = workspace.root if workspace else input_root
        argv = [self._bwrap]
        if not self.profile.allow_network:
            argv.append("--unshare-net")
        if Path(BASH_DEFAULT_INPUTS_DIR).is_dir():
            argv.extend(("--ro-bind", "/", "/"))
        else:
            # Bubblewrap must be able to create /workspace when the host has no mountpoint.
            for entry in sorted(Path("/").iterdir()):
                path = str(entry)
                if path in {"/dev", "/proc", BASH_TEMP_DIR, BASH_DEFAULT_INPUTS_DIR}:
                    continue
                if entry.is_symlink():
                    argv.extend(("--symlink", os.readlink(entry), path))
                elif entry.is_file() or entry.is_dir():
                    argv.extend(("--ro-bind", path, path))
        argv.extend(("--dev", "/dev", "--unshare-pid", "--proc", "/proc", "--die-with-parent",
                     "--tmpfs", BASH_TEMP_DIR))
        for path in sorted(self._hidden):
            if path.is_dir() and not path.is_relative_to(BASH_TEMP_DIR) and self._hidden.isdisjoint(path.parents):
                argv.extend(("--tmpfs", str(path)))
        if workspace is not None:
            argv.extend(("--tmpfs", BASH_DEFAULT_INPUTS_DIR))
        argv.extend(("--ro-bind", str(inputs), input_root))
        if scratch is not None:
            argv.extend(("--bind", str(scratch), BASH_TEMP_DIR))
        if workspace is not None:
            argv.extend(("--bind", str(self._shared), workdir))
            argv.extend(("--remount-ro", BASH_DEFAULT_INPUTS_DIR))
        argv.extend(("--remount-ro", "/"))
        argv.extend(("--chdir", str(PurePosixPath(workdir) / relative_workdir), "--", self._bash,
                     "--noprofile", "--norc"))
        if self._persistent is None:
            argv.append(f"{input_root}/command.sh")
        return argv

    def _run(self, command: BashExecutionCommand, inputs: Path, scratch: Path | None) -> BashBackendOutcome:
        remaining = (command.deadline_at - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return _unavailable(status="timed_out", error_code="deadline")
        started = monotonic()
        deadline = started + min(remaining, command.limits.timeout_seconds)
        env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": BASH_TEMP_DIR,
               "TMPDIR": BASH_TEMP_DIR, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        action = command.workspace_file
        version = self.tasks.observed_version(action.file_path) if action is not None and action.operation == "edit" else None
        if self._persistent is not None:
            publish_task_inputs(self.tasks.inputs, inputs, command)
            argv = self._argv(self.tasks.inputs, scratch, relative_workdir=".")
            outcome = self._persistent.run(argv, env, command, started=started, deadline=deadline, version=version)
        else:
            argv = self._argv(inputs, scratch, relative_workdir=command.workdir)
            if version is not None:
                env[WORKSPACE_VERSION_ENV] = version
            outcome = self._run_once(argv, env, command, started=started, deadline=deadline)
        if action is not None and outcome.execution.status == "succeeded":
            digest, _, stdout = outcome.stdout.partition(b"\n")
            self.tasks.observe(action.file_path, _FILE_DIGEST.validate_python(digest.decode("ascii")))
            outcome = outcome.model_copy(update={"stdout": stdout})
        return outcome

    @staticmethod
    def _run_once(
        argv: list[str], env: dict[str, str], command: BashExecutionCommand, *, started: float, deadline: float,
    ) -> BashBackendOutcome:
        with Popen(argv, env=env, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, start_new_session=True) as process:
            try:
                status, stdout, stderr, truncated = _capture(process, command, deadline)
            finally:
                if process.poll() is None:
                    stop_process(process)
            exit_code = process.returncode
        if exit_code is not None and exit_code < 0:
            exit_code = 128 - exit_code
        fact = BashExecutionFact(
            status=status, process_exit_code=exit_code, elapsed_seconds=monotonic() - started,
            stdout_truncated="stdout" in truncated, stderr_truncated="stderr" in truncated,
            error_code={"succeeded": None, "failed": "execution_failed",
                        "timed_out": "deadline", "output_limit": "output_limit"}[status],
        )
        return BashBackendOutcome(execution=fact, stdout=stdout, stderr=stderr)

    @staticmethod
    def _persist(output: Path, digest: Digest, outcome: BashBackendOutcome) -> None:
        (output / "stdout.json").write_bytes(outcome.stdout)
        (output / "stderr.log").write_bytes(outcome.stderr)
        write_record(output / "result.json", _Result(
            command_digest=digest, fact=outcome.execution,
            stdout_digest=sha256(outcome.stdout).hexdigest(), stderr_digest=sha256(outcome.stderr).hexdigest(),
        ))

    def reconcile(self, command: BashExecutionCommand) -> BashBackendOutcome:
        root = self._root(command)
        output = root / "execution"
        record = output / "result.json"
        with self._lock:
            if not record.is_file():
                return _unavailable()
            self._snapshot(root, command)
            saved = _Result.model_validate_json(record.read_bytes())
            if saved.command_digest != command.command_digest:
                raise ValueError(self._prompts.render("bash_recovery.capture_binding"))
            stdout_file, stderr_file = output / "stdout.json", output / "stderr.log"
            if not (stdout_file.is_file() and stderr_file.is_file()):
                return BashBackendOutcome(execution=saved.fact.model_copy(update={"output_available": False}),
                                          stdout=b"", stderr=b"")
            stdout, stderr = stdout_file.read_bytes(), stderr_file.read_bytes()
            if (len(stdout) > command.limits.stdout_bytes or len(stderr) > command.limits.stderr_bytes
                    or sha256(stdout).hexdigest() != saved.stdout_digest
                    or sha256(stderr).hexdigest() != saved.stderr_digest):
                raise ValueError(self._prompts.render("bash_recovery.output_incomplete"))
            return BashBackendOutcome(execution=saved.fact, stdout=stdout, stderr=stderr)

    def close_task_workspace(self) -> None:
        with self._lock:
            if self._persistent is not None:
                self._persistent.close()
            self.tasks.close()


def _capture(
    process: Popen[bytes], command: BashExecutionCommand, deadline: float,
) -> tuple[_SettledStatus, bytes, bytes, set[str]]:
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": command.limits.stdout_bytes, "stderr": command.limits.stderr_bytes}
    truncated: set[str] = set()
    status: _SettledStatus = "timed_out"
    with DefaultSelector() as selector:
        selector.register(process.stdout, EVENT_READ, "stdout")
        selector.register(process.stderr, EVENT_READ, "stderr")
        while selector.get_map() and not truncated:
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            for event, _ in selector.select(remaining):
                name = event.data
                available = limits[name] - len(buffers[name])
                chunk = os.read(event.fd, min(65_536, available + 1))
                if not chunk:
                    selector.unregister(event.fileobj)
                else:
                    buffers[name].extend(chunk[:available])
                    if len(chunk) > available:
                        truncated.add(name)
        if truncated:
            status = "output_limit"
        elif not selector.get_map():
            try:
                exit_code = process.wait(timeout=max(0.0, deadline - monotonic()))
                status = "succeeded" if exit_code == 0 else "failed"
            except TimeoutExpired:
                pass
    return status, bytes(buffers["stdout"]), bytes(buffers["stderr"]), truncated


def _unavailable(*, status: ProcessStatus = "unknown", error_code: ErrorCode = "backend_unknown") -> BashBackendOutcome:
    return BashBackendOutcome(
        execution=BashExecutionFact(status=status, output_available=False, error_code=error_code),
        stdout=b"", stderr=b"",
    )
