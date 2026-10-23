"""F2-only native connection interruption; never imported by production startup."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
import logging
from pathlib import Path
import re
from threading import RLock
from time import monotonic, sleep
from typing import Iterator
from urllib.parse import parse_qs, urlsplit

import docker
from pydantic import AliasPath, AwareDatetime, BaseModel, ConfigDict, Field
from urllib3.util import Timeout

from personal_agent.application.retrieval_experiment.contracts import (
    Digest,
    canonical_digest,
)
from personal_agent.application.retrieval_experiment.models import (
    BackendOutcome,
    BoundArtifact,
    ExperimentCommand,
    ExperimentExecutionFact,
)
from personal_agent.infra.retrieval_experiment.backend import (
    DockerExperimentBackend,
    _read_state,
)
from personal_agent.infra.retrieval_experiment.controller import _WORKER_STATE
from personal_agent.infra.retrieval_experiment.file_io import read_json, replace_json
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

logger = logging.getLogger(__name__)
_INSTALLED = False
_COMMAND: ContextVar[ExperimentCommand | None] = ContextVar("f2_command", default=None)
_OBSERVING: ContextVar[bool] = ContextVar("f2_observing", default=False)
_LAST_REQUEST: ContextVar[int | None] = ContextVar("f2_last_request", default=None)


class StartResponseFaultConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    principal: AuthenticatedPrincipal
    interaction_run_ref: str = Field(min_length=1)
    deployment_digest: Digest
    worker_image_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    endpoint: str = Field(pattern=r"^npipe://")
    workspace_root: Path
    output_directory: Path


class _DockerMount(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    source: str = Field(alias="Source")
    destination: str = Field(alias="Destination")
    writable: bool = Field(alias="RW")
    kind: str = Field(alias="Type")


class _DockerInspection(BaseModel):
    """Only external fields needed to bind the actual container; no environment."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    container_id: str = Field(alias="Id")
    name: str = Field(alias="Name")
    image: str = Field(alias="Image")
    labels: dict[str, str] = Field(validation_alias=AliasPath("Config", "Labels"))
    status: str = Field(validation_alias=AliasPath("State", "Status"))
    started_at: AwareDatetime = Field(validation_alias=AliasPath("State", "StartedAt"))
    mounts: tuple[_DockerMount, ...] = Field(alias="Mounts")


class _DockerCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    image: str = Field(alias="Image")
    labels: dict[str, str] = Field(alias="Labels")
    binds: tuple[str, ...] = Field(validation_alias=AliasPath("HostConfig", "Binds"))


class ObservedCreation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_digest: Digest
    job_key: Digest
    inputs_digest: Digest
    name: str
    image: str
    output_path: Path


class NativeRequestObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observed_at: AwareDatetime
    command_digest: Digest
    method: str
    path: str
    request_send_returned: bool
    error_type: str | None = None
    response_status: int | None = None
    response_error_type: str | None = None
    response_error_detail: str | None = None


class ObservedBackendOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    method: str
    command_digest: Digest
    execution: ExperimentExecutionFact
    failure_type: str | None = None
    failure_detail: str | None = None


class StartResponseInterruption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_digest: Digest
    creation: ObservedCreation
    before: _DockerInspection
    after: _DockerInspection
    observation_seconds: float = Field(ge=0, allow_inf_nan=False)
    connection_closed: bool = False


