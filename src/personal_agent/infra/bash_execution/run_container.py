"""Own Docker containers and mounts for authorized Bash execution."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import file_digest, sha256
import json
import logging
import math
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.bash_execution.models import (
    BASH_RUNTIME_DIR,
    BASH_SHARED_INPUTS_DIR,
    BASH_TEMP_DIR,
    BashExecutionCommand,
    BashExecutionProfile,
    BashInputIdentity,
    Digest,
    canonical_digest,
)
from personal_agent.application.bash_execution.ports import BashInputLoader
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .sandbox import _API_TIMEOUT, _API_VERSION, _write_json

if TYPE_CHECKING:
    from docker import DockerClient
    from docker.models.containers import Container

BASH_USER = "65534:65534"
logger = logging.getLogger(__name__)
_OWNER = "personal-agent.bash-owner"
_RUN = "personal-agent.bash-run"
_DEADLINE = "personal-agent.bash-deadline"
_WORKSPACE_VOLUME_API_VERSION = "1.45"
# A private IPC namespace persists across execs, even with /dev/shm disabled.
_CHECK_IPC = """
for table in /proc/sysvipc/{shm,sem,msg}; do
    [[ ! -e "$table" ]] && continue
    { IFS= read -r header && ! IFS= read -r entry; } < "$table" || exit 1
