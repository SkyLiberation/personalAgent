"""Immutable technical-execution and business-effectiveness outcome facts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class CapabilityExecutionOutcomeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str
    goal_id: str
    action_ref: str
    invocation_ref: str
    grant_ref: str
    capability_ref: str
    outcome: Literal[
        "succeeded", "failed", "provider_unavailable", "policy_denied",
        "cancelled", "outcome_unknown",
    ]
    latency_ms: float = Field(default=0.0, ge=0)
    cost: float = Field(default=0.0, ge=0)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CapabilityEffectivenessEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str
    goal_id: str
    capability_ref: str
    execution_outcome_ref: str
    verification_ref: str
    verdict: Literal["effective", "ineffective", "inconclusive"]
    criterion_ids: tuple[str, ...]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__ = ["CapabilityEffectivenessEvent", "CapabilityExecutionOutcomeEvent"]
