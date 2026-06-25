from __future__ import annotations

from typing import Iterable

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.kernel.contracts.events import AgentEvent
from personal_agent.infra.storage.postgres_common import PostgresStoreBase


class PostgresWorkflowEventStore(PostgresStoreBase):
    """Append-only workflow event log derived from public AgentEvents.

    ``AgentEvent`` remains the API/SSE projection. This store persists the same
    event stream as an internal immutable log so run debugging does not depend
    solely on the latest LangGraph checkpoint.
    """

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_events (
                        event_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workflow_events_run_sequence_idx
                    ON workflow_events (run_id, sequence)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workflow_events_thread_timestamp_idx
                    ON workflow_events (thread_id, timestamp)
                    """
                )
        self._initialized = True

    def record_agent_events(self, events: Iterable[AgentEvent]) -> int:
        materialized = list(events)
        if not materialized:
            return 0
        self.ensure_schema()
        inserted = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                max_sequence_by_run: dict[str, int] = {}
                for sequence, event in enumerate(materialized):
                    if event.run_id not in max_sequence_by_run:
                        cur.execute(
                            "SELECT COALESCE(MAX(sequence), -1) FROM workflow_events WHERE run_id = %s",
                            (event.run_id,),
                        )
                        current_max = cur.fetchone()[0]
                        max_sequence_by_run[event.run_id] = (
                            int(current_max) if current_max is not None else -1
                        )
                    cur.execute(
                        """
                        INSERT INTO workflow_events (
                            event_id, run_id, thread_id, sequence, type, payload, timestamp
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (event_id) DO NOTHING
                        """,
                        (
                            event.event_id,
                            event.run_id,
                            event.thread_id,
                            max_sequence_by_run[event.run_id] + sequence + 1,
                            event.type,
                            Jsonb(event.payload),
                            event.timestamp,
                        ),
                    )
                    inserted += cur.rowcount or 0
        return inserted

    def list_events(self, run_id: str) -> list[AgentEvent]:
        if not run_id.strip():
            return []
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT event_id, run_id, thread_id, type, payload, timestamp
                    FROM workflow_events
                    WHERE run_id = %s
                    ORDER BY sequence ASC, timestamp ASC
                    """,
                    (run_id,),
                )
                rows = cur.fetchall()
        return [
            AgentEvent(
                event_id=row["event_id"],
                run_id=row["run_id"],
                thread_id=row["thread_id"],
                type=row["type"],
                payload=row["payload"] or {},
                timestamp=row["timestamp"],
            )
            for row in rows
        ]
