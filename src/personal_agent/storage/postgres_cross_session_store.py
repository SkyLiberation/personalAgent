from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..core.models import Citation, local_now
from .postgres_common import PostgresStoreBase

MAX_CITATIONS = 30
MAX_DRAFTS = 10
MAX_CONCLUSIONS = 20
CITATION_TTL_HOURS = 24
DRAFT_TTL_HOURS = 48
CONCLUSION_TTL_HOURS = 72


class PostgresCrossSessionStore(PostgresStoreBase):
    """Database-backed transient artifacts shared across requests."""

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cross_session_artifacts (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        artifact_type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS cross_session_user_type_created_idx
                    ON cross_session_artifacts (user_id, artifact_type, created_at DESC)
                    """
                )
            conn.commit()
        self._initialized = True

    def add_citations(self, user_id: str, citations: list[Citation], question: str = "") -> None:
        now = local_now()
        for citation in citations:
            self._insert(
                user_id,
                "citation",
                {
                    "id": str(uuid4()),
                    "note_id": citation.note_id,
                    "title": citation.title,
                    "snippet": citation.snippet,
                    "relation_fact": citation.relation_fact,
                    "source_question": question,
                    "created_at": now.isoformat(),
                },
                now,
            )
        self._trim(user_id, "citation", CITATION_TTL_HOURS, MAX_CITATIONS)

    def recent_citations(self, user_id: str, limit: int = 10) -> list[dict]:
        return self._recent(user_id, "citation", CITATION_TTL_HOURS, limit)

    def save_draft(self, user_id: str, text: str, source_context: str = "") -> str:
        item_id = str(uuid4())
        now = local_now()
        self._insert(
            user_id,
            "draft",
            {
                "id": item_id,
                "text": text,
                "source_context": source_context,
                "status": "draft",
                "created_at": now.isoformat(),
            },
            now,
        )
        self._trim(user_id, "draft", DRAFT_TTL_HOURS, MAX_DRAFTS)
        return item_id

    def get_draft(self, user_id: str, draft_id: str) -> dict | None:
        return self._get(user_id, "draft", draft_id)

    def list_drafts(self, user_id: str, status: str | None = None) -> list[dict]:
        records = self._recent(user_id, "draft", DRAFT_TTL_HOURS, MAX_DRAFTS)
        return [item for item in records if status is None or item.get("status") == status]

    def mark_draft_status(self, user_id: str, draft_id: str, status: str) -> bool:
        return self._update_payload(user_id, "draft", draft_id, {"status": status})

    def add_conclusion(self, user_id: str, text: str, source_session_id: str = "") -> str:
        item_id = str(uuid4())
        now = local_now()
        self._insert(
            user_id,
            "conclusion",
            {
                "id": item_id,
                "text": text,
                "source_session_id": source_session_id,
                "solidified": False,
                "created_at": now.isoformat(),
            },
            now,
        )
        self._trim(user_id, "conclusion", CONCLUSION_TTL_HOURS, MAX_CONCLUSIONS)
        return item_id

    def list_conclusions(self, user_id: str, solidified: bool | None = None) -> list[dict]:
        records = self._recent(user_id, "conclusion", CONCLUSION_TTL_HOURS, MAX_CONCLUSIONS)
        return [item for item in records if solidified is None or item.get("solidified") == solidified]

    def mark_conclusion_solidified(self, user_id: str, conclusion_id: str) -> bool:
        return self._update_payload(user_id, "conclusion", conclusion_id, {"solidified": True})

    def clear_user(self, user_id: str) -> int:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM cross_session_artifacts WHERE user_id = %s", (user_id,))
                removed = cur.rowcount or 0
            conn.commit()
        return int(removed)

    def _insert(self, user_id: str, artifact_type: str, payload: dict, created_at: datetime) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cross_session_artifacts (id, user_id, artifact_type, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (payload["id"], user_id, artifact_type, Jsonb(payload), created_at),
                )
            conn.commit()

    def _get(self, user_id: str, artifact_type: str, item_id: str) -> dict | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM cross_session_artifacts
                    WHERE id = %s AND user_id = %s AND artifact_type = %s
                    """,
                    (item_id, user_id, artifact_type),
                )
                row = cur.fetchone()
        return row["payload"] if row else None

    def _recent(self, user_id: str, artifact_type: str, ttl_hours: int, limit: int) -> list[dict]:
        self.ensure_schema()
        cutoff = local_now() - timedelta(hours=ttl_hours)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload FROM cross_session_artifacts
                    WHERE user_id = %s AND artifact_type = %s AND created_at > %s
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (user_id, artifact_type, cutoff, limit),
                )
                rows = cur.fetchall()
        return [row["payload"] for row in reversed(rows)]

    def _update_payload(
        self, user_id: str, artifact_type: str, item_id: str, changes: dict
    ) -> bool:
        item = self._get(user_id, artifact_type, item_id)
        if item is None:
            return False
        item.update(changes)
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE cross_session_artifacts SET payload = %s WHERE id = %s",
                    (Jsonb(item), item_id),
                )
            conn.commit()
        return True

    def _trim(self, user_id: str, artifact_type: str, ttl_hours: int, maximum: int) -> None:
        self.ensure_schema()
        cutoff = local_now() - timedelta(hours=ttl_hours)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM cross_session_artifacts
                    WHERE user_id = %s AND artifact_type = %s AND created_at <= %s
                    """,
                    (user_id, artifact_type, cutoff),
                )
                cur.execute(
                    """
                    DELETE FROM cross_session_artifacts
                    WHERE id IN (
                        SELECT id FROM cross_session_artifacts
                        WHERE user_id = %s AND artifact_type = %s
                        ORDER BY created_at DESC OFFSET %s
                    )
                    """,
                    (user_id, artifact_type, maximum),
                )
            conn.commit()
