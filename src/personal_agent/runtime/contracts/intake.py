"""Durable task-intake state before a TaskContract exists."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskIntakeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intake_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    status: Literal["analyzing", "awaiting_input", "compiled", "cancelled"] = "analyzing"
    source_message_refs: tuple[str, ...] = ()
    original_input_ref: str
    current_proposal_ref: str | None = None
    proposal_revision: int = Field(default=0, ge=0)
    missing_requirement_ids: tuple[str, ...] = ()
    interaction_request_ref: str | None = None
    compiled_task_ref: str | None = None
    policy_revision: str = "v1"

    @model_validator(mode="after")
    def _state_is_complete(self) -> "TaskIntakeState":
        if self.status == "compiled" and self.compiled_task_ref is None:
            raise ValueError("compiled intake requires compiled_task_ref")
        if self.status == "awaiting_input" and self.interaction_request_ref is None:
            raise ValueError("awaiting_input intake requires interaction_request_ref")
        if self.status in {"analyzing", "cancelled"} and self.compiled_task_ref is not None:
            raise ValueError("uncompiled intake cannot reference a compiled task")
        return self


__all__ = ["TaskIntakeState"]

