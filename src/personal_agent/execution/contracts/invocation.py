"""Canonical typed invocations and their mutable attempt state."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from personal_agent.capabilities.contracts.execution import CapabilityRequirement


class InvocationAttemptState(BaseModel):
    """Mutable facts produced while executing one immutable invocation."""

    status: str = "planned"
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=3, ge=0)
    failure_reason: str = ""
    recoverable: bool = True
    input_artifact_id: str | None = None
    output_artifact_id: str | None = None
    error_artifact_id: str | None = None
    output_label: str = ""
    output_title: str = ""
    output_preview: str = ""


class DelegatedSubtaskInvocation(BaseModel):
    goal: str
    parent_goal_id: str
    context_projection_ids: tuple[str, ...] = ()
    required_capability: CapabilityRequirement
    expected_artifact_contract: str = "AgentArtifact"
    verification_policy: str = "required"
    max_provider_calls: int = Field(default=1, ge=1, le=16)
    requested_operations: tuple[str, ...] = ()


class ConditionalTransition(BaseModel):
    condition: str
    target: str


class ProcedureNodeInvocation(BaseModel):
    procedure_id: str = Field(min_length=1)
    procedure_version: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    recovery_policy: str = "skip"
    branch_policy: str = "continue"
    transitions: tuple[ConditionalTransition, ...] = ()


class ExecutableInvocation(BaseModel):
    """One canonical executable definition with a single nested attempt state.

    Definition fields are never mirrored into a checkpoint adapter. Runtime
    mutations are owned by ``attempt``.
    """

    step_id: str = Field(default_factory=lambda: uuid4().hex[:8], min_length=1)
    action_type: str = ""
    description: str = ""
    tool_name: str | None = None
    agent_id: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    expected_output: str = ""
    success_criteria: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = False
    on_failure: str = "skip"
    execution_mode: str = "deterministic"
    allowed_tools: list[str] = Field(default_factory=list)
    max_iterations: int = 3
    llm_decision_node: str = ""
    procedure: ProcedureNodeInvocation | None = None
    projection_kind: str = "bounded_action"
    goal_id: str | None = None
    task_input: str = ""
    execution_intent: str = ""
    output_contract: str = "ToolResult"
    execution_grant_ref: str | None = None
    skill_ids: list[str] = Field(default_factory=list)
    execution_guidance: list[str] = Field(default_factory=list)
    capability_requirements: list[CapabilityRequirement] = Field(default_factory=list)
    subtask: DelegatedSubtaskInvocation | None = None
    attempt: InvocationAttemptState = Field(default_factory=InvocationAttemptState)

    @property
    def procedure_id(self) -> str | None:
        return self.procedure.procedure_id if self.procedure else None

    @property
    def procedure_version(self) -> str | None:
        return self.procedure.procedure_version if self.procedure else None

    @property
    def procedure_node_id(self) -> str | None:
        return self.procedure.node_id if self.procedure else None

    @property
    def procedure_recovery_policy(self) -> str:
        return self.procedure.recovery_policy if self.procedure else "skip"

    @property
    def procedure_branch_policy(self) -> str:
        return self.procedure.branch_policy if self.procedure else "continue"

    @property
    def conditional_edges(self) -> tuple[ConditionalTransition, ...]:
        return self.procedure.transitions if self.procedure else ()

    @property
    def status(self) -> str:
        return self.attempt.status

    @status.setter
    def status(self, value: str) -> None:
        self.attempt.status = value

    @property
    def retry_count(self) -> int:
        return self.attempt.retry_count

    @retry_count.setter
    def retry_count(self, value: int) -> None:
        self.attempt.retry_count = value

    @property
    def max_retries(self) -> int:
        return self.attempt.max_retries

    @property
    def failure_reason(self) -> str:
        return self.attempt.failure_reason

    @failure_reason.setter
    def failure_reason(self, value: str) -> None:
        self.attempt.failure_reason = value

    @property
    def recoverable(self) -> bool:
        return self.attempt.recoverable

    @recoverable.setter
    def recoverable(self, value: bool) -> None:
        self.attempt.recoverable = value

    @property
    def input_artifact_id(self) -> str:
        return self.attempt.input_artifact_id or ""

    @input_artifact_id.setter
    def input_artifact_id(self, value: str) -> None:
        self.attempt.input_artifact_id = value or None

    @property
    def output_artifact_id(self) -> str:
        return self.attempt.output_artifact_id or ""

    @output_artifact_id.setter
    def output_artifact_id(self, value: str) -> None:
        self.attempt.output_artifact_id = value or None

    @property
    def error_artifact_id(self) -> str:
        return self.attempt.error_artifact_id or ""

    @error_artifact_id.setter
    def error_artifact_id(self, value: str) -> None:
        self.attempt.error_artifact_id = value or None

    @property
    def output_label(self) -> str:
        return self.attempt.output_label

    @output_label.setter
    def output_label(self, value: str) -> None:
        self.attempt.output_label = value

    @property
    def output_title(self) -> str:
        return self.attempt.output_title

    @output_title.setter
    def output_title(self, value: str) -> None:
        self.attempt.output_title = value

    @property
    def output_preview(self) -> str:
        return self.attempt.output_preview

    @output_preview.setter
    def output_preview(self, value: str) -> None:
        self.attempt.output_preview = value


__all__ = [
    "ConditionalTransition", "DelegatedSubtaskInvocation", "ExecutableInvocation",
    "InvocationAttemptState", "ProcedureNodeInvocation",
]
