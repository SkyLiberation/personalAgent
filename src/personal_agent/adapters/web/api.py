from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from personal_agent.kernel.config import Settings
from personal_agent.kernel.logging_utils import setup_logging
from personal_agent.adapters.web.auth import AuthMiddleware, RateLimiter
from personal_agent.adapters.web.context import WebAppContext, build_web_app_context
from personal_agent.adapters.web.routes import register_api_routes
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = Settings.from_env()
    log_file = setup_logging(settings.log_level)
    context = build_web_app_context(settings, logger)
    logger.info("Logging initialized at %s", log_file)
    app = FastAPI(
        title="Personal Agent API",
        version="0.2.0",
        description="FastAPI backend for the personal knowledge management agent.",
        lifespan=_lifespan(context),
    )
    context.attach_to(app)

    # Auth + rate limiting (applied before CORS)
    api_keys = settings.web.api_keys
    admin_api_keys = settings.web.admin_api_keys
    if api_keys or admin_api_keys:
        rate_limiter = RateLimiter(
            max_requests=settings.web.rate_limit_requests,
            window_seconds=settings.web.rate_limit_window_seconds,
        )
        app.add_middleware(
            AuthMiddleware,
            api_keys=api_keys,
            rate_limiter=rate_limiter,
            admin_api_keys=admin_api_keys,
        )
        logger.info(
            "Auth enabled with %d API keys (%d admin) and rate limiting",
            len(api_keys), len(admin_api_keys),
        )
    else:
        logger.info("Auth disabled — no API keys configured")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_api_routes(app, context)

    frontend_dist = _frontend_dist_dir()
    assets_dir = frontend_dist / "assets"
    if frontend_dist.exists() and assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/")
        def serve_index() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

        @app.get("/{full_path:path}")
        def serve_spa(full_path: str) -> FileResponse:
            candidate = frontend_dist / full_path
            if candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    return app


def _frontend_dist_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


def _lifespan(context: WebAppContext):
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        context.startup()
        try:
            yield
        finally:
            context.shutdown()

    return lifespan


app = create_app()
