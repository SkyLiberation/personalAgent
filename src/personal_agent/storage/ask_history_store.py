from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from psycopg import connect
from psycopg.rows import dict_row

from ..core.models import AskHistoryRecord, Citation

logger = logging.getLogger(__name__)


class AskHistoryStore:
    def __init__(self, postgres_url: str | None) -> None:
        self.postgres_url = postgres_url
        self._initialized = False

    def configured(self) -> bool:
        return bool(self.postgres_url)

    def _connect(self, *, row_factory: Any = None):
        if row_factory is None:
            return connect(_normalize_postgres_url(self.postgres_url))
        return connect(_normalize_postgres_url(self.postgres_url), row_factory=row_factory)

    def ensure_schema(self) -> None:
        if not self.configured() or self._initialized:
            return

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ask_history (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        session_id TEXT NOT NULL DEFAULT 'default',
                        question TEXT NOT NULL,
                        answer TEXT NOT NULL,
                        citations JSONB NOT NULL DEFAULT '[]'::jsonb,
                        graph_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS ask_history_user_created_at_idx
                    ON ask_history (user_id, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    ALTER TABLE ask_history
                    ADD COLUMN IF NOT EXISTS session_id TEXT NOT NULL DEFAULT 'default'
                    """
                )
            conn.commit()
        self._initialized = True
        logger.info("Ask history schema is ready in Postgres")

    def list_history(self, user_id: str, limit: int = 20, session_id: str | None = None) -> list[AskHistoryRecord]:
        if not self.configured():
            return []

        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                if session_id:
                    cur.execute(
                        """
                        SELECT id, user_id, session_id, question, answer, citations, graph_enabled, created_at
                        FROM ask_history
                        WHERE user_id = %s AND session_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (user_id, session_id, max(1, min(limit, 100))),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, user_id, session_id, question, answer, citations, graph_enabled, created_at
                        FROM ask_history
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (user_id, max(1, min(limit, 100))),
                    )
                rows = cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    def append(self, record: AskHistoryRecord) -> AskHistoryRecord:
        if not self.configured():
            return record

        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ask_history (id, user_id, session_id, question, answer, citations, graph_enabled, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        record.id,
                        record.user_id,
                        record.session_id,
                        record.question,
                        record.answer,
                        self._citations_json(record.citations),
                        record.graph_enabled,
                        record.created_at,
                    ),
                )
            conn.commit()
        return record

    def search_history(
        self, user_id: str, query: str, limit: int = 20, session_id: str | None = None,
    ) -> list[AskHistoryRecord]:
        if not self.configured() or not query.strip():
            return []

        self.ensure_schema()
        search_term = f"%{query.strip()}%"
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                if session_id:
                    cur.execute(
                        """
                        SELECT id, user_id, session_id, question, answer, citations, graph_enabled, created_at
                        FROM ask_history
                        WHERE user_id = %s AND session_id = %s
                          AND (question ILIKE %s OR answer ILIKE %s)
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (user_id, session_id, search_term, search_term, max(1, min(limit, 100))),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, user_id, session_id, question, answer, citations, graph_enabled, created_at
                        FROM ask_history
                        WHERE user_id = %s
                          AND (question ILIKE %s OR answer ILIKE %s)
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (user_id, search_term, search_term, max(1, min(limit, 100))),
                    )
                rows = cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete_record(self, user_id: str, record_id: str) -> bool:
        if not self.configured():
            return False

        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ask_history WHERE id = %s AND user_id = %s",
                    (record_id, user_id),
                )
                deleted = cur.rowcount or 0
            conn.commit()
        return deleted > 0

    def delete_session(self, user_id: str, session_id: str) -> int:
        if not self.configured():
            return 0

        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ask_history WHERE user_id = %s AND session_id = %s",
                    (user_id, session_id),
                )
                deleted_rows = cur.rowcount or 0
            conn.commit()
        return int(deleted_rows)

    def delete_history(self, user_id: str) -> int:
        if not self.configured():
            return 0

        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ask_history WHERE user_id = %s", (user_id,))
                deleted_rows = cur.rowcount or 0
            conn.commit()
        return int(deleted_rows)

    def _row_to_record(self, row: dict[str, Any]) -> AskHistoryRecord:
        citations = [Citation.model_validate(item) for item in (row.get("citations") or [])]
        return AskHistoryRecord(
            id=row["id"],
            user_id=row["user_id"],
            session_id=row.get("session_id", "default"),
            question=row["question"],
            answer=row["answer"],
            citations=citations,
            graph_enabled=bool(row["graph_enabled"]),
            created_at=row["created_at"],
        )

    def _citations_json(self, citations: list[Citation]) -> str:
        import json

        return json.dumps([citation.model_dump(mode="json") for citation in citations], ensure_ascii=False)


def _normalize_postgres_url(postgres_url: str | None) -> str:
    if not postgres_url:
        raise ValueError("Postgres URL is not configured.")

    parts = urlsplit(postgres_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("connect_timeout", "5")
    query.setdefault("sslmode", "disable")
    host = parts.hostname or ""
    if host == "localhost":
        host = "127.0.0.1"
        netloc = host
        if parts.username:
            auth = parts.username
            if parts.password:
                auth = f"{auth}:{parts.password}"
            netloc = f"{auth}@{netloc}"
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
    else:
        netloc = parts.netloc

    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), parts.fragment))
