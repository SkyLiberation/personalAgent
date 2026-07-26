from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from personal_agent.application.workspace.models import (
    Artifact,
    Claim,
    ClaimAdmissionDecision,
    ClaimSupportEvent,
    DecisionCard,
    EvidenceBlock,
    EvidenceSpan,
    ExtractionRun,
    GraphProjection,
    GroundingRun,
    KnowledgeGap,
    KnowledgeItem,
    KnowledgeStateEvent,
    KnowledgeRelation,
    ProjectionJob,
    ResearchEvent,
    ReviewItem,
)


class WorkspaceStore(Protocol):
    def save_artifact(self, artifact: Artifact) -> None: ...
    def save_extraction_run(self, run: ExtractionRun) -> None: ...
    def save_evidence_blocks(self, blocks: Iterable[EvidenceBlock]) -> None: ...
    def save_evidence_spans(self, spans: Iterable[EvidenceSpan]) -> None: ...
    def save_claims(self, claims: Iterable[Claim]) -> None: ...
    def save_grounding_runs(self, runs: Iterable[GroundingRun]) -> None: ...
    def save_claim_support_events(self, events: Iterable[ClaimSupportEvent]) -> None: ...
    def save_claim_admission_decisions(self, decisions: Iterable[ClaimAdmissionDecision]) -> None: ...
    def save_knowledge_state_events(self, events: Iterable[KnowledgeStateEvent]) -> None: ...
    def save_knowledge_relations(self, relations: Iterable[KnowledgeRelation]) -> None: ...
    def save_knowledge_items(self, items: Iterable[KnowledgeItem]) -> None: ...
    def save_decisions(self, decisions: Iterable[DecisionCard]) -> None: ...
    def save_research_events(self, events: Iterable[ResearchEvent]) -> None: ...
    def save_review_items(self, items: Iterable[ReviewItem]) -> None: ...
    def save_knowledge_gaps(self, gaps: Iterable[KnowledgeGap]) -> None: ...
    def save_graph_projections(self, projections: Iterable[GraphProjection]) -> None: ...
    def save_projection_jobs(self, jobs: Iterable[ProjectionJob]) -> None: ...
    def get_artifact(self, artifact_id: str) -> Artifact | None: ...
    def list_artifacts(
        self,
        workspace_id: str,
        *,
        source_type: str | None = None,
        limit: int = 100,
    ) -> list[Artifact]: ...
    def get_extraction_run(self, extraction_run_id: str) -> ExtractionRun | None: ...
    def get_claim(self, claim_id: str) -> Claim | None: ...
    def get_research_event(self, research_event_id: str) -> ResearchEvent | None: ...
    def get_decision(self, decision_id: str) -> DecisionCard | None: ...
    def get_evidence_block(self, evidence_block_id: str) -> EvidenceBlock | None: ...
    def get_evidence_span(self, evidence_span_id: str) -> EvidenceSpan | None: ...
    def list_evidence_spans(self, workspace_id: str, *, limit: int = 100) -> list[EvidenceSpan]: ...
    def list_claims(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[Claim]: ...
    def list_knowledge_relations(
        self,
        workspace_id: str,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        limit: int = 100,
    ) -> list[KnowledgeRelation]: ...
    def list_research_events(self, workspace_id: str, *, limit: int = 100) -> list[ResearchEvent]: ...
    def list_knowledge_items(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[KnowledgeItem]: ...
    def list_decisions(self, workspace_id: str, *, status: str | None = None, limit: int = 100) -> list[DecisionCard]: ...
    def list_review_items(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[ReviewItem]: ...
    def list_knowledge_gaps(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[KnowledgeGap]: ...
    def list_graph_projections(self, workspace_id: str, *, limit: int = 100) -> list[GraphProjection]: ...
    def list_projection_jobs(
        self,
        workspace_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ProjectionJob]: ...


class InMemoryWorkspaceStore:
    def __init__(self) -> None:
        self.artifacts: dict[str, Artifact] = {}
        self.extraction_runs: dict[str, ExtractionRun] = {}
        self.evidence_blocks: dict[str, EvidenceBlock] = {}
        self.evidence_spans: dict[str, EvidenceSpan] = {}
        self.claims: dict[str, Claim] = {}
        self.grounding_runs: dict[str, GroundingRun] = {}
        self.claim_support_events: dict[str, ClaimSupportEvent] = {}
        self.claim_admission_decisions: dict[str, ClaimAdmissionDecision] = {}
        self.knowledge_state_events: dict[str, KnowledgeStateEvent] = {}
        self.knowledge_relations: dict[str, KnowledgeRelation] = {}
        self.knowledge_items: dict[str, KnowledgeItem] = {}
        self.decisions: dict[str, DecisionCard] = {}
        self.research_events: dict[str, ResearchEvent] = {}
        self.review_items: dict[str, ReviewItem] = {}
        self.knowledge_gaps: dict[str, KnowledgeGap] = {}
        self.graph_projections: dict[str, GraphProjection] = {}
        self.projection_jobs: dict[str, ProjectionJob] = {}

    def save_artifact(self, artifact: Artifact) -> None:
        self.artifacts[artifact.artifact_id] = artifact

    def save_extraction_run(self, run: ExtractionRun) -> None:
        self.extraction_runs[run.extraction_run_id] = run

    def save_evidence_blocks(self, blocks: Iterable[EvidenceBlock]) -> None:
        for block in blocks:
            self.evidence_blocks[block.evidence_block_id] = block

    def save_evidence_spans(self, spans: Iterable[EvidenceSpan]) -> None:
        for span in spans:
            self.evidence_spans[span.evidence_span_id] = span

    def save_claims(self, claims: Iterable[Claim]) -> None:
        for claim in claims:
            self.claims[claim.claim_id] = claim

    def save_grounding_runs(self, runs: Iterable[GroundingRun]) -> None:
        for run in runs:
            self.grounding_runs[run.grounding_run_id] = run

    def save_claim_support_events(self, events: Iterable[ClaimSupportEvent]) -> None:
        for event in events:
            self.claim_support_events[event.event_id] = event

    def save_claim_admission_decisions(self, decisions: Iterable[ClaimAdmissionDecision]) -> None:
        for decision in decisions:
            self.claim_admission_decisions[decision.admission_id] = decision

    def save_knowledge_state_events(self, events: Iterable[KnowledgeStateEvent]) -> None:
        for event in events:
            self.knowledge_state_events[event.event_id] = event

    def save_knowledge_relations(self, relations: Iterable[KnowledgeRelation]) -> None:
        for relation in relations:
            self.knowledge_relations[relation.relation_id] = relation

    def save_knowledge_items(self, items: Iterable[KnowledgeItem]) -> None:
        for item in items:
            self.knowledge_items[item.knowledge_item_id] = item

    def save_decisions(self, decisions: Iterable[DecisionCard]) -> None:
        for decision in decisions:
            self.decisions[decision.decision_id] = decision

    def save_research_events(self, events: Iterable[ResearchEvent]) -> None:
        for event in events:
            self.research_events[event.research_event_id] = event

    def save_review_items(self, items: Iterable[ReviewItem]) -> None:
        for item in items:
            self.review_items[item.review_item_id] = item

    def save_knowledge_gaps(self, gaps: Iterable[KnowledgeGap]) -> None:
        for gap in gaps:
            self.knowledge_gaps[gap.gap_id] = gap

    def save_graph_projections(self, projections: Iterable[GraphProjection]) -> None:
        for projection in projections:
            self.graph_projections[projection.graph_projection_id] = projection

    def save_projection_jobs(self, jobs: Iterable[ProjectionJob]) -> None:
        for job in jobs:
            self.projection_jobs[job.projection_job_id] = job

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        return self.artifacts.get(artifact_id)

    def list_artifacts(
        self,
        workspace_id: str,
        *,
        source_type: str | None = None,
        limit: int = 100,
    ) -> list[Artifact]:
        artifacts = [
            artifact for artifact in self.artifacts.values()
            if artifact.workspace_id == workspace_id
            and (source_type is None or artifact.source_type == source_type)
        ]
        artifacts.sort(key=lambda item: item.created_at, reverse=True)
        return artifacts[:max(1, limit)]

    def get_extraction_run(self, extraction_run_id: str) -> ExtractionRun | None:
        return self.extraction_runs.get(extraction_run_id)

    def get_claim(self, claim_id: str) -> Claim | None:
        return self.claims.get(claim_id)

    def get_research_event(self, research_event_id: str) -> ResearchEvent | None:
        return self.research_events.get(research_event_id)

    def get_decision(self, decision_id: str) -> DecisionCard | None:
        return self.decisions.get(decision_id)

    def get_evidence_block(self, evidence_block_id: str) -> EvidenceBlock | None:
        return self.evidence_blocks.get(evidence_block_id)

    def get_evidence_span(self, evidence_span_id: str) -> EvidenceSpan | None:
        return self.evidence_spans.get(evidence_span_id)

    def list_evidence_spans(self, workspace_id: str, *, limit: int = 100) -> list[EvidenceSpan]:
        spans = [
            span for span in self.evidence_spans.values()
            if span.workspace_id == workspace_id
        ]
        spans.sort(key=lambda item: item.created_at, reverse=True)
        return spans[:max(1, limit)]

    def list_claims(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[Claim]:
        claims = [
            claim for claim in self.claims.values()
            if claim.workspace_id == workspace_id and (state is None or claim.state == state)
        ]
        claims.sort(key=lambda item: item.created_at, reverse=True)
        return claims[:max(1, limit)]

    def list_knowledge_relations(
        self,
        workspace_id: str,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        limit: int = 100,
    ) -> list[KnowledgeRelation]:
        relations = [
            relation for relation in self.knowledge_relations.values()
            if relation.workspace_id == workspace_id
            and (source_id is None or relation.source_id == source_id)
            and (target_id is None or relation.target_id == target_id)
            and (relation_type is None or relation.relation_type == relation_type)
        ]
        relations.sort(key=lambda item: item.created_at, reverse=True)
        return relations[:max(1, limit)]

    def list_research_events(self, workspace_id: str, *, limit: int = 100) -> list[ResearchEvent]:
        events = [event for event in self.research_events.values() if event.workspace_id == workspace_id]
        events.sort(key=lambda item: item.created_at, reverse=True)
        return events[:max(1, limit)]

    def list_knowledge_items(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[KnowledgeItem]:
        items = [
            item for item in self.knowledge_items.values()
            if item.workspace_id == workspace_id and (state is None or item.state == state)
        ]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[:max(1, limit)]

    def list_decisions(self, workspace_id: str, *, status: str | None = None, limit: int = 100) -> list[DecisionCard]:
        decisions = [
            decision for decision in self.decisions.values()
            if decision.workspace_id == workspace_id and (status is None or decision.status == status)
        ]
        decisions.sort(key=lambda item: item.created_at, reverse=True)
        return decisions[:max(1, limit)]

    def list_review_items(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[ReviewItem]:
        items = [
            item for item in self.review_items.values()
            if item.workspace_id == workspace_id and (state is None or item.state == state)
        ]
        items.sort(key=lambda item: (item.priority, item.created_at), reverse=True)
        return items[:max(1, limit)]

    def list_knowledge_gaps(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[KnowledgeGap]:
        gaps = [
            gap for gap in self.knowledge_gaps.values()
            if gap.workspace_id == workspace_id and (state is None or gap.state == state)
        ]
        gaps.sort(key=lambda item: (item.severity, item.created_at), reverse=True)
        return gaps[:max(1, limit)]

    def list_graph_projections(self, workspace_id: str, *, limit: int = 100) -> list[GraphProjection]:
        projections = [
            projection for projection in self.graph_projections.values()
            if projection.workspace_id == workspace_id
        ]
        projections.sort(key=lambda item: item.created_at, reverse=True)
        return projections[:max(1, limit)]

    def list_projection_jobs(
        self,
        workspace_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ProjectionJob]:
        jobs = [
            job for job in self.projection_jobs.values()
            if job.workspace_id == workspace_id and (status is None or job.status == status)
        ]
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return jobs[:max(1, limit)]
