"""FastAPI route modules."""

from __future__ import annotations

from fastapi import FastAPI

from ..context import WebAppContext
from .audit import register_audit_routes
from .digest import register_digest_routes
from .entry import register_entry_routes
from .graph import register_graph_routes
from .notes import register_note_routes
from .review import register_review_routes
from .research import register_research_routes
from .system import register_system_routes


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
