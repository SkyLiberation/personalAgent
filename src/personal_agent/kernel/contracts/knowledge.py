"""Evidence and memory-admission contracts for knowledge-quality runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from personal_agent.kernel.evidence import EvidenceItem


class SourceSnapshot(BaseModel):
    source_id: str
    locator: str
    retrieved_at: datetime
    freshness_at: datetime | None = None
    content_hash: str
    trust_profile: str


class ClaimSupport(BaseModel):
    claim_id: str
    evidence_ids: tuple[str, ...]
    relation: Literal["support", "contradict", "context"]
    confidence: float = Field(ge=0, le=1)


class EvidencePack(BaseModel):
    pack_id: str
    snapshots: tuple[SourceSnapshot, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    claim_support: tuple[ClaimSupport, ...] = ()
    unresolved_contradictions: tuple[str, ...] = ()
    freshness_gaps: tuple[str, ...] = ()


class MemoryAdmissionDecision(BaseModel):
    candidate_id: str
    decision: Literal["accept", "reject", "supersede", "merge"]
    provenance_refs: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


__all__ = [
    "ClaimSupport",
    "EvidenceItem",
    "EvidencePack",
    "MemoryAdmissionDecision",
    "SourceSnapshot",
]
