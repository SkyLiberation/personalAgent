from __future__ import annotations

from datetime import UTC, datetime

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..tools.base import ToolInvocationEvent
from ..tools.gateway import ToolAuditSink, ToolGatewayContext, IdempotencyStore
from .postgres_common import PostgresStoreBase


class PostgresToolGovernanceStore(PostgresStoreBase, ToolAuditSink, IdempotencyStore):
    """Durable ledger and audit sink for governed tool side effects."""

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tool_idempotency_ledger (
                        idempotency_key TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        thread_id TEXT,
                        step_id TEXT,
                        tool_call_id TEXT,
                        user_id TEXT,
                        reserved_at TIMESTAMPTZ NOT NULL,
                        committed_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS tool_idempotency_ledger_lookup_idx
                    ON tool_idempotency_ledger (user_id, tool_name, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tool_audit_events (
                        id BIGSERIAL PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL,
                        tool_name TEXT NOT NULL,
                        tool_call_id TEXT NOT NULL,
                        thread_id TEXT,
                        step_id TEXT,
                        user_id TEXT,
                        execution_mode TEXT NOT NULL,
                        artifact_ok BOOLEAN,
                        error_kind TEXT,
                        side_effect_id TEXT,
                        payload JSONB NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS tool_audit_events_lookup_idx
                    ON tool_audit_events (user_id, tool_name, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS tool_audit_events_thread_idx
                    ON tool_audit_events (thread_id, step_id, created_at DESC)
                    """
                )
            conn.commit()
        self._initialized = True

    def seen(self, key: str) -> bool:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM tool_idempotency_ledger
                    WHERE idempotency_key = %s
                      AND status IN ('reserved', 'committed')
                    LIMIT 1
                    """,
                    (key,),
                )
                return cur.fetchone() is not None

    def reserve(self, key: str, *, context: ToolGatewayContext, tool_name: str) -> bool:
        self.ensure_schema()
        now = datetime.now(UTC)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tool_idempotency_ledger (
                        idempotency_key, status, tool_name, thread_id, step_id,
                        tool_call_id, user_id, reserved_at, updated_at, metadata
                    )
                    VALUES (%s, 'reserved', %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """,
                    (
                        key,
                        tool_name,
                        context.thread_id,
                        context.step_id,
                        context.tool_call_id,
                        context.user_id,
                        now,
                        now,
                        Jsonb({
                            "session_id": context.session_id,
                            "source_platform": context.source_platform,
                            "execution_mode": context.execution_mode,
                        }),
                    ),
                )
                inserted = (cur.rowcount or 0) == 1
            conn.commit()
        return inserted

    def commit(self, key: str) -> None:
        self.ensure_schema()
        now = datetime.now(UTC)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE tool_idempotency_ledger
                    SET status = 'committed',
                        committed_at = COALESCE(committed_at, %s),
                        updated_at = %s
                    WHERE idempotency_key = %s
                    """,
                    (now, now, key),
                )
            conn.commit()

    def release(self, key: str) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM tool_idempotency_ledger
                    WHERE idempotency_key = %s
                      AND status = 'reserved'
                    """,
                    (key,),
                )
            conn.commit()

    def record(self, event: ToolInvocationEvent) -> None:
        self.ensure_schema()
        payload = event.model_dump(mode="json")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tool_audit_events (
                        created_at, tool_name, tool_call_id, thread_id, step_id,
                        user_id, execution_mode, artifact_ok, error_kind,
                        side_effect_id, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        datetime.now(UTC),
                        event.tool_name,
                        event.tool_call_id,
                        event.thread_id,
                        event.step_id,
                        event.user_id,
                        event.execution_mode,
                        event.artifact_ok,
                        event.error_kind,
                        event.side_effect_id,
                        Jsonb(payload),
                    ),
                )
            conn.commit()
