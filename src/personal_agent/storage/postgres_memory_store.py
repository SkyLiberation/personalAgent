from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime
from hashlib import blake2b
from math import sqrt
from pathlib import Path
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..core.config import LangSmithConfig
from ..core.embedding_trace import (
    log_embedding_fallback,
    log_local_embedding,
    traced_embedding,
)
from ..core.logging_utils import log_event
from ..core.models import KnowledgeNote, MemoryEpisode, MemoryItem, ReviewCard, local_now
from ..core.projections import retrieval_document_from_note
from ..core.query_understanding import RetrievalFilters
from .postgres_common import PostgresStoreBase

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeleteNoteStorageResult:
    target: KnowledgeNote
    notes: list[KnowledgeNote]
    review_cards: list[ReviewCard] = field(default_factory=list)
    snapshot_id: str = ""


@dataclass(frozen=True)
class RestoreNoteStorageResult:
    target: KnowledgeNote
    notes: list[KnowledgeNote]
    review_cards: list[ReviewCard] = field(default_factory=list)
    snapshot_id: str = ""


def _with_local_timezone(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value
    return value.replace(tzinfo=reference.tzinfo)


def _compact_whitespace(value: str) -> str:
    return " ".join(value.split())


_EMBEDDING_DIMENSIONS = 128

# pg_search (ParadeDB) BM25 configuration.
# The lexical path is backed by a BM25 index built on the ``search_text`` column.
# Chinese segmentation is handled by pg_search's own tokenizer (not zhparser /
# not tsvector). Tokenizer name is centralized here so it can be adjusted to
# match the installed pg_search version without touching the SQL builders.
_BM25_TOKENIZER = "chinese_compatible"
_BM25_KEY_FIELD = "id"
_BM25_TEXT_FIELD = "search_text"


def _bm25_text_fields_json() -> str:
    """JSON config for the BM25 index ``text_fields`` option.

    Single-field index over ``search_text`` with the Chinese-compatible
    tokenizer. Field-level weighting (former title*4 / summary*2 ...) is
    intentionally dropped in this first version; see plan trade-off #1.
    """
    return (
        '{"' + _BM25_TEXT_FIELD + '": {"tokenizer": {"type": "'
        + _BM25_TOKENIZER + '"}}}'
    )



def _search_text_for_note(note: KnowledgeNote) -> str:
    document = retrieval_document_from_note(note)
    parts = [
        document.title,
        document.summary,
        document.preextract_topic or "",
        " ".join(document.tags),
        " ".join(document.entity_names),
        " ".join(document.relation_facts),
        " ".join(str(value) for value in document.metadata.values() if value),
        document.source_fingerprint or "",
        document.content,
    ]
    return _compact_whitespace(" ".join(part for part in parts if part))


def _search_text_for_episode(episode: MemoryEpisode) -> str:
    parts = [
        episode.title,
        episode.summary,
        episode.workflow,
        episode.outcome,
        episode.entry_text,
        " ".join(episode.decisions),
        " ".join(episode.open_items),
        " ".join(episode.tool_refs),
        " ".join(episode.note_refs),
        " ".join(str(value) for value in episode.metadata.values() if value),
    ]
    return _compact_whitespace(" ".join(part for part in parts if part))


def _search_text_for_memory_item(item: MemoryItem) -> str:
    parts = [
        item.memory_type,
        item.title,
        item.content,
        item.status,
        " ".join(item.applies_to),
        " ".join(item.source_episode_ids),
        " ".join(item.source_run_ids),
        " ".join(item.evidence_refs),
        " ".join(str(value) for value in item.metadata.values() if value),
    ]
    return _compact_whitespace(" ".join(part for part in parts if part))


def _bm25_bonus(score: float) -> float:
    """Saturating bonus from a raw BM25 score, kept on the RRF scale.

    BM25 scores are unbounded and not comparable across queries, so we map them
    through a saturating curve capped near the magnitude of a top RRF term
    (~1/61). This lets a strong BM25 hit nudge ordering without letting an
    outlier score dominate the rank-based fusion.
    """
    if score <= 0.0:
        return 0.0
    # score/(score+k) saturates in [0,1); scale so the cap matches RRF magnitude.
    return 0.016 * (score / (score + 8.0))


def _query_terms(query: str) -> list[str]:
    normalized = query.lower()
    terms: list[str] = []

    for token in re.findall(r"[a-z0-9_+-]{2,}", normalized):
        if token not in terms:
            terms.append(token)

    cjk_runs = re.findall(r"[\u3400-\u9fff]{2,}", query)
    for run in cjk_runs:
        if run not in terms:
            terms.append(run)
        for size in (2, 3):
            for index in range(0, max(0, len(run) - size + 1)):
                gram = run[index:index + size]
                if gram not in terms:
                    terms.append(gram)

    for token in query.replace("？", " ").replace("，", " ").replace(",", " ").split():
        cleaned = token.strip().lower()
        if len(cleaned) >= 2 and cleaned not in terms:
            terms.append(cleaned)

    return terms[:16]


def _embedding_features(text: str) -> list[str]:
    features = _query_terms(text)
    compact_cjk = "".join(re.findall(r"[\u3400-\u9fff]", text))
    for size in (2, 3, 4):
        for index in range(0, max(0, len(compact_cjk) - size + 1)):
            gram = compact_cjk[index:index + size]
            if gram not in features:
                features.append(gram)
    return features[:512]


def _local_embedding(text: str, dimensions: int = _EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for feature in _embedding_features(text.lower()):
        digest = blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [round(value / norm, 6) for value in vector]


def _vector_literal(vector: list[float] | None) -> str | None:
    if vector is None:
        return None
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


def _filters_sql(filters: RetrievalFilters | None) -> tuple[str, list[object]]:
    if filters is None or not filters.active():
        return "", []

    clauses: list[str] = []
    params: list[object] = []

    source_types = [item.strip() for item in filters.source_types if item.strip()]
    if source_types:
        clauses.append("AND payload#>>'{source,type}' = ANY(%s)")
        params.append(source_types)

    if filters.source_ref_contains.strip():
        clauses.append("AND lower(coalesce(payload#>>'{source,ref}', '')) LIKE %s")
        params.append(f"%{filters.source_ref_contains.strip().lower()}%")

    tags = [tag.strip().lower() for tag in filters.tags if tag.strip()]
    if tags:
        clauses.append(
            """
            AND EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(coalesce(payload->'tags', '[]'::jsonb)) AS tag(value)
                WHERE lower(tag.value) = ANY(%s)
            )
            """
        )
        params.append(tags)

    if filters.created_after.strip():
        clauses.append("AND created_at >= %s::timestamptz")
        params.append(filters.created_after.strip())

    if filters.created_before.strip():
        clauses.append("AND created_at <= %s::timestamptz")
        params.append(filters.created_before.strip())

    if filters.metadata_contains.strip():
        clauses.append("AND lower(coalesce(payload#>>'{source,metadata}', '')) LIKE %s")
        params.append(f"%{filters.metadata_contains.strip().lower()}%")

    if filters.parent_note_id.strip():
        clauses.append("AND (id = %s OR parent_note_id = %s)")
        params.extend([filters.parent_note_id.strip(), filters.parent_note_id.strip()])

    return "\n".join(clauses), params


def _note_matches_filters(note: KnowledgeNote, filters: RetrievalFilters | None) -> bool:
    if filters is None or not filters.active():
        return True
    if filters.source_types and note.source.type not in filters.source_types:
        return False
    if filters.source_ref_contains.strip():
        needle = filters.source_ref_contains.strip().lower()
        if needle not in (note.source.ref or "").lower():
            return False
    if filters.tags:
        note_tags = {tag.lower() for tag in note.tags}
        if not all(tag.lower() in note_tags for tag in filters.tags):
            return False
    if filters.metadata_contains.strip():
        metadata_text = " ".join(str(value) for value in note.source.metadata.values()).lower()
        if filters.metadata_contains.strip().lower() not in metadata_text:
            return False
    if filters.created_after.strip():
        try:
            if note.created_at < datetime.fromisoformat(filters.created_after.strip()):
                return False
        except (TypeError, ValueError):
            pass
    if filters.created_before.strip():
        try:
            if note.created_at > datetime.fromisoformat(filters.created_before.strip()):
                return False
        except (TypeError, ValueError):
            pass
    if filters.parent_note_id.strip():
        parent_id = filters.parent_note_id.strip()
        if note.id != parent_id and note.chunk.parent_note_id != parent_id:
            return False
    return True


class PostgresMemoryStore(PostgresStoreBase):
    """Postgres-backed source of truth for notes and reviews."""

    def __init__(
        self,
        data_dir: Path,
        postgres_url: str,
        *,
        embedding_provider: str = "local",
        embedding_model: str = "local-hash-v1",
        embedding_api_key: str | None = None,
        embedding_base_url: str | None = None,
        langsmith_config: LangSmithConfig | None = None,
    ) -> None:
        super().__init__(postgres_url)
        self.data_dir = data_dir
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model
        self.embedding_api_key = embedding_api_key
        self.embedding_base_url = embedding_base_url
        self.langsmith_config = langsmith_config or LangSmithConfig()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_search")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS knowledge_notes (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        parent_note_id TEXT,
                        source_fingerprint TEXT,
                        graph_episode_uuid TEXT,
                        payload JSONB NOT NULL,
                        search_text TEXT NOT NULL DEFAULT '',
                        embedding_vector VECTOR(128),
                        embedding_model TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS search_text TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS source_fingerprint TEXT")
                cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
                cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS deleted_by TEXT")
                cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS delete_reason TEXT")
                cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS delete_run_id TEXT")
                cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS delete_checkpoint_id TEXT")
                cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS delete_snapshot_id TEXT")
                # Legacy tsvector lexical path removed in favor of pg_search BM25.
                cur.execute("DROP INDEX IF EXISTS knowledge_notes_search_vector_idx")
                cur.execute("DROP INDEX IF EXISTS knowledge_notes_search_text_trgm_idx")
                cur.execute("ALTER TABLE knowledge_notes DROP COLUMN IF EXISTS search_vector")
                cur.execute(
                    """
                    DO $$
                    DECLARE
                        embedding_type text;
                    BEGIN
                        SELECT format_type(a.atttypid, a.atttypmod)
                        INTO embedding_type
                        FROM pg_attribute a
                        JOIN pg_class c ON c.oid = a.attrelid
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relname = 'knowledge_notes'
                          AND n.nspname = current_schema()
                          AND a.attname = 'embedding_vector'
                          AND NOT a.attisdropped;

                        IF embedding_type IS NULL THEN
                            ALTER TABLE knowledge_notes ADD COLUMN embedding_vector vector(128);
                        ELSIF embedding_type = 'double precision[]' THEN
                            ALTER TABLE knowledge_notes
                            ALTER COLUMN embedding_vector TYPE vector(128)
                            USING CASE
                                WHEN embedding_vector IS NULL THEN NULL
                                ELSE ('[' || array_to_string(embedding_vector, ',') || ']')::vector(128)
                            END;
                        ELSIF embedding_type <> 'vector(128)' THEN
                            ALTER TABLE knowledge_notes
                            ALTER COLUMN embedding_vector TYPE vector(128)
                            USING embedding_vector::text::vector(128);
                        END IF;
                    END $$;
                    """
                )
                cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS embedding_model TEXT")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_user_idx ON knowledge_notes (user_id, created_at)"
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS knowledge_notes_active_user_idx
                    ON knowledge_notes (user_id, created_at)
                    WHERE deleted_at IS NULL
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_parent_idx ON knowledge_notes (parent_note_id)"
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS knowledge_notes_deleted_idx
                    ON knowledge_notes (user_id, deleted_at DESC)
                    WHERE deleted_at IS NOT NULL
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_episode_idx ON knowledge_notes (graph_episode_uuid)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_fingerprint_idx ON knowledge_notes (user_id, source_fingerprint)"
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS knowledge_notes_embedding_hnsw_idx
                    ON knowledge_notes
                    USING hnsw (embedding_vector vector_cosine_ops)
                    """
                )
                # Backfill search_text for legacy rows (BM25 index reads this column).
                cur.execute(
                    """
                    UPDATE knowledge_notes
                    SET search_text = concat_ws(
                            ' ',
                            payload#>>'{body,title}',
                            payload#>>'{body,summary}',
                            payload#>>'{preextract,topic}',
                            payload#>>'{source,fingerprint}',
                            payload#>>'{source,metadata}',
                            payload#>>'{body,content}'
                        ),
                        source_fingerprint = COALESCE(source_fingerprint, payload#>>'{source,fingerprint}')
                    WHERE search_text = ''
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS knowledge_notes_bm25_idx
                    ON knowledge_notes
                    USING bm25 (id, search_text)
                    WITH (key_field='{_BM25_KEY_FIELD}', text_fields='{_bm25_text_fields_json()}')
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS review_cards (
                        id TEXT PRIMARY KEY,
                        note_id TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        due_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS review_cards_note_idx ON review_cards (note_id, due_at)"
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS knowledge_delete_snapshots (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        target_note_id TEXT NOT NULL,
                        deleted_by TEXT NOT NULL,
                        delete_reason TEXT NOT NULL DEFAULT '',
                        run_id TEXT,
                        checkpoint_id TEXT,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS knowledge_delete_snapshots_note_idx
                    ON knowledge_delete_snapshots (user_id, target_note_id, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_episodes (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        workflow TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        title TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        search_text TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute("DROP INDEX IF EXISTS memory_episodes_search_vector_idx")
                cur.execute("DROP INDEX IF EXISTS memory_episodes_search_text_trgm_idx")
                cur.execute("ALTER TABLE memory_episodes DROP COLUMN IF EXISTS search_vector")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS memory_episodes_user_idx ON memory_episodes (user_id, created_at DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS memory_episodes_thread_idx ON memory_episodes (thread_id, created_at DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS memory_episodes_workflow_idx ON memory_episodes (user_id, workflow, created_at DESC)"
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS memory_episodes_bm25_idx
                    ON memory_episodes
                    USING bm25 (id, search_text)
                    WITH (key_field='{_BM25_KEY_FIELD}', text_fields='{_bm25_text_fields_json()}')
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_items (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        search_text TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute("DROP INDEX IF EXISTS memory_items_search_vector_idx")
                cur.execute("DROP INDEX IF EXISTS memory_items_search_text_trgm_idx")
                cur.execute("ALTER TABLE memory_items DROP COLUMN IF EXISTS search_vector")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS memory_items_user_type_idx ON memory_items (user_id, memory_type, status, created_at DESC)"
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS memory_items_bm25_idx
                    ON memory_items
                    USING bm25 (id, search_text)
                    WITH (key_field='{_BM25_KEY_FIELD}', text_fields='{_bm25_text_fields_json()}')
                    """
                )
            conn.commit()
        self._initialized = True

    def add_note(self, note: KnowledgeNote) -> None:
        self._upsert_note(note)

    def update_note(self, note: KnowledgeNote) -> None:
        self._upsert_note(note)

    def _upsert_note(self, note: KnowledgeNote) -> None:
        self.ensure_schema()
        search_text = _search_text_for_note(note)
        embedding_vector = _vector_literal(self._embed_text(search_text))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO knowledge_notes
                        (
                            id, user_id, parent_note_id, graph_episode_uuid, payload,
                            source_fingerprint, search_text, embedding_vector, embedding_model,
                            created_at, updated_at, deleted_at, deleted_by, delete_reason,
                            delete_run_id, delete_checkpoint_id, delete_snapshot_id
                        )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s::vector(128), %s, %s, %s, NULL, NULL, NULL, NULL, NULL, NULL
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        parent_note_id = EXCLUDED.parent_note_id,
                        graph_episode_uuid = EXCLUDED.graph_episode_uuid,
                        payload = EXCLUDED.payload,
                        source_fingerprint = EXCLUDED.source_fingerprint,
                        search_text = EXCLUDED.search_text,
                        embedding_vector = EXCLUDED.embedding_vector,
                        embedding_model = EXCLUDED.embedding_model,
                        updated_at = EXCLUDED.updated_at,
                        deleted_at = NULL,
                        deleted_by = NULL,
                        delete_reason = NULL,
                        delete_run_id = NULL,
                        delete_checkpoint_id = NULL,
                        delete_snapshot_id = NULL
                    """,
                    (
                        note.id,
                        note.user_id,
                        note.chunk.parent_note_id,
                        note.graph.episode_uuid,
                        Jsonb(note.model_dump(mode="json")),
                        note.source.fingerprint,
                        search_text,
                        embedding_vector,
                        self.embedding_model,
                        note.created_at,
                        note.updated_at,
                    ),
                )
            conn.commit()

    def add_review(self, review: ReviewCard) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO review_cards (id, note_id, payload, due_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        note_id = EXCLUDED.note_id,
                        payload = EXCLUDED.payload,
                        due_at = EXCLUDED.due_at
                    """,
                    (review.id, review.note_id, Jsonb(review.model_dump(mode="json")), review.due_at),
                )
            conn.commit()

    def add_episode(self, episode: MemoryEpisode) -> None:
        self.ensure_schema()
        search_text = _search_text_for_episode(episode)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_episodes
                        (
                            id, user_id, session_id, thread_id, run_id, workflow, outcome,
                            title, summary, payload, search_text, created_at, updated_at
                        )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        session_id = EXCLUDED.session_id,
                        thread_id = EXCLUDED.thread_id,
                        run_id = EXCLUDED.run_id,
                        workflow = EXCLUDED.workflow,
                        outcome = EXCLUDED.outcome,
                        title = EXCLUDED.title,
                        summary = EXCLUDED.summary,
                        payload = EXCLUDED.payload,
                        search_text = EXCLUDED.search_text,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        episode.id,
                        episode.user_id,
                        episode.session_id,
                        episode.thread_id,
                        episode.run_id,
                        episode.workflow,
                        episode.outcome,
                        episode.title,
                        episode.summary,
                        Jsonb(episode.model_dump(mode="json")),
                        search_text,
                        episode.created_at,
                        episode.updated_at,
                    ),
                )
            conn.commit()

    def add_memory_item(self, item: MemoryItem) -> None:
        self.ensure_schema()
        search_text = _search_text_for_memory_item(item)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_items
                        (
                            id, user_id, memory_type, status, title, content,
                            payload, search_text, created_at, updated_at
                        )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        memory_type = EXCLUDED.memory_type,
                        status = EXCLUDED.status,
                        title = EXCLUDED.title,
                        content = EXCLUDED.content,
                        payload = EXCLUDED.payload,
                        search_text = EXCLUDED.search_text,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        item.id,
                        item.user_id,
                        item.memory_type,
                        item.status,
                        item.title,
                        item.content,
                        Jsonb(item.model_dump(mode="json")),
                        search_text,
                        item.created_at,
                        item.updated_at,
                    ),
                )
            conn.commit()

    def list_memory_items(
        self,
        user_id: str,
        *,
        memory_type: str | None = None,
        status: str | list[str] | None = None,
        limit: int = 50,
    ) -> list[MemoryItem]:
        self.ensure_schema()
        clauses = ["user_id = %s"]
        params: list[object] = [user_id]
        if memory_type:
            clauses.append("memory_type = %s")
            params.append(memory_type)
        if status:
            if isinstance(status, list):
                clauses.append("status = ANY(%s)")
                params.append(status)
            else:
                clauses.append("status = %s")
                params.append(status)
        params.append(max(1, limit))
        where_sql = " AND ".join(clauses)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM memory_items
                    WHERE {where_sql}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [MemoryItem.model_validate(row["payload"]) for row in cur.fetchall()]

    def search_memory_items(
        self,
        user_id: str,
        query: str,
        *,
        memory_type: str | None = None,
        status: str | list[str] | None = "confirmed",
        limit: int = 5,
    ) -> list[MemoryItem]:
        self.ensure_schema()
        normalized_query = _compact_whitespace(query)
        if not normalized_query:
            return self.list_memory_items(
                user_id, memory_type=memory_type, status=status, limit=limit
            )
        clauses = ["user_id = %s"]
        params: list[object] = [user_id]
        if memory_type:
            clauses.append("memory_type = %s")
            params.append(memory_type)
        if status:
            if isinstance(status, list):
                clauses.append("status = ANY(%s)")
                params.append(status)
            else:
                clauses.append("status = %s")
                params.append(status)
        where_sql = " AND ".join(clauses)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload,
                           paradedb.score(id) AS score
                    FROM memory_items
                    WHERE {where_sql}
                      AND id @@@ paradedb.match('search_text', %s)
                    ORDER BY score DESC, created_at DESC
                    LIMIT %s
                    """,
                    (
                        *params,
                        normalized_query,
                        max(1, limit),
                    ),
                )
                return [MemoryItem.model_validate(row["payload"]) for row in cur.fetchall()]

    def get_memory_item(self, item_id: str, *, user_id: str | None = None) -> MemoryItem | None:
        self.ensure_schema()
        clauses = ["id = %s"]
        params: list[object] = [item_id]
        if user_id is not None:
            clauses.append("user_id = %s")
            params.append(user_id)
        where_sql = " AND ".join(clauses)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT payload FROM memory_items WHERE {where_sql} LIMIT 1",
                    tuple(params),
                )
                row = cur.fetchone()
                return MemoryItem.model_validate(row["payload"]) if row else None

    def list_episodes(
        self,
        user_id: str,
        *,
        limit: int = 50,
        session_id: str | None = None,
        workflow: str | None = None,
        outcome: str | None = None,
    ) -> list[MemoryEpisode]:
        self.ensure_schema()
        clauses = ["user_id = %s"]
        params: list[object] = [user_id]
        if session_id:
            clauses.append("session_id = %s")
            params.append(session_id)
        if workflow:
            clauses.append("workflow = %s")
            params.append(workflow)
        if outcome:
            clauses.append("outcome = %s")
            params.append(outcome)
        params.append(max(1, limit))
        where_sql = " AND ".join(clauses)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM memory_episodes
                    WHERE {where_sql}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [MemoryEpisode.model_validate(row["payload"]) for row in cur.fetchall()]

    def search_episodes(
        self,
        user_id: str,
        query: str,
        *,
        limit: int = 5,
        session_id: str | None = None,
    ) -> list[MemoryEpisode]:
        self.ensure_schema()
        normalized_query = _compact_whitespace(query)
        if not normalized_query:
            return self.list_episodes(user_id, limit=limit, session_id=session_id)
        clauses = ["user_id = %s"]
        params: list[object] = [user_id]
        if session_id:
            clauses.append("session_id = %s")
            params.append(session_id)
        where_sql = " AND ".join(clauses)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload,
                           paradedb.score(id) AS score
                    FROM memory_episodes
                    WHERE {where_sql}
                      AND id @@@ paradedb.match('search_text', %s)
                    ORDER BY score DESC, created_at DESC
                    LIMIT %s
                    """,
                    (
                        *params,
                        normalized_query,
                        max(1, limit),
                    ),
                )
                rows = cur.fetchall()
        return [MemoryEpisode.model_validate(row["payload"]) for row in rows]

    def list_notes(self, user_id: str, *, include_chunks: bool = True) -> list[KnowledgeNote]:
        self.ensure_schema()
        clause = "" if include_chunks else " AND parent_note_id IS NULL"
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM knowledge_notes
                    WHERE user_id = %s AND deleted_at IS NULL{clause}
                    ORDER BY created_at
                    """,
                    (user_id,),
                )
                return [KnowledgeNote.model_validate(row["payload"]) for row in cur.fetchall()]

    def get_note(self, note_id: str, *, include_deleted: bool = False) -> KnowledgeNote | None:
        self.ensure_schema()
        deleted_sql = "" if include_deleted else "AND deleted_at IS NULL"
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT payload FROM knowledge_notes WHERE id = %s {deleted_sql}", (note_id,))
                row = cur.fetchone()
        return KnowledgeNote.model_validate(row["payload"]) if row else None

    def find_note_by_source_fingerprint(
        self,
        user_id: str,
        source_fingerprint: str | None,
    ) -> KnowledgeNote | None:
        if not source_fingerprint:
            return None
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM knowledge_notes
                    WHERE user_id = %s AND source_fingerprint = %s
                      AND deleted_at IS NULL
                    ORDER BY
                        CASE
                            WHEN coalesce(payload#>>'{version,status}', 'current') = 'current'
                                 AND coalesce(payload#>>'{version,superseded_by_note_id}', '') = ''
                            THEN 0 ELSE 1
                        END,
                        (parent_note_id IS NOT NULL),
                        created_at DESC
                    LIMIT 1
                    """,
                    (user_id, source_fingerprint),
                )
                row = cur.fetchone()
        return KnowledgeNote.model_validate(row["payload"]) if row else None

    def get_chunks_for_parent(self, parent_note_id: str) -> list[KnowledgeNote]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM knowledge_notes
                    WHERE parent_note_id = %s
                      AND deleted_at IS NULL
                    ORDER BY (payload#>>'{chunk,index}')::integer NULLS LAST
                    """,
                    (parent_note_id,),
                )
                return [KnowledgeNote.model_validate(row["payload"]) for row in cur.fetchall()]

    def get_parent_note(self, note_id: str) -> KnowledgeNote | None:
        note = self.get_note(note_id)
        if note is None or note.chunk.parent_note_id is None:
            return None
        return self.get_note(note.chunk.parent_note_id)

    def find_notes_by_graph_episode_uuids(
        self, user_id: str, episode_uuids: list[str], filters: RetrievalFilters | None = None
    ) -> list[KnowledgeNote]:
        if not episode_uuids:
            return []
        self.ensure_schema()
        filter_sql, filter_params = _filters_sql(filters)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM knowledge_notes
                    WHERE user_id = %s AND graph_episode_uuid = ANY(%s)
                    AND deleted_at IS NULL
                    {_active_version_sql()}
                    {filter_sql}
                    """,
                    (user_id, episode_uuids, *filter_params),
                )
                by_episode = {
                    note.graph.episode_uuid: note
                    for row in cur.fetchall()
                    for note in [KnowledgeNote.model_validate(row["payload"])]
                }
        return [by_episode[item] for item in episode_uuids if item in by_episode]

    def list_notes_by_graph_sync_status(
        self,
        *,
        user_id: str | None = None,
        statuses: list[str] | None = None,
        include_chunks: bool = True,
        limit: int | None = None,
    ) -> list[KnowledgeNote]:
        self.ensure_schema()
        clauses: list[str] = []
        params: list[object] = []
        if user_id is not None:
            clauses.append("user_id = %s")
            params.append(user_id)
        clauses.append("deleted_at IS NULL")
        if statuses:
            clauses.append("payload#>>'{graph_sync,status}' = ANY(%s)")
            params.append(statuses)
        if not include_chunks:
            clauses.append("parent_note_id IS NULL")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT %s"
            params.append(max(1, limit))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload FROM knowledge_notes
                    {where_sql}
                    ORDER BY updated_at DESC
                    {limit_sql}
                    """,
                    tuple(params),
                )
                return [KnowledgeNote.model_validate(row["payload"]) for row in cur.fetchall()]

    def find_similar_notes(
        self,
        user_id: str,
        query: str,
        limit: int = 8,
        filters: RetrievalFilters | None = None,
    ) -> list[KnowledgeNote]:
        self.ensure_schema()
        normalized_query = _compact_whitespace(query)
        if not normalized_query:
            return []

        start = time.monotonic()
        candidate_limit = max(limit * 8, 50)

        query_embedding = _vector_literal(self._embed_text(normalized_query))
        lexical_rows: list[dict] = []
        vector_rows: list[dict] = []
        filter_sql, filter_params = _filters_sql(filters)
        active_version_sql = _active_version_sql()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload,
                           paradedb.score(id) AS score
                    FROM knowledge_notes
                    WHERE user_id = %s
                      AND deleted_at IS NULL
                      {active_version_sql}
                      {filter_sql}
                      AND id @@@ paradedb.match('search_text', %s)
                    ORDER BY score DESC, updated_at DESC
                    LIMIT %s
                    """,
                    (
                        user_id,
                        *filter_params,
                        normalized_query,
                        candidate_limit,
                    ),
                )
                lexical_rows = list(cur.fetchall())
                if query_embedding:
                    cur.execute(
                        f"""
                        SELECT payload,
                               1 - (embedding_vector <=> %s::vector(128)) AS vector_score
                        FROM knowledge_notes
                        WHERE user_id = %s
                          AND deleted_at IS NULL
                          {active_version_sql}
                          {filter_sql}
                          AND embedding_vector IS NOT NULL
                          AND embedding_model = %s
                        ORDER BY embedding_vector <=> %s::vector(128)
                        LIMIT %s
                        """,
                        (
                            query_embedding,
                            user_id,
                            *filter_params,
                            self.embedding_model,
                            query_embedding,
                            candidate_limit,
                        ),
                    )
                    vector_rows = list(cur.fetchall())

        candidates = self._merge_lexical_and_vector_rows(
            lexical_rows,
            vector_rows,
            query_embedding,
            candidate_limit,
        )
        result = self._expand_ranked_notes(candidates, limit, filters)
        log_event(
            logger,
            logging.INFO,
            "retrieval.local",
            component="postgres_memory_store",
            provider="postgres",
            query_chars=len(normalized_query),
            limit=limit,
            candidate_limit=candidate_limit,
            lexical_candidates=len(lexical_rows),
            vector_candidates=len(vector_rows),
            merged_candidates=len(candidates),
            result_count=len(result),
            filters_active=bool(filters and filters.active()),
            embedding_used=query_embedding is not None,
            latency_ms=round((time.monotonic() - start) * 1000, 2),
        )
        return result

    def _embed_text(self, text: str) -> list[float] | None:
        if not text.strip():
            return None
        if self.embedding_provider == "local" or not self.embedding_api_key:
            log_local_embedding(
                model=self.embedding_model,
                input_chars=len(text),
                metadata={"component": "postgres_memory_store"},
            )
            return _local_embedding(text)
        try:
            result = traced_embedding(
                api_key=self.embedding_api_key,
                base_url=self.embedding_base_url,
                model=self.embedding_model,
                text=text,
                timeout_seconds=30.0,
                metadata={"component": "postgres_memory_store"},
                upload_inputs_outputs=self.langsmith_config.upload_inputs,
            )
            return result.vector
        except Exception as exc:
            log_embedding_fallback(
                model=self.embedding_model,
                provider=self.embedding_provider,
                input_chars=len(text[:8000]),
                reason=str(exc),
            )
            return _local_embedding(text)

    def _merge_lexical_and_vector_rows(
        self,
        lexical_rows: list[dict],
        vector_rows: list[dict],
        query_embedding: str | None,
        candidate_limit: int,
    ) -> list[KnowledgeNote]:
        scores: dict[str, float] = defaultdict(float)
        payloads: dict[str, object] = {}

        for rank, row in enumerate(lexical_rows, 1):
            note = KnowledgeNote.model_validate(row["payload"])
            payloads[note.id] = row["payload"]
            bm25_score = float(row["score"] or 0.0)
            # RRF on rank is the primary, scale-robust signal. BM25 raw scores are
            # unbounded (commonly 0~20+) and not comparable to cosine similarity,
            # so we add only a small saturating bonus instead of the old /100 scale.
            scores[note.id] += 1.0 / (60 + rank)
            scores[note.id] += _bm25_bonus(bm25_score)

        vector_scored: list[tuple[float, object, str]] = []
        if query_embedding:
            for row in vector_rows:
                similarity = float(row["vector_score"] or 0.0)
                if similarity <= 0.05:
                    continue
                note = KnowledgeNote.model_validate(row["payload"])
                vector_scored.append((similarity, row["payload"], note.id))
        vector_scored.sort(key=lambda item: item[0], reverse=True)

        for rank, (similarity, payload, note_id) in enumerate(vector_scored[:candidate_limit], 1):
            payloads[note_id] = payload
            scores[note_id] += 1.0 / (60 + rank)
            scores[note_id] += similarity / 10.0

        ranked_ids = sorted(scores, key=lambda note_id: scores[note_id], reverse=True)
        return [
            KnowledgeNote.model_validate(payloads[note_id])
            for note_id in ranked_ids[:candidate_limit]
            if note_id in payloads
        ]

    def _expand_ranked_notes(
        self,
        ranked_notes: list[KnowledgeNote],
        limit: int,
        filters: RetrievalFilters | None = None,
    ) -> list[KnowledgeNote]:
        results: list[KnowledgeNote] = []
        seen_note_ids: set[str] = set()
        seen_parent_ids: set[str] = set()

        def add(note: KnowledgeNote | None) -> None:
            if note is None or note.id in seen_note_ids:
                return
            if not _note_is_current(note):
                return
            if not _note_matches_filters(note, filters):
                return
            seen_note_ids.add(note.id)
            results.append(note)

        for note in ranked_notes:
            if len(results) >= limit:
                break
            if note.chunk.parent_note_id:
                add(note)
                parent = self.get_note(note.chunk.parent_note_id)
                add(parent)
                if note.chunk.parent_note_id not in seen_parent_ids:
                    seen_parent_ids.add(note.chunk.parent_note_id)
                    for neighbor in self._neighbor_chunks(note):
                        add(neighbor)
            else:
                add(note)
        return results[:limit]

    def _neighbor_chunks(self, note: KnowledgeNote) -> list[KnowledgeNote]:
        if note.chunk.parent_note_id is None or note.chunk.index is None:
            return []
        chunks = self.get_chunks_for_parent(note.chunk.parent_note_id)
        return [
            chunk for chunk in chunks
            if chunk.id != note.id
            and chunk.chunk.index is not None
            and abs(chunk.chunk.index - note.chunk.index) <= 1
        ]

    def due_reviews(self, user_id: str) -> list[ReviewCard]:
        now = local_now()
        return [
            review for review in self.list_reviews(user_id)
            if _with_local_timezone(review.due_at, now) <= now
        ]

    def list_reviews(self, user_id: str) -> list[ReviewCard]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT r.payload FROM review_cards r
                    JOIN knowledge_notes n ON n.id = r.note_id
                    WHERE n.user_id = %s AND n.deleted_at IS NULL
                    ORDER BY r.due_at
                    """,
                    (user_id,),
                )
                return [ReviewCard.model_validate(row["payload"]) for row in cur.fetchall()]

    def delete_note(
        self,
        note_id: str,
        user_id: str,
        cascade_chunks: bool = False,
        *,
        deleted_by: str | None = None,
        delete_reason: str = "",
        run_id: str | None = None,
        checkpoint_id: str | None = None,
    ) -> DeleteNoteStorageResult | None:
        target = self.get_note(note_id)
        if target is None or target.user_id != user_id:
            return None
        targets = [target]
        if cascade_chunks:
            targets.extend(note for note in self.get_chunks_for_parent(note_id) if note.user_id == user_id)
        ids = [note.id for note in targets]
        now = local_now()
        snapshot_id = f"kdel-{uuid4().hex}"
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM review_cards
                    WHERE note_id = ANY(%s)
                    ORDER BY due_at
                    """,
                    (ids,),
                )
                reviews = [ReviewCard.model_validate(row["payload"]) for row in cur.fetchall()]
                snapshot_payload = {
                    "snapshot_id": snapshot_id,
                    "user_id": user_id,
                    "target_note_id": note_id,
                    "deleted_by": deleted_by or user_id,
                    "delete_reason": delete_reason,
                    "run_id": run_id,
                    "checkpoint_id": checkpoint_id,
                    "deleted_at": now.isoformat(),
                    "notes": [note.model_dump(mode="json") for note in targets],
                    "review_cards": [review.model_dump(mode="json") for review in reviews],
                }
                cur.execute(
                    """
                    INSERT INTO knowledge_delete_snapshots (
                        id, user_id, target_note_id, deleted_by, delete_reason,
                        run_id, checkpoint_id, payload, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        snapshot_id,
                        user_id,
                        note_id,
                        deleted_by or user_id,
                        delete_reason,
                        run_id,
                        checkpoint_id,
                        Jsonb(snapshot_payload),
                        now,
                    ),
                )
                cur.execute(
                    """
                    UPDATE knowledge_notes
                    SET deleted_at = %s,
                        deleted_by = %s,
                        delete_reason = %s,
                        delete_run_id = %s,
                        delete_checkpoint_id = %s,
                        delete_snapshot_id = %s,
                        updated_at = %s
                    WHERE id = ANY(%s)
                      AND user_id = %s
                      AND deleted_at IS NULL
                    """,
                    (
                        now,
                        deleted_by or user_id,
                        delete_reason,
                        run_id,
                        checkpoint_id,
                        snapshot_id,
                        now,
                        ids,
                        user_id,
                    ),
                )
            conn.commit()
        return DeleteNoteStorageResult(
            target=target,
            notes=targets,
            review_cards=reviews,
            snapshot_id=snapshot_id,
        )

    def restore_note(
        self,
        *,
        user_id: str,
        note_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> RestoreNoteStorageResult | None:
        self.ensure_schema()
        if not note_id and not snapshot_id:
            raise ValueError("note_id or snapshot_id is required.")
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                if snapshot_id:
                    cur.execute(
                        """
                        SELECT id, payload FROM knowledge_delete_snapshots
                        WHERE id = %s AND user_id = %s
                        """,
                        (snapshot_id, user_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, payload FROM knowledge_delete_snapshots
                        WHERE target_note_id = %s AND user_id = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (note_id, user_id),
                    )
                row = cur.fetchone()
        if row is None:
            return None

        resolved_snapshot_id = str(row["id"])
        payload = row["payload"] or {}
        notes = [
            KnowledgeNote.model_validate(item)
            for item in payload.get("notes", [])
            if isinstance(item, dict)
        ]
        reviews = [
            ReviewCard.model_validate(item)
            for item in payload.get("review_cards", [])
            if isinstance(item, dict)
        ]
        if not notes:
            return None
        target_id = str(payload.get("target_note_id") or note_id or notes[0].id)
        target = next((item for item in notes if item.id == target_id), notes[0])
        if any(note.user_id != user_id for note in notes):
            return None

        with self._connect() as conn:
            with conn.cursor() as cur:
                for note in notes:
                    search_text = _search_text_for_note(note)
                    embedding_vector = _vector_literal(self._embed_text(search_text))
                    cur.execute(
                        """
                        INSERT INTO knowledge_notes
                            (
                                id, user_id, parent_note_id, graph_episode_uuid, payload,
                                source_fingerprint, search_text, embedding_vector, embedding_model,
                                created_at, updated_at, deleted_at, deleted_by, delete_reason,
                                delete_run_id, delete_checkpoint_id, delete_snapshot_id
                            )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s::vector(128), %s, %s, %s, NULL, NULL, NULL, NULL, NULL, NULL
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            user_id = EXCLUDED.user_id,
                            parent_note_id = EXCLUDED.parent_note_id,
                            graph_episode_uuid = EXCLUDED.graph_episode_uuid,
                            payload = EXCLUDED.payload,
                            source_fingerprint = EXCLUDED.source_fingerprint,
                            search_text = EXCLUDED.search_text,
                            embedding_vector = EXCLUDED.embedding_vector,
                            embedding_model = EXCLUDED.embedding_model,
                            updated_at = EXCLUDED.updated_at,
                            deleted_at = NULL,
                            deleted_by = NULL,
                            delete_reason = NULL,
                            delete_run_id = NULL,
                            delete_checkpoint_id = NULL,
                            delete_snapshot_id = NULL
                        """,
                        (
                            note.id,
                            note.user_id,
                            note.chunk.parent_note_id,
                            note.graph.episode_uuid,
                            Jsonb(note.model_dump(mode="json")),
                            note.source.fingerprint,
                            search_text,
                            embedding_vector,
                            self.embedding_model,
                            note.created_at,
                            local_now(),
                        ),
                    )
                for review in reviews:
                    cur.execute(
                        """
                        INSERT INTO review_cards (id, note_id, payload, due_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            note_id = EXCLUDED.note_id,
                            payload = EXCLUDED.payload,
                            due_at = EXCLUDED.due_at
                        """,
                        (review.id, review.note_id, Jsonb(review.model_dump(mode="json")), review.due_at),
                    )
            conn.commit()
        return RestoreNoteStorageResult(
            target=target,
            notes=notes,
            review_cards=reviews,
            snapshot_id=resolved_snapshot_id,
        )

    def clear_user_data(self, user_id: str, remove_uploaded_files: bool = True) -> dict[str, int]:
        notes = self.list_notes(user_id)
        ids = [note.id for note in notes]
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                if ids:
                    cur.execute("DELETE FROM review_cards WHERE note_id = ANY(%s)", (ids,))
                    removed_reviews = cur.rowcount or 0
                else:
                    removed_reviews = 0
                cur.execute("DELETE FROM knowledge_notes WHERE user_id = %s", (user_id,))
                removed_notes = cur.rowcount or 0
                cur.execute("DELETE FROM memory_episodes WHERE user_id = %s", (user_id,))
                removed_episodes = cur.rowcount or 0
                cur.execute("DELETE FROM memory_items WHERE user_id = %s", (user_id,))
                removed_memory_items = cur.rowcount or 0
            conn.commit()
        removed_uploads = self._remove_uploads(notes) if remove_uploaded_files else 0
        return {
            "notes": int(removed_notes),
            "reviews": int(removed_reviews),
            "episodes": int(removed_episodes),
            "memory_items": int(removed_memory_items),
            "conversations": 0,
            "uploads": removed_uploads,
        }

    def _remove_uploads(self, notes: list[KnowledgeNote]) -> int:
        uploads_dir = (self.data_dir / "uploads").resolve()
        removed = 0
        for note in notes:
            if not note.source.ref:
                continue
            try:
                source_path = Path(note.source.ref).resolve()
                if _is_relative_to(source_path, uploads_dir) and source_path.is_file():
                    source_path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _note_is_current(note: KnowledgeNote) -> bool:
    return note.version.status == "current" and note.version.superseded_by_note_id is None


def _active_version_sql() -> str:
    return (
        "AND coalesce(payload#>>'{version,status}', 'current') = 'current' "
        "AND coalesce(payload#>>'{version,superseded_by_note_id}', '') = ''"
    )
