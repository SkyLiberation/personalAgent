from __future__ import annotations

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.infra.storage.postgres_common import PostgresStoreBase
from personal_agent.runtime.run_manager import DurableRun, RunLease, RunStateError


class PostgresDurableRunRepository(PostgresStoreBase):
    """Optimistic run repository shared by API and worker processes."""

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS durable_runs (
                        run_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        execution_mode TEXT NOT NULL,
                        fencing_token BIGINT NOT NULL,
                        revision BIGINT NOT NULL,
                        orphan_artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS durable_run_leases (
                        run_id TEXT PRIMARY KEY REFERENCES durable_runs(run_id) ON DELETE CASCADE,
                        lease_id TEXT NOT NULL,
                        fencing_token BIGINT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS durable_run_submissions (
                        idempotency_key TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES durable_runs(run_id) ON DELETE CASCADE
                    )
                    """
                )
        self._initialized = True

    def create(self, run: DurableRun) -> DurableRun:
        self.ensure_schema()
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO durable_runs (
                            run_id, status, execution_mode, fencing_token, revision,
                            orphan_artifact_refs
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            run.run_id,
                            run.status,
                            run.execution_mode,
                            run.fencing_token,
                            run.revision,
                            Jsonb(list(run.orphan_artifact_refs)),
                        ),
                    )
        except UniqueViolation as exc:
            raise RunStateError(f"run already exists: {run.run_id}") from exc
        return run

    def get(self, run_id: str) -> DurableRun | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM durable_runs WHERE run_id = %s", (run_id,))
                row = cur.fetchone()
        return _run_from_row(row) if row else None

    def compare_and_set(self, run: DurableRun, *, expected_revision: int) -> DurableRun:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE durable_runs
                    SET status = %s,
                        execution_mode = %s,
                        fencing_token = %s,
                        revision = %s,
                        orphan_artifact_refs = %s,
                        updated_at = now()
                    WHERE run_id = %s AND revision = %s
                    RETURNING *
                    """,
                    (
                        run.status,
                        run.execution_mode,
                        run.fencing_token,
                        run.revision,
                        Jsonb(list(run.orphan_artifact_refs)),
                        run.run_id,
                        expected_revision,
                    ),
                )
                row = cur.fetchone()
        if row is None:
            raise RunStateError("concurrent run update")
        return _run_from_row(row)

    def bind_submission(self, idempotency_key: str, run_id: str) -> str:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO durable_run_submissions (idempotency_key, run_id)
                    VALUES (%s, %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """,
                    (idempotency_key, run_id),
                )
                cur.execute(
                    "SELECT run_id FROM durable_run_submissions WHERE idempotency_key = %s",
                    (idempotency_key,),
                )
                row = cur.fetchone()
        return str(row[0])

    def get_submission(self, idempotency_key: str) -> str | None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_id FROM durable_run_submissions WHERE idempotency_key = %s",
                    (idempotency_key,),
                )
                row = cur.fetchone()
        return str(row[0]) if row else None

    def put_lease(self, run_id: str, lease: RunLease) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO durable_run_leases (
                        run_id, lease_id, fencing_token, expires_at
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE SET
                        lease_id = EXCLUDED.lease_id,
                        fencing_token = EXCLUDED.fencing_token,
                        expires_at = EXCLUDED.expires_at
                    WHERE durable_run_leases.fencing_token <= EXCLUDED.fencing_token
                    """,
                    (run_id, lease.lease_id, lease.fencing_token, lease.expires_at),
                )

    def get_lease(self, run_id: str) -> RunLease | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT lease_id, fencing_token, expires_at FROM durable_run_leases WHERE run_id = %s",
                    (run_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return RunLease(
            lease_id=str(row["lease_id"]),
            fencing_token=int(row["fencing_token"]),
            expires_at=row["expires_at"],
        )

    def renew_lease(self, run_id: str, lease: RunLease) -> bool:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE durable_run_leases
                    SET expires_at = %s
                    WHERE run_id = %s
                      AND lease_id = %s
                      AND fencing_token = %s
                    """,
                    (
                        lease.expires_at,
                        run_id,
                        lease.lease_id,
                        lease.fencing_token,
                    ),
                )
                return cur.rowcount == 1


def _run_from_row(row) -> DurableRun:
    return DurableRun(
        run_id=str(row["run_id"]),
        status=str(row["status"]),
        execution_mode=str(row["execution_mode"]),
        fencing_token=int(row["fencing_token"]),
        revision=int(row["revision"]),
        orphan_artifact_refs=tuple(row["orphan_artifact_refs"] or ()),
    )


__all__ = ["PostgresDurableRunRepository"]
