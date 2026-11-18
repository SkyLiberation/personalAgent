"""Own the Docker container and its mounts for one authorized Turn."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import math
from pathlib import Path
import shutil
import tempfile
import time
from typing import TYPE_CHECKING

from personal_agent.application.bash_execution.models import (
    BASH_RUNTIME_DIR,
    BASH_SHARED_INPUTS_DIR,
    BashExecutionProfile,
    BashInputContent,
    canonical_digest,
)
from personal_agent.kernel.contracts.scope import ExecutionScope

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
_RESET_SCRATCH = """
for table in /proc/sysvipc/{shm,sem,msg}; do
    [[ ! -e "$table" ]] && continue
    { IFS= read -r header && ! IFS= read -r entry; } < "$table" || exit 1
done
shopt -s nullglob dotglob
queues=(/dev/mqueue/*)
(( ${#queues[@]} == 0 )) || exit 1
exec find /tmp -mindepth 1 -delete
"""


class BashTurnContainers:
    def __init__(self, endpoint: str, work_root: Path, profile: BashExecutionProfile) -> None:
        self.endpoint = endpoint
        self.root = work_root / "runs"
        self.profile = profile
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
        # The field names are part of existing Docker and staging identities.
        return canonical_digest({
            "principal": scope.principal.model_dump(mode="json"),
            "run": scope.execution_id,
            "conversation": scope.thread_id,
            "deployment": self.profile.deployment_digest,
        })

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
        environment = {"PYTHONDONTWRITEBYTECODE": "1", "HOME": "/tmp"}
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
        container = client.containers.create(
            image=image.id, name=self._name(key), entrypoint=[],
            command=["sh", "-c", 'left=$(($1 - $(date +%s))); [ "$left" -gt 0 ] && exec sleep "$left"',
                     "bash-run", str(math.ceil(deadline_at.timestamp()))],
            user="0:0", working_dir="/tmp", environment=environment, use_config_proxy=False,
            healthcheck={"test": ["NONE"]}, mounts=mounts, network_mode=self.network_mode, read_only=True,
            privileged=False, cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
            mem_limit=limits.memory_mb * 1024 * 1024, memswap_limit=limits.memory_mb * 1024 * 1024,
            nano_cpus=int(limits.cpus * 1_000_000_000), pids_limit=limits.pids_limit, ipc_mode="none",
            tmpfs={"/tmp": f"rw,noexec,nosuid,nodev,size={limits.scratch_mb}m,mode=1777"},
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
                inputs: tuple[BashInputContent, ...]) -> Container:
        container = self.lookup(client, key)
        if container is not None:
            if container.labels.get(_DEADLINE) != deadline_at.isoformat():
                raise ValueError("Bash Run 截止时间与原容器不匹配")
            if not self.idle(container) or not self._reset_scratch(client, container):
                self.discard(container)
                container = None

        stage = self._staging(key)
        expiry = self.expiry_record(key)
        self.root.mkdir(parents=True, exist_ok=True)
        if expiry.exists():
            if datetime.fromisoformat(json.loads(expiry.read_bytes())) != deadline_at:
                raise ValueError("Bash Run 截止时间与暂存记录不匹配")
        else:
            _write_json(expiry, deadline_at.isoformat())
        stage.mkdir(parents=True, exist_ok=True)
        self._clear_snapshot(stage)
        for item in inputs:
            target = stage / item.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(item.content)
            target.chmod(0o444)
        return container if container is not None else self._create(client, key, deadline_at)

    @staticmethod
    def _reset_scratch(client: DockerClient, container: Container) -> bool:
        # Attach stdout so exec_start waits for EOF. Without an attached
        # stream Docker may return before the cleanup process exits.
        identity = client.api.exec_create(
            container.id, ["bash", "--noprofile", "--norc", "-c", _RESET_SCRATCH],
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
        stage = self._staging(key)
        if stage.exists():
            self._clear_snapshot(stage)
            stage.rmdir()
        self.active_record(key).unlink(missing_ok=True)
        self.expiry_record(key).unlink(missing_ok=True)

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
