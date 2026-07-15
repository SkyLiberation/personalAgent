"""AgentGraphState, AgentEvent and related types for LangGraph orchestration.

These models are serialisable and checkpoint-safe.  They carry the run-time
state of an entry orchestration execution, distinct from the business-fact store
(PostgresMemoryStore).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import uuid4

from langchain_core.messages import AnyMessage

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from personal_agent.kernel.models import Citation, EntryInput, ThreadSummary, local_now
from personal_agent.planning.task_analyzer import TaskAnalysis
from personal_agent.kernel.contracts.events import AgentEvent, AgentEventType
from personal_agent.kernel.contracts.agentic import (
    ContextEnvelope,
    ContextProjection,
    ExecutionEvent,
    ExecutionLedger,
    TaskSpec,
)
from personal_agent.kernel.contracts.executive import (
    ActionOutcome,
    BoundedAction,
    CompletionReport,
    ControlDecision,
    ControlState,
    ObservationRef,
    ResolvedActionSpec,
    RetryDirective,
)
from personal_agent.kernel.contracts.procedure import ProcedureInstance
from personal_agent.kernel.contracts.planning import (
    DispatchGroup,
    FrontierDecision,
    PlanLedger,
    PlanMonitorDecision,
    PlannerExecutionProfile,
    PlanningBudget,
    PlanningFacts,
    PlanningModeAssessment,
    ReplanRequest,
)

if TYPE_CHECKING:
    from personal_agent.kernel.contracts.execution import ExecutionStep


def _new_run_id() -> str:
    return uuid4().hex[:12]


def _new_thread_id(user_id: str, session_id: str, run_id: str | None = None) -> str:
    """Return the stable LangGraph conversation thread identifier.

    ``run_id`` remains accepted for callers migrating from the former
    per-run thread format, but runs in one session share one thread.
    """
    return f"{user_id}:{session_id}"


# ---------------------------------------------------------------------------
# Run status / snapshot (query models, not checkpoint state)
# ---------------------------------------------------------------------------

class AgentRunStatus(str, Enum):
    created = "created"
    queued = "queued"
    running = "running"
    waiting = "waiting"
    blocked_approval = "blocked_approval"
    cancel_requested = "cancel_requested"
    cancelling = "cancelling"
    completed = "completed"
    completed_degraded = "completed_degraded"
    cancelled = "cancelled"
    failed = "failed"
    timed_out = "timed_out"


class AgentRunSnapshot(BaseModel):
    """A read-only summary of a graph run for API queries."""

    run_id: str
    thread_id: str
    user_id: str
    session_id: str
    status: AgentRunStatus = AgentRunStatus.created
    result_contracts: list[str] = Field(default_factory=list)
    procedure_id: str = ""
    procedure_version: str = ""
    entry_text: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    execution_trace: list[str] = Field(default_factory=list)
    answer: str | None = None
    pending_confirmation: dict[str, Any] | None = None
    confirmation_decision: str | None = None
    confirmed_step_id: str = ""
    last_event: AgentEvent | None = None
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)


# ---------------------------------------------------------------------------
# StepRunState - checkpoint-safe execution step model
# ---------------------------------------------------------------------------


class StepRunState(BaseModel):
    """Checkpoint-safe, serialisable execution step projection state.

    Mirrors the ``ExecutionStep`` dataclass fields so that the orchestration graph
    can store and resume step projections without dict conversion.
    """

    step_id: str = ""
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
    status: str = "planned"
    retry_count: int = 0
    max_retries: int = 3
    failure_reason: str = ""
    recoverable: bool = True
    execution_mode: str = "deterministic"
    allowed_tools: list[str] = Field(default_factory=list)
    max_iterations: int = 3
    llm_decision_node: str = ""
    procedure_id: str = ""
    procedure_version: str = ""
    procedure_node_id: str = ""
    procedure_recovery_policy: str = "skip"
    procedure_branch_policy: str = "continue"
    conditional_edges: list[dict[str, str]] = Field(default_factory=list)
    projection_kind: str = "bounded_action"
    task_id: str = ""
    task_input: str = ""
    meta_capability: str = ""
    output_contract: str = "ToolResult"
    skill_ids: list[str] = Field(default_factory=list)
    execution_guidance: list[str] = Field(default_factory=list)
    capability_requirements: list[dict[str, Any]] = Field(default_factory=list)
    subtask_spec: dict[str, Any] = Field(default_factory=dict)
    input_artifact_id: str = ""
    output_artifact_id: str = ""
    error_artifact_id: str = ""
    output_label: str = ""
    output_title: str = ""
    output_preview: str = ""

    @classmethod
    def from_execution_step(cls, s: "ExecutionStep") -> "StepRunState":
        """Create a StepRunState from an execution step projection."""
        return cls(
            step_id=s.step_id,
            action_type=s.action_type,
            description=s.description,
            tool_name=s.tool_name,
            agent_id=s.agent_id,
            tool_input=s.tool_input,
            depends_on=s.depends_on,
            expected_output=s.expected_output,
            success_criteria=s.success_criteria,
            risk_level=s.risk_level,
            requires_confirmation=s.requires_confirmation,
            on_failure=s.on_failure,
            status=s.status,
            retry_count=s.retry_count,
            execution_mode=s.execution_mode,
            allowed_tools=s.allowed_tools,
            max_iterations=s.max_iterations,
            llm_decision_node=s.llm_decision_node,
            procedure_id=s.procedure_id,
            procedure_version=s.procedure_version,
            procedure_node_id=s.procedure_node_id,
            procedure_recovery_policy=s.procedure_recovery_policy,
            procedure_branch_policy=s.procedure_branch_policy,
            conditional_edges=s.conditional_edges,
            projection_kind=s.projection_kind,
            task_id=s.task_id,
            task_input=s.task_input,
            meta_capability=s.meta_capability,
            output_contract=s.output_contract,
            skill_ids=s.skill_ids,
            execution_guidance=s.execution_guidance,
            capability_requirements=s.capability_requirements,
            subtask_spec=s.subtask_spec,
        )

    def to_execution_step(self) -> "ExecutionStep":
        """Convert back to a step projection for validator / executor consumption."""
        from personal_agent.kernel.contracts.execution import ExecutionStep

        return ExecutionStep(
            step_id=self.step_id,
            action_type=self.action_type,
            description=self.description,
            tool_name=self.tool_name,
            agent_id=self.agent_id,
            tool_input=self.tool_input,
            depends_on=self.depends_on,
            expected_output=self.expected_output,
            success_criteria=self.success_criteria,
            risk_level=self.risk_level,
            requires_confirmation=self.requires_confirmation,
            on_failure=self.on_failure,
            status=self.status,
            retry_count=self.retry_count,
            execution_mode=self.execution_mode,
            allowed_tools=self.allowed_tools,
            max_iterations=self.max_iterations,
            llm_decision_node=self.llm_decision_node,
            procedure_id=self.procedure_id,
            procedure_version=self.procedure_version,
            procedure_node_id=self.procedure_node_id,
            procedure_recovery_policy=self.procedure_recovery_policy,
            procedure_branch_policy=self.procedure_branch_policy,
            conditional_edges=self.conditional_edges,
            projection_kind=self.projection_kind,
            task_id=self.task_id,
            task_input=self.task_input,
            meta_capability=self.meta_capability,
            output_contract=self.output_contract,
            skill_ids=self.skill_ids,
            execution_guidance=self.execution_guidance,
            capability_requirements=self.capability_requirements,
            subtask_spec=self.subtask_spec,
        )


# ---------------------------------------------------------------------------
# AgentGraphState — the checkpoint-able state for the orchestration graph
# ---------------------------------------------------------------------------

class ReactSubState(BaseModel):
    """ReAct loop private state — only meaningful inside react_graph."""

    iterations: list[dict[str, Any]] = Field(default_factory=list)
    step_id: str = ""
    iteration_index: int = 0
    max_iterations: int = 3
    allowed_tools: list[str] = Field(default_factory=list)
    user_prompt: str = ""
    done: bool = False
    result: dict[str, Any] = Field(default_factory=dict)
    status: Literal["idle", "running", "waiting_tool", "completed", "failed", "exhausted"] = "idle"
    stop_reason: str = ""
    pending_thought: str = ""
    pending_tool: str = ""
    pending_input: dict[str, Any] = Field(default_factory=dict)


class StepExecutionState(BaseModel):
    """Step execution private state."""

    steps: list[StepRunState] = Field(default_factory=list)
    current_step_index: int = 0
    results: dict[str, Any] = Field(default_factory=dict)
    aborted: bool = False
    retry_counts: dict[str, int] = Field(default_factory=dict)


class ToolTrackingSubState(BaseModel):
    """Tool call tracking — shared across plan and react execution."""

    active_context: Literal["step_execution", "react"] | None = None
    pending_step_id: str = ""
    pending_call_id: str = ""
    pending_tool_name: str = ""
    pending_tool_input: dict[str, Any] = Field(default_factory=dict)
    pending_react_iteration: int | None = None


class AgentGraphState(BaseModel):
    """Checkpoint-safe, serialisable state for the entry orchestration graph.

    Design principles
    -----------------
    - This holds resumable process state and reducer-backed dialogue messages.
    - Per-run results are reset on a new entry; ``messages`` persists within
      the stable conversation thread.
    - Business facts live in PostgresMemoryStore.
    - Large payloads (note text, full search results) are stored by
      reference, not by value.
    - Sub-system state (react, step_execution, tool_tracking) is grouped into
      sub-models to reduce field count and clarify ownership boundaries.
    """

    # Identity
    run_id: str = Field(default_factory=_new_run_id)
    thread_id: str = ""
    user_id: str = "default"
    session_id: str = "default"

    # Entry
    entry_input: EntryInput | None = None
    entry_text: str = ""

    # Durable conversation history accumulated across runs in one thread.
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    thread_summary: ThreadSummary | None = None

    # Ephemeral ToolGateway exchange for the current action only; unlike
    # ``messages`` it is overwritten instead of accumulated across the thread.
    tool_messages: list[AnyMessage] = Field(default_factory=list)

    # Routing
    task_analysis: TaskAnalysis | None = None
    task_spec: TaskSpec | None = None
    execution_ledger: ExecutionLedger | None = None
    context_envelope: ContextEnvelope = Field(default_factory=ContextEnvelope)
    context_projections: list[ContextProjection] = Field(default_factory=list)
    planning_model_context: dict[str, object] = Field(default_factory=dict)
    control_model_context: dict[str, object] = Field(default_factory=dict)
    procedure_id: str = ""
    procedure_version: str = ""
    active_procedure: ProcedureInstance | None = None

    # Adaptive planning owns short-horizon strategy. Step status is projected
    # exclusively from plan events rather than duplicated on PlanStep.
    planning_facts: PlanningFacts | None = None
    planning_mode: PlanningModeAssessment | None = None
    planner_profile: PlannerExecutionProfile | None = None
    planning_budget: PlanningBudget = Field(default_factory=PlanningBudget)
    plan_ledger: PlanLedger = Field(default_factory=PlanLedger)
    frontier_decision: FrontierDecision | None = None
    selected_plan_step_ids: list[str] = Field(default_factory=list)
    plan_monitor_decision: PlanMonitorDecision | None = None
    replan_request: ReplanRequest | None = None

    # Task-level executive control. These fields, rather than the projected
    # step list, own open-task progress and completion semantics.
    control_state: ControlState | None = None
    control_decision: ControlDecision | None = None
    current_action: BoundedAction | None = None
    current_actions: list[BoundedAction] = Field(default_factory=list)
    current_action_outcome: ActionOutcome | None = None
    resolved_action_spec: ResolvedActionSpec | None = None
    resolved_action_specs: list[ResolvedActionSpec] = Field(default_factory=list)
    dispatch_groups: list[DispatchGroup] = Field(default_factory=list)
    retry_directive: RetryDirective | None = None
    latest_observations: list[ObservationRef] = Field(default_factory=list)
    completion_report: CompletionReport | None = None
    execution_events: list[ExecutionEvent] = Field(default_factory=list)
    executive_turn: int = 0
    last_decision_hash: str = ""
    repeated_decision_count: int = 0
    control_route: str = ""

    # Sub-models (grouped private state)
    react: ReactSubState = Field(default_factory=ReactSubState)
    step_execution: StepExecutionState = Field(default_factory=StepExecutionState)
    tool_tracking: ToolTrackingSubState = Field(default_factory=ToolTrackingSubState)

    # Tool results
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    provider_call_count: int = 0

    # Lightweight execution trace for user-visible progress.
    execution_trace: list[str] = Field(default_factory=list)

    # Reflection ids injected into this run (replan/ask), for post-run promotion
    applied_reflection_ids: list[str] = Field(default_factory=list)

    # Evidence & citations (summary form to avoid checkpoint bloat)
    citations: list[Citation] = Field(default_factory=list)
    matches: list[dict[str, Any]] = Field(default_factory=list)

    # HITL
    pending_confirmation: dict[str, Any] | None = None
    confirmation_decision: str | None = None
    confirmed_step_id: str = ""

    # Final
    answer: str | None = None
    answer_completed: bool = False

    # Events (accumulated during the run)
    events: list[AgentEvent] = Field(default_factory=list)

    # Errors
    errors: list[str] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def add_event(self, event_type: AgentEventType, payload: dict[str, Any] | None = None) -> AgentEvent:
        event = AgentEvent(
            run_id=self.run_id,
            thread_id=self.thread_id,
            type=event_type,
            payload=payload or {},
        )
        self.events.append(event)
        self.updated_at = event.timestamp
        return event

    def update_step_status(self, step_id: str, status: str) -> None:
        for s in self.step_execution.steps:
            if s.step_id == step_id:
                s.status = status
                return

    def to_run_snapshot(self, status: AgentRunStatus | None = None) -> AgentRunSnapshot:
        resolved_status = status or _infer_status(self)
        last = self.events[-1] if self.events else None
        return AgentRunSnapshot(
            run_id=self.run_id,
            thread_id=self.thread_id,
            user_id=self.user_id,
            session_id=self.session_id,
            status=resolved_status,
            result_contracts=(
                [goal.result_contract for goal in self.task_analysis.goals]
                if self.task_analysis else []
            ),
            procedure_id=self.procedure_id,
            procedure_version=self.procedure_version,
            entry_text=self.entry_text,
            steps=[s.model_dump(mode="json") for s in self.step_execution.steps],
            execution_trace=self.execution_trace,
            answer=self.answer,
            pending_confirmation=self.pending_confirmation,
            confirmation_decision=self.confirmation_decision,
            last_event=last,
            errors=self.errors,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


def _infer_status(state: AgentGraphState) -> AgentRunStatus:
    if state.errors:
        return AgentRunStatus.failed
    if state.answer_completed:
        return AgentRunStatus.completed
    if state.pending_confirmation is not None:
        if state.pending_confirmation.get("kind") == "clarification_required":
            return AgentRunStatus.waiting
        return AgentRunStatus.blocked_approval
    if state.task_analysis is not None:
        return AgentRunStatus.running
    return AgentRunStatus.created


# ---------------------------------------------------------------------------
# Conversion helpers: EntryResult <-> AgentEvent / AgentGraphState
# ---------------------------------------------------------------------------

def execution_trace_to_events(
    traces: list[str], run_id: str, thread_id: str
) -> list[AgentEvent]:
    """Convert execution trace strings into step-started / step-completed events."""
    events: list[AgentEvent] = []
    for i, desc in enumerate(traces):
        step_id = f"trace_{i}"
        events.append(
            AgentEvent(
                run_id=run_id,
                thread_id=thread_id,
                type="step_started",
                payload={"step_id": step_id, "description": desc},
            )
        )
        events.append(
            AgentEvent(
                run_id=run_id,
                thread_id=thread_id,
                type="step_completed",
                payload={"step_id": step_id, "description": desc},
            )
        )
    return events


# ---------------------------------------------------------------------------
# Phase 5: event → consumer format converters
# ---------------------------------------------------------------------------

def execution_trace_from_events(events: list[AgentEvent]) -> list[str]:
    """Derive ``execution_trace`` strings from structured ``AgentEvent`` objects.

    Extracts descriptions from ``step_started`` and ``react_iteration`` events.
    Returns a deduplicated, ordered list suitable for display in plan/trace panels.
    """
    trace: list[str] = []
    seen: set[str] = set()
    for evt in events:
        if evt.type == "step_started":
            desc = str(evt.payload.get("description", ""))
            if desc and desc not in seen:
                trace.append(desc)
                seen.add(desc)
        elif evt.type == "react_iteration":
            thought = str(evt.payload.get("thought", ""))
            label = f"ReAct 推理轮次 {evt.payload.get('iteration', '?')}"
            if thought:
                label = f"{label}: {thought[:80]}"
            if label not in seen:
                trace.append(label)
                seen.add(label)
        elif evt.type == "executive_decision":
            decision = evt.payload.get("decision") or {}
            action = str(decision.get("action") or "")
            progress = str(decision.get("expected_progress") or "")
            label = progress or action
            if label and label not in seen:
                trace.append(label)
                seen.add(label)
        elif evt.type == "procedure_started":
            call = evt.payload.get("procedure_call") or {}
            procedure_id = str(call.get("procedure_id") or "")
            label = f"执行受治理过程: {procedure_id}" if procedure_id else "执行受治理过程"
            if label not in seen:
                trace.append(label)
                seen.add(label)
    return trace


_SSE_EVENT_TYPE_MAP: dict[str, str] = {
    "entry_started": "status",
    "clarification_required": "confirmation_required",
    "clarification_resumed": "status",
    "task_analyzed": "task_analysis",
    "goal_graph_compiled": "goal_graph_compiled",
    "executive_decision": "executive_decision",
    "action_materialized": "action_materialized",
    "action_outcome": "action_outcome",
    "procedure_started": "procedure_started",
    "procedure_completed": "procedure_completed",
    "goal_verification": "goal_verification",
    "completion_checked": "completion_checked",
    "completion_rejected": "completion_rejected",
    "step_started": "step_started",
    "react_iteration": "react_iteration",
    "tool_called": "tool_called",
    "tool_result": "tool_result",
    "confirmation_required": "confirmation_required",
    "confirmation_resumed": "status",
    "draft_ready": "draft_ready",
    "answer_delta": "answer_delta",
    "answer_completed": "done",
    "step_completed": "step_completed",
    "step_failed": "step_failed",
    "replan_attempted": "step_replan_attempt",
    "replan_completed": "steps_replanned",
    "run_completed": "done",
    "run_failed": "status",
}


def events_to_sse_tuples(
    events: list[AgentEvent],
) -> list[tuple[str, dict[str, Any]]]:
    """Convert a list of ``AgentEvent`` objects into SSE-compatible
    ``(event_type, payload)`` tuples for streaming endpoints.
    """
    result: list[tuple[str, dict[str, Any]]] = []
    for evt in events:
        sse_type = _SSE_EVENT_TYPE_MAP.get(evt.type, "status")
        payload: dict[str, Any] = dict(evt.payload)
        payload.setdefault("_event_id", evt.event_id)
        payload.setdefault("_event_type", evt.type)
        result.append((sse_type, payload))
    return result
