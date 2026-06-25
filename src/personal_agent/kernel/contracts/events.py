"""Orchestration event contract (pure data).

``AgentEvent`` is the serialisable event emitted during a graph run and persisted
by the infra event store. It lives in the kernel so the infra layer can read/write
it without importing the orchestration package. Richer state models
(``AgentGraphState`` etc.) stay in the orchestration layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from personal_agent.kernel.models import local_now

AgentEventType = Literal[
    "entry_started",
    "clarification_required",
    "clarification_resumed",
    "intent_classified",
    "steps_projected",
    "steps_validated",
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
    "workflow_forked",
    "workflow_replayed",
    "artifact_written",
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


__all__ = [
    "AgentEventType",
    "AgentEvent",
]
