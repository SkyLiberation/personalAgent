from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from personal_agent.adapters.web.routes._shared import (
    auth_is_disabled,
    is_admin,
    resolve_principal,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.orchestration.service import AgentService
from personal_agent.tools import tool_governance
from personal_agent.kernel.contracts.scope import interaction_execution_scope

logger = logging.getLogger(__name__)


class ResetDebugDataResponse(BaseModel):
    deleted_notes: int = 0
    deleted_reviews: int = 0
    deleted_upload_files: int = 0
    deleted_graph_nodes: int = 0
    deleted_checkpoints: int = 0
    deleted_checkpoint_blobs: int = 0
    deleted_checkpoint_writes: int = 0
    deleted_checkpoint_migrations: int = 0
    truncated_postgres_tables: int = 0
    deleted_postgres_rows: int = 0


class ToolDescriptionResponse(BaseModel):
    name: str
    description: str
    exposure: str = "public_agent"


class ToolExecuteRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    kwargs: dict[str, object] = Field(default_factory=dict)


class ToolExecuteResponse(BaseModel):
    ok: bool
    data: object = None
    error: str | None = None
    deleted_graph_episodes: int = 0


def register_system_routes(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
) -> None:
    @app.get("/api/health")
    def health() -> dict[str, object]:
        logger.debug("Health check requested")
        return service.health()

    @app.get("/api/tools", response_model=list[ToolDescriptionResponse])
    def list_tools() -> list[dict[str, object]]:
        specs = service.list_tools()
        return [
            {
                "name": s.name,
                "description": s.description,
                "exposure": tool_governance(s).exposure,
            }
            for s in specs
        ]

    @app.get("/api/capabilities/inventory")
    def capability_inventory() -> dict[str, object]:
        return service.capability_inventory().model_dump(mode="json")

    @app.post("/api/tools/{name}/execute", response_model=ToolExecuteResponse)
    def execute_tool(
        name: str,
        body: ToolExecuteRequest,
        request: Request,
    ) -> dict[str, object]:
        if auth_is_disabled(settings):
            principal = AuthenticatedPrincipal(
                tenant_id=body.tenant_id,
                user_id=body.user_id,
            )
        else:
            principal = resolve_principal(request, settings)
            if (
                principal.tenant_id != body.tenant_id
                or principal.user_id != body.user_id
            ):
                raise HTTPException(status_code=404, detail="Resource not found.")
        result = service.execute_tool(
            name,
            execution_scope=interaction_execution_scope(
                tenant_id=principal.tenant_id,
                workspace_id=body.workspace_id,
                user_id=principal.user_id,
                execution_id=f"direct:{name}",
                task_id=name,
            ),
            **body.kwargs,
        )
        return {"ok": result.get("ok", False), "data": result.get("data"), "error": result.get("error")}

    @app.post("/api/debug/reset-database", response_model=ResetDebugDataResponse)
    def reset_debug_data(request: Request) -> ResetDebugDataResponse:
        if not auth_is_disabled(settings) and not is_admin(request):
            raise HTTPException(status_code=403, detail="Admin access required.")
        logger.warning("Full debug data reset requested")
        result = service.reset_debug_data()
        return ResetDebugDataResponse(**result.model_dump())
