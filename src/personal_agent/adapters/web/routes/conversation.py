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
    ConversationWorkingPlan,
)
from personal_agent.application.conversation.models import KnowledgeDeleteConfirmation
from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.adapters.web.routes._shared import resolve_requested_principal
from personal_agent.adapters.web.routes.artifacts import (
    ArtifactResourceView,
    artifact_resource_view,
)


class ConversationTurnRequest(BaseModel):
    input_artifact_refs: tuple[ResourceRef, ...] = ()
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
            "auto admits a new plan without waiting, then exposes its pending "
            "steps for bound execution on the next model turn"
        ),
    )


class ConversationKnowledgeSaveDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, min_length=1, max_length=200)
    decision: Literal["confirm", "reject"]
    confirmation_ref: str = Field(default="", max_length=500)


class ConversationTurnResponse(BaseModel):
    """HTTP projection of a turn with authenticated download paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resources: tuple[ArtifactResourceView, ...] = ()
    interaction_run_ref: str = ""
    conversation_id: str
    disposition: Literal[
        "answer",
        "clarification_required",
        "confirmation_required",
        "plan_ready",
        "limitation",
        "failed",
    ]
    message: ConversationMessage
    pending_confirmation: (
        ConversationKnowledgeSaveOperation | KnowledgeDeleteConfirmation | None
    ) = None
    working_plan: ConversationWorkingPlan | None = None


def conversation_turn_response(
    view: ConversationTurnView,
    *,
    principal: AuthenticatedPrincipal,
    settings: Settings,
) -> ConversationTurnResponse:
    return ConversationTurnResponse(
        resources=tuple(
            artifact_resource_view(resource, principal=principal, settings=settings)
            for resource in view.resources
        ),
        interaction_run_ref=view.interaction_run_ref,
        conversation_id=view.conversation_id,
        disposition=view.disposition,
        message=view.message,
        pending_confirmation=view.pending_confirmation,
        working_plan=view.working_plan,
    )


def register_conversation_routes(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
) -> None:
    @app.post(
        "/api/conversation/turn",
        response_model=ConversationTurnResponse,
        response_model_exclude_none=True,
    )
    def conversation_turn(
        body: ConversationTurnRequest,
        request: Request,
    ) -> ConversationTurnResponse:
        # Decision Ownership Taxonomy: the complete caller-supplied conversation
        # is the accepted semantic input. The model alone owns answer-vs-
        # clarification semantics; this boundary only admits or rejects.
        try:
            principal = resolve_requested_principal(
                request,
                settings,
                body.user_id,
            )
            view = service.converse(
                conversation_id=body.conversation_id,
                messages=body.messages,
                interaction_run_ref=body.interaction_run_ref,
                principal=principal,
                source_platform="web",
                interaction_mode=body.interaction_mode,
                input_artifact_refs=body.input_artifact_refs,
            )
            return conversation_turn_response(
                view, principal=principal, settings=settings
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ConversationOperationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
