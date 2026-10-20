"""Project canonical knowledge through the Conversation read Port."""

from __future__ import annotations

from personal_agent.application.knowledge.service import KnowledgeService

from .models import (
    PersonalKnowledgeCandidate,
    PersonalKnowledgeEvidenceCitation,
    PersonalKnowledgeEvidenceSnapshot,
)


class ConversationKnowledgeReadAdapter:
    def __init__(self, knowledge_service: KnowledgeService) -> None:
        self._knowledge_service = knowledge_service

    def list_personal_knowledge(
        self,
        *,
        owner_id: str,
        user_id: str,
        limit: int,
    ) -> tuple[PersonalKnowledgeCandidate, ...]:
        items = self._knowledge_service.store.list_knowledge_items(
            owner_id,
            limit=500,
        )
        visible = tuple(
            PersonalKnowledgeCandidate(
                knowledge_item_id=item.knowledge_item_id,
                title=item.title,
                summary=item.summary,
                state=item.state,
            )
            for item in items
            if item.user_id == user_id and item.state not in {"deleted", "deprecated"}
        )
        return visible[:limit]

    def select_personal_evidence(
        self,
        *,
        question: str,
        owner_id: str,
        user_id: str,
        limit: int,
    ) -> PersonalKnowledgeEvidenceSnapshot:
        selection = self._knowledge_service.select_evidence(
            question,
            owner_id=owner_id,
            limit=limit,
        )
        return PersonalKnowledgeEvidenceSnapshot(
            question=selection.question,
            citations=tuple(
                PersonalKnowledgeEvidenceCitation(
                    evidence_span_id=item.evidence_span_id,
                    quote=item.quote,
                    locator=item.locator,
                    claim_ids=tuple(item.claim_ids),
                )
                for item in selection.citations
            ),
            claim_summaries=tuple(item.statement for item in selection.selected_claims),
            conflicted_claim_ids=tuple(selection.conflicted_claim_ids),
            potential_conflicted_claim_ids=tuple(
                selection.potential_conflicted_claim_ids
            ),
            reason=selection.reason,
        )
