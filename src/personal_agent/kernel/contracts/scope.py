"""Typed identity, resource-ownership, and execution-association scopes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _ScopeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthenticatedPrincipal(_ScopeModel):
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)

    @property
    def principal_id(self) -> str:
        return f"{self.tenant_id}:{self.user_id}"


class SecurityScope(_ScopeModel):
    tenant_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)


class ExecutionScope(_ScopeModel):
    """Association of one execution with its resource scope and parent run.

    Project fields are required for Investigation Project work. Other product
    entries use ``execution_id`` plus an explicit thread/conversation
    association without pretending that the interaction is a Project.
    """

    security_scope: SecurityScope
    principal_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    project_id: str | None = None
    plan_version: int | None = Field(default=None, ge=1)
    logical_subgoal_id: str | None = None
    subgoal_version: int | None = Field(default=None, ge=1)
    thread_id: str | None = None
    task_id: str | None = None

    @model_validator(mode="after")
    def validate_project_binding(self) -> "ExecutionScope":
        project_fields = (
            self.plan_version,
            self.logical_subgoal_id,
            self.subgoal_version,
        )
        if any(value is not None for value in project_fields) and self.project_id is None:
            raise ValueError("plan/subgoal execution fields require project_id")
        if (self.logical_subgoal_id is None) != (self.subgoal_version is None):
            raise ValueError("logical_subgoal_id and subgoal_version must be provided together")
        return self


def interaction_execution_scope(
    *,
    tenant_id: str,
    workspace_id: str,
    user_id: str,
    execution_id: str,
    thread_id: str | None = None,
    task_id: str | None = None,
) -> ExecutionScope:
    """Materialize a typed non-Project execution scope at an interface edge."""

    principal = AuthenticatedPrincipal(tenant_id=tenant_id, user_id=user_id)
    return ExecutionScope(
        security_scope=SecurityScope(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        ),
        principal_id=principal.principal_id,
        execution_id=execution_id,
        thread_id=thread_id,
        task_id=task_id,
    )


__all__ = [
    "AuthenticatedPrincipal",
    "ExecutionScope",
    "SecurityScope",
    "interaction_execution_scope",
]
