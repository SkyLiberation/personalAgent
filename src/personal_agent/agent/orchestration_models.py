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

from ..core.models import Citation, EntryInput, EntryIntent, ThreadSummary, local_now
from .router import RouterDecision

if TYPE_CHECKING:
    from .planner import PlanStep


def _new_run_id() -> str:
    return uuid4().hex[:12]


def _new_thread_id(user_id: str, session_id: str, run_id: str | None = None) -> str:
    """Return the stable LangGraph conversation thread identifier.

    ``run_id`` remains accepted for callers migrating from the former
    per-run thread format, but runs in one session share one thread.
    """
    return f"{user_id}:{session_id}"


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------

AgentEventType = Literal[
    "entry_started",
    "clarification_required",
    "clarification_resumed",
    "intent_classified",
    "plan_created",
    "plan_validated",
    "step_started",
    "react_iteration",
    "tool_called",
    "tool_result",
    "confirmation_required",
    "confirmation_resumed",
    "draft_ready",
    "answer_delta",
    "answer_completed",
    "step_completed",
    "step_failed",
    "replan_attempted",
    "replan_completed",
    "run_completed",
    "run_failed",
]


class AgentEvent(BaseModel):
    """A structured, serialisable event emitted during a graph run."""

    event_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    run_id: str = ""
    thread_id: str = ""
    type: AgentEventType
    timestamp: datetime = Field(default_factory=local_now)
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Run status / snapshot (query models, not checkpoint state)
# ---------------------------------------------------------------------------

class AgentRunStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    waiting_confirmation = "waiting_confirmation"
    cancelled = "cancelled"


class AgentRunSnapshot(BaseModel):
    """A read-only summary of a graph run for API queries."""

    run_id: str
    thread_id: str
    user_id: str
    session_id: str
    status: AgentRunStatus = AgentRunStatus.pending
    intent: EntryIntent = "unknown"
    entry_text: str = ""
    plan_steps: list[dict[str, Any]] = Field(default_factory=list)
    execution_trace: list[str] = Field(default_factory=list)
    answer: str | None = None
    pending_confirmation: dict[str, Any] | None = None
    confirmation_decision: str | None = None
    last_event: AgentEvent | None = None
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)


# ---------------------------------------------------------------------------
# PlanStepState — checkpoint-safe plan step model
# ---------------------------------------------------------------------------


class PlanStepState(BaseModel):
    """Checkpoint-safe, serialisable workflow step projection state.

    Mirrors the ``PlanStep`` dataclass fields so that the orchestration graph
    can store and resume step projections without dict conversion.
    """

    step_id: str = ""
    action_type: str = ""
    description: str = ""
    tool_name: str | None = None
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
    workflow_id: str = ""
    workflow_version: str = ""
    workflow_step_id: str = ""
    projection_kind: str = "workflow_step"
    output_label: str = ""
    output_title: str = ""
    output_preview: str = ""

    @classmethod
    def from_plan_step(cls, s: "PlanStep") -> "PlanStepState":
        """Create a PlanStepState from a workflow step projection."""
        return cls(
            step_id=s.step_id,
            action_type=s.action_type,
            description=s.description,
            tool_name=s.tool_name,
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
            workflow_id=s.workflow_id,
            workflow_version=s.workflow_version,
            workflow_step_id=s.workflow_step_id,
            projection_kind=s.projection_kind,
        )

    def to_plan_step(self) -> "PlanStep":
        """Convert back to a step projection for validator / executor consumption."""
        from .planner import PlanStep

        return PlanStep(
            step_id=self.step_id,
            action_type=self.action_type,
            description=self.description,
            tool_name=self.tool_name,
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
            workflow_id=self.workflow_id,
            workflow_version=self.workflow_version,
            workflow_step_id=self.workflow_step_id,
            projection_kind=self.projection_kind,
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


class PlanSubState(BaseModel):
    """Plan execution private state — only meaningful inside plan_execution_graph."""

    steps: list[PlanStepState] = Field(default_factory=list)
    current_step_index: int = 0
    step_results: dict[str, Any] = Field(default_factory=dict)
    aborted: bool = False
    retry_counts: dict[str, int] = Field(default_factory=dict)


class ToolTrackingSubState(BaseModel):
    """Tool call tracking — shared across plan and react execution."""

    active_context: Literal["plan", "react"] | None = None
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
    - Sub-system state (react, plan, tool_tracking) is grouped into
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
    router_decision: RouterDecision | None = None

    # Sub-models (grouped private state)
    react: ReactSubState = Field(default_factory=ReactSubState)
    plan: PlanSubState = Field(default_factory=PlanSubState)
    tool_tracking: ToolTrackingSubState = Field(default_factory=ToolTrackingSubState)

    # Tool results
    tool_results: list[dict[str, Any]] = Field(default_factory=list)

    # Lightweight execution trace (for non-planning intents)
    execution_trace: list[str] = Field(default_factory=list)

    # Evidence & citations (summary form to avoid checkpoint bloat)
    citations: list[Citation] = Field(default_factory=list)
    matches: list[dict[str, Any]] = Field(default_factory=list)

    # HITL
    pending_confirmation: dict[str, Any] | None = None
    confirmation_decision: str | None = None

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
        for s in self.plan.steps:
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
            intent=self.router_decision.route if self.router_decision else "unknown",
            entry_text=self.entry_text,
            plan_steps=[s.model_dump(mode="json") for s in self.plan.steps],
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
        return AgentRunStatus.waiting_confirmation
    if state.router_decision is not None:
        return AgentRunStatus.running
    return AgentRunStatus.pending


# ---------------------------------------------------------------------------
# Conversion helpers: EntryResult <-> AgentEvent / AgentGraphState
# ---------------------------------------------------------------------------

def plan_steps_to_plan_created_events(
    plan_steps: list[dict[str, Any]], run_id: str, thread_id: str
) -> list[AgentEvent]:
    """Create a ``plan_created`` event from plan step dicts."""
    return [
        AgentEvent(
            run_id=run_id,
            thread_id=thread_id,
            type="plan_created",
            payload={"plan_steps": plan_steps},
        )
    ]


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
    return trace


_SSE_EVENT_TYPE_MAP: dict[str, str] = {
    "entry_started": "status",
    "clarification_required": "confirmation_required",
    "clarification_resumed": "status",
    "intent_classified": "intent",
    "plan_created": "plan_created",
    "plan_validated": "status",
    "step_started": "plan_step_started",
    "react_iteration": "react_iteration",
    "tool_called": "tool_called",
    "tool_result": "tool_result",
    "confirmation_required": "confirmation_required",
    "confirmation_resumed": "status",
    "draft_ready": "draft_ready",
    "answer_delta": "answer_delta",
    "answer_completed": "done",
    "step_completed": "plan_step_completed",
    "step_failed": "plan_step_failed",
    "replan_attempted": "plan_replan_attempt",
    "replan_completed": "plan_replanned",
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
