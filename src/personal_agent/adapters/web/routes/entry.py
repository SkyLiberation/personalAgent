from __future__ import annotations

from fastapi import FastAPI

from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.adapters.web.routes.entry_stream import register_entry_stream_route


def register_entry_routes(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
) -> None:
    register_entry_stream_route(app, settings=settings, service=service)
