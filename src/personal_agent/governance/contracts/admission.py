"""Stage-local admission decision and monotonicity proof contracts."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class GovernanceSnapshotRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_revision: int = Field(ge=1)
    runtime_revision: int = Field(ge=0)
    policy_revision: str
    authority_revision: int = Field(default=1, ge=1)


class MonotonicityProof(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operations_expanded: bool = False
    resources_expanded: bool = False
    budgets_expanded: bool = False
    provider_bound_early: bool = False


class StageAdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    admission_id: str = Field(default_factory=lambda: uuid4().hex)
    stage: Literal["control_decision"] = "control_decision"
    proposal_ref: str
    verdict: Literal["accepted", "denied", "interaction_required"]
    effective_constraint_refs: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    snapshot: GovernanceSnapshotRef
    monotonicity: MonotonicityProof = Field(default_factory=MonotonicityProof)


__all__ = ["GovernanceSnapshotRef", "MonotonicityProof", "StageAdmissionDecision"]
