from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.kernel.contracts.tool import ToolInvocationEvent
from personal_agent.kernel.contracts.tool_runtime import (
    IdempotencyStore,
    ToolAuditSink,
    ToolGatewayContext,
)
from personal_agent.infra.storage.audit_redaction import redact_audit_payload
from personal_agent.infra.storage.postgres_common import PostgresStoreBase

# 表示一次确认动作被幂等机制拦截（重复副作用）的审计错误特征。
_DUPLICATE_SIDE_EFFECT_MARKER = "已执行过或正在执行"


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
                        run_id TEXT,
                        user_id TEXT,
                        execution_mode TEXT NOT NULL,
                        risk_level TEXT,
                        requires_confirmation BOOLEAN,
                        confirmed BOOLEAN,
                        artifact_ok BOOLEAN,
                        error_kind TEXT,
                        error TEXT,
                        latency_ms DOUBLE PRECISION,
                        attempts INTEGER,
                        side_effect_id TEXT,
                        payload JSONB NOT NULL
                    )
                    """
                )
                # 不考虑兼容旧库：对已存在的表补齐新增列。
                for column, ddl in (
                    ("run_id", "ALTER TABLE tool_audit_events ADD COLUMN IF NOT EXISTS run_id TEXT"),
                    ("risk_level", "ALTER TABLE tool_audit_events ADD COLUMN IF NOT EXISTS risk_level TEXT"),
                    (
                        "requires_confirmation",
                        "ALTER TABLE tool_audit_events ADD COLUMN IF NOT EXISTS requires_confirmation BOOLEAN",
                    ),
                    ("confirmed", "ALTER TABLE tool_audit_events ADD COLUMN IF NOT EXISTS confirmed BOOLEAN"),
                    ("error", "ALTER TABLE tool_audit_events ADD COLUMN IF NOT EXISTS error TEXT"),
                    (
                        "latency_ms",
                        "ALTER TABLE tool_audit_events ADD COLUMN IF NOT EXISTS latency_ms DOUBLE PRECISION",
                    ),
                    ("attempts", "ALTER TABLE tool_audit_events ADD COLUMN IF NOT EXISTS attempts INTEGER"),
                ):
                    cur.execute(ddl)
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
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS tool_audit_events_risk_idx
                    ON tool_audit_events (risk_level, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS tool_audit_events_side_effect_idx
                    ON tool_audit_events (side_effect_id, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tool_policy_decisions (
                        id BIGSERIAL PRIMARY KEY,
                        created_at TIMESTAMPTZ NOT NULL,
                        action TEXT NOT NULL,
                        effect TEXT NOT NULL,
                        rule TEXT NOT NULL,
                        reason TEXT,
                        tool_name TEXT,
                        permission_scope TEXT,
                        resource TEXT,
                        risk_level TEXT,
                        user_id TEXT,
                        session_id TEXT,
                        source_platform TEXT,
                        execution_mode TEXT,
                        thread_id TEXT,
                        run_id TEXT,
                        langsmith_run_id TEXT
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS tool_policy_decisions_effect_idx
                    ON tool_policy_decisions (effect, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS tool_policy_decisions_user_idx
                    ON tool_policy_decisions (user_id, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS tool_policy_decisions_tool_idx
                    ON tool_policy_decisions (tool_name, created_at DESC)
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
                            "run_id": context.run_id,
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
                        run_id, user_id, execution_mode, risk_level,
                        requires_confirmation, confirmed, artifact_ok, error_kind,
                        error, latency_ms, attempts, side_effect_id, payload
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        datetime.now(UTC),
                        event.tool_name,
                        event.tool_call_id,
                        event.thread_id,
                        event.step_id,
                        event.run_id,
                        event.user_id,
                        event.execution_mode,
                        event.risk_level,
                        event.requires_confirmation,
                        event.confirmed,
                        event.artifact_ok,
                        event.error_kind,
                        event.error,
                        event.latency_ms,
                        event.attempts,
                        event.side_effect_id,
                        Jsonb(payload),
                    ),
                )
            conn.commit()

    def record_policy_decision(self, payload: dict[str, Any]) -> None:
        """Persist a policy decision so authorization outcomes stay queryable."""
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tool_policy_decisions (
                        created_at, action, effect, rule, reason, tool_name,
                        permission_scope, resource, risk_level, user_id, session_id,
                        source_platform, execution_mode, thread_id, run_id, langsmith_run_id
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        datetime.now(UTC),
                        payload.get("action", "unknown"),
                        payload.get("effect", "unknown"),
                        payload.get("rule", ""),
                        payload.get("reason"),
                        payload.get("tool_name"),
                        payload.get("permission_scope"),
                        payload.get("resource"),
                        payload.get("risk_level"),
                        payload.get("user_id"),
                        payload.get("session_id"),
                        payload.get("source_platform"),
                        payload.get("execution_mode"),
                        payload.get("thread_id"),
                        payload.get("run_id"),
                        payload.get("langsmith_run_id"),
                    ),
                )
            conn.commit()

    # -- query API ---------------------------------------------------------

    def query_audit_events(
        self,
        *,
        user_id: str | None = None,
        tool_name: str | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        risk_level: str | None = None,
        execution_mode: str | None = None,
        side_effect_id: str | None = None,
        artifact_ok: bool | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        reveal: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return tool audit events filtered by governance dimensions.

        ``reveal=False`` (the default) masks user content in each event's
        ``payload`` so non-admin callers never see knowledge text or PII.
        """
        self.ensure_schema()
        clauses: list[str] = []
        params: list[Any] = []
        filters = (
            ("user_id", user_id),
            ("tool_name", tool_name),
            ("thread_id", thread_id),
            ("run_id", run_id),
            ("risk_level", risk_level),
            ("execution_mode", execution_mode),
            ("side_effect_id", side_effect_id),
        )
        for column, value in filters:
            if value is not None:
                clauses.append(f"{column} = %s")
                params.append(value)
        if artifact_ok is not None:
            clauses.append("artifact_ok = %s")
            params.append(artifact_ok)
        if since is not None:
            clauses.append("created_at >= %s")
            params.append(since)
        if until is not None:
            clauses.append("created_at <= %s")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, created_at, tool_name, tool_call_id, thread_id, step_id,
                           run_id, user_id, execution_mode, risk_level,
                           requires_confirmation, confirmed, artifact_ok, error_kind,
                           error, latency_ms, attempts, side_effect_id, payload
                    FROM tool_audit_events
                    {where}
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [self._serialize_audit_row(row, reveal=reveal) for row in rows]

    def query_policy_decisions(
        self,
        *,
        user_id: str | None = None,
        tool_name: str | None = None,
        effect: str | None = None,
        action: str | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.ensure_schema()
        clauses: list[str] = []
        params: list[Any] = []
        filters = (
            ("user_id", user_id),
            ("tool_name", tool_name),
            ("effect", effect),
            ("action", action),
            ("thread_id", thread_id),
            ("run_id", run_id),
        )
        for column, value in filters:
            if value is not None:
                clauses.append(f"{column} = %s")
                params.append(value)
        if since is not None:
            clauses.append("created_at >= %s")
            params.append(since)
        if until is not None:
            clauses.append("created_at <= %s")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, created_at, action, effect, rule, reason, tool_name,
                           permission_scope, resource, risk_level, user_id, session_id,
                           source_platform, execution_mode, thread_id, run_id, langsmith_run_id
                    FROM tool_policy_decisions
                    {where}
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [self._serialize_row(row) for row in rows]

    def trace_idempotency(self, key: str, *, reveal: bool = False) -> dict[str, Any] | None:
        """Return the full lifecycle of one confirmed tool call by its key.

        Combines the idempotency ledger row, every audit event sharing the key
        as ``side_effect_id``, and any policy decisions on the same run/thread —
        answering "who confirmed what, when, and was it executed".
        """
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT idempotency_key, status, tool_name, thread_id, step_id,
                           tool_call_id, user_id, reserved_at, committed_at, updated_at, metadata
                    FROM tool_idempotency_ledger
                    WHERE idempotency_key = %s
                    """,
                    (key,),
                )
                ledger = cur.fetchone()
        events = self.query_audit_events(side_effect_id=key, reveal=reveal, limit=200)
        if ledger is None and not events:
            return None
        return {
            "idempotency_key": key,
            "ledger": self._serialize_row(ledger) if ledger else None,
            "events": events,
        }

    def audit_metrics(self, *, window_hours: int = 24) -> dict[str, Any]:
        """Aggregate audit signals over a recent window for metrics and alerts."""
        self.ensure_schema()
        since = datetime.now(UTC) - timedelta(hours=max(1, window_hours))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE risk_level = 'high') AS high_risk,
                        COUNT(*) FILTER (WHERE artifact_ok IS FALSE) AS failures,
                        COUNT(*) FILTER (
                            WHERE 'delete_longterm' = ANY(
                                ARRAY(SELECT jsonb_array_elements_text(payload->'side_effects'))
                            )
                        ) AS deletes,
                        COUNT(*) FILTER (
                            WHERE artifact_ok IS FALSE
                              AND 'delete_longterm' = ANY(
                                ARRAY(SELECT jsonb_array_elements_text(payload->'side_effects'))
                              )
                        ) AS delete_failures,
                        COUNT(*) FILTER (WHERE error LIKE %s) AS duplicate_side_effects
                    FROM tool_audit_events
                    WHERE created_at >= %s
                    """,
                    (f"%{_DUPLICATE_SIDE_EFFECT_MARKER}%", since),
                )
                audit = cur.fetchone() or {}
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE effect IN ('deny', 'require_escalation')) AS denials
                    FROM tool_policy_decisions
                    WHERE created_at >= %s
                    """,
                    (since,),
                )
                policy = cur.fetchone() or {}
        total = int(audit.get("total") or 0)
        failures = int(audit.get("failures") or 0)
        deletes = int(audit.get("deletes") or 0)
        delete_failures = int(audit.get("delete_failures") or 0)
        return {
            "window_hours": window_hours,
            "total_invocations": total,
            "high_risk_invocations": int(audit.get("high_risk") or 0),
            "failures": failures,
            "failure_rate": round(failures / total, 4) if total else 0.0,
            "deletes": deletes,
            "delete_failures": delete_failures,
            "delete_failure_rate": round(delete_failures / deletes, 4) if deletes else 0.0,
            "duplicate_side_effects": int(audit.get("duplicate_side_effects") or 0),
            "policy_denials": int(policy.get("denials") or 0),
        }

    # -- serialization helpers --------------------------------------------

    @staticmethod
    def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
        serialized: dict[str, Any] = {}
        for key, value in row.items():
            serialized[key] = value.isoformat() if isinstance(value, datetime) else value
        return serialized

    def _serialize_audit_row(self, row: dict[str, Any], *, reveal: bool) -> dict[str, Any]:
        serialized = self._serialize_row(row)
        payload = serialized.get("payload")
        if isinstance(payload, dict):
            serialized["payload"] = redact_audit_payload(payload, reveal=reveal)
        return serialized
