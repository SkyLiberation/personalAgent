"""PostgreSQL canonical definition and append-only journal for Projects."""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.domain.investigation_project import (
    InvestigationProject,
    InvestigationProjectDefinition,
    ProjectEvent,
)
from personal_agent.infra.storage.postgres_common import PostgresStoreBase
from personal_agent.kernel.contracts.scope import SecurityScope


class ProjectConcurrencyError(RuntimeError):
    pass


class ProjectIdempotencyConflict(RuntimeError):
    pass


class PostgresInvestigationProjectStore(PostgresStoreBase):
    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS investigation_projects (
                        project_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        create_idempotency_key TEXT NOT NULL,
                        definition_digest TEXT NOT NULL,
                        definition JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE (tenant_id, workspace_id, principal_id, create_idempotency_key)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS investigation_project_events (
                        event_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES investigation_projects(project_id),
                        sequence INTEGER NOT NULL,
                        event_kind TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE (project_id, sequence)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS investigation_project_scope_idx
                    ON investigation_projects (tenant_id, workspace_id, project_id)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS investigation_project_events_project_idx
                    ON investigation_project_events (project_id, sequence)
                    """
                )
        self._initialized = True

    def create(self, definition: InvestigationProjectDefinition) -> InvestigationProject:
        from personal_agent.domain.investigation_project import canonical_digest

        self.ensure_schema()
        definition_digest = canonical_digest({
            "principal": definition.principal.model_dump(mode="json"),
            "security_scope": definition.security_scope.model_dump(mode="json"),
            "title": definition.title,
            "goal": definition.goal,
            "user_requirements": definition.user_requirements.model_dump(
                mode="json",
                exclude={"created_at"},
            ),
            "budget": definition.budget.model_dump(mode="json"),
            "create_idempotency_key": definition.create_idempotency_key,
        })
        scope = definition.security_scope
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO investigation_projects (
                        project_id, tenant_id, workspace_id, principal_id,
                        create_idempotency_key, definition_digest, definition, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (
                        tenant_id, workspace_id, principal_id, create_idempotency_key
                    ) DO NOTHING
                    RETURNING definition, definition_digest
                    """,
                    (
                        definition.project_id,
                        scope.tenant_id,
                        scope.workspace_id,
                        definition.principal.principal_id,
                        definition.create_idempotency_key,
                        definition_digest,
                        Jsonb(definition.model_dump(mode="json")),
                        definition.created_at,
                    ),
                )
                inserted = cur.fetchone()
                if inserted is None:
                    cur.execute(
                        """
                        SELECT definition, definition_digest
                        FROM investigation_projects
                        WHERE tenant_id = %s
                          AND workspace_id = %s
                          AND principal_id = %s
                          AND create_idempotency_key = %s
                        """,
                        (
                            scope.tenant_id,
                            scope.workspace_id,
                            definition.principal.principal_id,
                            definition.create_idempotency_key,
                        ),
                    )
                    inserted = cur.fetchone()
                    if inserted["definition_digest"] != definition_digest:
                        raise ProjectIdempotencyConflict(
                            "create idempotency key is bound to a different definition"
                        )
        persisted = InvestigationProjectDefinition.model_validate(inserted["definition"])
        return self.load(persisted.security_scope, persisted.project_id) or InvestigationProject(
            definition=persisted
        )

    def load(
        self,
        security_scope: SecurityScope,
        project_id: str,
    ) -> InvestigationProject | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT definition
                    FROM investigation_projects
                    WHERE project_id = %s AND tenant_id = %s AND workspace_id = %s
                    """,
                    (
                        project_id,
                        security_scope.tenant_id,
                        security_scope.workspace_id,
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                cur.execute(
                    """
                    SELECT payload
                    FROM investigation_project_events
                    WHERE project_id = %s
                    ORDER BY sequence
                    """,
                    (project_id,),
                )
                event_rows = cur.fetchall()
        definition = InvestigationProjectDefinition.model_validate(row["definition"])
        events = tuple(ProjectEvent.model_validate(item["payload"]) for item in event_rows)
        return InvestigationProject.rehydrate(definition, events)

    def append(
        self,
        *,
        security_scope: SecurityScope,
        project_id: str,
        expected_sequence: int,
        events: tuple[ProjectEvent, ...],
    ) -> InvestigationProject:
        self.ensure_schema()
        if not events:
            project = self.load(security_scope, project_id)
            if project is None:
                raise KeyError(f"unknown project_id={project_id}")
            return project
        expected_event_sequences = tuple(
            range(expected_sequence + 1, expected_sequence + len(events) + 1)
        )
        if tuple(event.sequence for event in events) != expected_event_sequences:
            raise ValueError("event batch does not continue expected sequence")
        if any(event.project_id != project_id for event in events):
            raise ValueError("event batch contains a different project id")
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tenant_id, workspace_id
                    FROM investigation_projects
                    WHERE project_id = %s
                    FOR UPDATE
                    """,
                    (project_id,),
                )
                owner = cur.fetchone()
                if owner is None:
                    raise KeyError(f"unknown project_id={project_id}")
                if (
                    owner["tenant_id"] != security_scope.tenant_id
                    or owner["workspace_id"] != security_scope.workspace_id
                ):
                    raise PermissionError("project belongs to a different security scope")
                cur.execute(
                    """
                    SELECT COALESCE(MAX(sequence), 0) AS sequence
                    FROM investigation_project_events
                    WHERE project_id = %s
                    """,
                    (project_id,),
                )
                actual = int(cur.fetchone()["sequence"])
                if actual != expected_sequence:
                    raise ProjectConcurrencyError(
                        f"stale project sequence: expected={expected_sequence} actual={actual}"
                    )
                for event in events:
                    cur.execute(
                        """
                        INSERT INTO investigation_project_events (
                            event_id, project_id, sequence, event_kind, payload, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            event.event_id,
                            event.project_id,
                            event.sequence,
                            event.data.kind,
                            Jsonb(event.model_dump(mode="json")),
                            event.created_at,
                        ),
                    )
        project = self.load(security_scope, project_id)
        if project is None:
            raise RuntimeError("project disappeared after event append")
        return project

    def list_recoverable(self, *, limit: int = 100) -> tuple[InvestigationProject, ...]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT project_id, tenant_id, workspace_id
                    FROM investigation_projects
                    ORDER BY created_at
                    LIMIT %s
                    """,
                    (max(1, limit),),
                )
                rows = cur.fetchall()
        projects: list[InvestigationProject] = []
        for row in rows:
            scope = SecurityScope(
                tenant_id=row["tenant_id"],
                workspace_id=row["workspace_id"],
            )
            project = self.load(scope, row["project_id"])
            if project is not None and not project.is_terminal:
                projects.append(project)
        return tuple(projects)


__all__ = [
    "PostgresInvestigationProjectStore",
    "ProjectConcurrencyError",
    "ProjectIdempotencyConflict",
]
