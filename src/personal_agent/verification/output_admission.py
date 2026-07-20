"""Admission for model-authored final business answers."""

from __future__ import annotations

from personal_agent.governance.contracts.admission import (
    DecisionFeedback,
    GovernanceSnapshotRef,
    StageAdmissionDecision,
)
from personal_agent.governance.guardrails import get_content_guard
from personal_agent.runtime.contracts.control import FinalAnswerProposal, canonical_digest
from personal_agent.runtime.contracts.task import TaskContract
from personal_agent.verification.contracts.reports import CompletionReport


class FinalAnswerAdmission:
    def admit(
        self,
        task: TaskContract,
        runtime_revision: int,
        completion: CompletionReport,
        proposal: FinalAnswerProposal,
        *,
        required_report_refs: tuple[str, ...],
        allowed_citation_refs: tuple[str, ...],
    ) -> StageAdmissionDecision:
        reasons: list[str] = []
        if proposal.task_ref != task.task_id or proposal.task_revision != task.revision:
            reasons.append("output_task_binding_mismatch")
        if completion.status != "complete":
            reasons.append("completion_not_verified")
        if set(proposal.verified_goal_refs) != set(completion.verified_goal_ids):
            reasons.append("verified_goal_binding_mismatch")
        if set(proposal.verification_report_refs) != set(required_report_refs):
            reasons.append("verification_report_binding_mismatch")
        if not set(proposal.citation_refs).issubset(allowed_citation_refs):
            reasons.append("citation_binding_failed")
        if get_content_guard().check_output(proposal.answer).changed:
            reasons.append("output_guard_denied")
        snapshot = GovernanceSnapshotRef(
            task_revision=task.revision,
            runtime_revision=runtime_revision,
            policy_revision="final-answer-admission:v1",
        )
        if not reasons:
            return StageAdmissionDecision(
                stage="output",
                proposal_ref=proposal.proposal_id,
                verdict="accepted",
                effective_constraint_refs=(
                    f"task:{task.task_id}:revision:{task.revision}",
                    f"completion:{completion.report_id}",
                ),
                reason_codes=("verified_output_binding_passed",),
                snapshot=snapshot,
            )
        feedback = DecisionFeedback(
            stage="output",
            rejected_proposal_ref=proposal.proposal_id,
            reason_codes=tuple(reasons),
            violated_constraint_refs=(f"completion:{completion.report_id}",),
            rejected_field_refs=("answer", "citation_refs"),
            mutable_field_refs=("answer", "citation_refs"),
            immutable_field_refs=(
                "task_ref", "task_revision", "verified_goal_refs",
                "verification_report_refs",
            ),
            required_repairs=tuple(reasons),
            revision_scope="semantic_revision",
            disposition="revise_model" if proposal.revision_attempt < 1 else "terminal",
            revision_budget_remaining=max(1 - proposal.revision_attempt, 0),
            governance_snapshot_ref=canonical_digest(snapshot),
            rejection_equivalence_hash=canonical_digest({
                "reasons": reasons,
                "answer": proposal.answer,
                "citations": proposal.citation_refs,
            }),
        )
        return StageAdmissionDecision(
            stage="output",
            proposal_ref=proposal.proposal_id,
            verdict="not_accepted",
            disposition=feedback.disposition,
            effective_constraint_refs=(f"completion:{completion.report_id}",),
            reason_codes=tuple(reasons),
            snapshot=snapshot,
            feedback=feedback,
        )


__all__ = ["FinalAnswerAdmission"]
