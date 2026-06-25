"""FastAPI route modules."""

from __future__ import annotations

from fastapi import FastAPI

from personal_agent.adapters.web.context import WebAppContext
from personal_agent.adapters.web.routes.audit import register_audit_routes
from personal_agent.adapters.web.routes.digest import register_digest_routes
from personal_agent.adapters.web.routes.entry import register_entry_routes
from personal_agent.adapters.web.routes.graph import register_graph_routes
from personal_agent.adapters.web.routes.notes import register_note_routes
from personal_agent.adapters.web.routes.review import register_review_routes
from personal_agent.adapters.web.routes.research import register_research_routes
from personal_agent.adapters.web.routes.system import register_system_routes


def register_api_routes(app: FastAPI, context: WebAppContext) -> None:
    settings = context.settings
    register_system_routes(app, service=context.service)
    register_note_routes(app, settings=settings, service=context.service)
    register_digest_routes(app, settings=settings, service=context.service)
    register_review_routes(
        app,
        settings=settings,
        service=context.service,
        review_digest_store=context.review_digest_store,
        review_feedback_use_case=context.review_feedback_use_case,
    )
    register_audit_routes(app, settings=settings, service=context.service)
    register_research_routes(app, settings=settings, service=context.service)
    register_entry_routes(
        app,
        settings=settings,
        service=context.service,
        capture_service=context.capture_service,
    )
    register_graph_routes(app, settings=settings, service=context.service)
