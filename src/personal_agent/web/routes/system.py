from __future__ import annotations

import logging

from fastapi import FastAPI
from pydantic import BaseModel, Field

from ...agent.service import AgentService
from ...tools import tool_governance

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
    kwargs: dict[str, object] = Field(default_factory=dict)


class ToolExecuteResponse(BaseModel):
    ok: bool
    data: object = None
    error: str | None = None
    deleted_graph_episodes: int = 0


def register_system_routes(app: FastAPI, *, service: AgentService) -> None:
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

    @app.post("/api/tools/{name}/execute", response_model=ToolExecuteResponse)
    def execute_tool(name: str, body: ToolExecuteRequest) -> dict[str, object]:
        result = service.execute_tool(name, **body.kwargs)
        return {"ok": result.get("ok", False), "data": result.get("data"), "error": result.get("error")}

    @app.post("/api/debug/reset-database", response_model=ResetDebugDataResponse)
    def reset_debug_data() -> ResetDebugDataResponse:
        logger.warning("Full debug data reset requested")
        result = service.reset_debug_data()
        return ResetDebugDataResponse(**result.model_dump())
