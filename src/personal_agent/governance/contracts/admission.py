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
    semantics_modified: bool = False


RevisionScope = Literal[
    "format_only", "grounding_only", "parameter_completion",
    "semantic_revision", "upstream_replan",
]
AdmissionDisposition = Literal[
    "revise_model", "request_external_input", "request_capability_acquisition",
    "await_environment_change", "terminal",
]


class DecisionFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    feedback_id: str = Field(default_factory=lambda: uuid4().hex)
    stage: Literal["task_analysis", "planning", "context", "control", "route", "output"]
    rejected_proposal_ref: str
    reason_codes: tuple[str, ...]
    violated_constraint_refs: tuple[str, ...] = ()
    rejected_field_refs: tuple[str, ...] = ()
    mutable_field_refs: tuple[str, ...] = ()
    immutable_field_refs: tuple[str, ...] = ()
    required_repairs: tuple[str, ...] = ()
    revision_scope: RevisionScope
    disposition: AdmissionDisposition
    revision_budget_remaining: int = Field(ge=0)
    governance_snapshot_ref: str
    rejection_equivalence_hash: str
    candidate_summary_refs: tuple[str, ...] = ()


class StageAdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    admission_id: str = Field(default_factory=lambda: uuid4().hex)
    stage: Literal["task_analysis", "control_decision", "output"] = "control_decision"
    proposal_ref: str
    verdict: Literal["accepted", "not_accepted"]
    disposition: AdmissionDisposition | None = None
    effective_constraint_refs: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    snapshot: GovernanceSnapshotRef
    monotonicity: MonotonicityProof = Field(default_factory=MonotonicityProof)
    feedback: DecisionFeedback | None = None


__all__ = [
    "AdmissionDisposition", "DecisionFeedback", "GovernanceSnapshotRef",
    "MonotonicityProof", "RevisionScope", "StageAdmissionDecision",
]
