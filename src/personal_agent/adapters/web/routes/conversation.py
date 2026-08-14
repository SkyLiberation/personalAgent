from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.conversation import (
    ConversationMessage,
    ConversationKnowledgeSaveOperation,
    ConversationInteractionMode,
    ConversationOperationConflict,
    ConversationOperationNotFound,
    ConversationTurnView,
    ConversationUnavailable,
)
from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.adapters.web.routes._shared import resolve_requested_principal


class ConversationTurnRequest(BaseModel):
    conversation_id: str = Field(
        min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    messages: list[ConversationMessage] = Field(min_length=1, max_length=100)
    interaction_run_ref: str | None = Field(
        default=None, pattern=r"^irun_[A-Za-z0-9_-]+$"
    )
    user_id: str | None = Field(default=None, min_length=1, max_length=200)
    interaction_mode: ConversationInteractionMode = Field(
        default="default",
        description=(
            "default requires review before a new formal plan can execute; "
            "auto authorizes plan creation and execution in the same turn"
        ),
    )


class ConversationKnowledgeSaveDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, min_length=1, max_length=200)
    decision: Literal["confirm", "reject"]
    confirmation_ref: str = Field(default="", max_length=500)


def register_conversation_routes(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
) -> None:
    @app.post(
        "/api/conversation/turn",
        response_model=ConversationTurnView,
        response_model_exclude_none=True,
    )
    def conversation_turn(
        body: ConversationTurnRequest,
        request: Request,
    ) -> ConversationTurnView:
        # Decision Ownership Taxonomy: the complete caller-supplied conversation
        # is the accepted semantic input. The model alone owns answer-vs-
        # clarification semantics; this boundary only admits or rejects.
        try:
            principal = resolve_requested_principal(
                request,
                settings,
                body.user_id,
            )
            return service.converse(
                conversation_id=body.conversation_id,
                messages=body.messages,
                interaction_run_ref=body.interaction_run_ref,
                principal=principal,
                source_platform="web",
                interaction_mode=body.interaction_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (ConversationOperationNotFound, PermissionError):
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except ConversationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/conversation/runs/{interaction_run_ref}")
    def conversation_trace(
        interaction_run_ref: str,
        request: Request,
        user_id: str | None = None,
    ):
        try:
            principal = resolve_requested_principal(request, settings, user_id)
            trace = service.conversation_trace(
                interaction_run_ref,
                principal=principal,
            )
        except (ConversationOperationNotFound, PermissionError):
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        if trace is None:
            raise HTTPException(status_code=404, detail="interaction run not found")
        return trace

    @app.post(
        "/api/conversation/runs/{interaction_run_ref}/knowledge-save-decision",
        response_model=ConversationKnowledgeSaveOperation,
    )
    def decide_conversation_knowledge_save(
        interaction_run_ref: str,
        body: ConversationKnowledgeSaveDecisionRequest,
        request: Request,
    ) -> ConversationKnowledgeSaveOperation:
        try:
            principal = resolve_requested_principal(request, settings, body.user_id)
            return service.decide_conversation_knowledge_save(
                interaction_run_ref=interaction_run_ref,
                principal=principal,
                decision=body.decision,
                confirmation_ref=body.confirmation_ref,
            )
        except (ConversationOperationNotFound, PermissionError):
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except ConversationOperationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ConversationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
