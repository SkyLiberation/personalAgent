"""Conservative lazy-direct admission independent from answer generation."""

from __future__ import annotations

from pydantic import BaseModel

from personal_agent.runtime.contracts.task import SuccessCriterion


class DirectCandidate(BaseModel):
    goal: str
    criteria: tuple[SuccessCriterion, ...]
    answer: str
    requires_external_resource: bool = False
    unresolved_gaps: tuple[str, ...] = ()
    freshness_required: bool = False
    high_risk_domain: bool = False


class DirectAdmission:
    def admit(
        self,
        candidate: DirectCandidate,
        *,
        required_criteria: tuple[SuccessCriterion, ...],
    ) -> bool:
        if (
            candidate.requires_external_resource
            or candidate.unresolved_gaps
            or candidate.freshness_required
            or candidate.high_risk_domain
        ):
            return False
        candidate_by_id = {item.criterion_id: item for item in candidate.criteria}
        for required in required_criteria:
            supplied = candidate_by_id.get(required.criterion_id)
            if supplied is None:
                return False
            if supplied.description != required.description:
                return False
            if supplied.source != required.source or supplied.mutability != required.mutability:
                return False
        return bool(candidate.answer.strip())


__all__ = ["DirectAdmission", "DirectCandidate"]
