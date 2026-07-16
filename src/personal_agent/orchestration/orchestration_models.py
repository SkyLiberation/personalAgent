"""RunCheckpoint, AgentEvent and related types for LangGraph orchestration.

These models are serialisable and checkpoint-safe.  They carry the run-time
state of an entry orchestration execution, distinct from the business-fact store
(PostgresMemoryStore).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import uuid4

from langchain_core.messages import AnyMessage

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from personal_agent.kernel.models import Citation, EntryInput, ThreadSummary, local_now
from personal_agent.planning.task_analyzer import TaskAnalysis
from personal_agent.kernel.contracts.events import AgentEvent, AgentEventType
from personal_agent.runtime.contracts.task import (
    ContextInventory,
    ContextProjection,
    ExecutionEvent,
    TaskRuntimeProjection,
    TaskContract,
    MaterializedGoalView,
    materialize_goals,
)
from personal_agent.runtime.contracts.intake import TaskIntakeState
from personal_agent.runtime.contracts.control import (
    BoundedAction,
    ControlTurnState,
    ResolvedActionSpec,
)
from personal_agent.verification.contracts.reports import CompletionReport, VerificationReport
from personal_agent.execution.contracts.invocation import ExecutableInvocation
from personal_agent.execution.contracts.journal import InvocationJournalProjection
from personal_agent.capabilities.contracts.grants import ExecutionGrant
from personal_agent.capabilities.contracts.acquisition import CapabilityAcquisitionProjection
from personal_agent.governance.contracts.evidence import EvidenceAdmissionDecision
from personal_agent.governance.contracts.admission import StageAdmissionDecision
from personal_agent.runtime.contracts.commits import ControlCommit, TaskCompilationCommit
from personal_agent.capabilities.contracts.outcomes import (
    CapabilityEffectivenessEvent,
    CapabilityExecutionOutcomeEvent,
)
from personal_agent.kernel.contracts.interaction import InteractionDecision, InteractionRequest
from personal_agent.capabilities.contracts.procedure import ProcedureRunProjection
from personal_agent.runtime.contracts.planning import (
    FrontierDecision,
    PlanDefinition,
    PlanRuntimeProjection,
    PlanMonitorDecision,
    PlannerExecutionProfile,
    PlanningUsage,
    PlanningFacts,
    CoordinationAssessment,
    ReplanRequest,
)

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
    procedure_id: str | None = None
    procedure_version: str | None = None
    entry_text: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    execution_trace: list[str] = Field(default_factory=list)
    answer: str | None = None
    pending_confirmation: InteractionRequest | None = None
    confirmation_decision: InteractionDecision | None = None
    confirmed_step_id: str | None = None
    last_event: AgentEvent | None = None
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)


# ---------------------------------------------------------------------------
# RunCheckpoint — the checkpoint-able state for the orchestration graph
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


class InvocationBatchState(BaseModel):
    """Canonical invocations and their attempt state for the current batch."""

    invocations: list[ExecutableInvocation] = Field(default_factory=list)
    current_step_index: int = 0
    results: dict[str, Any] = Field(default_factory=dict)
    aborted: bool = False
    retry_counts: dict[str, int] = Field(default_factory=dict)


class ToolTrackingSubState(BaseModel):
    """Tool call tracking — shared across plan and react execution."""

    active_context: Literal["invocation_batch", "react"] | None = None
    pending_step_id: str = ""
    pending_call_id: str = ""
    pending_tool_name: str = ""
    pending_tool_input: dict[str, Any] = Field(default_factory=dict)
    pending_react_iteration: int | None = None


class RunCheckpoint(BaseModel):
    """Checkpoint-safe, serialisable state for the entry orchestration graph.

    Design principles
    -----------------
    - This holds resumable process state and reducer-backed dialogue messages.
    - Per-run results are reset on a new entry; ``messages`` persists within
      the stable conversation thread.
    - Business facts live in PostgresMemoryStore.
    - Large payloads (note text, full search results) are stored by
      reference, not by value.
    - Sub-system state (react, invocation_batch, tool_tracking) is grouped into
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
    intake: TaskIntakeState | None = None
    task_analysis: TaskAnalysis | None = None
    task_contract: TaskContract | None = None
    task_runtime: TaskRuntimeProjection | None = None
    context_inventory: ContextInventory = Field(default_factory=ContextInventory)
    context_projections: list[ContextProjection] = Field(default_factory=list)
    active_procedure: ProcedureRunProjection | None = None

    # Adaptive planning owns short-horizon strategy. Step status is projected
    # exclusively from plan events rather than duplicated on PlanStep.
    planning_facts: PlanningFacts | None = None
    coordination: CoordinationAssessment | None = None
    planner_profile: PlannerExecutionProfile | None = None
    planning_usage: PlanningUsage = Field(default_factory=PlanningUsage)
    plan_definition: PlanDefinition | None = None
    plan_runtime: PlanRuntimeProjection = Field(default_factory=PlanRuntimeProjection)
    frontier_decision: FrontierDecision | None = None
    plan_monitor_decision: PlanMonitorDecision | None = None
    replan_request: ReplanRequest | None = None

    # One checkpoint-local owner for the bounded executive turn. Business
    # facts remain in Task/Plan/Invocation/Observation aggregates.
    control: ControlTurnState = Field(default_factory=ControlTurnState)
    decision_admission: StageAdmissionDecision | None = None
    verification_reports: dict[str, VerificationReport] = Field(default_factory=dict)
    completion_report: CompletionReport | None = None
    execution_events: list[ExecutionEvent] = Field(default_factory=list)
    execution_grants: dict[str, ExecutionGrant] = Field(default_factory=dict)
    invocation_journal: InvocationJournalProjection = Field(default_factory=InvocationJournalProjection)
    capability_acquisition: CapabilityAcquisitionProjection = Field(
        default_factory=CapabilityAcquisitionProjection,
    )
    evidence_admissions: dict[str, EvidenceAdmissionDecision] = Field(default_factory=dict)
    capability_execution_outcomes: list[CapabilityExecutionOutcomeEvent] = Field(default_factory=list)
    capability_effectiveness_outcomes: list[CapabilityEffectivenessEvent] = Field(default_factory=list)
    task_compilation_commit: TaskCompilationCommit | None = None
    control_commits: list[ControlCommit] = Field(default_factory=list)

    # Sub-models (grouped private state)
    react: ReactSubState = Field(default_factory=ReactSubState)
    invocation_batch: InvocationBatchState = Field(default_factory=InvocationBatchState)
    tool_tracking: ToolTrackingSubState = Field(default_factory=ToolTrackingSubState)

    # Tool results
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    provider_call_count: int = 0

    # Reflection ids injected into this run (replan/ask), for post-run promotion
    applied_reflection_ids: list[str] = Field(default_factory=list)

    # Evidence & citations (summary form to avoid checkpoint bloat)
    citations: list[Citation] = Field(default_factory=list)
    matches: list[dict[str, Any]] = Field(default_factory=list)

    # HITL
    # Final
    answer: str | None = None

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

    @property
    def goals(self) -> tuple[MaterializedGoalView, ...]:
        """Return the canonical definition/runtime join for task goals."""
        if self.task_contract is None or self.task_runtime is None:
            return ()
        return materialize_goals(self.task_contract, self.task_runtime)

    @property
    def answer_completed(self) -> bool:
        """Derive completion from canonical task lifecycle or terminal run facts."""
        if self.task_runtime is not None and self.task_runtime.lifecycle in {"completed", "terminated"}:
            return True
        return any(event.type in {"answer_completed", "run_completed"} for event in self.events)

    @property
    def execution_trace(self) -> list[str]:
        return execution_trace_from_events(self.events)

    @property
    def current_action(self) -> BoundedAction | None:
        return self.control.actions[0] if self.control.actions else None

    @property
    def resolved_action_spec(self) -> ResolvedActionSpec | None:
        return self.control.resolved_actions[0] if self.control.resolved_actions else None

    @property
    def selected_plan_step_ids(self) -> list[str]:
        return [
            step_id for step_id, status in self.plan_runtime.step_statuses.items()
            if status in {"selected", "running", "observed"}
        ]

    @property
    def procedure_id(self) -> str | None:
        return self.active_procedure.procedure.procedure_id if self.active_procedure else None

    @property
    def procedure_version(self) -> str | None:
        return self.active_procedure.procedure.version if self.active_procedure else None

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
        for s in self.invocation_batch.invocations:
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
            steps=[s.model_dump(mode="json") for s in self.invocation_batch.invocations],
            execution_trace=self.execution_trace,
            answer=self.answer,
            pending_confirmation=self.control.pending_interaction,
            confirmation_decision=self.control.interaction_decision,
            confirmed_step_id=self.control.confirmed_invocation_id,
            last_event=last,
            errors=self.errors,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


def _infer_status(state: RunCheckpoint) -> AgentRunStatus:
    if state.errors:
        return AgentRunStatus.failed
    if state.answer_completed:
        return AgentRunStatus.completed
    if state.control.pending_interaction is not None:
        if state.control.pending_interaction.kind == "clarification_required":
            return AgentRunStatus.waiting
        return AgentRunStatus.blocked_approval
    if state.task_analysis is not None:
        return AgentRunStatus.running
    return AgentRunStatus.created


# ---------------------------------------------------------------------------
# Conversion helpers: EntryResult <-> AgentEvent / RunCheckpoint
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
            call = evt.payload.get("procedure_invocation") or {}
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
