"""Invocation journal contracts; the journal owns remote-execution truth."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


InvocationJournalStatus = Literal[
    "reserved", "dispatched", "acknowledged", "observed", "outcome_unknown",
    "reconciled", "cancelled",
]


class InvocationJournalEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invocation_id: str
    grant_ref: str
    execution_command_digest: str = Field(min_length=1)
    idempotency_key: str
    status: InvocationJournalStatus = "reserved"
    provider_ref: str
    remote_receipt_ref: str | None = None
    observation_ref: str | None = None
    reconciliation_required: bool = False
    updated_at: datetime


class InvocationJournalProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(default=0, ge=0)
    entries: dict[str, InvocationJournalEntry] = Field(default_factory=dict)
    outbox: dict[str, "InvocationOutboxEntry"] = Field(default_factory=dict)


class InvocationOutboxEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invocation_id: str
    grant_ref: str
    execution_command_digest: str = Field(min_length=1)
    provider_ref: str
    idempotency_key: str
    payload_ref: str
    status: Literal["prepared", "dispatched", "cancelled"] = "prepared"
    prepared_at: datetime


class DispatchCommit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    commit_id: str = Field(default_factory=lambda: uuid4().hex)
    invocation_id: str
    expected_journal_revision: int
    journal_revision: int
    outbox_ref: str
    dispatch_required: bool
    recovered_receipt_ref: str | None = None


__all__ = [
    "DispatchCommit", "InvocationJournalEntry", "InvocationJournalProjection",
    "InvocationJournalStatus", "InvocationOutboxEntry",
]