done
shopt -s nullglob dotglob
queues=(/dev/mqueue/*)
(( ${#queues[@]} == 0 )) || exit 1
"""


class BashWorkspaceUnavailable(Exception):
    pass


class _TaskWorkspaceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    turn_id: str
    inputs: frozenset[ResourceRef]
    container_id: str | None = None
    started_at: str | None = None
    file_versions: dict[str, Digest] = Field(default_factory=dict)


class BashTurnContainers:
    def __init__(
        self, endpoint: str, work_root: Path, profile: BashExecutionProfile,
        *, prompts: PromptCatalog = DEFAULT_PROMPTS,
    ) -> None:
        self.endpoint = endpoint
        self.root = work_root / "runs"
        self.profile = profile
        self._prompts = prompts
        self.owner = sha256(str(self.root).encode("utf-8")).hexdigest()
        # Complete model-visible paths can be nested below long Windows evidence
        # roots. Mount a short host path and keep durable lifecycle records apart.
        self.staging_root = Path(tempfile.gettempdir()).resolve() / f"pa-bash-{self.owner[:16]}"
        workspace = profile.workspace
        self.inputs_path = BASH_SHARED_INPUTS_DIR if workspace is not None else "/workspace"
        self.workdir = workspace.root if workspace is not None else "/workspace"
        network_owner = workspace.network_container_id if workspace is not None else None
        self.network_mode = f"container:{network_owner}" if network_owner else "none"

    def connect(self) -> DockerClient:
        from docker import DockerClient

        version = _WORKSPACE_VOLUME_API_VERSION if self.profile.workspace is not None else _API_VERSION
        client = DockerClient(base_url=self.endpoint, version=version, timeout=_API_TIMEOUT)
        client.api.trust_env = False
        return client

    def key(self, scope: ExecutionScope) -> str:
        if scope.principal != self.profile.authorized_principal:
            raise PermissionError("Bash Run 与部署主体不匹配")
        if self.profile.task_workspace is not None:
            if scope.thread_id != self.profile.task_workspace.conversation_id:
                raise PermissionError("Bash task workspace does not belong to this conversation")
            return self.task_key()
        # The field names are part of existing Docker and staging identities.
        return canonical_digest({
            "principal": scope.principal.model_dump(mode="json"),
            "run": scope.execution_id,
            "conversation": scope.thread_id,
            "deployment": self.profile.deployment_digest,
        })

    def task_key(self) -> str:
        return canonical_digest({"task_workspace_deployment": self.profile.deployment_digest})

    def _task_record(self, key: str) -> Path:
        return self.root / f"{key}.workspace"

    def _read_task(self, key: str) -> _TaskWorkspaceRecord | None:
        path = self._task_record(key)
        return _TaskWorkspaceRecord.model_validate_json(path.read_bytes()) if path.is_file() else None

    def observed_file_version(self, key: str, container_id: str, file_path: str) -> str | None:
        record = self._read_task(key)
        if record is None or record.container_id != container_id:
            raise BashWorkspaceUnavailable
        return record.file_versions.get(file_path)

    def record_file_version(self, key: str, container_id: str, file_path: str, digest: str) -> None:
        record = self._read_task(key)
        if record is None or record.container_id != container_id:
            raise BashWorkspaceUnavailable
        versions = {**record.file_versions, file_path: digest}
        _write_json(self._task_record(key), record.model_copy(update={"file_versions": versions}).model_dump(mode="json"))

    def _name(self, key: str) -> str:
        return f"personal-agent-bash-{self.owner[:12]}-{key}"

    def _staging(self, key: str) -> Path:
        stage = self.staging_root / key[:24]
        if any(path.is_symlink() for path in (stage, *stage.parents)):
            raise ValueError("Bash Run 暂存路径不能是符号链接")
        return stage

    def active_record(self, key: str) -> Path:
        return self.root / f"{key}.active"

    def expiry_record(self, key: str) -> Path:
        return self.root / f"{key}.expires"

    def lookup(
        self, client: DockerClient, key: str, *, identity: str | None = None, expired: bool = False,
    ) -> Container | None:
        from docker.errors import NotFound

        try:
            container = client.containers.get(identity or self._name(key))
        except NotFound:
            return None
        if (
            container.name != self._name(key)
            or container.labels.get(_OWNER) != self.owner
            or container.labels.get(_RUN) != key
            or (identity is not None and container.id != identity)
            or (not expired and (container.attrs.get("Image") != self.profile.image_id
                                 or container.attrs["HostConfig"]["NetworkMode"] != self.network_mode))
        ):
            raise ValueError("Docker 容器与 Bash Run 绑定不匹配")
        return container

    @staticmethod
    def idle(container: Container) -> bool:
        from docker.errors import NotFound

        try:
            container.reload()
            state = container.attrs["State"]
            if state["Status"] != "running":
                return False
            rows = container.top(ps_args="-eo pid")
        except NotFound:
            return False
        return rows["Titles"] == ["PID"] and rows["Processes"] == [[str(state["Pid"])]]

    def _create(self, client: DockerClient, key: str, deadline_at: datetime) -> Container:
        from docker.types import Mount

        image = client.images.get(self.profile.image_id)
        if image.id != self.profile.image_id or image.attrs.get("Os") != "linux":
            raise ValueError("Bash Run 必须使用绑定的 Linux 镜像")
        if image.attrs.get("Config", {}).get("Volumes"):
            raise ValueError("Bash Run 镜像不能声明可写卷")
        workspace = self.profile.workspace
        mounts = [Mount(self.inputs_path, str(self._staging(key)), type="bind", read_only=True)]
        environment = {"PYTHONDONTWRITEBYTECODE": "1", "HOME": BASH_TEMP_DIR}
        if workspace is not None:
            client.volumes.get(workspace.volume_name)
            task_mount = Mount(workspace.root, workspace.volume_name, type="volume", no_copy=True)
            task_mount["VolumeOptions"]["Subpath"] = workspace.subdirectory
            mounts.append(task_mount)
            if workspace.runtime_volume_name is not None:
                client.volumes.get(workspace.runtime_volume_name)
                mounts.append(Mount(BASH_RUNTIME_DIR, workspace.runtime_volume_name,
                                    type="volume", read_only=True, no_copy=True))
                image_path = next(value.removeprefix("PATH=") for value in image.attrs["Config"]["Env"]
                                  if value.startswith("PATH="))
                environment["PATH"] = f"{BASH_RUNTIME_DIR}/bin:{image_path}"

        if deadline_at <= datetime.now(timezone.utc):
            raise TimeoutError("Bash Run 已到截止时间")
        limits = self.profile.limits
        tmpfs = {BASH_TEMP_DIR: f"rw,noexec,nosuid,nodev,size={limits.scratch_mb}m,mode=1777"}
        container = client.containers.create(
            image=image.id, name=self._name(key), entrypoint=[],
            command=["sh", "-c", 'left=$(($1 - $(date +%s))); [ "$left" -gt 0 ] && exec sleep "$left"',
                     "bash-run", str(math.ceil(deadline_at.timestamp()))],
            user="0:0", working_dir=BASH_TEMP_DIR, environment=environment, use_config_proxy=False,
            healthcheck={"test": ["NONE"]}, mounts=mounts, network_mode=self.network_mode, read_only=True,
            privileged=False, cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
            mem_limit=limits.memory_mb * 1024 * 1024, memswap_limit=limits.memory_mb * 1024 * 1024,
            nano_cpus=int(limits.cpus * 1_000_000_000), pids_limit=limits.pids_limit, ipc_mode="none",
            tmpfs=tmpfs,
            labels={_OWNER: self.owner, _RUN: key, _DEADLINE: deadline_at.isoformat()},
        )
        container.start()
        return container

    @staticmethod
    def _clear_snapshot(stage: Path) -> None:
        if not stage.exists():
            return
        for path in stage.rglob("*"):
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise ValueError("Bash Run 暂存目录中存在非普通输入")
            if path.is_file():
                path.chmod(0o600)
        for entry in stage.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()

    def prepare(self, client: DockerClient, key: str, deadline_at: datetime,
                command: BashExecutionCommand, load_input: BashInputLoader) -> Container:
        container = self.lookup(client, key)
        if container is not None:
            if container.labels.get(_DEADLINE) != deadline_at.isoformat():
                raise ValueError("Bash Run 截止时间与原容器不匹配")
            if not self.idle(container) or not self._prepare_for_reuse(client, container):
                self.discard(container)
                container = None

        self._stage_inputs(key, deadline_at, command, load_input)
        return container if container is not None else self._create(client, key, deadline_at)

    @staticmethod
    def _snapshot_matches_paths(stage: Path, expected: tuple[BashInputIdentity, ...]) -> bool:
        files = {item.name for item in expected}
        directories = {parent.as_posix() for name in files for parent in PurePosixPath(name).parents}
        for path in stage.rglob("*"):
            name = path.relative_to(stage).as_posix()
            if path.is_symlink() or name not in (directories if path.is_dir() else files):
                return False
            if name in files and not path.is_file():
                return False
        return True

    @staticmethod
    def _matches_input(path: Path, item: BashInputIdentity) -> bool:
        if not path.is_file() or path.stat().st_size != item.size_bytes:
            return False
        with path.open("rb") as stream:
            return file_digest(stream, "sha256").hexdigest() == item.content_digest

    def _stage_inputs(
        self, key: str, deadline_at: datetime, command: BashExecutionCommand,
        load_input: BashInputLoader, *, reuse: bool = False,
    ) -> None:
        stage = self._staging(key)
        expiry = self.expiry_record(key)
        self.root.mkdir(parents=True, exist_ok=True)
        if expiry.exists():
            if datetime.fromisoformat(json.loads(expiry.read_bytes())) != deadline_at:
                raise ValueError("Bash Run 截止时间与暂存记录不匹配")
        else:
            _write_json(expiry, deadline_at.isoformat())
        stage.mkdir(parents=True, exist_ok=True)
        inputs = (command.program, *command.inputs)
        if not reuse or not self._snapshot_matches_paths(stage, inputs):
            self._clear_snapshot(stage)
        for item in inputs:
            target = stage / item.name
            if reuse and self._matches_input(target, item):
                continue
            contents = load_input(item)
            if contents.identity() != item:
                raise ValueError(self._prompts.render("bash_backend.input_command"))
            if target.exists():
                target.chmod(0o600)
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(contents.content)
            target.chmod(0o444)

    def prepare_task(
        self, client: DockerClient, key: str, command: BashExecutionCommand,
        load_input: BashInputLoader,
    ) -> Container:
        policy, access = self.profile.task_workspace, command.task_workspace
        if policy is None or access is None or policy.expires_at <= datetime.now(timezone.utc):
            raise BashWorkspaceUnavailable
        turn_id = command.execution_scope.execution_id
        current_inputs = frozenset(item.resource_ref for item in command.inputs)
        record = self._read_task(key)
        path = self._task_record(key)
        if record is None:
            self._stage_inputs(key, policy.expires_at, command, load_input)
            record = _TaskWorkspaceRecord(task_id=access.task_id, turn_id=turn_id, inputs=current_inputs)
            # Claim before Docker creates the instance. An interrupted creation
            # can leave an orphan, but must never be mistaken for a fresh lease.
            _write_json(path, record.model_dump(mode="json"))
            container = self._create(client, key, policy.expires_at)
            container.reload()
            record = record.model_copy(update={
                "container_id": container.id, "started_at": container.attrs["State"]["StartedAt"],
            })
            _write_json(path, record.model_dump(mode="json"))
            return container
        if record.task_id != access.task_id or (
            record.turn_id != turn_id and record.turn_id not in access.predecessor_turn_ids
        ):
            raise BashWorkspaceUnavailable
        container = self.lookup(client, key, identity=record.container_id)
        if (
            container is None or not record.inputs.issubset(current_inputs)
            or not self.idle(container) or container.attrs["State"]["StartedAt"] != record.started_at
            or not self._prepare_for_reuse(client, container)
        ):
            self.invalidate_task(client, key)
            raise BashWorkspaceUnavailable
        self._stage_inputs(key, policy.expires_at, command, load_input, reuse=True)
        _write_json(path, record.model_copy(update={
            "turn_id": turn_id, "inputs": current_inputs,
        }).model_dump(mode="json"))
        return container

    def task_turn_owns_workspace(self, key: str, turn_id: str) -> bool:
        record = self._read_task(key)
        return record is not None and record.turn_id == turn_id

    def close_task_turn(self, client: DockerClient, key: str) -> None:
        container = self.lookup(client, key)
        if container is None:
            self._clear_snapshot(self._staging(key))
        elif not self.idle(container) or not self._prepare_for_reuse(client, container):
            self.discard(container)
            self._clear_snapshot(self._staging(key))

    def invalidate_task(self, client: DockerClient, key: str) -> None:
        container = self.lookup(client, key)
        if container is not None:
            self.discard(container)
        self._remove_staging(key)

    def _prepare_for_reuse(self, client: DockerClient, container: Container) -> bool:
        command = _CHECK_IPC
        if self.profile.task_workspace is None:
            command += f"exec find {BASH_TEMP_DIR} -mindepth 1 -delete\n"
        # Attach stdout so exec_start waits for EOF. Without an attached
        # stream Docker may return before the checks and cleanup finish.
        identity = client.api.exec_create(
            container.id, ["bash", "--noprofile", "--norc", "-c", command],
            user=BASH_USER, stdout=True, stderr=False,
        )["Id"]
        client.api.exec_start(identity)
        deadline = time.monotonic() + 0.25
        while True:
            state = client.api.exec_inspect(identity)
            if not state["Running"] and state["ExitCode"] is not None:
                return state["ExitCode"] == 0
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    @staticmethod
    def discard(container: Container) -> None:
        from docker.errors import NotFound

        try:
            # Successful removal or a missing immutable ID proves every process
            # in its private PID namespace has stopped.
            container.remove(force=True)
        except NotFound:
            return

    def close(self, client: DockerClient, key: str) -> None:
        container = self.lookup(client, key)
        if container is not None:
            self.discard(container)
        self._clear_records(key)

    def _clear_records(self, key: str) -> None:
        self._remove_staging(key)
        self.active_record(key).unlink(missing_ok=True)
        self.expiry_record(key).unlink(missing_ok=True)
        self._task_record(key).unlink(missing_ok=True)

    def _remove_staging(self, key: str) -> None:
        stage = self._staging(key)
        if stage.exists():
            self._clear_snapshot(stage)
            stage.rmdir()

    def sweep_expired(self, client: DockerClient) -> None:
        now = datetime.now(timezone.utc)
        for expiry in self.root.glob("*.expires"):
            key = expiry.stem
            if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
                continue
            try:
                deadline = datetime.fromisoformat(json.loads(expiry.read_bytes()))
                if deadline > now:
                    continue
                container = self.lookup(client, key, expired=True)
                if container is not None:
                    if datetime.fromisoformat(container.labels[_DEADLINE]) != deadline:
                        raise ValueError("Bash Run 截止时间与原容器不匹配")
                    self.discard(container)
                self._clear_records(key)
            except Exception:
                logger.exception("Could not release expired Bash Run %s", key)
