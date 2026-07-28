"""Durable child-Agent definition, submission binding, and projection store."""

from __future__ import annotations

from dataclasses import asdict

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.infra.storage.postgres_common import PostgresStoreBase
from personal_agent.kernel.contracts.agent import (
    AgentArtifact,
    AgentGatewayContext,
    AgentTask,
    ChildAgentArtifactIndex,
    ChildAgentRunDefinition,
    ChildAgentRunEvent,
    ChildAgentRunProjection,
    ChildAgentRunRecord,
    ReservedAgentSubmission,
)
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.contracts.resource import ResourceRef


class AgentSubmissionConflict(RuntimeError):
    pass


class PostgresAgentRunStore(PostgresStoreBase):
    """Canonical production store for child-Agent lifecycle state."""

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_runs (
                        agent_run_id TEXT PRIMARY KEY,
                        submission_key TEXT NOT NULL UNIQUE,
                        definition_digest TEXT NOT NULL,
                        parent_run_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        provider_task_id TEXT,
                        payload JSONB NOT NULL,
                        revision INTEGER NOT NULL DEFAULT 1,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS agent_runs_parent_idx
                    ON agent_runs (parent_run_id, agent_id)
                    """
                )
        self._initialized = True

    def reserve_submission(
        self,
        *,
        submission_key: str,
        definition_digest: str,
        definition: ChildAgentRunDefinition,
    ) -> ReservedAgentSubmission:
        self.ensure_schema()
        run = _reserved_record(definition)
        payload = _record_payload(run)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_runs (
                        agent_run_id, submission_key, definition_digest,
                        parent_run_id, agent_id, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (submission_key) DO NOTHING
                    RETURNING payload
                    """,
                    (
                        definition.agent_run_id,
                        submission_key,
                        definition_digest,
                        definition.context.execution_scope.execution_id,
                        definition.agent_id,
                        Jsonb(payload),
                    ),
                )
                inserted = cur.fetchone()
                if inserted is not None:
                    return ReservedAgentSubmission(
                        _record_from_payload(inserted["payload"]),
                        created=True,
                    )
                cur.execute(
                    """
                    SELECT definition_digest, payload
                    FROM agent_runs
                    WHERE submission_key = %s
                    """,
                    (submission_key,),
                )
                existing = cur.fetchone()
        if existing is None:
            raise RuntimeError("submission reservation disappeared")
        if existing["definition_digest"] != definition_digest:
            raise AgentSubmissionConflict(
                "submission_key is bound to a different child definition"
            )
        return ReservedAgentSubmission(
            _record_from_payload(existing["payload"]),
            created=False,
        )

    def commit_submission(
        self,
        *,
        submission_key: str,
        definition_digest: str,
        run: ChildAgentRunRecord,
    ) -> ChildAgentRunRecord:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_runs
                    SET provider_task_id = %s,
                        payload = %s,
                        revision = revision + 1,
                        updated_at = NOW()
                    WHERE submission_key = %s
                      AND definition_digest = %s
                    RETURNING payload
                    """,
                    (
                        run.projection.external_task_id,
                        Jsonb(_record_payload(run)),
                        submission_key,
                        definition_digest,
                    ),
                )
                row = cur.fetchone()
        if row is None:
            raise AgentSubmissionConflict(
                "submission reservation or definition digest does not match"
            )
        return _record_from_payload(row["payload"])

    def put(self, run: ChildAgentRunRecord) -> ChildAgentRunRecord:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_runs
                    SET provider_task_id = %s,
                        payload = %s,
                        revision = revision + 1,
                        updated_at = NOW()
                    WHERE agent_run_id = %s
                    RETURNING payload
                    """,
                    (
                        run.projection.external_task_id,
                        Jsonb(_record_payload(run)),
                        run.definition.agent_run_id,
                    ),
                )
                row = cur.fetchone()
        if row is None:
            raise KeyError(
                f"Unknown agent_run_id={run.definition.agent_run_id!r}."
            )
        return _record_from_payload(row["payload"])

    def get(self, agent_run_id: str) -> ChildAgentRunRecord | None:
        return self._find("agent_run_id = %s", (agent_run_id,))

    def get_by_submission_key(
        self,
        submission_key: str,
    ) -> ChildAgentRunRecord | None:
        return self._find("submission_key = %s", (submission_key,))

    def list(
        self,
        *,
        run_id: str | None = None,
        agent_id: str | None = None,
    ) -> tuple[ChildAgentRunRecord, ...]:
        self.ensure_schema()
        clauses: list[str] = []
        values: list[str] = []
        if run_id is not None:
            clauses.append("parent_run_id = %s")
            values.append(run_id)
        if agent_id is not None:
            clauses.append("agent_id = %s")
            values.append(agent_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT payload FROM agent_runs {where} ORDER BY updated_at",  # noqa: S608
                    tuple(values),
                )
                rows = cur.fetchall()
        return tuple(_record_from_payload(row["payload"]) for row in rows)

    def _find(
        self,
        predicate: str,
        values: tuple[str, ...],
    ) -> ChildAgentRunRecord | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT payload FROM agent_runs WHERE {predicate}",  # noqa: S608
                    values,
                )
                row = cur.fetchone()
        return _record_from_payload(row["payload"]) if row is not None else None


