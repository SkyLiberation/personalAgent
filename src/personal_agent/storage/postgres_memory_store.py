from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from hashlib import blake2b
from math import sqrt
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..core.models import KnowledgeNote, ReviewCard, local_now
from ..core.projections import retrieval_document_from_note
from ..core.query_understanding import RetrievalFilters
from .postgres_common import PostgresStoreBase


def _with_local_timezone(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value
    return value.replace(tzinfo=reference.tzinfo)


def _compact_whitespace(value: str) -> str:
    return " ".join(value.split())


_EMBEDDING_DIMENSIONS = 128


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
    ) -> None:
        super().__init__(postgres_url)
        self.data_dir = data_dir
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model
        self.embedding_api_key = embedding_api_key
        self.embedding_base_url = embedding_base_url
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
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
                        search_vector TSVECTOR NOT NULL DEFAULT ''::tsvector,
                        embedding_vector VECTOR(128),
                        embedding_model TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS search_text TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS source_fingerprint TEXT")
                cur.execute(
                    "ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS search_vector TSVECTOR NOT NULL DEFAULT ''::tsvector"
                )
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
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_parent_idx ON knowledge_notes (parent_note_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_episode_idx ON knowledge_notes (graph_episode_uuid)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_fingerprint_idx ON knowledge_notes (user_id, source_fingerprint)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_search_vector_idx ON knowledge_notes USING GIN (search_vector)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS knowledge_notes_search_text_trgm_idx ON knowledge_notes USING GIN (search_text gin_trgm_ops)"
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS knowledge_notes_embedding_hnsw_idx
                    ON knowledge_notes
                    USING hnsw (embedding_vector vector_cosine_ops)
                    """
                )
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
                        search_vector = to_tsvector(
                            'simple',
                            concat_ws(
                                ' ',
                                payload#>>'{body,title}',
                                payload#>>'{body,summary}',
                                payload#>>'{preextract,topic}',
                                payload#>>'{source,fingerprint}',
                                payload#>>'{source,metadata}',
                                payload#>>'{body,content}'
                            )
                        ),
                        source_fingerprint = COALESCE(source_fingerprint, payload#>>'{source,fingerprint}'),
                        embedding_vector = CASE
                            WHEN embedding_vector IS NULL THEN NULL
                            ELSE embedding_vector
                        END
                    WHERE search_text = '' OR search_vector = ''::tsvector
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
                            source_fingerprint, search_text, search_vector, embedding_vector, embedding_model,
                            created_at, updated_at
                        )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, to_tsvector('simple', %s),
                        %s::vector(128), %s, %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        parent_note_id = EXCLUDED.parent_note_id,
                        graph_episode_uuid = EXCLUDED.graph_episode_uuid,
                        payload = EXCLUDED.payload,
                        source_fingerprint = EXCLUDED.source_fingerprint,
                        search_text = EXCLUDED.search_text,
                        search_vector = EXCLUDED.search_vector,
                        embedding_vector = EXCLUDED.embedding_vector,
                        embedding_model = EXCLUDED.embedding_model,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        note.id,
                        note.user_id,
                        note.chunk.parent_note_id,
                        note.graph.episode_uuid,
                        Jsonb(note.model_dump(mode="json")),
                        note.source.fingerprint,
                        search_text,
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

    def list_notes(self, user_id: str, *, include_chunks: bool = True) -> list[KnowledgeNote]:
        self.ensure_schema()
        clause = "" if include_chunks else " AND parent_note_id IS NULL"
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT payload FROM knowledge_notes WHERE user_id = %s{clause} ORDER BY created_at",
                    (user_id,),
                )
                return [KnowledgeNote.model_validate(row["payload"]) for row in cur.fetchall()]

    def get_note(self, note_id: str) -> KnowledgeNote | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM knowledge_notes WHERE id = %s", (note_id,))
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
                    ORDER BY (parent_note_id IS NOT NULL), created_at DESC
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

        terms = _query_terms(normalized_query)
        patterns = [f"%{term}%" for term in terms[:12]] or [f"%{normalized_query}%"]
        candidate_limit = max(limit * 8, 50)

        query_embedding = _vector_literal(self._embed_text(normalized_query))
        lexical_rows: list[dict] = []
        vector_rows: list[dict] = []
        filter_sql, filter_params = _filters_sql(filters)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    WITH q AS (
                        SELECT plainto_tsquery('simple', %s) AS tsq
                    )
                    SELECT payload,
                           (
                               CASE WHEN search_vector @@ q.tsq THEN ts_rank_cd(search_vector, q.tsq) * 6 ELSE 0 END
                               + similarity(search_text, %s) * 3
                               + CASE WHEN lower(payload#>>'{{body,title}}') LIKE ANY(%s) THEN 4 ELSE 0 END
                               + CASE WHEN lower(payload#>>'{{body,summary}}') LIKE ANY(%s) THEN 2 ELSE 0 END
                               + CASE WHEN lower(coalesce(payload#>>'{{preextract,topic}}', '')) LIKE ANY(%s) THEN 2 ELSE 0 END
                               + CASE WHEN lower(payload#>>'{{body,content}}') LIKE ANY(%s) THEN 1 ELSE 0 END
                               + CASE WHEN parent_note_id IS NOT NULL THEN 0.25 ELSE 0 END
                           ) AS score
                    FROM knowledge_notes, q
                    WHERE user_id = %s
                      {filter_sql}
                      AND (
                          search_vector @@ q.tsq
                          OR search_text %% %s
                          OR lower(search_text) LIKE ANY(%s)
                      )
                    ORDER BY score DESC, updated_at DESC
                    LIMIT %s
                    """,
                    (
                        normalized_query,
                        normalized_query.lower(),
                        patterns,
                        patterns,
                        patterns,
                        patterns,
                        user_id,
                        *filter_params,
                        normalized_query.lower(),
                        patterns,
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
        return self._expand_ranked_notes(candidates, limit, filters)

    def _embed_text(self, text: str) -> list[float] | None:
        if not text.strip():
            return None
        if self.embedding_provider == "local" or not self.embedding_api_key:
            return _local_embedding(text)
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.embedding_api_key,
                base_url=self.embedding_base_url,
                timeout=30.0,
            )
            response = client.embeddings.create(model=self.embedding_model, input=text[:8000])
            return [float(value) for value in response.data[0].embedding]
        except Exception:
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
            score = float(row["score"] or 0.0)
            # RRF keeps strong lexical hits stable while still allowing vector recall.
            scores[note.id] += 1.0 / (60 + rank)
            scores[note.id] += min(score, 10.0) / 100.0

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
                    WHERE n.user_id = %s ORDER BY r.due_at
                    """,
                    (user_id,),
                )
                return [ReviewCard.model_validate(row["payload"]) for row in cur.fetchall()]

    def delete_note(self, note_id: str, user_id: str, cascade_chunks: bool = False) -> KnowledgeNote | None:
        target = self.get_note(note_id)
        if target is None or target.user_id != user_id:
            return None
        targets = [target]
        if cascade_chunks:
            targets.extend(note for note in self.get_chunks_for_parent(note_id) if note.user_id == user_id)
        ids = [note.id for note in targets]
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM review_cards WHERE note_id = ANY(%s)", (ids,))
                cur.execute("DELETE FROM knowledge_notes WHERE id = ANY(%s)", (ids,))
            conn.commit()
        self._remove_uploads(targets)
        return target

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
            conn.commit()
        removed_uploads = self._remove_uploads(notes) if remove_uploaded_files else 0
        return {
            "notes": int(removed_notes),
            "reviews": int(removed_reviews),
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
