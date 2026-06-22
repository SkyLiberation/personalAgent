"""Framework-level planning and execution contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from pydantic import BaseModel, Field

from ..core.models import EntryIntent


@dataclass(slots=True)
class ExecutionStep:
    """A workflow node compiled for one concrete task."""

    step_id: str = field(default_factory=lambda: uuid4().hex[:8])
    action_type: str = ""
    description: str = ""
    tool_name: str | None = None
    tool_input: dict[str, object] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    expected_output: str = ""
    success_criteria: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = False
    on_failure: str = "skip"
    status: str = "planned"
    retry_count: int = 0
    execution_mode: str = "deterministic"
    allowed_tools: list[str] = field(default_factory=list)
    max_iterations: int = 3
    workflow_id: str = ""
    workflow_version: str = ""
    workflow_step_id: str = ""
    projection_kind: str = "workflow_step"
    task_id: str = ""
    task_intent: EntryIntent = "unknown"
    task_input: str = ""


class WorkflowTask(BaseModel):
    """One selected workflow bound to a user goal."""

    task_id: str
    intent: EntryIntent
    input: str
    depends_on: list[str] = Field(default_factory=list)
    workflow_id: str
    workflow_version: str
    step_ids: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    """Immutable task-level plan consumed by orchestration."""

    plan_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    tasks: list[WorkflowTask] = Field(default_factory=list)

    @property
    def primary_intent(self) -> EntryIntent:
        return self.tasks[-1].intent if self.tasks else "unknown"

    def task(self, task_id: str) -> WorkflowTask | None:
        return next((task for task in self.tasks if task.task_id == task_id), None)
