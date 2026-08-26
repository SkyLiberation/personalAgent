"""Semantic verification contracts shared by the verifier tool and admission.

The tool that produces a receipt lives in ``personal_agent.tools``; the
admission that consumes one lives in ``personal_agent.application``. The
explicit package DAG forbids ``application -> tools``, so the receipt type has
to live in a package both may depend on. Keeping it here is what lets admission
parse a receipt into its declared type instead of reading an untyped ``dict``:
a renamed field then fails loudly at the boundary rather than degrading into a
silent ``None`` that no caller can distinguish from a real mismatch.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VerificationVerdict = Literal["passed", "needs_revision", "insufficient_evidence"]


class VerificationCriterionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str
    status: Literal["satisfied", "not_satisfied", "insufficient_evidence"]
    feedback: str = ""


class SemanticVerificationReport(BaseModel):
    """The model-authored per-criterion judgments.

    This is the verifier's ``output_type``, so the model owns all of it. It
    deliberately carries no aggregate verdict, identity, or digest: anything a
    later admission decision can derive from these judgments is computed by the
    tool, never proposed redundantly by the model.
    """

    model_config = ConfigDict(extra="forbid")

    criterion_results: tuple[VerificationCriterionResult, ...] = Field(min_length=1)
    revision_feedback: str = ""


class SemanticVerificationReceipt(SemanticVerificationReport):
    """A report plus the tool-computed facts an admission may rely on.

    ``receipt_id`` is derived from ``draft_digest``, so referencing an id is
    equivalent to referencing an exact draft and the model cannot fabricate a
    reference to text that was never verified.

    ``success_criteria`` is the preimage of ``criteria_digest``. Carrying it is
    what makes a criteria-drift rejection repairable: the caller is told the
    exact criteria to re-verify against instead of being asked to reproduce
    bytes it no longer has. It also gives the digest an auditable preimage in the
    journal rather than an unverifiable hash.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: VerificationVerdict
    receipt_id: str = Field(pattern=r"^svr_[0-9a-f]{20}$")
    verified_draft: str = Field(min_length=1, max_length=20_000)
    draft_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    success_criteria: tuple[str, ...] = Field(min_length=1)
    criteria_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


__all__ = [
    "SemanticVerificationReceipt",
    "SemanticVerificationReport",
    "VerificationCriterionResult",
    "VerificationVerdict",
]
