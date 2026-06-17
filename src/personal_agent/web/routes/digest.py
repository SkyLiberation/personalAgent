from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from ...agent.service import AgentService
from ...core.config import Settings
from ...core.models import KnowledgeNote, ReviewCard
from ._shared import resolve_user_id

logger = logging.getLogger(__name__)


class DigestResponse(BaseModel):
    message: str
    recent_notes: list[KnowledgeNote] = Field(default_factory=list)
    due_reviews: list[ReviewCard] = Field(default_factory=list)


def register_digest_routes(app: FastAPI, *, settings: Settings, service: AgentService) -> None:
    @app.get("/api/digest", response_model=DigestResponse)
    def get_digest(request: Request, user_id: str | None = None) -> DigestResponse:
        resolved_user = user_id or resolve_user_id(request, settings)
        logger.info("Digest requested for user=%s", resolved_user)
        result = service.digest(resolved_user)
        return DigestResponse(**result.model_dump())
