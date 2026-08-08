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
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


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
                    CREATE TABLE IF NOT EXISTS personal_investigation_projects (
                        project_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        create_idempotency_key TEXT NOT NULL,
                        definition_digest TEXT NOT NULL,
                        definition JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE (tenant_id, user_id, create_idempotency_key)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS personal_investigation_project_events (
                        event_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES personal_investigation_projects(project_id),
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
                    CREATE INDEX IF NOT EXISTS personal_investigation_project_owner_idx
                    ON personal_investigation_projects (tenant_id, user_id, project_id)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS personal_investigation_project_events_project_idx
                    ON personal_investigation_project_events (project_id, sequence)
                    """
                )
        self._initialized = True

    def create(self, definition: InvestigationProjectDefinition) -> InvestigationProject:
        from personal_agent.domain.investigation_project import canonical_digest

        self.ensure_schema()
        definition_digest = canonical_digest({
            "principal": definition.principal.model_dump(mode="json"),
            "title": definition.title,
            "goal": definition.goal,
            "user_requirements": definition.user_requirements.model_dump(
                mode="json",
                exclude={"created_at"},
            ),
            "budget": definition.budget.model_dump(mode="json"),
            "create_idempotency_key": definition.create_idempotency_key,
        })
        owner = definition.principal
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO personal_investigation_projects (
                        project_id, tenant_id, user_id,
                        create_idempotency_key, definition_digest, definition, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (
                        tenant_id, user_id, create_idempotency_key
                    ) DO NOTHING
                    RETURNING definition, definition_digest
                    """,
                    (
                        definition.project_id,
                        owner.tenant_id,
                        owner.user_id,
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
                        FROM personal_investigation_projects
                        WHERE tenant_id = %s
                          AND user_id = %s
                          AND create_idempotency_key = %s
                        """,
                        (
                            owner.tenant_id,
                            owner.user_id,
                            definition.create_idempotency_key,
                        ),
                    )
                    inserted = cur.fetchone()
                    if inserted["definition_digest"] != definition_digest:
                        raise ProjectIdempotencyConflict(
                            "create idempotency key is bound to a different definition"
                        )
        persisted = InvestigationProjectDefinition.model_validate(inserted["definition"])
        return self.load(persisted.principal, persisted.project_id) or InvestigationProject(
            definition=persisted
        )

    def load(
        self,
        owner: AuthenticatedPrincipal,
        project_id: str,
    ) -> InvestigationProject | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT definition
                    FROM personal_investigation_projects
                    WHERE project_id = %s AND tenant_id = %s AND user_id = %s
                    """,
                    (
                        project_id,
                        owner.tenant_id,
                        owner.user_id,
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                cur.execute(
                    """
                    SELECT payload
                    FROM personal_investigation_project_events
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
        owner: AuthenticatedPrincipal,
        project_id: str,
        expected_sequence: int,
        events: tuple[ProjectEvent, ...],
    ) -> InvestigationProject:
        self.ensure_schema()
        if not events:
            project = self.load(owner, project_id)
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
                    SELECT tenant_id, user_id
                    FROM personal_investigation_projects
                    WHERE project_id = %s
                    FOR UPDATE
                    """,
                    (project_id,),
                )
                persisted_owner = cur.fetchone()
                if persisted_owner is None:
                    raise KeyError(f"unknown project_id={project_id}")
                if (
                    persisted_owner["tenant_id"] != owner.tenant_id
                    or persisted_owner["user_id"] != owner.user_id
                ):
                    raise PermissionError("project belongs to a different principal")
                cur.execute(
                    """
                    SELECT COALESCE(MAX(sequence), 0) AS sequence
                    FROM personal_investigation_project_events
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
                        INSERT INTO personal_investigation_project_events (
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
        project = self.load(owner, project_id)
        if project is None:
            raise RuntimeError("project disappeared after event append")
        return project

    def list_recoverable(self, *, limit: int = 100) -> tuple[InvestigationProject, ...]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT project_id, tenant_id, user_id
                    FROM personal_investigation_projects
                    ORDER BY created_at
                    LIMIT %s
                    """,
                    (max(1, limit),),
                )
                rows = cur.fetchall()
        projects: list[InvestigationProject] = []
        for row in rows:
            owner = AuthenticatedPrincipal(
                tenant_id=row["tenant_id"],
                user_id=row["user_id"],
            )
            project = self.load(owner, row["project_id"])
            if project is not None and not project.is_terminal:
                projects.append(project)
        return tuple(projects)


__all__ = [
    "PostgresInvestigationProjectStore",
    "ProjectConcurrencyError",
    "ProjectIdempotencyConflict",
]
