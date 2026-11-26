"""Freeze this call's inputs and retain only explicitly authorized task files."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.bash_execution.models import BashExecutionCommand, BashExecutionProfile, Digest
from personal_agent.kernel.contracts.resource import ResourceRef

if TYPE_CHECKING:
    from personal_agent.application.bash_execution.ports import BashInputLoader


class BashWorkspaceUnavailable(Exception):
    pass


class _TaskWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    turn_id: str
    inputs: frozenset[ResourceRef]
    file_versions: dict[str, Digest] = Field(default_factory=dict)


def write_record(path: Path, record: BaseModel) -> None:
    pending = path.with_suffix(".pending")
    pending.write_text(record.model_dump_json(), encoding="utf-8")
    pending.replace(path)


def stage_inputs(directory: Path, command: BashExecutionCommand, load_input: BashInputLoader) -> None:
    directory.mkdir(mode=0o700)
    for identity in (command.program, *command.inputs):
        contents = load_input(identity)
        if contents.identity() != identity:
            raise ValueError("Bash input does not match the accepted command")
        path = directory / identity.name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(contents.content)


def publish_task_inputs(directory: Path, staged: Path, command: BashExecutionCommand) -> None:
    """Publish verified bytes under the stable read-only mount of this task."""
    directory.mkdir(mode=0o700, exist_ok=True)
    with TemporaryDirectory(dir=staged.parent) as temporary:
        link = Path(temporary) / "input"
        for identity in (command.program, *command.inputs):
            destination = directory / identity.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.link(staged / identity.name, link)
            link.replace(destination)


class BashTaskFiles:
    def __init__(self, root: Path, profile: BashExecutionProfile) -> None:
        self.profile = profile
        self.directory = root / "task-workspaces" / profile.deployment_digest
        self.record = self.directory / "workspace.json"
        self.scratch = self.directory / "scratch"
        self.inputs = self.directory / "inputs"

    def prepare(self, command: BashExecutionCommand) -> Path:
        policy, access, scope = self.profile.task_workspace, command.task_workspace, command.execution_scope
        if policy is None or access is None or scope.thread_id != policy.conversation_id:
            raise BashWorkspaceUnavailable
        inputs = frozenset(item.resource_ref for item in command.inputs)
        if not self.record.is_file():
            if self.directory.exists():
                raise BashWorkspaceUnavailable
            self.directory.mkdir(parents=True, mode=0o700)
            self.scratch.mkdir(mode=0o700)
            state = _TaskWorkspace(task_id=access.task_id, turn_id=scope.execution_id, inputs=inputs)
        else:
            state = self._read()
            if (state.task_id != access.task_id
                    or (state.turn_id != scope.execution_id and state.turn_id not in access.predecessor_turn_ids)
                    or not state.inputs.issubset(inputs) or not self.scratch.is_dir()):
                raise BashWorkspaceUnavailable
            state = state.model_copy(update={"turn_id": scope.execution_id, "inputs": inputs})
        write_record(self.record, state)
        return self.scratch

    def _read(self) -> _TaskWorkspace:
        return _TaskWorkspace.model_validate_json(self.record.read_bytes())

    def observed_version(self, path: str) -> Digest | None:
        return self._read().file_versions.get(path)

    def observe(self, path: str, digest: Digest) -> None:
        state = self._read()
        write_record(self.record, state.model_copy(update={"file_versions": {**state.file_versions, path: digest}}))

    def close(self) -> None:
        if self.directory.exists():
            shutil.rmtree(self.directory)
