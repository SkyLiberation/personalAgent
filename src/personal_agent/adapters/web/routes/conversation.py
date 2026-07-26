from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from personal_agent.application.conversation import (
    ConversationMessage,
    ConversationTurnView,
    ConversationUnavailable,
)
from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.adapters.web.routes._shared import resolve_user_id


class ConversationTurnRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    messages: list[ConversationMessage] = Field(min_length=1, max_length=100)
    interaction_run_ref: str | None = Field(default=None, pattern=r"^irun_[A-Za-z0-9_-]+$")
    user_id: str | None = Field(default=None, min_length=1, max_length=200)


def register_conversation_routes(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
) -> None:
    @app.post("/api/conversation/turn", response_model=ConversationTurnView)
    def conversation_turn(
        body: ConversationTurnRequest,
        request: Request,
    ) -> ConversationTurnView:
        # Decision Ownership Taxonomy: the complete caller-supplied conversation
        # is the accepted semantic input. The model alone owns answer-vs-
        # clarification semantics; this boundary only admits or rejects.
        try:
            return service.converse(
                conversation_id=body.conversation_id,
                messages=body.messages,
                interaction_run_ref=body.interaction_run_ref,
                user_id=body.user_id or resolve_user_id(request, settings),
                source_platform="web",
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ConversationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/conversation/runs/{interaction_run_ref}")
    def conversation_trace(interaction_run_ref: str):
        trace = service.conversation_trace(interaction_run_ref)
        if trace is None:
            raise HTTPException(status_code=404, detail="interaction run not found")
        return trace
