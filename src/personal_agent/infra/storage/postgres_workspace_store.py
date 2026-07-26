from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

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
from personal_agent.infra.storage.postgres_common import PostgresStoreBase


class PostgresWorkspaceStore(PostgresStoreBase):
    def __init__(self, postgres_url: str, data_dir: Path | None = None) -> None:
        super().__init__(postgres_url)
        self.data_dir = data_dir

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workspace_artifacts (
                        artifact_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_artifacts_workspace_idx
                    ON workspace_artifacts (workspace_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_extraction_runs (
                        extraction_run_id TEXT PRIMARY KEY,
                        artifact_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_extraction_runs_artifact_idx
                    ON workspace_extraction_runs (artifact_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_evidence_blocks (
                        evidence_block_id TEXT PRIMARY KEY,
                        artifact_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_evidence_blocks_artifact_idx
                    ON workspace_evidence_blocks (artifact_id, created_at);

                    CREATE TABLE IF NOT EXISTS workspace_evidence_spans (
                        evidence_span_id TEXT PRIMARY KEY,
                        evidence_block_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        quote_hash TEXT NOT NULL,
                        text_span TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_evidence_spans_workspace_idx
                    ON workspace_evidence_spans (workspace_id, created_at DESC);
                    CREATE INDEX IF NOT EXISTS workspace_evidence_spans_block_idx
                    ON workspace_evidence_spans (evidence_block_id);

                    CREATE TABLE IF NOT EXISTS workspace_claims (
                        claim_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        support_status TEXT NOT NULL,
                        canonical_key TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_claims_state_idx
                    ON workspace_claims (workspace_id, state, created_at DESC);
                    CREATE INDEX IF NOT EXISTS workspace_claims_canonical_idx
                    ON workspace_claims (workspace_id, canonical_key);

                    CREATE TABLE IF NOT EXISTS workspace_grounding_runs (
                        grounding_run_id TEXT PRIMARY KEY,
                        claim_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_grounding_runs_claim_idx
                    ON workspace_grounding_runs (claim_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_claim_support_events (
                        event_id TEXT PRIMARY KEY,
                        claim_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_claim_support_events_claim_idx
                    ON workspace_claim_support_events (claim_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_claim_admission_decisions (
                        admission_id TEXT PRIMARY KEY,
                        claim_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        admission_result TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_claim_admission_decisions_claim_idx
                    ON workspace_claim_admission_decisions (claim_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_knowledge_state_events (
                        event_id TEXT PRIMARY KEY,
                        target_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        to_state TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_knowledge_state_events_target_idx
                    ON workspace_knowledge_state_events (target_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_knowledge_relations (
                        relation_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        relation_type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_knowledge_relations_source_idx
                    ON workspace_knowledge_relations (workspace_id, source_id, relation_type, created_at DESC);
                    CREATE INDEX IF NOT EXISTS workspace_knowledge_relations_target_idx
                    ON workspace_knowledge_relations (workspace_id, target_id, relation_type, created_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_knowledge_items (
                        knowledge_item_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_knowledge_items_workspace_idx
                    ON workspace_knowledge_items (workspace_id, state, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_decisions (
                        decision_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        decision_type TEXT NOT NULL,
                        risk_level TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_decisions_workspace_idx
                    ON workspace_decisions (workspace_id, status, created_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_research_events (
                        research_event_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_research_events_workspace_idx
                    ON workspace_research_events (workspace_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_review_items (
                        review_item_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        claim_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        priority DOUBLE PRECISION NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_review_items_workspace_idx
                    ON workspace_review_items (workspace_id, state, priority DESC);

                    CREATE TABLE IF NOT EXISTS workspace_knowledge_gaps (
                        gap_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        gap_type TEXT NOT NULL,
                        state TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_knowledge_gaps_workspace_idx
                    ON workspace_knowledge_gaps (workspace_id, state, severity, created_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_graph_projections (
                        graph_projection_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        source_claim_id TEXT NOT NULL,
                        quality_signal TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_graph_projections_workspace_idx
                    ON workspace_graph_projections (workspace_id, source_claim_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS workspace_projection_jobs (
                        projection_job_id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        projection_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        source_object_id TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS workspace_projection_jobs_workspace_idx
                    ON workspace_projection_jobs (workspace_id, status, created_at DESC);
                    """
                )
            conn.commit()
        self._initialized = True

    def save_artifact(self, artifact: Artifact) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workspace_artifacts
                        (artifact_id, workspace_id, user_id, content_hash, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (artifact_id) DO UPDATE SET
                        workspace_id = EXCLUDED.workspace_id,
                        user_id = EXCLUDED.user_id,
                        content_hash = EXCLUDED.content_hash,
                        payload = EXCLUDED.payload
                    """,
                    (
                        artifact.artifact_id,
                        artifact.workspace_id,
                        artifact.user_id,
                        artifact.content_hash,
                        Jsonb(artifact.model_dump(mode="json")),
                        artifact.created_at,
                    ),
                )
            conn.commit()

    def save_extraction_run(self, run: ExtractionRun) -> None:
        self._upsert_payload(
            "workspace_extraction_runs",
            "extraction_run_id",
            run.extraction_run_id,
            {
                "artifact_id": run.artifact_id,
                "workspace_id": run.workspace_id,
                "payload": Jsonb(run.model_dump(mode="json")),
                "created_at": run.created_at,
            },
        )

    def save_evidence_blocks(self, blocks: Iterable[EvidenceBlock]) -> None:
        for block in blocks:
            self._upsert_payload(
                "workspace_evidence_blocks",
                "evidence_block_id",
                block.evidence_block_id,
                {
                    "artifact_id": block.artifact_id,
                    "workspace_id": block.workspace_id,
                    "payload": Jsonb(block.model_dump(mode="json")),
                    "created_at": block.created_at,
                },
            )

    def save_evidence_spans(self, spans: Iterable[EvidenceSpan]) -> None:
        for span in spans:
            self._upsert_payload(
                "workspace_evidence_spans",
                "evidence_span_id",
                span.evidence_span_id,
                {
                    "evidence_block_id": span.evidence_block_id,
                    "workspace_id": span.workspace_id,
                    "quote_hash": span.quote_hash,
                    "text_span": span.text_span,
                    "payload": Jsonb(span.model_dump(mode="json")),
                    "created_at": span.created_at,
                },
            )

    def save_claims(self, claims: Iterable[Claim]) -> None:
        for claim in claims:
            self._upsert_payload(
                "workspace_claims",
                "claim_id",
                claim.claim_id,
                {
                    "workspace_id": claim.workspace_id,
                    "user_id": claim.user_id,
                    "state": claim.state,
                    "support_status": claim.support_status,
                    "canonical_key": claim.canonical_key,
                    "payload": Jsonb(claim.model_dump(mode="json")),
                    "created_at": claim.created_at,
                    "updated_at": claim.updated_at,
                },
            )

    def save_grounding_runs(self, runs: Iterable[GroundingRun]) -> None:
        for run in runs:
            self._upsert_payload(
                "workspace_grounding_runs",
                "grounding_run_id",
                run.grounding_run_id,
                {
                    "claim_id": run.claim_id,
                    "workspace_id": run.workspace_id,
                    "payload": Jsonb(run.model_dump(mode="json")),
                    "created_at": run.created_at,
                },
            )

    def save_claim_support_events(self, events: Iterable[ClaimSupportEvent]) -> None:
        for event in events:
            self._upsert_payload(
                "workspace_claim_support_events",
                "event_id",
                event.event_id,
                {
                    "claim_id": event.claim_id,
                    "workspace_id": event.workspace_id,
                    "payload": Jsonb(event.model_dump(mode="json")),
                    "created_at": event.created_at,
                },
            )

    def save_claim_admission_decisions(self, decisions: Iterable[ClaimAdmissionDecision]) -> None:
        for decision in decisions:
            self._upsert_payload(
                "workspace_claim_admission_decisions",
                "admission_id",
                decision.admission_id,
                {
                    "claim_id": decision.claim_id,
                    "workspace_id": decision.workspace_id,
                    "admission_result": decision.admission_result,
                    "payload": Jsonb(decision.model_dump(mode="json")),
                    "created_at": decision.created_at,
                },
            )

    def save_knowledge_state_events(self, events: Iterable[KnowledgeStateEvent]) -> None:
        for event in events:
            self._upsert_payload(
                "workspace_knowledge_state_events",
                "event_id",
                event.event_id,
                {
                    "target_id": event.target_id,
                    "workspace_id": event.workspace_id,
                    "to_state": event.to_state,
                    "payload": Jsonb(event.model_dump(mode="json")),
                    "created_at": event.created_at,
                },
            )

    def save_knowledge_relations(self, relations: Iterable[KnowledgeRelation]) -> None:
        for relation in relations:
            self._upsert_payload(
                "workspace_knowledge_relations",
                "relation_id",
                relation.relation_id,
                {
                    "workspace_id": relation.workspace_id,
                    "source_id": relation.source_id,
                    "target_id": relation.target_id,
                    "relation_type": relation.relation_type,
                    "payload": Jsonb(relation.model_dump(mode="json")),
                    "created_at": relation.created_at,
                },
            )

    def save_knowledge_items(self, items: Iterable[KnowledgeItem]) -> None:
        for item in items:
            self._upsert_payload(
                "workspace_knowledge_items",
                "knowledge_item_id",
                item.knowledge_item_id,
                {
                    "workspace_id": item.workspace_id,
                    "user_id": item.user_id,
                    "state": item.state,
                    "payload": Jsonb(item.model_dump(mode="json")),
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                },
            )

    def save_decisions(self, decisions: Iterable[DecisionCard]) -> None:
        for decision in decisions:
            self._upsert_payload(
                "workspace_decisions",
                "decision_id",
                decision.decision_id,
                {
                    "workspace_id": decision.workspace_id,
                    "status": decision.status,
                    "decision_type": decision.decision_type,
                    "risk_level": decision.risk_level,
                    "payload": Jsonb(decision.model_dump(mode="json")),
                    "created_at": decision.created_at,
                },
            )

    def save_research_events(self, events: Iterable[ResearchEvent]) -> None:
        for event in events:
            self._upsert_payload(
                "workspace_research_events",
                "research_event_id",
                event.research_event_id,
                {
                    "workspace_id": event.workspace_id,
                    "user_id": event.user_id,
                    "status": event.status,
                    "payload": Jsonb(event.model_dump(mode="json")),
                    "created_at": event.created_at,
                    "updated_at": event.updated_at,
                },
            )

    def save_review_items(self, items: Iterable[ReviewItem]) -> None:
        for item in items:
            self._upsert_payload(
                "workspace_review_items",
                "review_item_id",
                item.review_item_id,
                {
                    "workspace_id": item.workspace_id,
                    "claim_id": item.claim_id,
                    "state": item.state,
                    "priority": item.priority,
                    "payload": Jsonb(item.model_dump(mode="json")),
                    "created_at": item.created_at,
                },
            )

    def save_knowledge_gaps(self, gaps: Iterable[KnowledgeGap]) -> None:
        for gap in gaps:
            self._upsert_payload(
                "workspace_knowledge_gaps",
                "gap_id",
                gap.gap_id,
                {
                    "workspace_id": gap.workspace_id,
                    "gap_type": gap.gap_type,
                    "state": gap.state,
                    "severity": gap.severity,
                    "payload": Jsonb(gap.model_dump(mode="json")),
                    "created_at": gap.created_at,
                },
            )

    def save_graph_projections(self, projections: Iterable[GraphProjection]) -> None:
        for projection in projections:
            self._upsert_payload(
                "workspace_graph_projections",
                "graph_projection_id",
                projection.graph_projection_id,
                {
                    "workspace_id": projection.workspace_id,
                    "source_claim_id": projection.source_claim_id,
                    "quality_signal": projection.quality_signal,
                    "payload": Jsonb(projection.model_dump(mode="json")),
                    "created_at": projection.created_at,
                },
            )

    def save_projection_jobs(self, jobs: Iterable[ProjectionJob]) -> None:
        for job in jobs:
            self._upsert_payload(
                "workspace_projection_jobs",
                "projection_job_id",
                job.projection_job_id,
                {
                    "workspace_id": job.workspace_id,
                    "projection_type": job.projection_type,
                    "status": job.status,
                    "source_object_id": job.source_object_id,
                    "payload": Jsonb(job.model_dump(mode="json")),
                    "created_at": job.created_at,
                    "updated_at": job.updated_at,
                },
            )

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        row = self._fetch_payload("workspace_artifacts", "artifact_id", artifact_id)
        return Artifact.model_validate(row) if row else None

    def list_artifacts(
        self,
        workspace_id: str,
        *,
        source_type: str | None = None,
        limit: int = 100,
    ) -> list[Artifact]:
        self.ensure_schema()
        clauses = ["workspace_id = %s"]
        params: list[object] = [workspace_id]
        if source_type:
            clauses.append("payload ->> 'source_type' = %s")
            params.append(source_type)
        params.append(max(1, limit))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM workspace_artifacts
                    WHERE {' AND '.join(clauses)}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [Artifact.model_validate(row["payload"]) for row in cur.fetchall()]

    def get_extraction_run(self, extraction_run_id: str) -> ExtractionRun | None:
        row = self._fetch_payload("workspace_extraction_runs", "extraction_run_id", extraction_run_id)
        return ExtractionRun.model_validate(row) if row else None

    def get_claim(self, claim_id: str) -> Claim | None:
        row = self._fetch_payload("workspace_claims", "claim_id", claim_id)
        return Claim.model_validate(row) if row else None

    def get_research_event(self, research_event_id: str) -> ResearchEvent | None:
        row = self._fetch_payload("workspace_research_events", "research_event_id", research_event_id)
        return ResearchEvent.model_validate(row) if row else None

    def get_decision(self, decision_id: str) -> DecisionCard | None:
        row = self._fetch_payload("workspace_decisions", "decision_id", decision_id)
        return DecisionCard.model_validate(row) if row else None

    def get_evidence_block(self, evidence_block_id: str) -> EvidenceBlock | None:
        row = self._fetch_payload("workspace_evidence_blocks", "evidence_block_id", evidence_block_id)
        return EvidenceBlock.model_validate(row) if row else None

    def get_evidence_span(self, evidence_span_id: str) -> EvidenceSpan | None:
        row = self._fetch_payload("workspace_evidence_spans", "evidence_span_id", evidence_span_id)
        return EvidenceSpan.model_validate(row) if row else None

    def list_evidence_spans(self, workspace_id: str, *, limit: int = 100) -> list[EvidenceSpan]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM workspace_evidence_spans
                    WHERE workspace_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (workspace_id, max(1, limit)),
                )
                return [EvidenceSpan.model_validate(row["payload"]) for row in cur.fetchall()]

    def list_claims(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[Claim]:
        self.ensure_schema()
        clauses = ["workspace_id = %s"]
        params: list[object] = [workspace_id]
        if state:
            clauses.append("state = %s")
            params.append(state)
        params.append(max(1, limit))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM workspace_claims
                    WHERE {' AND '.join(clauses)}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [Claim.model_validate(row["payload"]) for row in cur.fetchall()]

    def list_knowledge_relations(
        self,
        workspace_id: str,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        limit: int = 100,
    ) -> list[KnowledgeRelation]:
        self.ensure_schema()
        clauses = ["workspace_id = %s"]
        params: list[object] = [workspace_id]
        if source_id:
            clauses.append("source_id = %s")
            params.append(source_id)
        if target_id:
            clauses.append("target_id = %s")
            params.append(target_id)
        if relation_type:
            clauses.append("relation_type = %s")
            params.append(relation_type)
        params.append(max(1, limit))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM workspace_knowledge_relations
                    WHERE {' AND '.join(clauses)}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [KnowledgeRelation.model_validate(row["payload"]) for row in cur.fetchall()]

    def list_knowledge_items(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[KnowledgeItem]:
        self.ensure_schema()
        clauses = ["workspace_id = %s"]
        params: list[object] = [workspace_id]
        if state:
            clauses.append("state = %s")
            params.append(state)
        params.append(max(1, limit))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM workspace_knowledge_items
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [KnowledgeItem.model_validate(row["payload"]) for row in cur.fetchall()]

    def list_decisions(self, workspace_id: str, *, status: str | None = None, limit: int = 100) -> list[DecisionCard]:
        self.ensure_schema()
        clauses = ["workspace_id = %s"]
        params: list[object] = [workspace_id]
        if status:
            clauses.append("status = %s")
            params.append(status)
        params.append(max(1, limit))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM workspace_decisions
                    WHERE {' AND '.join(clauses)}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [DecisionCard.model_validate(row["payload"]) for row in cur.fetchall()]

    def list_research_events(self, workspace_id: str, *, limit: int = 100) -> list[ResearchEvent]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM workspace_research_events
                    WHERE workspace_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (workspace_id, max(1, limit)),
                )
                return [ResearchEvent.model_validate(row["payload"]) for row in cur.fetchall()]

    def list_review_items(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[ReviewItem]:
        self.ensure_schema()
        clauses = ["workspace_id = %s"]
        params: list[object] = [workspace_id]
        if state:
            clauses.append("state = %s")
            params.append(state)
        params.append(max(1, limit))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM workspace_review_items
                    WHERE {' AND '.join(clauses)}
                    ORDER BY priority DESC, created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [ReviewItem.model_validate(row["payload"]) for row in cur.fetchall()]

    def list_knowledge_gaps(self, workspace_id: str, *, state: str | None = None, limit: int = 100) -> list[KnowledgeGap]:
        self.ensure_schema()
        clauses = ["workspace_id = %s"]
        params: list[object] = [workspace_id]
        if state:
            clauses.append("state = %s")
            params.append(state)
        params.append(max(1, limit))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM workspace_knowledge_gaps
                    WHERE {' AND '.join(clauses)}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [KnowledgeGap.model_validate(row["payload"]) for row in cur.fetchall()]

    def list_graph_projections(self, workspace_id: str, *, limit: int = 100) -> list[GraphProjection]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM workspace_graph_projections
                    WHERE workspace_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (workspace_id, max(1, limit)),
                )
                return [GraphProjection.model_validate(row["payload"]) for row in cur.fetchall()]

    def list_projection_jobs(
        self,
        workspace_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ProjectionJob]:
        self.ensure_schema()
        clauses = ["workspace_id = %s"]
        params: list[object] = [workspace_id]
        if status:
            clauses.append("status = %s")
            params.append(status)
        params.append(max(1, limit))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM workspace_projection_jobs
                    WHERE {' AND '.join(clauses)}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [ProjectionJob.model_validate(row["payload"]) for row in cur.fetchall()]

    def _upsert_payload(self, table: str, key_column: str, key: str, values: dict[str, object]) -> None:
        self.ensure_schema()
        columns = [key_column, *values.keys()]
        placeholders = ", ".join(["%s"] * len(columns))
        assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in values)
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({key_column}) DO UPDATE SET {assignments}"
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (key, *values.values()))
            conn.commit()

    def _fetch_payload(self, table: str, key_column: str, key: str) -> dict | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT payload FROM {table} WHERE {key_column} = %s", (key,))
                row = cur.fetchone()
        return row["payload"] if row else None
