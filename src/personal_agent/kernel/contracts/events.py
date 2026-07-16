"""Orchestration event contract (pure data).

``AgentEvent`` is the serialisable event emitted during a graph run and persisted
by the infra event store. It lives in the kernel so the infra layer can read/write
it without importing the orchestration package. Richer state models
(``RunCheckpoint`` etc.) stay in the orchestration layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from personal_agent.kernel.models import local_now

AgentEventType = str


class AgentEvent(BaseModel):
    """A structured, serialisable event emitted during a graph run."""

    event_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    run_id: str | None = None
    thread_id: str | None = None
    type: AgentEventType
    timestamp: datetime = Field(default_factory=local_now)
    payload: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AgentEventType",
    "AgentEvent",
]
