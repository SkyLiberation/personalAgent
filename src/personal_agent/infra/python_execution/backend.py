"""Fixed Docker Python execution with immutable input and recovery identity."""

from __future__ import annotations

import hashlib
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from pydantic import TypeAdapter

from personal_agent.application.python_execution.models import (
    PythonBackendOutcome,
    PythonExecutionCommand,
    PythonExecutionFact,
    PythonExecutionProfile,
    PythonInputContent,
)
from .sandbox import (
    SandboxLimits,
    SandboxResult,
    _API_TIMEOUT,
    _API_VERSION,
    _JobRecord,
    _recover_program,
    _remove_staging,
    _write_json,
    run_program,
)


class DockerPythonExecutionBackend:
    def __init__(
        self, *, endpoint: str, work_root: Path, profile: PythonExecutionProfile
    ) -> None:
        if (
            not endpoint.startswith(
                ("unix://", "npipe://", "tcp://", "http://", "https://")
            )
            or "@" in endpoint
        ):
            raise ValueError("Python执行器需要无内嵌凭证的显式Docker Engine端点")
        self.endpoint = endpoint
        self.work_root = work_root.resolve()
        self.profile = profile

    def _root(self, command: PythonExecutionCommand) -> Path:
        if (
            command.execution_scope.principal != self.profile.authorized_principal
            or command.deployment_digest != self.profile.deployment_digest
            or command.image_id != self.profile.image_id
            or command.limits.timeout_seconds > self.profile.limits.timeout_seconds
            or command.limits.model_dump(exclude={"timeout_seconds"})
            != self.profile.limits.model_dump(exclude={"timeout_seconds"})
        ):
            raise PermissionError("Python Command与固定执行部署不同")
        root = self.work_root / command.command_digest
        for path in (root, *root.parents):
            if path.is_symlink():
                raise ValueError("Python执行目录不得包含符号链接")
        if not root.resolve().is_relative_to(self.work_root):
            raise ValueError("Python执行目录越界")
        return root

    @staticmethod
    def _snapshot(root: Path, command: PythonExecutionCommand) -> None:
        path = root / "command.json"
        if path.exists():
            if (
                path.is_symlink()
                or PythonExecutionCommand.model_validate_json(path.read_bytes())
                != command
            ):
                raise ValueError("Python原作业与冻结Command不同")
        else:
            raise ValueError("Python原作业缺少冻结Command，禁止重新执行")

    @staticmethod
    def _paths(
        root: Path, command: PythonExecutionCommand
    ) -> tuple[Path, dict[str, Path]]:
        program = root / "bound" / "program.py"
        paths = {item.name: root / "bound" / item.name for item in command.inputs}
        for item in (command.program, *command.inputs):
            path = root / "bound" / item.name
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != item.size_bytes
                or hashlib.sha256(path.read_bytes()).hexdigest() != item.content_digest
            ):
                raise ValueError("Python后端输入与冻结原字节不同")
        return program, paths

    def execute(
        self, command: PythonExecutionCommand, inputs: tuple[PythonInputContent, ...]
    ) -> PythonBackendOutcome:
        root = self._root(command)
        identities = tuple(item.identity() for item in inputs)
        if identities != (command.program, *command.inputs):
            raise ValueError("执行输入与冻结Python Command不同")
        if (root / "command.json").exists():
            self._snapshot(root, command)
        else:
            root.mkdir(parents=True, exist_ok=True)
            if any(root.iterdir()):
                raise ValueError("Python工作目录缺少原身份，禁止重新执行")
            path = root / "command.json"
            with path.open("xb") as stream:
                stream.write((command.model_dump_json() + "\n").encode("utf-8"))
        if (root / "execution").exists() and any((root / "execution").iterdir()):
            return self.reconcile(command)
        bound = root / "bound"
        bound.mkdir(exist_ok=True)
        if bound.is_symlink():
            raise ValueError("Python输入目录不得是符号链接")
        for item in inputs:
            target = bound / item.name
            if target.exists():
                if target.is_symlink() or target.read_bytes() != item.content:
                    raise ValueError("Python输入快照冲突")
            else:
                with target.open("xb") as stream:
                    stream.write(item.content)
        program, paths = self._paths(root, command)
        result = run_program(
            endpoint=self.endpoint,
            image=command.image_id,
            program=program,
            inputs=paths,
            output_dir=root / "execution",
            limits=SandboxLimits(**command.limits.model_dump()),
            job_key=command.command_digest,
            deadline_at=command.deadline_at,
            retain_jobs=True,
        )
        return self._outcome(result)

    def reconcile(self, command: PythonExecutionCommand) -> PythonBackendOutcome:
        root = self._root(command)
        if (root / "command.json").exists():
            self._snapshot(root, command)
        if not (root / "execution" / "job.json").is_file():
            # Dispatch may have been interrupted before its durable backend
            # identity. Absence cannot prove that another process never ran.
            return PythonBackendOutcome(
                execution=PythonExecutionFact(
                    status="unknown",
                    output_available=False,
                    error_code="backend_unknown",
                ),
                stdout=b"",
                stderr=b"",
            )
        self._record(root, command)
        result = _recover_program(
            endpoint=self.endpoint,
            image=command.image_id,
            output_dir=root / "execution",
            job_key=command.command_digest,
            input_sha256={
                item.name: item.content_digest
                for item in (command.program, *command.inputs)
            },
        )
        return self._outcome(result)

    @staticmethod
    def _outcome(result: SandboxResult) -> PythonBackendOutcome:
        error = {
            "succeeded": None,
            "failed": "execution_failed",
            "timed_out": "deadline",
            "output_limit": "output_limit",
            "unknown": "backend_unknown",
        }[result.status]
        if result.oom_killed and result.status == "failed":
            error = "oom"
        if not result.output_available and result.status != "unknown":
            error = "output_unavailable"
        return PythonBackendOutcome(
            execution=PythonExecutionFact(
                status=result.status,
                process_exit_code=result.exit_code,
                elapsed_seconds=result.elapsed_seconds
                if result.elapsed_known
                else None,
                container_id=result.container_id or None,
                image_id=result.image_id or None,
                oom_killed=result.oom_killed,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                output_available=result.output_available,
                error_code=error,
            ),
            stdout=result.stdout,
            stderr=result.stderr_raw,
        )

    def cleanup(self, command: PythonExecutionCommand) -> None:
        root = self._root(command)
        if (root / "command.json").exists():
            self._snapshot(root, command)
        record_path = root / "execution" / "job.json"
        if not record_path.exists():
            return
        record = self._record(root, command)
        if record.phase == "unknown":
            return
        if not record.container_removed and record.container_id:
            from docker import DockerClient
            from docker.errors import NotFound

            with closing(
                DockerClient(
                    base_url=self.endpoint, version=_API_VERSION, timeout=_API_TIMEOUT
                )
            ) as client:
                client.api.trust_env = False
                try:
                    container = client.containers.get(record.container_name)
                    container.reload()
                    if (
                        container.id != record.container_id
                        or container.attrs.get("Image") != command.image_id
                        or container.labels.get("personal-agent.job")
                        != command.command_digest
                        or container.status not in {"exited", "dead", "created"}
                    ):
                        raise ValueError("Python清理未确认匹配的停止容器")
                    container.remove()
                except NotFound:
                    pass
                record.container_removed = True
        if record.container_removed or not record.container_id:
            staging = Path(record.staging_directory)
            if staging.exists():
                _remove_staging(staging)
            _write_json(record_path, asdict(record))

    def _record(self, root: Path, command: PythonExecutionCommand) -> _JobRecord:
        path = root / "execution" / "job.json"
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("Python原作业记录不得是符号链接")
        record = TypeAdapter(_JobRecord).validate_json(path.read_bytes())
        if (
            record.job_key != command.command_digest
            or record.container_name
            != "retrieval-candidate-" + command.command_digest[:40]
            or record.endpoint != self.endpoint
            or record.image_id not in {"", command.image_id}
            or asdict(record.limits) != command.limits.model_dump()
            or record.input_sha256
            != {
                item.name: item.content_digest
                for item in (command.program, *command.inputs)
            }
        ):
            raise ValueError("Python后端作业与冻结Command不符")
        return record
