"""Goal and task completion verification independent from action success."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from personal_agent.runtime.contracts.task import (
    TaskRuntimeProjection,
    MaterializedGoalView,
    TaskContract,
    materialize_goals,
)
from personal_agent.runtime.contracts.control import CompletionClaim
from personal_agent.governance.contracts.evidence import EvidenceRef
from personal_agent.verification.contracts.reports import (
    CompletionReport,
    CriterionResult,
    VerificationReport,
    VerificationGap,
)

if TYPE_CHECKING:
    from personal_agent.capabilities.contracts.model import StructuredModelClient

logger = logging.getLogger(__name__)


class _CriterionJudgment(BaseModel):
    criterion_id: str
    status: Literal["passed", "failed", "inconclusive"]
    reason_code: str


class _SemanticVerification(BaseModel):
    judgments: list[_CriterionJudgment]


class GoalVerifier:
    def __init__(self, model_client: "StructuredModelClient | None" = None) -> None:
        self._model_client = model_client

    @property
    def semantic_enabled(self) -> bool:
        return self._model_client is not None

    def verify(
        self,
        task: TaskContract,
        goal: MaterializedGoalView,
        *,
        answer: str | None,
        citation_count: int,
        tool_results: tuple[dict, ...],
        evidence: tuple[EvidenceRef, ...] = (),
        model_context: dict[str, object] | None = None,
    ) -> VerificationReport:
        criteria_by_id = {item.criterion_id: item for item in task.success_criteria}
        results: list[CriterionResult] = []
        result_refs = tuple(
            str(item.get("artifact_id") or item.get("note_id") or item.get("agent_run_id") or "")
            for item in tool_results
            if isinstance(item, dict)
        )
        result_refs = tuple(item for item in result_refs if item)
        evidence_refs = tuple(dict.fromkeys(item.evidence_ref for item in evidence))
        source_count = len(evidence_refs)
        for criterion_id in goal.success_criterion_ids:
            criterion = criteria_by_id[criterion_id]
            if criterion.acceptance_contract == "MutationReceipt":
                passed = any(_looks_like_receipt(item) for item in tool_results)
                status = "passed" if passed else "inconclusive"
                reason = "mutation_receipt_present" if passed else "mutation_receipt_missing"
                criterion_evidence_refs = result_refs if passed else ()
            elif criterion.evidence_policy.citation_required:
                passed = bool(answer and answer.strip()) and (
                    citation_count + source_count >= (criterion.evidence_policy.minimum_source_count or 1)
                )
                status = "passed" if passed else "inconclusive"
                reason = "evidence_covered" if passed else "evidence_or_citation_missing"
                criterion_evidence_refs = evidence_refs
            else:
                passed = bool(answer and answer.strip()) or bool(tool_results)
                status = "passed" if passed else "inconclusive"
                reason = "result_present" if passed else "result_missing"
                criterion_evidence_refs = evidence_refs
            results.append(CriterionResult(
                criterion_id=criterion_id,
                status=status,
                evidence_refs=criterion_evidence_refs,
                reason_code=reason,
            ))
        semantic = self._semantic_judgments(
            task,
            goal,
            model_context=model_context,
        )
        if semantic:
            acceptance_by_id = {
                item.criterion_id: item.acceptance_contract for item in criteria_by_id.values()
            }
            results = [
                item.model_copy(update={
                    "status": semantic[item.criterion_id].status,
                    "reason_code": semantic[item.criterion_id].reason_code,
                })
                if (
                    item.status == "passed"
                    and item.criterion_id in semantic
                    and acceptance_by_id[item.criterion_id] != "MutationReceipt"
                    and semantic[item.criterion_id].status in {"passed", "failed", "inconclusive"}
                ) else item
                for item in results
            ]
        required = [criteria_by_id[item] for item in goal.success_criterion_ids if criteria_by_id[item].required]
        required_results = [item for item in results if item.criterion_id in {c.criterion_id for c in required}]
        status = "passed" if required_results and all(item.status == "passed" for item in required_results) else "inconclusive"
        gaps = tuple(item.reason_code for item in required_results if item.status != "passed")
        gap_contracts = tuple(
            VerificationGap(
                gap_code=item.reason_code,
                affected_criteria=(item.criterion_id,),
                remediation_classes=(
                    "acquire_fresh_evidence" if "evidence" in item.reason_code
                    else "verify_again",
                ),
                severity="high" if item.reason_code == "mutation_receipt_missing" else "medium",
                confidence=1.0,
                evidence_refs=item.evidence_refs,
                verifier_id="goal-composite",
                verifier_version="v2",
                decision_basis="deterministic contract checks plus optional semantic downgrade",
                calibration_profile="deterministic-v1",
            )
            for item in required_results if item.status != "passed"
        )
        return VerificationReport(
            subject_id=goal.goal_id,
            status=status,
            checked_criteria=tuple(results),
            evidence_refs=tuple(dict.fromkeys((
                *evidence_refs,
                *(ref for item in results for ref in item.evidence_refs),
            ))),
            unresolved_gaps=gaps,
            recommended_next_actions=("acquire_more_evidence",) if gaps else (),
            gaps=gap_contracts,
        )

    def _semantic_judgments(
        self,
        task: TaskContract,
        goal: MaterializedGoalView,
        *,
        model_context: dict[str, object] | None,
    ) -> dict[str, _CriterionJudgment]:
        if self._model_client is None or model_context is None:
            return {}
        try:
            from personal_agent.capabilities.contracts.model import StructuredModelRequest

            response = self._model_client.generate(StructuredModelRequest(
                operation="goal_semantic_verification",
                version="v1",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Judge whether the supplied answer and goal-scoped evidence support each success criterion. "
                            "Do not infer missing evidence. Return passed, failed, or inconclusive for every criterion. "
                            "Return only the structured object and no chain-of-thought."
                        ),
                    },
                    {"role": "user", "content": json.dumps({
                        "model_context": model_context,
                    }, ensure_ascii=False)},
                ],
                output_type=_SemanticVerification,
                context_projection_ref=str(model_context.get("projection_id") or ""),
                temperature=0,
                max_tokens=500,
                kind="structured",
                metadata={"task_id": task.task_id, "goal_id": goal.goal_id},
            ))
            return {item.criterion_id: item for item in response.value.judgments}
        except Exception:
            logger.exception("Semantic goal verification failed; retaining deterministic evidence checks")
            return {}


class CompletionVerifier:
    def verify(
        self,
        task: TaskContract,
        ledger: TaskRuntimeProjection,
        claim: CompletionClaim | None,
        *,
        verification_reports: dict[str, VerificationReport],
        pending_confirmation: bool,
    ) -> CompletionReport:
        goals = materialize_goals(task, ledger)
        verified = tuple(item.goal_id for item in goals if item.status == "verified")
        unresolved = tuple(
            item.goal_id for item in goals
            if item.status not in {"verified", "degraded", "abandoned"}
        )
        checked = {
            result.criterion_id
            for goal_id in (item.goal_id for item in goals)
            for result in verification_reports.get(
                goal_id,
                VerificationReport(subject_id=goal_id, status="inconclusive"),
            ).checked_criteria
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
