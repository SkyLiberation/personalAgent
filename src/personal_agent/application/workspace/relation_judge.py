from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from personal_agent.application.workspace.models import Claim
from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)


RelationVerdictType = Literal[
    "duplicate",
    "supplement",
    "supersede",
    "conflict",
    "unrelated",
    "uncertain",
]


class ClaimRelationAdjudication(BaseModel):
    relation_type: RelationVerdictType = "uncertain"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    requires_decision: bool = True


@dataclass(frozen=True, slots=True)
class ClaimRelationCandidate:
    relation_type: str
    confidence: float
    reason: str
    source: str = "deterministic_candidate"


class ClaimRelationJudge(Protocol):
    name: str

    def judge(
        self,
        candidate: ClaimRelationCandidate,
        new_claim: Claim,
        existing_claim: Claim,
    ) -> ClaimRelationAdjudication:
        ...


class LLMClaimRelationJudge:
    """Semantic relation judge for Claim pairs.

    Deterministic code may propose candidates, but this judge owns the semantic
    uncertainty boundary for conflicts, supersession and non-obvious equivalence.
    """

    name = "llm-claim-relation-v1"

    def __init__(self, model_client: StructuredModelClient) -> None:
        self._model_client = model_client

    def judge(
        self,
        candidate: ClaimRelationCandidate,
        new_claim: Claim,
        existing_claim: Claim,
    ) -> ClaimRelationAdjudication:
        messages = [
            {
                "role": "system",
                "content": (
                    "You adjudicate semantic relationships between two knowledge claims. "
                    "Use only the two claims and their metadata. Return conflict only when "
                    "both claims are about the same subject/scope and cannot both be true. "
                    "Return uncertain when the relation depends on missing context."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Candidate relation:\n"
                    f"- type: {candidate.relation_type}\n"
                    f"- confidence: {candidate.confidence:.2f}\n"
                    f"- reason: {candidate.reason}\n\n"
                    "New claim:\n"
                    f"- statement: {new_claim.statement}\n"
                    f"- type: {new_claim.claim_type}\n"
                    f"- scope: {new_claim.scope or '(none)'}\n"
                    f"- valid_time: {new_claim.valid_time or '(none)'}\n\n"
                    "Existing claim:\n"
                    f"- statement: {existing_claim.statement}\n"
                    f"- type: {existing_claim.claim_type}\n"
                    f"- scope: {existing_claim.scope or '(none)'}\n"
                    f"- valid_time: {existing_claim.valid_time or '(none)'}"
                ),
            },
        ]
        response = self._model_client.generate(StructuredModelRequest(
            operation="workspace_claim_relation_judge",
            version="v1",
            kind="structured",
            output_type=ClaimRelationAdjudication,
            temperature=0,
            max_tokens=500,
            messages=messages,
            context_projection_ref=sealed_context_projection_ref(
                purpose="workspace_claim_relation_judge", messages=messages,
            ),
            metadata={
                "candidate_relation_type": candidate.relation_type,
                "new_claim_id": new_claim.claim_id,
                "existing_claim_id": existing_claim.claim_id,
            },
        ))
        return response.value
