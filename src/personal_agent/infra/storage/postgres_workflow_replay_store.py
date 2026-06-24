from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.infra.storage.postgres_common import PostgresStoreBase


@dataclass(frozen=True, slots=True)
class WorkflowArtifactRecord:
    artifact_id: str
    run_id: str
    kind: str
    payload: dict
    content_hash: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    redacted_at: datetime | None


@dataclass(frozen=True, slots=True)
class WorkflowReplayRecord:
    replay_id: str
    source_run_id: str
    source_thread_id: str
    source_checkpoint_id: str | None
    mode: str
    status: str
    new_run_id: str | None
    payload: dict
    created_at: datetime
    updated_at: datetime


class PostgresWorkflowReplayStore(PostgresStoreBase):
    """Durable artifact lookup and replay/fork metadata."""

    def ensure_schema(self) -> None:
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
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        expires_at TIMESTAMPTZ,
                        redacted_at TIMESTAMPTZ
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE workflow_artifacts ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"
                )
                cur.execute(
                    "ALTER TABLE workflow_artifacts ADD COLUMN IF NOT EXISTS redacted_at TIMESTAMPTZ"
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workflow_artifacts_run_kind_idx
                    ON workflow_artifacts (run_id, kind, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_replay_runs (
                        replay_id TEXT PRIMARY KEY,
                        source_run_id TEXT NOT NULL,
                        source_thread_id TEXT NOT NULL,
                        source_checkpoint_id TEXT,
                        mode TEXT NOT NULL,
                        status TEXT NOT NULL,
                        new_run_id TEXT,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workflow_replay_runs_source_idx
                    ON workflow_replay_runs (source_run_id, created_at DESC)
                    """
                )
        self._initialized = True

    def put_artifact(
        self,
        *,
        artifact_id: str,
        run_id: str,
        kind: str,
        payload: dict,
        retention_days: int | None = None,
    ) -> WorkflowArtifactRecord:
        self.ensure_schema()
        expires_at = None
        if retention_days is not None:
            expires_at = (
                datetime.now(UTC) - timedelta(seconds=1)
                if retention_days <= 0
                else datetime.now(UTC) + timedelta(days=retention_days)
            )
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        content_hash = sha256(canonical.encode("utf-8")).hexdigest()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workflow_artifacts (
                        artifact_id, run_id, kind, payload, content_hash, expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (artifact_id) DO UPDATE
                    SET payload = EXCLUDED.payload,
                        content_hash = EXCLUDED.content_hash,
                        expires_at = EXCLUDED.expires_at,
                        redacted_at = NULL,
                        updated_at = now()
                    RETURNING artifact_id, run_id, kind, payload, content_hash,
                              created_at, updated_at, expires_at, redacted_at
                    """,
                    (artifact_id, run_id, kind, Jsonb(payload), content_hash, expires_at),
                )
                row = cur.fetchone()
        return _artifact_from_row(row)

    def list_artifacts(
        self,
        run_id: str,
        *,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[WorkflowArtifactRecord]:
        if not run_id.strip():
            return []
        self.ensure_schema()
        clauses = ["run_id = %s"]
        params: list[object] = [run_id]
        if kind:
            clauses.append("kind = %s")
            params.append(kind)
        params.append(max(1, limit))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT artifact_id, run_id, kind, payload, content_hash,
                           created_at, updated_at, expires_at, redacted_at
                    FROM workflow_artifacts
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [_artifact_from_row(row) for row in rows]

    def get_artifact(self, artifact_id: str) -> WorkflowArtifactRecord | None:
        if not artifact_id.strip():
            return None
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT artifact_id, run_id, kind, payload, content_hash,
                           created_at, updated_at, expires_at, redacted_at
                    FROM workflow_artifacts
                    WHERE artifact_id = %s
                    """,
                    (artifact_id,),
                )
                row = cur.fetchone()
        return _artifact_from_row(row) if row else None

    def redact_artifact(
        self,
        artifact_id: str,
        *,
        keys: set[str] | None = None,
    ) -> WorkflowArtifactRecord | None:
        record = self.get_artifact(artifact_id)
        if record is None:
            return None
        sensitive = {key.lower() for key in (keys or {
            "answer",
            "content",
            "entry_text",
            "text",
            "tool_input",
            "result",
        })}
        payload = _redact_payload(record.payload, sensitive)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content_hash = sha256(canonical.encode("utf-8")).hexdigest()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE workflow_artifacts
                    SET payload = %s, content_hash = %s, redacted_at = now(), updated_at = now()
                    WHERE artifact_id = %s
                    RETURNING artifact_id, run_id, kind, payload, content_hash,
                              created_at, updated_at, expires_at, redacted_at
                    """,
                    (Jsonb(payload), content_hash, artifact_id),
                )
                row = cur.fetchone()
        return _artifact_from_row(row) if row else None

    def purge_expired_artifacts(self, *, limit: int = 1000) -> int:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM workflow_artifacts
                    WHERE artifact_id IN (
                        SELECT artifact_id
                        FROM workflow_artifacts
                        WHERE expires_at IS NOT NULL AND expires_at <= clock_timestamp()
                        ORDER BY expires_at
                        LIMIT %s
                    )
                    """,
                    (max(1, limit),),
                )
                return cur.rowcount or 0

    def create_replay_run(
        self,
        *,
        source_run_id: str,
        source_thread_id: str,
        source_checkpoint_id: str | None,
        mode: str,
        payload: dict | None = None,
        status: str = "started",
    ) -> WorkflowReplayRecord:
        self.ensure_schema()
        replay_id = f"replay-{uuid4().hex[:16]}"
        now_payload = dict(payload or {})
        now_payload.setdefault("created_from", source_run_id)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workflow_replay_runs (
                        replay_id, source_run_id, source_thread_id,
                        source_checkpoint_id, mode, status, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING replay_id, source_run_id, source_thread_id,
                              source_checkpoint_id, mode, status, new_run_id,
                              payload, created_at, updated_at
                    """,
                    (
                        replay_id,
                        source_run_id,
                        source_thread_id,
                        source_checkpoint_id,
                        mode,
                        status,
                        Jsonb(now_payload),
                    ),
                )
                row = cur.fetchone()
        return _replay_from_row(row)

    def finish_replay_run(
        self,
        replay_id: str,
        *,
        status: str,
        new_run_id: str | None = None,
        payload_update: dict | None = None,
    ) -> WorkflowReplayRecord | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE workflow_replay_runs
                    SET status = %s,
                        new_run_id = COALESCE(%s, new_run_id),
                        payload = payload || %s,
                        updated_at = now()
                    WHERE replay_id = %s
                    RETURNING replay_id, source_run_id, source_thread_id,
                              source_checkpoint_id, mode, status, new_run_id,
                              payload, created_at, updated_at
                    """,
                    (
                        status,
                        new_run_id,
                        Jsonb(payload_update or {}),
                        replay_id,
                    ),
                )
                row = cur.fetchone()
        return _replay_from_row(row) if row else None

    def list_replay_runs(
        self,
        source_run_id: str,
        *,
        limit: int = 50,
    ) -> list[WorkflowReplayRecord]:
        if not source_run_id.strip():
            return []
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT replay_id, source_run_id, source_thread_id,
                           source_checkpoint_id, mode, status, new_run_id,
                           payload, created_at, updated_at
                    FROM workflow_replay_runs
                    WHERE source_run_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (source_run_id, max(1, limit)),
                )
                rows = cur.fetchall()
        return [_replay_from_row(row) for row in rows]

    def build_debug_bundle(
        self,
        *,
        run_id: str,
        events: list[dict],
        history: list[dict],
        projection: dict | None = None,
    ) -> dict[str, object]:
        artifacts = [
            {
                "artifact_id": item.artifact_id,
                "kind": item.kind,
                "content_hash": item.content_hash,
                "updated_at": item.updated_at.isoformat(),
                "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                "redacted_at": item.redacted_at.isoformat() if item.redacted_at else None,
            }
            for item in self.list_artifacts(run_id, limit=100)
        ]
        replays = [
            {
                "replay_id": item.replay_id,
                "mode": item.mode,
                "status": item.status,
                "new_run_id": item.new_run_id,
                "source_checkpoint_id": item.source_checkpoint_id,
                "created_at": item.created_at.isoformat(),
            }
            for item in self.list_replay_runs(run_id, limit=50)
        ]
        return {
            "run_id": run_id,
            "events": events,
            "artifacts": artifacts,
            "history": history,
            "replays": replays,
            "projection": projection,
            "generated_at": datetime.now(UTC).isoformat(),
        }


def _artifact_from_row(row) -> WorkflowArtifactRecord:
    return WorkflowArtifactRecord(
        artifact_id=row["artifact_id"],
        run_id=row["run_id"],
        kind=row["kind"],
        payload=row["payload"] or {},
        content_hash=row["content_hash"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row.get("expires_at"),
        redacted_at=row.get("redacted_at"),
    )


def _replay_from_row(row) -> WorkflowReplayRecord:
    return WorkflowReplayRecord(
        replay_id=row["replay_id"],
        source_run_id=row["source_run_id"],
        source_thread_id=row["source_thread_id"],
        source_checkpoint_id=row["source_checkpoint_id"],
        mode=row["mode"],
        status=row["status"],
        new_run_id=row["new_run_id"],
        payload=row["payload"] or {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _redact_payload(value, keys: set[str]):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in keys else _redact_payload(item, keys)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_payload(item, keys) for item in value]
    return value
