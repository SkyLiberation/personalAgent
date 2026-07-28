"""HTTP interface for durable Investigation Project use cases."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from personal_agent.application.investigation_project import (
    ApproveInvestigationCommand,
    CancelInvestigationProject,
    CreateInvestigationProject,
    PauseInvestigationProject,
    QueryInvestigationProject,
    ResumeInvestigationProject,
    SteerInvestigationProject,
)
from personal_agent.domain.investigation_project import ProjectBudgetLimit, UserRequirement
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, SecurityScope


class _CallerScope(BaseModel):
    tenant_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class CreateInvestigationProjectRequest(_CallerScope):
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    requirements: tuple[UserRequirement, ...] = Field(min_length=1)
    budget: ProjectBudgetLimit = Field(default_factory=ProjectBudgetLimit)
    idempotency_key: str = Field(min_length=1)


class SteerInvestigationProjectRequest(_CallerScope):
    expected_plan_version: int = Field(ge=1)
    statement: str = Field(min_length=1)
    waived_requirement_ids: tuple[str, ...] = ()
    added_requirements: tuple[UserRequirement, ...] = ()
    idempotency_key: str = Field(min_length=1)


class ApproveInvestigationCommandRequest(_CallerScope):
    authorization_digest: str = Field(min_length=16)


class CancelInvestigationProjectRequest(_CallerScope):
    reason: str = Field(default="user_cancelled", min_length=1)


class PauseInvestigationProjectRequest(_CallerScope):
    pass


class ResumeInvestigationProjectRequest(_CallerScope):
    pass


def register_investigation_project_routes(
    app: FastAPI,
    *,
    settings: Settings,
    service,
) -> None:
    @app.post(
        "/api/investigation-projects",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_project(
        body: CreateInvestigationProjectRequest,
        request: Request,
    ):
        principal, security_scope = _resolve_scope(request, settings, body)
        try:
            view = service.create_investigation_project(CreateInvestigationProject(
                principal=principal,
                security_scope=security_scope,
                title=body.title,
                goal=body.goal,
                requirements=body.requirements,
                budget=body.budget,
                idempotency_key=body.idempotency_key,
            ))
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _view_payload(view)

    @app.get("/api/investigation-projects/{project_id}")
    def get_project(
        project_id: str,
        request: Request,
        tenant_id: str = Query(min_length=1),
        workspace_id: str = Query(min_length=1),
        user_id: str = Query(min_length=1),
    ):
        principal, security_scope = _resolve_scope_values(
            request,
            settings,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        try:
            return _view_payload(service.get_investigation_project(
                QueryInvestigationProject(
                    principal=principal,
                    security_scope=security_scope,
                    project_id=project_id,
                )
            ))
        except (KeyError, PermissionError):
            raise HTTPException(status_code=404, detail="Resource not found.") from None

    @app.post("/api/investigation-projects/{project_id}/steering")
    def steer_project(
        project_id: str,
        body: SteerInvestigationProjectRequest,
        request: Request,
    ):
        principal, security_scope = _resolve_scope(request, settings, body)
        try:
            view = service.steer_investigation_project(SteerInvestigationProject(
                principal=principal,
                security_scope=security_scope,
                project_id=project_id,
                expected_plan_version=body.expected_plan_version,
                statement=body.statement,
                waived_requirement_ids=body.waived_requirement_ids,
                added_requirements=body.added_requirements,
                idempotency_key=body.idempotency_key,
            ))
        except KeyError:
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _view_payload(view)

    @app.post(
        "/api/investigation-projects/{project_id}/commands/{command_id}/decision"
    )
    def approve_command(
        project_id: str,
        command_id: str,
        body: ApproveInvestigationCommandRequest,
        request: Request,
    ):
        principal, security_scope = _resolve_scope(request, settings, body)
        try:
            view = service.approve_investigation_command(ApproveInvestigationCommand(
                principal=principal,
                security_scope=security_scope,
                project_id=project_id,
                command_id=command_id,
                authorization_digest=body.authorization_digest,
            ))
        except KeyError:
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _view_payload(view)

    @app.post("/api/investigation-projects/{project_id}/cancel")
    def cancel_project(
        project_id: str,
        body: CancelInvestigationProjectRequest,
        request: Request,
    ):
        principal, security_scope = _resolve_scope(request, settings, body)
        try:
            view = service.cancel_investigation_project(CancelInvestigationProject(
                principal=principal,
                security_scope=security_scope,
                project_id=project_id,
                reason=body.reason,
            ))
        except KeyError:
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _view_payload(view)

    @app.post("/api/investigation-projects/{project_id}/pause")
    def pause_project(
        project_id: str,
        body: PauseInvestigationProjectRequest,
        request: Request,
    ):
        principal, security_scope = _resolve_scope(request, settings, body)
        try:
            return _view_payload(service.pause_investigation_project(
                PauseInvestigationProject(
                    principal=principal,
                    security_scope=security_scope,
                    project_id=project_id,
                )
            ))
        except KeyError:
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/investigation-projects/{project_id}/resume")
    def resume_project(
        project_id: str,
        body: ResumeInvestigationProjectRequest,
        request: Request,
    ):
        principal, security_scope = _resolve_scope(request, settings, body)
        try:
            return _view_payload(service.resume_investigation_project(
                ResumeInvestigationProject(
                    principal=principal,
                    security_scope=security_scope,
                    project_id=project_id,
                )
            ))
        except KeyError:
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


def _resolve_scope(request: Request, settings: Settings, body: _CallerScope):
    return _resolve_scope_values(
        request,
        settings,
        tenant_id=body.tenant_id,
        workspace_id=body.workspace_id,
        user_id=body.user_id,
    )


def _resolve_scope_values(
    request: Request,
    settings: Settings,
    *,
    tenant_id: str,
    workspace_id: str,
    user_id: str,
):
    authenticated = getattr(request.state, "principal", None)
    if authenticated is not None:
        principal = AuthenticatedPrincipal.model_validate(authenticated)
        if principal.tenant_id != tenant_id or principal.user_id != user_id:
            raise HTTPException(status_code=404, detail="Resource not found.")
    elif settings.web.api_keys or settings.web.admin_api_keys:
        raise HTTPException(status_code=401, detail="Authenticated principal is missing.")
    else:
        principal = AuthenticatedPrincipal(tenant_id=tenant_id, user_id=user_id)
    return principal, SecurityScope(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )


def _view_payload(view) -> dict:
    payload = view.model_dump(mode="json")
    payload["project_id"] = view.definition.project_id
    return payload


__all__ = ["register_investigation_project_routes"]
