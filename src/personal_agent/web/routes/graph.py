from __future__ import annotations

from fastapi import FastAPI, Request

from ...agent.service import AgentService
from ...core.config import Settings
from ._shared import resolve_user_id


def register_graph_routes(app: FastAPI, *, settings: Settings, service: AgentService) -> None:
    @app.get("/api/graph/topology")
    def get_graph_topology(request: Request, user_id: str | None = None):
        """Return all entity nodes and edges from Neo4j for force-graph rendering."""
        resolved_user = user_id or resolve_user_id(request, settings)
        return service.graph_store.get_topology(resolved_user)
