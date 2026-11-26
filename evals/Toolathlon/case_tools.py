"""Bind Toolathlon's computation requirement to a scoped Bash deployment."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel

from evals.Toolathlon import runner
from evals.Toolathlon.workspace_inputs import WORKSPACE
from personal_agent.application.bash_execution.models import (
    BashExecutionAuthorization,
    BashWorkspaceBinding,
)
from personal_agent.infra.bash_execution.deployment import BashExecutionDeploymentConfig
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


EXECUTE_BASH = "bash"
TASK_VOLUME_ROOT = "/workspace/dumps"
def bind_gateway_workspace(container: str, server_id: str) -> BashWorkspaceBinding:
    mounts = json.loads(runner.docker("inspect", "--format", "{{json .Mounts}}", container))
    mounts = [mount for mount in mounts if mount["Destination"] == TASK_VOLUME_ROOT and mount["RW"]]
    if len(mounts) != 1:
        raise RuntimeError("Toolathlon requires one gateway workspace shared with the Linux Agent host")
    directory = Path(mounts[0]["Source"]) / "workspace"
    if not directory.is_dir() or not os.access(directory, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError("Use a gateway workspace mount accessible to the host Agent user")
    return BashWorkspaceBinding(mcp_server_id=server_id, host_path=directory, root=WORKSPACE)


class TaskToolRequirements(BaseModel):
    needed_mcp_servers: tuple[str, ...]
    needed_local_tools: tuple[str, ...] | None

    @property
    def needs_bash(self) -> bool:
        return "python_execute" in (self.needed_local_tools or ())


@dataclass(frozen=True)
class BashSandbox:
    version: str

    @classmethod
    def native(cls) -> BashSandbox:
        executable = shutil.which("bwrap")
        if executable is None:
            raise RuntimeError("Toolathlon Bash requires the native Linux bubblewrap executable")
        version = subprocess.check_output((executable, "--version"), text=True, timeout=5).strip()
        return cls(version=version)

    def deployment(
        self, principal: AuthenticatedPrincipal, session_id: str, *,
        timeout_seconds: int, max_total_tokens: int,
        workspace: BashWorkspaceBinding | None = None,
    ) -> BashExecutionDeploymentConfig:
        return BashExecutionDeploymentConfig(
            authorization=BashExecutionAuthorization(
                authorized_principal=principal,
                conversation_id=session_id,
                turn_timeout_seconds=timeout_seconds,
                max_total_tokens=max_total_tokens,
                max_execution_seconds=timeout_seconds,
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
