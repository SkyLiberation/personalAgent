"""Append-only records for model proposals and admission outcomes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.governance.contracts.admission import StageAdmissionDecision
from personal_agent.runtime.contracts.control import ControlProposal


class DecisionAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: str = Field(default_factory=lambda: uuid4().hex)
    run_id: str = Field(min_length=1)
    turn_ref: str = Field(min_length=1)
    proposal: ControlProposal
    admission: StageAdmissionDecision
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__ = ["DecisionAuditRecord"]
