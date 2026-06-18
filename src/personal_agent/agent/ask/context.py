"""Run-scoped context for the staged ask pipeline.

The ask flow is split into three bounded stages (retrieval, generation,
verification) that map 1:1 onto the ``ask-retrieve`` / ``ask-compose`` /
``ask-verify`` workflow steps. ``AskRunContext`` is the mutable carrier that
threads intermediate state between those stages within a single run.

The large retrieval payload (evidence pool, context pack, scored matches) is
stored as a workflow artifact instead of on the checkpointed
``AgentGraphState``.  This keeps LangGraph checkpoints compact while allowing
compose / verify to recover the staged ask context after process restarts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from ...core.evidence import ContextPack, EvidenceItem
from ...core.models import Citation, KnowledgeNote
from ...core.query_understanding import QueryUnderstanding, RetrievalPlan


@dataclass
class AskRunContext:
    """Mutable per-run carrier threaded across the three ask stages."""

    question: str
    user_id: str
    session_id: str
    working_context: str
    structured_context: str = ""
    has_dialogue_context: bool = False
    trace_id: str = ""

    # Query understanding (filled by RetrievalStage)
    understanding: QueryUnderstanding | None = None
    retrieval_plan: RetrievalPlan | None = None
    effective_query: str = ""

    # Evidence pool + accumulated candidates (filled by RetrievalStage / web fallback)
    evidence_pool: list[EvidenceItem] = field(default_factory=list)
    combined_matches: list[KnowledgeNote] = field(default_factory=list)
    combined_citations: list[Citation] = field(default_factory=list)
    web_tried: bool = False

    # Context assembly output
    context_pack: ContextPack | None = None
    selected_matches: list[KnowledgeNote] = field(default_factory=list)
    selected_citations: list[Citation] = field(default_factory=list)

    # Generation + verification output
    answer: str = ""
    verification: object | None = None

    # Human-readable trace breadcrumbs (parity with the old add_trace_step)
    trace_steps: list[str] = field(default_factory=list)

    def add_trace(self, message: str) -> None:
        self.trace_steps.append(message)

    @property
    def web_search_enabled_for_selected(self) -> bool:
        return any(c.source_type == "web" for c in self.selected_citations)

    @property
    def thread_key(self) -> str:
        return f"{self.user_id}:{self.session_id}"

    def to_artifact_payload(self) -> dict[str, Any]:
        """Serialize the staged context into a JSON-compatible artifact payload."""
        return {
            "schema_version": 1,
            "question": self.question,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "working_context": self.working_context,
            "structured_context": self.structured_context,
            "has_dialogue_context": self.has_dialogue_context,
            "trace_id": self.trace_id,
            "understanding": _dump_model(self.understanding),
            "retrieval_plan": _dump_model(self.retrieval_plan),
            "effective_query": self.effective_query,
            "evidence_pool": [_dump_model(item) for item in self.evidence_pool],
            "combined_matches": [_dump_model(item) for item in self.combined_matches],
            "combined_citations": [_dump_model(item) for item in self.combined_citations],
            "web_tried": self.web_tried,
            "context_pack": _dump_model(self.context_pack),
            "selected_matches": [_dump_model(item) for item in self.selected_matches],
            "selected_citations": [_dump_model(item) for item in self.selected_citations],
            "answer": self.answer,
            "verification": _dump_verification(self.verification),
            "trace_steps": list(self.trace_steps),
        }

    @classmethod
    def from_artifact_payload(cls, payload: dict[str, Any]) -> "AskRunContext":
        """Restore a staged context from an artifact payload."""
        ctx = cls(
            question=str(payload.get("question") or ""),
            user_id=str(payload.get("user_id") or "default"),
            session_id=str(payload.get("session_id") or "default"),
            working_context=str(payload.get("working_context") or ""),
            structured_context=str(payload.get("structured_context") or ""),
            has_dialogue_context=bool(payload.get("has_dialogue_context")),
            trace_id=str(payload.get("trace_id") or ""),
        )
        ctx.understanding = _load_model(QueryUnderstanding, payload.get("understanding"))
        ctx.retrieval_plan = _load_model(RetrievalPlan, payload.get("retrieval_plan"))
        ctx.effective_query = str(payload.get("effective_query") or "")
        ctx.evidence_pool = _load_model_list(EvidenceItem, payload.get("evidence_pool"))
        ctx.combined_matches = _load_model_list(KnowledgeNote, payload.get("combined_matches"))
        ctx.combined_citations = _load_model_list(Citation, payload.get("combined_citations"))
        ctx.web_tried = bool(payload.get("web_tried"))
        ctx.context_pack = _load_model(ContextPack, payload.get("context_pack"))
        ctx.selected_matches = _load_model_list(KnowledgeNote, payload.get("selected_matches"))
        ctx.selected_citations = _load_model_list(Citation, payload.get("selected_citations"))
        ctx.answer = str(payload.get("answer") or "")
        ctx.verification = _load_verification(payload.get("verification"))
        trace_steps = payload.get("trace_steps")
        ctx.trace_steps = [str(item) for item in trace_steps] if isinstance(trace_steps, list) else []
        return ctx


class AskRunContextStore:
    """Artifact-compatible run-scoped store for :class:`AskRunContext`.

    This in-memory implementation stores serialized payloads, not live object
    references, so tests exercise the same serialization boundary as the
    durable Postgres implementation.
    """

    def __init__(self) -> None:
        self._by_run: dict[str, dict[str, Any]] = {}

    def put(self, run_id: str, ctx: AskRunContext) -> None:
        if run_id:
            self._by_run[run_id] = ctx.to_artifact_payload()

    def get(self, run_id: str) -> AskRunContext | None:
        payload = self._by_run.get(run_id)
        if payload is None:
            return None
        return AskRunContext.from_artifact_payload(payload)

    def clear(self, run_id: str) -> None:
        self._by_run.pop(run_id, None)


class PostgresAskRunContextStore(AskRunContextStore):
    """Durable ask context artifact store backed by Postgres JSONB."""

    def __init__(self, postgres_url: str) -> None:
        super().__init__()
        self.postgres_url = postgres_url
        self._initialized = False

    def put(self, run_id: str, ctx: AskRunContext) -> None:
        if not run_id:
            return
        payload = ctx.to_artifact_payload()
        content_hash = _payload_hash(payload)
        self._ensure_schema()
        from psycopg.types.json import Jsonb

        artifact_id = self._artifact_id(run_id)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workflow_artifacts (
                        artifact_id, run_id, kind, payload, content_hash, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT (artifact_id) DO UPDATE
                    SET payload = EXCLUDED.payload,
                        content_hash = EXCLUDED.content_hash,
                        updated_at = now()
                    """,
                    (artifact_id, run_id, "ask_run_context", Jsonb(payload), content_hash),
                )

    def get(self, run_id: str) -> AskRunContext | None:
        if not run_id:
            return None
        self._ensure_schema()
        with self._connect(row_factory=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload
                    FROM workflow_artifacts
                    WHERE artifact_id = %s AND kind = 'ask_run_context'
                    """,
                    (self._artifact_id(run_id),),
                )
                row = cur.fetchone()
        if row is None:
            return None
        payload = row["payload"] if isinstance(row, dict) else row[0]
        if not isinstance(payload, dict):
            return None
        return AskRunContext.from_artifact_payload(payload)

    def clear(self, run_id: str) -> None:
        if not run_id:
            return
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM workflow_artifacts WHERE artifact_id = %s",
                    (self._artifact_id(run_id),),
                )

    def _connect(self, *, row_factory: bool = False):
        from psycopg import connect
        from psycopg.rows import dict_row
        from ...storage.postgres_common import normalize_postgres_url

        if row_factory:
            return connect(normalize_postgres_url(self.postgres_url), row_factory=dict_row)
        return connect(normalize_postgres_url(self.postgres_url))

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_artifacts (
                        artifact_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        content_hash TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workflow_artifacts_run_kind_idx
                    ON workflow_artifacts (run_id, kind, updated_at DESC)
                    """
                )
        self._initialized = True

    @staticmethod
    def _artifact_id(run_id: str) -> str:
        return f"ask_run_context:{run_id}"


