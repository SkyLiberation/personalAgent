"""Application-owned durable worker queue port and task contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

WorkerTaskStatus = Literal["queued", "running", "completed", "failed", "dead"]


class WorkerTask(BaseModel):
    task_id: str
    queue: str
    task_type: str
    status: WorkerTaskStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    priority: int = 0
    attempts: int = 0
    max_attempts: int = 1
    leased_by: str | None = None
    leased_until: datetime | None = None
    due_at: datetime
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkerQueuePort(Protocol):
    def enqueue(
        self,
        *,
        queue: str,
        task_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        priority: int = 0,
        max_attempts: int = 1,
        due_at: datetime | None = None,
    ) -> WorkerTask: ...


__all__ = ["WorkerQueuePort", "WorkerTask", "WorkerTaskStatus"]
