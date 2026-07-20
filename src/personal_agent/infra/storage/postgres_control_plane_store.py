"""Canonical command/domain persistence and separate decision audit storage."""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel
from typing import TypeVar

from personal_agent.infra.storage.postgres_common import PostgresStoreBase
from personal_agent.runtime.contracts.control import ResolvedExecutionCommand
from personal_agent.runtime.contracts.task import ExecutionEvent


AuditRecordT = TypeVar("AuditRecordT", bound=BaseModel)


class ImmutableCommandConflict(RuntimeError):
    pass


class ImmutableDomainEventConflict(RuntimeError):
    pass


class PostgresControlPlaneStore(PostgresStoreBase):
    """Own immutable Commands, canonical DomainEvents, and Decision Audit records."""

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS resolved_execution_commands (
                        command_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        accepted_intent_ref TEXT NOT NULL,
                        supersedes_command_ref TEXT,
                        authorization_digest TEXT NOT NULL,
                        execution_command_digest TEXT NOT NULL UNIQUE,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS resolved_commands_run_created_idx
                    ON resolved_execution_commands (run_id, created_at)
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS canonical_domain_events (
                        event_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        UNIQUE (run_id, task_id, sequence)
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS decision_audit_records (
                        audit_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        turn_ref TEXT NOT NULL,
                        proposal_ref TEXT NOT NULL,
                        admission_ref TEXT NOT NULL,
                        verdict TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS decision_audit_run_recorded_idx
                    ON decision_audit_records (run_id, recorded_at)
                """)
        self._initialized = True

    def put_command(self, run_id: str, command: ResolvedExecutionCommand) -> None:
        self.ensure_schema()
        payload = command.model_dump(mode="json")
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM resolved_execution_commands WHERE command_id = %s",
                    (command.command_id,),
                )
                existing = cur.fetchone()
                if existing is not None:
                    restored = ResolvedExecutionCommand.model_validate(existing["payload"])
                    if restored != command:
                        raise ImmutableCommandConflict(
                            f"resolved command {command.command_id} is immutable"
                        )
                    return
                cur.execute("""
                    INSERT INTO resolved_execution_commands (
                        command_id, run_id, accepted_intent_ref, supersedes_command_ref,
                        authorization_digest, execution_command_digest, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    command.command_id,
                    run_id,
                    command.accepted_intent_ref,
                    command.supersedes_command_ref,
                    command.authorization_digest,
                    command.execution_command_digest,
                    Jsonb(payload),
                ))

    def get_command(self, command_id: str) -> ResolvedExecutionCommand | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM resolved_execution_commands WHERE command_id = %s",
                    (command_id,),
                )
                row = cur.fetchone()
        return ResolvedExecutionCommand.model_validate(row["payload"]) if row else None

    def list_commands(self, run_id: str) -> tuple[ResolvedExecutionCommand, ...]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT payload FROM resolved_execution_commands
                    WHERE run_id = %s ORDER BY created_at, command_id
                """, (run_id,))
                rows = cur.fetchall()
        return tuple(ResolvedExecutionCommand.model_validate(row["payload"]) for row in rows)

    def append_domain_event(self, run_id: str, event: ExecutionEvent) -> None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT event_type, payload FROM canonical_domain_events
                    WHERE run_id = %s AND task_id = %s AND sequence = %s
                """, (run_id, event.task_id, event.sequence))
                existing = cur.fetchone()
                if existing is not None:
                    if (
                        existing["event_type"] != event.event_type
                        or existing["payload"] != event.payload
                    ):
                        raise ImmutableDomainEventConflict(
                            f"domain event sequence {event.sequence} already has different facts"
                        )
                    return
                cur.execute("""
                    INSERT INTO canonical_domain_events (
                        event_id, run_id, task_id, sequence, event_type, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                """, (
                    event.event_id,
                    run_id,
                    event.task_id,
                    event.sequence,
                    event.event_type,
                    Jsonb(event.payload),
                ))

    def append_decision_audit(self, record: BaseModel) -> None:
        audit_id = str(getattr(record, "audit_id"))
        run_id = str(getattr(record, "run_id"))
        turn_ref = str(getattr(record, "turn_ref"))
        proposal = getattr(record, "proposal")
        admission = getattr(record, "admission")
        recorded_at = getattr(record, "recorded_at")
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO decision_audit_records (
                        audit_id, run_id, turn_ref, proposal_ref, admission_ref,
                        verdict, payload, recorded_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (audit_id) DO NOTHING
                """, (
                    audit_id,
                    run_id,
                    turn_ref,
                    proposal.proposal_id,
                    admission.admission_id,
                    admission.verdict,
                    Jsonb(record.model_dump(mode="json")),
                    recorded_at,
                ))

    def list_domain_events(self, run_id: str) -> tuple[ExecutionEvent, ...]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT event_id, sequence, task_id, event_type, payload
                    FROM canonical_domain_events
                    WHERE run_id = %s ORDER BY sequence, event_id
                """, (run_id,))
                rows = cur.fetchall()
        return tuple(ExecutionEvent(
            event_id=row["event_id"],
            sequence=row["sequence"],
            task_id=row["task_id"],
            event_type=row["event_type"],
            payload=row["payload"] or {},
        ) for row in rows)

    def list_decision_audit(
        self,
        run_id: str,
        record_type: type[AuditRecordT],
    ) -> tuple[AuditRecordT, ...]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT payload FROM decision_audit_records
                    WHERE run_id = %s ORDER BY recorded_at, audit_id
                """, (run_id,))
                rows = cur.fetchall()
        return tuple(record_type.model_validate(row["payload"]) for row in rows)


__all__ = [
    "ImmutableCommandConflict", "ImmutableDomainEventConflict", "PostgresControlPlaneStore",
]