def _dump_model(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return None


def _load_model(model_type, value: Any):
    if not isinstance(value, dict):
        return None
    return model_type.model_validate(value)


def _load_model_list(model_type, value: Any) -> list:
    if not isinstance(value, list):
        return []
    return [
        model_type.model_validate(item)
        for item in value
        if isinstance(item, dict)
    ]


def _dump_verification(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    from dataclasses import asdict, is_dataclass

    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return None


def _load_verification(value: Any):
    if not isinstance(value, dict):
        return None
    from ..verifier import ClaimVerification, VerificationResult

    checks = value.get("claim_checks")
    claim_checks = [
        ClaimVerification(
            claim=str(item.get("claim") or ""),
            status=str(item.get("status") or "not_found"),
            supporting_evidence_ids=[
                str(eid) for eid in item.get("supporting_evidence_ids", [])
            ],
            reason=str(item.get("reason") or ""),
        )
        for item in checks
        if isinstance(item, dict)
    ] if isinstance(checks, list) else []
    return VerificationResult(
        evidence_score=float(value.get("evidence_score") or 0.0),
        citation_valid=bool(value.get("citation_valid")),
        issues=[str(item) for item in value.get("issues", [])],
        warnings=[str(item) for item in value.get("warnings", [])],
        claim_checks=claim_checks,
    )


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
