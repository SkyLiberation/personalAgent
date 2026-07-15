"""Framework-level planning and execution contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

@dataclass(slots=True)
class ExecutionStep:
    """A bounded action or governed procedure node ready for execution."""

    step_id: str = field(default_factory=lambda: uuid4().hex[:8])
    action_type: str = ""
    description: str = ""
    tool_name: str | None = None
    agent_id: str | None = None
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
    llm_decision_node: str = ""
    procedure_id: str = ""
    procedure_version: str = ""
    procedure_node_id: str = ""
    procedure_recovery_policy: str = "skip"
    procedure_branch_policy: str = "continue"
    conditional_edges: list[dict[str, str]] = field(default_factory=list)
    projection_kind: str = "bounded_action"
    task_id: str = ""
    task_input: str = ""
    meta_capability: str = ""
    output_contract: str = "ToolResult"
    skill_ids: list[str] = field(default_factory=list)
    execution_guidance: list[str] = field(default_factory=list)
    capability_requirements: list[dict[str, object]] = field(default_factory=list)
    subtask_spec: dict[str, object] = field(default_factory=dict)
