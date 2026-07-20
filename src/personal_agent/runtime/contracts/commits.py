"""Canonical commit records for task compilation and accepted control commands."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class TaskCompilationCommit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    commit_id: str = Field(default_factory=lambda: uuid4().hex)
    intake_ref: str
    expected_proposal_revision: int = Field(ge=0)
    task_ref: str
    task_revision: int = Field(ge=1)
    initial_runtime_ref: str
    runtime_revision: int = Field(ge=1)
    event_cursor: int = Field(ge=0)
    committed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ControlCommit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    commit_id: str = Field(default_factory=lambda: uuid4().hex)
    turn_ref: str
    proposal_ref: str
    admission_ref: str
    accepted_intent_ref: str
    command_ref: str
    authorization_digest: str
    execution_command_digest: str
    expected_task_revision: int = Field(ge=1)
    expected_event_cursor: int = Field(ge=0)
    committed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__ = ["ControlCommit", "TaskCompilationCommit"]
