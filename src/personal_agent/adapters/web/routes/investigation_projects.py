"""HTTP interface for durable Investigation Project use cases."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.investigation_project import (
    ApproveInvestigationCommand,
    CancelInvestigationProject,
    CreateInvestigationProject,
    GetInvestigationReport,
    PauseInvestigationProject,
    QueryInvestigationProject,
    ResumeInvestigationProject,
    SteerInvestigationProject,
)
from personal_agent.domain.investigation_project import ProjectBudgetLimit, UserRequirement
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


class _CallerIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class CreateInvestigationProjectRequest(_CallerIdentity):
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    requirements: tuple[UserRequirement, ...] = Field(min_length=1)
    budget: ProjectBudgetLimit = Field(default_factory=ProjectBudgetLimit)
    idempotency_key: str = Field(min_length=1)


class SteerInvestigationProjectRequest(_CallerIdentity):
    expected_plan_version: int = Field(ge=1)
    statement: str = Field(min_length=1)
    waived_requirement_ids: tuple[str, ...] = ()
    added_requirements: tuple[UserRequirement, ...] = ()
    idempotency_key: str = Field(min_length=1)


class ApproveInvestigationCommandRequest(_CallerIdentity):
    authorization_digest: str = Field(min_length=16)


class CancelInvestigationProjectRequest(_CallerIdentity):
    reason: str = Field(default="user_cancelled", min_length=1)


class PauseInvestigationProjectRequest(_CallerIdentity):
    pass


class ResumeInvestigationProjectRequest(_CallerIdentity):
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
        principal = _resolve_principal(request, settings, body)
        try:
            view = service.create_investigation_project(CreateInvestigationProject(
                principal=principal,
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
        user_id: str = Query(min_length=1),
    ):
        principal = _resolve_principal_values(
            request,
            settings,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        try:
            return _view_payload(service.get_investigation_project(
                QueryInvestigationProject(
                    principal=principal,
                    project_id=project_id,
                )
            ))
        except (KeyError, PermissionError):
            raise HTTPException(status_code=404, detail="Resource not found.") from None

    @app.get("/api/investigation-projects/{project_id}/report")
    def get_project_report(
        project_id: str,
        request: Request,
        tenant_id: str = Query(min_length=1),
        user_id: str = Query(min_length=1),
    ):
        principal = _resolve_principal_values(
            request,
            settings,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        try:
            report = service.get_investigation_report(GetInvestigationReport(
                principal=principal,
                project_id=project_id,
            ))
        except (KeyError, PermissionError):
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return report.model_dump(mode="json")

    @app.post("/api/investigation-projects/{project_id}/steering")
    def steer_project(
        project_id: str,
        body: SteerInvestigationProjectRequest,
        request: Request,
    ):
        principal = _resolve_principal(request, settings, body)
        try:
            view = service.steer_investigation_project(SteerInvestigationProject(
                principal=principal,
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
        principal = _resolve_principal(request, settings, body)
        try:
            view = service.approve_investigation_command(ApproveInvestigationCommand(
                principal=principal,
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
        principal = _resolve_principal(request, settings, body)
        try:
            view = service.cancel_investigation_project(CancelInvestigationProject(
                principal=principal,
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
        principal = _resolve_principal(request, settings, body)
        try:
            return _view_payload(service.pause_investigation_project(
                PauseInvestigationProject(
                    principal=principal,
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
        principal = _resolve_principal(request, settings, body)
        try:
            return _view_payload(service.resume_investigation_project(
                ResumeInvestigationProject(
                    principal=principal,
                    project_id=project_id,
                )
            ))
        except KeyError:
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


def _resolve_principal(request: Request, settings: Settings, body: _CallerIdentity):
    return _resolve_principal_values(
        request,
        settings,
        tenant_id=body.tenant_id,
        user_id=body.user_id,
    )


def _resolve_principal_values(
    request: Request,
    settings: Settings,
    *,
    tenant_id: str,
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
    return principal


def _view_payload(view) -> dict:
    payload = view.model_dump(mode="json")
    payload["project_id"] = view.definition.project_id
    return payload


__all__ = ["register_investigation_project_routes"]