def _reserved_record(
    definition: ChildAgentRunDefinition,
) -> ChildAgentRunRecord:
    return ChildAgentRunRecord(
        definition=definition,
        projection=ChildAgentRunProjection(
            agent_run_id=definition.agent_run_id,
            status="created",
        ),
        artifact_index=ChildAgentArtifactIndex(
            agent_run_id=definition.agent_run_id,
        ),
    )


def _record_payload(run: ChildAgentRunRecord) -> dict[str, object]:
    payload = asdict(run)
    payload["definition"]["context"]["execution_scope"] = (
        run.definition.context.execution_scope.model_dump(mode="json")
    )
    for index, artifact in enumerate(run.artifact_index.artifacts):
        payload["artifact_index"]["artifacts"][index]["artifact_ref"] = (
            artifact.artifact_ref.model_dump(mode="json")
        )
    return payload


def _record_from_payload(payload: dict) -> ChildAgentRunRecord:
    definition_payload = payload["definition"]
    task_payload = definition_payload["task"]
    context_payload = definition_payload["context"]
    definition = ChildAgentRunDefinition(
        agent_run_id=definition_payload["agent_run_id"],
        agent_id=definition_payload["agent_id"],
        task=AgentTask(
            task_text=task_payload["task_text"],
            task_type=task_payload.get("task_type", "research"),
            input=dict(task_payload.get("input") or {}),
            metadata=dict(task_payload.get("metadata") or {}),
        ),
        context=AgentGatewayContext(
            execution_scope=ExecutionScope.model_validate(
                context_payload["execution_scope"]
            ),
            source_platform=context_payload.get("source_platform", ""),
            confirmed=bool(context_payload.get("confirmed", False)),
        ),
        submission_key=definition_payload.get("submission_key", ""),
        authorization_digest=definition_payload.get("authorization_digest", ""),
        execution_command_digest=definition_payload.get(
            "execution_command_digest",
            "",
        ),
    )
    projection_payload = payload["projection"]
    projection = ChildAgentRunProjection(
        agent_run_id=definition.agent_run_id,
        status=projection_payload["status"],
        external_task_id=projection_payload.get("external_task_id"),
        result=dict(projection_payload.get("result") or {}),
        error=projection_payload.get("error"),
    )
    artifacts = tuple(
        AgentArtifact(
            agent_run_id=item["agent_run_id"],
            kind=item["kind"],
            artifact_ref=ResourceRef.model_validate(item["artifact_ref"]),
            producer_verification_status=item.get(
                "producer_verification_status",
                "unverified",
            ),
        )
        for item in payload.get("artifact_index", {}).get("artifacts", ())
    )
    events = tuple(
        ChildAgentRunEvent(
            event_id=item["event_id"],
            agent_run_id=definition.agent_run_id,
            type=item["type"],
            payload=dict(item.get("payload") or {}),
        )
        for item in payload.get("events", ())
    )
    return ChildAgentRunRecord(
        definition=definition,
        projection=projection,
        artifact_index=ChildAgentArtifactIndex(
            agent_run_id=definition.agent_run_id,
            artifacts=artifacts,
        ),
        events=events,
    )


__all__ = ["AgentSubmissionConflict", "PostgresAgentRunStore"]
