from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from personal_agent.application.workspace.models import (
    AnswerVerificationAssessment,
    AnswerVerificationConflict,
    CoverageManifest,
    EvidenceCoverage,
    EvidenceSpan,
)
from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)


class WorkspaceAnswerVerifier(Protocol):
    name: str
    version: str

    def verify(
        self,
        *,
        question: str,
        candidate_answer: str,
        selected: list[EvidenceSpan],
        available: list[EvidenceSpan],
        manifests: list[CoverageManifest],
    ) -> AnswerVerificationAssessment:
        ...


class _AnswerVerificationDraft(BaseModel):
    verdict: Literal["passed", "needs_revision", "insufficient_evidence"]
    conclusion_status: Literal[
        "supported",
        "conflicted",
        "insufficient_evidence",
    ]
    evidence_coverage: EvidenceCoverage = "none"
    conflicts: list[AnswerVerificationConflict] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_sections: list[dict[str, str]] = Field(default_factory=list)
    feedback: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class LLMWorkspaceAnswerVerifier:
    name = "llm-workspace-answer-verifier"
    version = "v1"

    def __init__(self, model_client: StructuredModelClient) -> None:
        self._model_client = model_client

    def verify(
        self,
        *,
        question: str,
        candidate_answer: str,
        selected: list[EvidenceSpan],
        available: list[EvidenceSpan],
        manifests: list[CoverageManifest],
    ) -> AnswerVerificationAssessment:
        messages = [
            {
                "role": "system",
                "content": (
                    "Verify the candidate answer against the user's requested result and "
                    "the supplied evidence. This is semantic verification, not answer "
                    "generation: do not rewrite the answer, invent evidence, or decide "
                    "completion. Detect mutually incompatible facts even when each fact "
                    "has its own citation. Set conclusion_status=conflicted whenever the "
                    "selected evidence contains unresolved incompatible conclusions. "
                    "Return verdict=needs_revision when the candidate omits a conflict the "
                    "user asked to make explicit, contains an unsupported claim, or "
                    "misrepresents evidence. Return insufficient_evidence when the evidence "
                    "cannot decide. Return passed only when the candidate itself satisfies "
                    "the request. Every conflict must reference at least two supplied "
                    "selected evidence_span_ids and no other identifiers."
                ),
            },
            {
                "role": "user",
                "content": _verification_prompt(
                    question,
                    candidate_answer,
                    selected,
                    available,
                    manifests,
                ),
            },
        ]
        response = self._model_client.generate(StructuredModelRequest(
            operation="workspace_answer_semantic_verification",
            version=self.version,
            kind="structured",
            output_type=_AnswerVerificationDraft,
            temperature=0,
            max_tokens=1400,
            messages=messages,
            context_projection_ref=sealed_context_projection_ref(
                purpose="workspace_answer_semantic_verification",
                messages=messages,
            ),
            metadata={
                "selected_span_count": len(selected),
                "available_span_count": len(available),
            },
        ))
        return _admit_assessment(
            response.value,
            selected=selected,
            verifier_name=self.name,
            verifier_version=self.version,
        )


@dataclass(slots=True)
class FixtureWorkspaceAnswerVerifier:
    """Deterministic external-model substitute for unit and contract tests."""

    name: str = "fixture-workspace-answer-verifier"
    version: str = "v1"

    def verify(
        self,
        *,
        question: str,
        candidate_answer: str,
        selected: list[EvidenceSpan],
        available: list[EvidenceSpan],
        manifests: list[CoverageManifest],
    ) -> AnswerVerificationAssessment:
        if not selected:
            return unavailable_answer_verification("no selected evidence")
        conflicts = _fixture_conflicts(selected)
        coverage, missing = _fixture_coverage(selected, available, manifests)
        has_explicit_conflict = "冲突" in candidate_answer or "conflict" in candidate_answer.lower()
        if conflicts:
            return AnswerVerificationAssessment(
                verdict="passed" if has_explicit_conflict else "needs_revision",
                conclusion_status="conflicted",
                evidence_coverage=coverage,
                conflicts=conflicts,
                missing_sections=missing,
                feedback=(
                    "" if has_explicit_conflict
                    else "The candidate answer must explicitly identify the conflicting evidence."
                ),
                confidence=0.9,
                verifier_name=self.name,
                verifier_version=self.version,
            )
        return AnswerVerificationAssessment(
            verdict="passed",
            conclusion_status="supported",
            evidence_coverage=coverage,
            missing_sections=missing,
            confidence=0.8,
            verifier_name=self.name,
            verifier_version=self.version,
        )


