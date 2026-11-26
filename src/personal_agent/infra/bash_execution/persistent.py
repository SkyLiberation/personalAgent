"""One Bash interpreter inside the authorized task's native sandbox."""

import os
import re
from selectors import DefaultSelector, EVENT_READ
from shlex import quote
import signal
from subprocess import PIPE, Popen, TimeoutExpired
from time import monotonic
from uuid import uuid4

from personal_agent.application.bash_execution.models import (
    BASH_DEFAULT_INPUTS_DIR, BashBackendOutcome, BashExecutionCommand, BashExecutionFact,
    ErrorCode, ProcessStatus,
)
from personal_agent.application.bash_execution.workspace_edit import WORKSPACE_VERSION_ENV


def stop_process(process: Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


class _CommandStream:
    def __init__(self, marker: bytes, limit: int) -> None:
        self.begin = b"\x1e" + marker + b":"
        self.end = b"\x1e" + marker + b"="
        self.limit = limit
        self.pending = b""
        self.output = bytearray()
        self.prelude = bytearray()
        self.prelude_truncated = False
        self.started = False
        self.truncated = False
        self.exit_code: int | None = None

    def _append(self, chunk: bytes) -> None:
        available = self.limit - len(self.output)
        self.output.extend(chunk[:available])
        self.truncated |= len(chunk) > available

    def read(self, chunk: bytes) -> None:
        data = self.pending + chunk
        if not self.started:
            _, start, data_after_start = data.partition(self.begin)
            if not start:
                retained = len(self.begin) - 1
                available = self.limit - len(self.prelude)
                self.prelude.extend(data[:-retained][:available])
                self.prelude_truncated |= len(data[:-retained]) > available
                self.pending = data[-retained:]
                return
            self.started = True
            self.prelude.clear()
            data = data_after_start
        body, end, tail = data.partition(self.end)
        if end:
            self._append(body)
            code, newline, _ = tail.partition(b"\n")
            if newline:
                if not re.fullmatch(rb"[0-9]{1,3}", code) or int(code) > 255:
                    raise ValueError("Invalid persistent Bash exit status")
                self.exit_code = int(code)
                self.pending = b""
            elif len(tail) > 3:
                raise ValueError("Invalid persistent Bash exit status")
            else:
                self.pending = end + tail
            return
        retained = len(self.end) - 1
        self.pending = body[-retained:]
        self._append(body[:-retained])

    def finish(self) -> bytes:
        if not self.started:
            self._append(bytes(self.prelude))
            self._append(self.pending)
            self.truncated |= self.prelude_truncated
        elif not self.pending.startswith(self.end):
            self._append(self.pending)
        return bytes(self.output)


def _submission(command: BashExecutionCommand, marker: str, version: str | None) -> bytes:
    start = f"builtin printf '\\036%s:' {marker}"
    end = f"builtin printf '\\036%s=%d\\n' {marker} \"$__pa_bash_status\""
    source = f"builtin source {BASH_DEFAULT_INPUTS_DIR}/command.sh </dev/null"
    if command.workdir != ".":
        source = f"builtin cd {quote(f'{BASH_DEFAULT_INPUTS_DIR}/{command.workdir}')} && {source}"
    if command.workspace_file is not None:
        version_command = f"unset {WORKSPACE_VERSION_ENV}" if version is None else (
            f"export {WORKSPACE_VERSION_ENV}={quote(version)}"
        )
        source = f"{version_command}; {source}"
    return f"{start}; {start} >&2; {source}; __pa_bash_status=$?; {end}; {end} >&2\n".encode()


def _collect(process: Popen[bytes], stdout: _CommandStream, stderr: _CommandStream, deadline: float) -> bool:
    with DefaultSelector() as selector:
        selector.register(process.stdout, EVENT_READ, stdout)
        selector.register(process.stderr, EVENT_READ, stderr)
        while selector.get_map() and not (stdout.truncated or stderr.truncated):
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            for event, _ in selector.select(remaining):
                stream = event.data
                chunk = os.read(event.fd, 65_536)
                if chunk:
                    stream.read(chunk)
                if not chunk or stream.exit_code is not None:
                    selector.unregister(event.fileobj)
    return True


class PersistentBash:
    def __init__(self) -> None:
        self._process: Popen[bytes] | None = None

    def close(self) -> None:
        if (process := self._process) is not None:
            stop_process(process)
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()
            self._process = None

    def run(
        self, argv: list[str], env: dict[str, str], command: BashExecutionCommand,
        *, started: float, deadline: float, version: str | None,
    ) -> BashBackendOutcome:
        if self._process is None or self._process.poll() is not None:
            self.close()
            self._process = Popen(
                argv, env=env, stdin=PIPE, stdout=PIPE, stderr=PIPE, bufsize=0, start_new_session=True,
            )
        process = self._process
        marker = uuid4().hex
        stdout = _CommandStream(marker.encode(), command.limits.stdout_bytes)
        stderr = _CommandStream(marker.encode(), command.limits.stderr_bytes)
        try:
            process.stdin.write(_submission(command, marker, version))
            completed = _collect(process, stdout, stderr, deadline)
            out, err = stdout.finish(), stderr.finish()
        except BaseException:
            self.close()
            raise
        status: ProcessStatus
        error: ErrorCode | None
        matched = stdout.exit_code is not None and stdout.exit_code == stderr.exit_code
        exit_code = stdout.exit_code if matched else process.poll()
        if not matched and completed and not (stdout.truncated or stderr.truncated) and exit_code is None:
            try:
                exit_code = process.wait(timeout=max(0.0, deadline - monotonic()))
            except TimeoutExpired:
                completed = False
        if stdout.truncated or stderr.truncated:
            status, error = "output_limit", "output_limit"
        elif not completed:
            status, error = "timed_out", "deadline"
        elif (matched or stdout.started and stderr.started) and exit_code == 0:
            status, error = "succeeded", None
        else:
            status, error = "failed", "execution_failed"
        if not matched or status in ("output_limit", "timed_out"):
            self.close()
        if exit_code is not None and exit_code < 0:
            exit_code = 128 - exit_code
        return BashBackendOutcome(
            execution=BashExecutionFact(
                status=status, process_exit_code=exit_code, elapsed_seconds=monotonic() - started,
                stdout_truncated=stdout.truncated, stderr_truncated=stderr.truncated, error_code=error,
            ),
            stdout=out, stderr=err,
        )
