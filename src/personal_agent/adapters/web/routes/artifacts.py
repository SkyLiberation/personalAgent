"""Authenticated original Artifact upload/download without knowledge ingestion."""

from urllib.parse import quote, urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from personal_agent.adapters.web.routes._shared import (
    auth_is_disabled,
    resolve_requested_principal,
)
from personal_agent.application.artifacts import ArtifactService
from personal_agent.application.artifacts.models import ArtifactResourceItem
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


class ArtifactResourceView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource: ArtifactResourceItem
    download_url: str


def artifact_resource_view(
    resource: ArtifactResourceItem,
    *,
    principal: AuthenticatedPrincipal,
    settings: Settings,
) -> ArtifactResourceView:
    """Project a relative path; the download endpoint still resolves identity."""
    ref = resource.resource_ref
    path = (
        f"/api/artifacts/{quote(ref.resource_id, safe='')}/revisions/{ref.revision}"
    )
    if auth_is_disabled(settings) and principal.user_id != settings.default_user:
        path += "?" + urlencode({"user_id": principal.user_id})
    return ArtifactResourceView(resource=resource, download_url=path)


def register_artifact_routes(
    app: FastAPI, *, settings: Settings, artifact_service: ArtifactService
) -> None:
    @app.post("/api/artifacts/upload", response_model=ArtifactResourceView)
    def upload_artifact(
        request: Request, file: UploadFile = File(...), user_id: str | None = Form(None)
    ) -> ArtifactResourceView:
        principal = resolve_requested_principal(request, settings, user_id)
        try:
            ref = artifact_service.save_upload(
                filename=file.filename or "upload",
                content_type=file.content_type,
                file_bytes=file.file.read(),
                uploads_dir=settings.data_dir / "uploads",
                principal=principal,
                owner=principal,
            )
            return artifact_resource_view(
                artifact_service.resource_item(
                    ref, principal=principal, owner=principal
                ),
                principal=principal,
                settings=settings,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/artifacts/{resource_id}/revisions/{revision}")
    def download_artifact(
        resource_id: str, revision: int, request: Request, user_id: str | None = None
    ) -> Response:
        principal = resolve_requested_principal(request, settings, user_id)
        try:
            ref = ResourceRef(
                resource_id=resource_id,
                resource_type="artifact",
                revision=revision,
                owner=principal,
            )
            record, content = artifact_service.read_upload(
                ref, principal=principal, owner=principal
            )
        except (PermissionError, FileNotFoundError, KeyError):
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return Response(
            content=content,
            media_type=record.content_type or "application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(record.filename, safe='')}"
            },
        )
