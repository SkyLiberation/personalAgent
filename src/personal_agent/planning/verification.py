"""Goal and task completion verification independent from action success."""

from __future__ import annotations

from personal_agent.kernel.contracts.agentic import ExecutionLedger, ExecutionLedgerItem, TaskSpec
from personal_agent.kernel.contracts.executive import (
    CompletionClaim,
    CompletionReport,
    CriterionResult,
    VerificationReport,
)


class GoalVerifier:
    def verify(
        self,
        task: TaskSpec,
        goal: ExecutionLedgerItem,
        *,
        answer: str | None,
        citation_count: int,
        tool_results: tuple[dict, ...],
    ) -> VerificationReport:
        criteria_by_id = {item.criterion_id: item for item in task.success_criteria}
        results: list[CriterionResult] = []
        evidence_refs = tuple(
            str(item.get("artifact_id") or item.get("note_id") or item.get("agent_run_id") or "")
            for item in tool_results
            if isinstance(item, dict)
        )
        evidence_refs = tuple(item for item in evidence_refs if item)
        for criterion_id in goal.success_criterion_ids:
            criterion = criteria_by_id[criterion_id]
            if criterion.acceptance_contract == "MutationReceipt":
                passed = any(_looks_like_receipt(item) for item in tool_results)
                status = "passed" if passed else "inconclusive"
                reason = "mutation_receipt_present" if passed else "mutation_receipt_missing"
            elif criterion.evidence_policy.citation_required:
                passed = bool(answer and answer.strip()) and citation_count >= (criterion.evidence_policy.minimum_source_count or 1)
                status = "passed" if passed else "inconclusive"
                reason = "evidence_covered" if passed else "evidence_or_citation_missing"
            else:
                passed = bool(answer and answer.strip()) or bool(tool_results)
                status = "passed" if passed else "inconclusive"
                reason = "result_present" if passed else "result_missing"
            results.append(CriterionResult(
                criterion_id=criterion_id,
                status=status,
                evidence_refs=evidence_refs,
                reason_code=reason,
            ))
        required = [criteria_by_id[item] for item in goal.success_criterion_ids if criteria_by_id[item].required]
        required_results = [item for item in results if item.criterion_id in {c.criterion_id for c in required}]
        status = "passed" if required_results and all(item.status == "passed" for item in required_results) else "inconclusive"
        gaps = tuple(item.reason_code for item in required_results if item.status != "passed")
        return VerificationReport(
            subject_id=goal.goal_id,
            status=status,
            checked_criteria=tuple(results),
            evidence_refs=evidence_refs,
            unresolved_gaps=gaps,
            recommended_next_actions=("acquire_more_evidence",) if gaps else (),
        )


class CompletionVerifier:
    def verify(
        self,
        task: TaskSpec,
        ledger: ExecutionLedger,
        claim: CompletionClaim | None,
        *,
        pending_confirmation: bool,
    ) -> CompletionReport:
        verified = tuple(item.goal_id for item in ledger.items if item.status == "verified")
        unresolved = tuple(
            item.goal_id for item in ledger.items
            if item.status not in {"verified", "degraded", "abandoned"}
        )
        checked = {
            result.criterion_id
            for item in ledger.items
            if item.verification is not None
            for result in item.verification.checked_criteria
            if result.status == "passed"
        }
        required = {item.criterion_id for item in task.success_criteria if item.required}
        unmet = tuple(sorted(required - checked))
        reasons = []
        if unresolved:
            reasons.append("goals_unresolved")
        if unmet:
            reasons.append("criteria_unmet")
        if pending_confirmation:
            reasons.append("approval_pending")
        if claim is None:
            reasons.append("completion_claim_missing")
        status = "complete" if not reasons else "incomplete"
        return CompletionReport(
            status=status,
            verified_goal_ids=verified,
            unresolved_goal_ids=unresolved,
            unmet_criterion_ids=unmet,
            reason_codes=tuple(reasons),
        )


def _looks_like_receipt(item: dict) -> bool:
    if not isinstance(item, dict) or not item.get("ok", True):
        return False
    keys = set(item)
    if keys.intersection({
        "note_id", "note", "capture_result", "mutation_receipt", "subscription_id", "run_id", "updated",
    }):
        return True
    data = item.get("data")
    return isinstance(data, dict) and _looks_like_receipt(data)


__all__ = ["CompletionVerifier", "GoalVerifier"]
