"""Bind Toolathlon's computation requirement to a scoped Bash deployment."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from pydantic import BaseModel

from evals.Toolathlon import runner
from evals.Toolathlon.workspace_inputs import WORKSPACE
from personal_agent.application.bash_execution.models import (
    BASH_RUNTIME_DIR,
    BashExecutionAuthorization,
    BashWorkspaceBinding,
)
from personal_agent.infra.bash_execution.deployment import BashExecutionDeploymentConfig
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


EXECUTE_BASH = "bash"
TASK_VOLUME_ROOT = "/workspace/dumps"
FIXTURE_PYTHON = "/workspace/.venv/bin/python"
PREPARE_FIXTURE_PYTHON = """\
from pathlib import Path
from shutil import copytree
import sys

runtime = Path(sys.argv[1])
source = Path(sys.base_prefix)
interpreter = Path(sys.executable).resolve().relative_to(source)
copytree(source, runtime / "python", symlinks=True)
bin_dir = runtime / "bin"
bin_dir.mkdir()
for name in ("python", "python3", f"python{sys.version_info.major}.{sys.version_info.minor}"):
    (bin_dir / name).symlink_to(Path("../python") / interpreter)
(runtime / "lib").symlink_to(Path(sys.prefix) / "lib", target_is_directory=True)
home = runtime / "python" / interpreter.parent
(runtime / "pyvenv.cfg").write_text(f"home = {home}\\ninclude-system-site-packages = false\\n")
"""


@contextmanager
def task_workspace_volume():
    with _volume("workspace") as volume:
        yield volume


@contextmanager
def _volume(purpose: str):
    volume = runner.docker("volume", "create", f"toolathlon-{purpose}-{uuid4().hex}")
    try:
        yield volume
    finally:
        runner.docker("volume", "rm", volume)


def bind_gateway_workspace(container: str, server_id: str, *, runtime_volume_name: str | None) -> BashWorkspaceBinding:
    mount = '{{range .Mounts}}{{if and (eq .Destination "/workspace/dumps") (eq .Type "volume") .RW}}{{.Name}}{{end}}{{end}}'
    volume = runner.docker("inspect", "--format", mount, container)
    binding = BashWorkspaceBinding(
        mcp_server_id=server_id, volume_name=volume, subdirectory="workspace", root=WORKSPACE,
        runtime_volume_name=runtime_volume_name, network_container_id=container,
    )
    runner.docker("exec", container, "chown", "-hR", "65534:65534", binding.root)
    return binding


class TaskToolRequirements(BaseModel):
    needed_mcp_servers: tuple[str, ...]
    needed_local_tools: tuple[str, ...] | None

    @property
    def needs_bash(self) -> bool:
        return "python_execute" in (self.needed_local_tools or ())


@dataclass(frozen=True)
class BashSandbox:
    image_id: str
    endpoint: str
    runtime_volume_name: str | None = None

    @classmethod
    @contextmanager
    def from_fixture_image(cls, image: str):
        base = cls.from_local_image(image)
        with _volume("runtime") as volume:
            with runner.container(
                base.image_id, "--network", "none", "--entrypoint", FIXTURE_PYTHON,
                "--mount", f"type=volume,source={volume},target={BASH_RUNTIME_DIR},volume-nocopy",
                command=("-c", PREPARE_FIXTURE_PYTHON, BASH_RUNTIME_DIR),
            ) as initializer:
                runner.docker("start", "-a", initializer)
            yield cls(image_id=base.image_id, endpoint=base.endpoint, runtime_volume_name=volume)

    @classmethod
    def from_local_image(cls, image: str) -> BashSandbox:
        image_id = runner.docker("image", "inspect", "--format", "{{.Id}}", image)
        endpoint = None if os.environ.get("DOCKER_CONTEXT") else os.environ.get("DOCKER_HOST")
        if endpoint is None:
            endpoint = runner.docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
        return cls(image_id=image_id, endpoint=endpoint)

    def deployment(
        self, principal: AuthenticatedPrincipal, session_id: str, *,
        timeout_seconds: int, max_total_tokens: int,
        workspace: BashWorkspaceBinding | None = None,
    ) -> BashExecutionDeploymentConfig:
        return BashExecutionDeploymentConfig(
            endpoint=self.endpoint,
            authorization=BashExecutionAuthorization(
                authorized_principal=principal,
                conversation_id=session_id,
                # Allow for Web startup while keeping the full configured turn budget.
                expires_at=datetime.now(UTC) + timedelta(seconds=timeout_seconds + 180),
                turn_timeout_seconds=timeout_seconds,
                max_total_tokens=max_total_tokens,
                max_execution_seconds=timeout_seconds,
                image_id=self.image_id,
                workspace=workspace,
            ),
        )


class BashToolEvidence(TypedDict):
    authorization_digest: str | None
    tool_request_count: int
    visible_request_count: int
    execution_statuses: list[str]


def bash_tool_evidence(output: Path, trace: dict) -> BashToolEvidence:
    tool_requests = visible = 0
    for path in runner.model_request_paths(output):
        tools = {
            definition["target_name"]
            for definition in json.loads(path.read_bytes())["action_definitions"]
            if definition["kind"] == "tool"
        }
        tool_requests += bool(tools)
        visible += EXECUTE_BASH in tools
    return BashToolEvidence(
        authorization_digest=trace["bash_authorization_digest"],
        tool_request_count=tool_requests,
        visible_request_count=visible,
        execution_statuses=[
            event["status"] for event in trace["inputs"]
            if event["kind"] == "tool_result" and event["capability_id"] == EXECUTE_BASH
        ],
    )
