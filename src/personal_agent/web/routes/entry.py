from __future__ import annotations

from fastapi import FastAPI

from personal_agent.agent.service import AgentService
from personal_agent.capture import CaptureService
from personal_agent.core.config import Settings
from personal_agent.web.routes.entry_runs import register_entry_run_routes
from personal_agent.web.routes.entry_stream import register_entry_stream_route
from personal_agent.web.routes.entry_upload import register_entry_upload_route


def register_entry_routes(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
    capture_service: CaptureService,
) -> None:
    register_entry_stream_route(app, settings=settings, service=service)
    register_entry_upload_route(
        app,
        settings=settings,
        service=service,
        capture_service=capture_service,
    )
    register_entry_run_routes(app, settings=settings, service=service)