class StartResponseFaultObservation(BaseModel):
    """Control observations only; a separate case consumer must score F2 safety."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = "f2-native-start-response-v1"
    attempted: bool
    interruption: StartResponseInterruption | None
    creations: tuple[ObservedCreation, ...]
    native_requests: tuple[NativeRequestObservation, ...]
    backend_outcomes: tuple[ObservedBackendOutcome, ...]
    control_errors: tuple[str, ...]


class StartResponseFaultControl:
    def __init__(self, configuration: StartResponseFaultConfiguration) -> None:
        if (
            not configuration.workspace_root.is_absolute()
            or not configuration.output_directory.is_absolute()
        ):
            raise ValueError("F2 工作目录和记录目录必须为显式绝对路径")
        self.configuration = configuration
        configuration.output_directory.mkdir(parents=True, exist_ok=False)
        self._lock = RLock()
        self._attempted = False
        self._interruption: StartResponseInterruption | None = None
        self._creations: list[ObservedCreation] = []
        self._requests: list[NativeRequestObservation] = []
        self._outcomes: list[ObservedBackendOutcome] = []
        self._errors: list[str] = []
        self._save()

    def _save(self) -> bool:
        with self._lock:
            observation = StartResponseFaultObservation(
                attempted=self._attempted,
                interruption=self._interruption,
                creations=tuple(self._creations),
                native_requests=tuple(self._requests),
                backend_outcomes=tuple(self._outcomes),
                control_errors=tuple(self._errors),
            )
            try:
                replace_json(
                    self.configuration.output_directory / "transport-observations.json",
                    observation.model_dump(mode="json"),
                )
            except OSError as error:
                self._errors.append("observation_write:" + type(error).__name__)
                logger.error("F2 observation write failed: %s", type(error).__name__)
                return False
        return True

    def _error(self, stage: str, error: Exception) -> None:
        with self._lock:
            self._errors.append(
                stage + ":" + type(error).__name__ + ":" + str(error)[:400]
            )
        self._save()

    def _matches(
        self, backend: DockerExperimentBackend, command: ExperimentCommand
    ) -> bool:
        config = self.configuration
        return (
            command.execution_scope.principal == config.principal
            and command.execution_scope.execution_id == config.interaction_run_ref
            and command.deployment_digest == config.deployment_digest
            and backend.environment.workspace_root.resolve()
            == config.workspace_root.resolve()
            and backend.environment.endpoint == config.endpoint
        )

    @contextmanager
    def bind(
        self, backend: DockerExperimentBackend, command: ExperimentCommand
    ) -> Iterator[None]:
        token = _COMMAND.set(command if self._matches(backend, command) else None)
        try:
            yield
        finally:
            _COMMAND.reset(token)

    def outcome(
        self,
        method: str,
        backend: DockerExperimentBackend,
        command: ExperimentCommand,
        result: BackendOutcome,
    ) -> None:
        if _COMMAND.get() is None:
            return
        try:
            saved = _read_state(backend._root(command))
        except Exception as error:
            self._error("backend_outcome_observation", error)
            return
        with self._lock:
            self._outcomes.append(
                ObservedBackendOutcome(
                    method=method,
                    command_digest=command.command_digest,
                    execution=result.execution,
                    failure_type=saved.get("failure_type"),
                    failure_detail=saved.get("failure_detail"),
                )
            )
        self._save()

    def creation(self, command: ExperimentCommand, url: str, body: bytes | str) -> None:
        value = _DockerCreate.model_validate_json(body)
        if value.image != self.configuration.worker_image_id:
            return
        names = parse_qs(urlsplit(url).query).get("name", [])
        outputs = [
            row.rsplit(":", 2)[0]
            for row in value.binds
            if row.rsplit(":", 2)[-2:] == ["/output", "rw"]
        ]
        if len(names) != 1 or len(outputs) != 1:
            raise ValueError("F2 create 名称或 output bind 不唯一")
        output = Path(outputs[0]).resolve()
        root = (self.configuration.workspace_root / command.command_digest).resolve()
        if (
            not output.is_relative_to(root)
            or value.labels.get("personal-agent.command") != command.command_digest
        ):
            raise ValueError("F2 create 不属于实际 Command 工作目录")
        record = ObservedCreation(
            command_digest=command.command_digest,
            name=names[0],
            image=value.image,
            job_key=value.labels["personal-agent.job"],
            inputs_digest=value.labels["personal-agent.inputs"],
            output_path=output,
        )
        with self._lock:
            self._creations.append(record)
        self._save()

    @staticmethod
    def _inspect(
        client: docker.DockerClient, container_id: str, deadline: float
    ) -> _DockerInspection:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("F2 独立观察时间已用尽")
        client.api.timeout = Timeout(total=remaining)
        token = _OBSERVING.set(True)
        try:
            inspection = _DockerInspection.model_validate(
                client.api.inspect_container(container_id)
            )
        finally:
            _OBSERVING.reset(token)
        if monotonic() > deadline:
            raise TimeoutError("F2 原生观察查询已超窗，不使用迟到结果")
        return inspection

    def before(
        self, client: docker.DockerClient, command: ExperimentCommand, container_id: str
    ) -> tuple[ObservedCreation, _DockerInspection]:
        inspection = self._inspect(client, container_id, monotonic() + 5)
        matching = [
            row
            for row in self._creations
            if row.command_digest == command.command_digest
            and row.name == inspection.name.lstrip("/")
        ]
        if len(matching) != 1:
            raise ValueError("F2 缺少本次真实 create 观察，禁止猜测 mount 路径")
        creation = matching[0]
        state = _WORKER_STATE.validate_python(
            read_json(creation.output_path / "job.json")
        )
        mounts = [
            mount for mount in inspection.mounts if mount.destination == "/output"
        ]
        expected_labels = {
            "personal-agent.command": command.command_digest,
            "personal-agent.job": creation.job_key,
            "personal-agent.inputs": creation.inputs_digest,
        }
        if (
            inspection.container_id != container_id
            or inspection.image != creation.image
            or inspection.status != "created"
            or inspection.started_at.year != 1
            or any(
                inspection.labels.get(key) != value
                for key, value in expected_labels.items()
            )
            or len(mounts) != 1
            or mounts[0].kind != "bind"
            or not mounts[0].writable
            or state["container_id"] != container_id
            or state["container_name"] != creation.name
            or state["job_key"] != creation.job_key
            or state["image_id"] != creation.image
            or canonical_digest(state["input_hashes"]) != creation.inputs_digest
            or not state["start_requested"]
            or not state["create_requested"]
        ):
            raise ValueError("F2 start 的真实容器／job／输入绑定不成立")
        return creation, inspection

    def is_target_start(self, command: ExperimentCommand, container_id: str) -> bool:
        with self._lock:
            creations = tuple(self._creations)
        for creation in creations:
            if creation.command_digest != command.command_digest:
                continue
            state = _WORKER_STATE.validate_python(
                read_json(creation.output_path / "job.json")
            )
            if state["container_id"] == container_id:
                return True
        return False

    def start(
        self,
        original,
        connection,
        command: ExperimentCommand,
        method: str,
        url: str,
        args,
        kwargs,
    ):
        container_id = urlsplit(url).path.split("/")[-2]
        client = docker.DockerClient(
            base_url=self.configuration.endpoint, version="1.44", timeout=5
        )
        try:
            try:
                creation, before = self.before(client, command, container_id)
            except Exception as error:
                self._error("binding", error)
                return original(connection, method, url, *args, **kwargs)
            # The daemon receives the real request; no response is consumed or replaced here.
            value = original(connection, method, url, *args, **kwargs)
            started = monotonic()
            deadline = started + 5
            try:
                while True:
                    after = self._inspect(client, container_id, deadline)
                    if (
                        after.container_id != before.container_id
                        or after.image != before.image
                        or after.labels != before.labels
                    ):
                        raise ValueError("F2 启动后观察不是原容器身份")
                    if after.started_at.year != 1:
                        break
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError("F2 未在五秒内确认实际启动")
                    sleep(min(0.025, remaining))
                elapsed = monotonic() - started
                if elapsed > 5:
                    raise TimeoutError("F2 实际启动观察超过五秒，未中断响应")
                self._interruption = StartResponseInterruption(
                    command_digest=command.command_digest,
                    creation=creation,
                    before=before,
                    after=after,
                    observation_seconds=elapsed,
                )
                if self._save():
                    connection.close()
                    self._interruption = self._interruption.model_copy(
                        update={"connection_closed": True}
                    )
                    self._save()
            except Exception as error:
                self._error("start_observation_or_close", error)
            return value
        finally:
            client.close()

    def install(self) -> None:
        """Explicit F2 process only; original execution and SDK returns stay authoritative."""
        global _INSTALLED
        if _INSTALLED:
            raise RuntimeError("同一进程只能安装一次 F2 控制")
        from docker.transport.npipeconn import NpipeHTTPConnection

        original_execute = DockerExperimentBackend.execute
        original_reconcile = DockerExperimentBackend.reconcile
        original_cleanup = DockerExperimentBackend.cleanup
        original_request = NpipeHTTPConnection.request
        original_getresponse = NpipeHTTPConnection.getresponse
        control = self

        @wraps(original_execute)
        def execute(
            backend: DockerExperimentBackend,
            command: ExperimentCommand,
            inputs: tuple[BoundArtifact, ...],
        ) -> BackendOutcome:
            with control.bind(backend, command):
                result = original_execute(backend, command, inputs)
                control.outcome("execute", backend, command, result)
                return result

        @wraps(original_reconcile)
        def reconcile(
            backend: DockerExperimentBackend, command: ExperimentCommand
        ) -> BackendOutcome:
            with control.bind(backend, command):
                result = original_reconcile(backend, command)
                control.outcome("reconcile", backend, command, result)
                return result

        @wraps(original_cleanup)
        def cleanup(
            backend: DockerExperimentBackend, command: ExperimentCommand
        ) -> None:
            with control.bind(backend, command):
                return original_cleanup(backend, command)

        @wraps(original_request)
        def request(connection, method: str, url: str, *args, **kwargs):
            command = _COMMAND.get()
            if command is None or _OBSERVING.get():
                return original_request(connection, method, url, *args, **kwargs)
            observed_at = datetime.now(UTC)
            returned = False
            error_type = None
            path = urlsplit(url).path
            try:
                if method == "POST" and path.endswith("/containers/create"):
                    try:
                        control.creation(
                            command, url, kwargs.get("body", args[0] if args else None)
                        )
                    except Exception as error:
                        control._error("create_observation", error)
                target = False
                if method == "POST" and re.fullmatch(
                    r"/(?:v[0-9.]+/)?containers/[^/]+/start", path
                ):
                    try:
                        target = control.is_target_start(command, path.split("/")[-2])
                    except Exception as error:
                        control._error("target_job_observation", error)
                with control._lock:
                    interrupt = target and not control._attempted
                    if interrupt:
                        control._attempted = True
                result = (
                    control.start(
                        original_request, connection, command, method, url, args, kwargs
                    )
                    if interrupt
                    else original_request(connection, method, url, *args, **kwargs)
                )
                returned = True
                return result
            except Exception as error:
                error_type = type(error).__name__
                raise
            finally:
                with control._lock:
                    control._requests.append(
                        NativeRequestObservation(
                            observed_at=observed_at,
                            command_digest=command.command_digest,
                            method=method,
                            path=path,
                            request_send_returned=returned,
                            error_type=error_type,
                        )
                    )
                    _LAST_REQUEST.set(len(control._requests) - 1)
                control._save()

        @wraps(original_getresponse)
        def getresponse(connection, *args, **kwargs):
            status = None
            error_type = None
            error_detail = None
            try:
                response = original_getresponse(connection, *args, **kwargs)
                status = response.status
                return response
            except Exception as error:
                error_type = type(error).__name__
                error_detail = str(error)[:400]
                raise
            finally:
                command = _COMMAND.get()
                index = _LAST_REQUEST.get()
                if command is not None and not _OBSERVING.get() and index is not None:
                    with control._lock:
                        row = control._requests[index]
                        if row.command_digest == command.command_digest:
                            control._requests[index] = row.model_copy(
                                update={
                                    "response_status": status,
                                    "response_error_type": error_type,
                                    "response_error_detail": error_detail,
                                }
                            )
                    control._save()

        DockerExperimentBackend.execute = execute
        DockerExperimentBackend.reconcile = reconcile
        DockerExperimentBackend.cleanup = cleanup
        NpipeHTTPConnection.request = request
        NpipeHTTPConnection.getresponse = getresponse
        _INSTALLED = True


def install_start_response_fault(
    configuration: StartResponseFaultConfiguration,
) -> StartResponseFaultControl:
    control = StartResponseFaultControl(configuration)
    control.install()
    return control
