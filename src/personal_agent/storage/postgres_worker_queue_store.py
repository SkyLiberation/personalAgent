from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from personal_agent.storage.postgres_common import PostgresStoreBase

WorkerTaskStatus = Literal["queued", "running", "completed", "failed", "dead"]


class WorkerTask(BaseModel):
    task_id: str
    queue: str
    task_type: str
    status: WorkerTaskStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    priority: int = 0
    attempts: int = 0
    max_attempts: int = 1
    leased_by: str | None = None
    leased_until: datetime | None = None
    due_at: datetime
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class PostgresWorkerQueueStore(PostgresStoreBase):
    """Durable worker queue with idempotent enqueue and lease-based claiming."""

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS worker_queue_tasks (
                        task_id TEXT PRIMARY KEY,
                        queue TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        priority INTEGER NOT NULL DEFAULT 0,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        max_attempts INTEGER NOT NULL DEFAULT 1,
                        leased_by TEXT,
                        leased_until TIMESTAMPTZ,
                        due_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        last_error TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS worker_queue_tasks_ready_idx
                    ON worker_queue_tasks (queue, status, priority DESC, due_at, created_at)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS worker_queue_tasks_type_idx
                    ON worker_queue_tasks (task_type, status, updated_at DESC)
                    """
                )
        self._initialized = True

    def enqueue(
        self,
        *,
        queue: str,
        task_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        priority: int = 0,
        max_attempts: int = 1,
        due_at: datetime | None = None,
    ) -> WorkerTask:
        self.ensure_schema()
        task_id = uuid4().hex
        due = due_at or datetime.now(UTC)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO worker_queue_tasks (
                        task_id, queue, task_type, status, payload, idempotency_key,
                        priority, max_attempts, due_at
                    )
                    VALUES (%s, %s, %s, 'queued', %s, %s, %s, %s, %s)
                    ON CONFLICT (idempotency_key) DO UPDATE
                    SET payload = CASE
                            WHEN worker_queue_tasks.status IN ('queued', 'failed', 'dead')
                            THEN EXCLUDED.payload
                            ELSE worker_queue_tasks.payload
                        END,
                        status = CASE
                            WHEN worker_queue_tasks.status IN ('failed', 'dead')
                            THEN 'queued'
                            ELSE worker_queue_tasks.status
                        END,
                        due_at = CASE
                            WHEN worker_queue_tasks.status IN ('queued', 'failed', 'dead')
                            THEN LEAST(worker_queue_tasks.due_at, EXCLUDED.due_at)
                            ELSE worker_queue_tasks.due_at
                        END,
                        updated_at = now()
                    RETURNING *
                    """,
                    (
                        task_id,
                        queue,
                        task_type,
                        Jsonb(payload),
                        idempotency_key,
                        priority,
                        max(1, max_attempts),
                        due,
                    ),
                )
                row = cur.fetchone()
        return _task_from_row(row)

    def lease_next(
        self,
        *,
        queue: str,
        worker_id: str,
        lease_seconds: int = 300,
        max_running_per_user: int = 0,
    ) -> WorkerTask | None:
        self.ensure_schema()
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=max(1, lease_seconds))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH candidate AS (
                        SELECT task_id
                        FROM worker_queue_tasks
                        WHERE queue = %s
                          AND (
                            status = 'queued'
                            OR (status = 'running' AND leased_until < %s)
                          )
                          AND due_at <= %s
                          AND (
                            %s <= 0
                            OR COALESCE(payload->>'user_id', '') = ''
                            OR (
                                SELECT COUNT(*)
                                FROM worker_queue_tasks running
                                WHERE running.queue = worker_queue_tasks.queue
                                  AND running.status = 'running'
                                  AND running.leased_until >= %s
                                  AND running.payload->>'user_id' = worker_queue_tasks.payload->>'user_id'
                            ) < %s
                          )
                        ORDER BY priority DESC, due_at ASC, created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE worker_queue_tasks t
                    SET status = 'running',
                        attempts = attempts + 1,
                        leased_by = %s,
                        leased_until = %s,
                        updated_at = now()
                    FROM candidate
                    WHERE t.task_id = candidate.task_id
                    RETURNING t.*
                    """,
                    (
                        queue,
                        now,
                        now,
                        max_running_per_user,
                        now,
                        max_running_per_user,
                        worker_id,
                        lease_until,
                    ),
                )
                row = cur.fetchone()
        return _task_from_row(row) if row else None

    def heartbeat(self, task_id: str, worker_id: str, *, lease_seconds: int = 300) -> bool:
        self.ensure_schema()
        lease_until = datetime.now(UTC) + timedelta(seconds=max(1, lease_seconds))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE worker_queue_tasks
                    SET leased_until = %s,
                        updated_at = now()
                    WHERE task_id = %s
                      AND status = 'running'
                      AND leased_by = %s
                    """,
                    (lease_until, task_id, worker_id),
                )
                return bool(cur.rowcount)

    def complete(self, task_id: str) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE worker_queue_tasks
                    SET status = 'completed',
                        leased_by = NULL,
                        leased_until = NULL,
                        last_error = NULL,
                        updated_at = now()
                    WHERE task_id = %s
                    """,
                    (task_id,),
                )

    def fail(self, task_id: str, error: str, *, retry_delay_seconds: int = 60) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE worker_queue_tasks
                    SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'failed' END,
                        leased_by = NULL,
                        leased_until = NULL,
                        due_at = CASE
                            WHEN attempts >= max_attempts THEN due_at
                            ELSE now() + (%s || ' seconds')::interval
                        END,
                        last_error = %s,
                        updated_at = now()
                    WHERE task_id = %s
                    """,
                    (max(0, retry_delay_seconds), error[:1000], task_id),
                )

    def retry_dead(self, task_id: str, *, due_at: datetime | None = None) -> bool:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE worker_queue_tasks
                    SET status = 'queued',
                        attempts = 0,
                        leased_by = NULL,
                        leased_until = NULL,
                        due_at = %s,
                        last_error = NULL,
                        updated_at = now()
                    WHERE task_id = %s AND status = 'dead'
                    """,
                    (due_at or datetime.now(UTC), task_id),
                )
                return bool(cur.rowcount)

    def queue_stats(self, queue: str | None = None) -> dict[str, int]:
        self.ensure_schema()
        where = "WHERE queue = %s" if queue else ""
        params = (queue,) if queue else ()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT status, COUNT(*) AS count
                    FROM worker_queue_tasks
                    {where}
                    GROUP BY status
                    """,
                    params,
                )
                rows = cur.fetchall()
        stats = {status: 0 for status in ("queued", "running", "completed", "failed", "dead")}
        for row in rows:
            stats[str(row["status"])] = int(row["count"])
        return stats

    def list_tasks(
        self,
        *,
        queue: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 100,
    ) -> list[WorkerTask]:
        self.ensure_schema()
        clauses: list[str] = []
        params: list[Any] = []
        if queue:
            clauses.append("queue = %s")
            params.append(queue)
        if statuses:
            clauses.append("status = ANY(%s)")
            params.append(statuses)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, limit))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM worker_queue_tasks
                    {where}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [_task_from_row(row) for row in rows]


def _task_from_row(row: dict[str, Any]) -> WorkerTask:
    return WorkerTask(
        task_id=row["task_id"],
        queue=row["queue"],
        task_type=row["task_type"],
        status=row["status"],
        payload=row["payload"] or {},
        idempotency_key=row["idempotency_key"],
        priority=int(row["priority"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        leased_by=row["leased_by"],
        leased_until=row["leased_until"],
        due_at=row["due_at"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
