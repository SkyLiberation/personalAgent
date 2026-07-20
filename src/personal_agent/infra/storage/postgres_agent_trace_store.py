"""Append-only persistence for non-canonical AgentEvent traces."""

from __future__ import annotations

from collections.abc import Iterable

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.infra.storage.postgres_common import PostgresStoreBase
from personal_agent.kernel.contracts.events import AgentEvent


class PostgresAgentTraceStore(PostgresStoreBase):
    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS agent_trace_events (
                        event_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS agent_trace_run_sequence_idx
                    ON agent_trace_events (run_id, sequence)
                """)
        self._initialized = True

    def record(self, events: Iterable[AgentEvent]) -> int:
        materialized = tuple(events)
        if not materialized:
            return 0
        self.ensure_schema()
        inserted = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM agent_trace_events WHERE run_id = %s",
                    (materialized[0].run_id,),
                )
                start = int(cur.fetchone()[0] or 0)
                for offset, event in enumerate(materialized, start=1):
                    cur.execute("""
                        INSERT INTO agent_trace_events (
                            event_id, run_id, thread_id, sequence, type, payload, timestamp
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (event_id) DO NOTHING
                    """, (
                        event.event_id, event.run_id, event.thread_id, start + offset,
                        event.type, Jsonb(event.payload), event.timestamp,
                    ))
                    inserted += cur.rowcount or 0
        return inserted

    def list_events(self, run_id: str) -> tuple[AgentEvent, ...]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT event_id, run_id, thread_id, type, payload, timestamp
                    FROM agent_trace_events WHERE run_id = %s ORDER BY sequence
                """, (run_id,))
                rows = cur.fetchall()
        return tuple(AgentEvent(
            event_id=row["event_id"], run_id=row["run_id"], thread_id=row["thread_id"],
            type=row["type"], payload=row["payload"] or {}, timestamp=row["timestamp"],
        ) for row in rows)


__all__ = ["PostgresAgentTraceStore"]
