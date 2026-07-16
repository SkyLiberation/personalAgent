"""Verification-owned reports; runtime may consume but never author them."""

from __future__ import annotations

from uuid import uuid4

from typing import Literal
from pydantic import BaseModel, Field


def _short_id() -> str:
    return uuid4().hex[:12]


class CriterionResult(BaseModel):
    criterion_id: str
    status: Literal["passed", "failed", "inconclusive"]
    evidence_refs: tuple[str, ...] = ()
    reason_code: str = ""


class VerificationGap(BaseModel):
    gap_id: str = Field(default_factory=_short_id)
    gap_code: str
    affected_criteria: tuple[str, ...] = ()
    remediation_classes: tuple[str, ...] = ()
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    confidence: float = Field(default=1.0, ge=0, le=1)
    evidence_refs: tuple[str, ...] = ()
    verifier_id: str
    verifier_version: str
    decision_basis: str
    calibration_profile: str


class VerificationReport(BaseModel):
    report_id: str = Field(default_factory=_short_id)
    subject_id: str
    status: Literal["passed", "failed", "inconclusive"]
    checked_criteria: tuple[CriterionResult, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    unresolved_gaps: tuple[str, ...] = ()
    recommended_next_actions: tuple[str, ...] = ()
    gaps: tuple[VerificationGap, ...] = ()


class CompletionReport(BaseModel):
    report_id: str = Field(default_factory=_short_id)
    status: Literal["complete", "incomplete"]
    verified_goal_ids: tuple[str, ...] = ()
    unresolved_goal_ids: tuple[str, ...] = ()
    unmet_criterion_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


__all__ = ["CompletionReport", "CriterionResult", "VerificationGap", "VerificationReport"]
