"""Observation-to-evidence admission contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_ref: str = Field(default_factory=lambda: uuid4().hex[:12])
    observation_ref: str
    admitted_purpose: str
    criterion_scope: tuple[str, ...]
    trust: Literal["trusted", "scoped", "external", "untrusted"]
    content_hash: str
    admitted_at: datetime
    freshness_expires_at: datetime | None = None


class EvidenceAdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    admission_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    observation_ref: str
    verdict: Literal["accepted", "rejected"]
    evidence: EvidenceRef | None = None
    reason_codes: tuple[str, ...] = ()
    policy_revision: str = "evidence-policy:v1"


__all__ = ["EvidenceAdmissionDecision", "EvidenceRef"]