def unavailable_answer_verification(reason: str) -> AnswerVerificationAssessment:
    return AnswerVerificationAssessment(
        verdict="insufficient_evidence",
        conclusion_status="insufficient_evidence",
        evidence_coverage="none",
        missing_sections=[{"reason": reason}],
        feedback="Answer verification could not establish that the candidate is supported.",
        verifier_name="unavailable-workspace-answer-verifier",
        verifier_version="v1",
    )


def _admit_assessment(
    draft: _AnswerVerificationDraft,
    *,
    selected: list[EvidenceSpan],
    verifier_name: str,
    verifier_version: str,
) -> AnswerVerificationAssessment:
    allowed_ids = {item.evidence_span_id for item in selected}
    referenced_ids = {
        span_id
        for conflict in draft.conflicts
        for span_id in conflict.evidence_span_ids
    }
    if referenced_ids - allowed_ids:
        raise ValueError("answer verifier referenced evidence outside the selected set")
    if draft.conclusion_status == "conflicted" and not draft.conflicts:
        raise ValueError("conflicted answer verification requires conflict evidence")
    if draft.conflicts and draft.conclusion_status != "conflicted":
        raise ValueError("conflict evidence requires conclusion_status=conflicted")
    return AnswerVerificationAssessment(
        **draft.model_dump(mode="python"),
        verifier_name=verifier_name,
        verifier_version=verifier_version,
    )


def _verification_prompt(
    question: str,
    candidate_answer: str,
    selected: list[EvidenceSpan],
    available: list[EvidenceSpan],
    manifests: list[CoverageManifest],
) -> str:
    selected_lines = "\n".join(
        f"[{item.evidence_span_id}] {item.text_span}"
        for item in selected
    )
    available_lines = "\n".join(
        f"[{item.evidence_span_id}] {item.text_span}"
        for item in available[:30]
    )
    manifest_lines = "\n".join(
        manifest.model_dump_json()
        for manifest in manifests
    )
    return (
        f"Question:\n{question}\n\nCandidate answer:\n{candidate_answer}\n\n"
        f"Selected evidence:\n{selected_lines}\n\nAvailable evidence:\n"
        f"{available_lines}\n\nCoverage manifests:\n{manifest_lines}"
    )


def _fixture_conflicts(
    selected: list[EvidenceSpan],
) -> list[AnswerVerificationConflict]:
    for index, left in enumerate(selected):
        left_dates = set(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", left.text_span))
        for right in selected[index + 1:]:
            right_dates = set(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", right.text_span))
            negated = "不是" in left.text_span or "不是" in right.text_span
            incompatible_dates = bool(left_dates and right_dates and left_dates != right_dates)
            if negated or incompatible_dates:
                return [AnswerVerificationConflict(
                    evidence_span_ids=[
                        left.evidence_span_id,
                        right.evidence_span_id,
                    ],
                    description="selected evidence contains incompatible conclusions",
                )]
    return []


def _fixture_coverage(
    selected: list[EvidenceSpan],
    available: list[EvidenceSpan],
    manifests: list[CoverageManifest],
) -> tuple[EvidenceCoverage, list[dict[str, str]]]:
    missing: list[dict[str, str]] = []
    for manifest in manifests:
        for region in manifest.expected_regions:
            if (
                region.parse_status in {"omitted", "partial", "failed"}
                or region.semantic_status in {"omitted", "partial", "failed"}
            ):
                missing.append({
                    "locator": region.locator,
                    "reason": region.reason or "coverage manifest reports unavailable region",
                })
    if any(manifest.omitted_region_count for manifest in manifests):
        return "partial", missing
    if len(selected) >= len(available):
        return "complete", []
    return ("sparse" if len(selected) == 1 and len(available) > 3 else "partial"), missing


__all__ = [
    "FixtureWorkspaceAnswerVerifier",
    "LLMWorkspaceAnswerVerifier",
    "WorkspaceAnswerVerifier",
    "unavailable_answer_verification",
]
