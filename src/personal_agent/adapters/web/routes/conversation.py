from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.conversation import (
    ConversationMessage,
    ConversationKnowledgeSaveOperation,
    ConversationInteractionMode,
    ConversationFailure,
    ConversationInputError,
    ConversationOperationConflict,
    ConversationOperationNotFound,
    ConversationTurnView,
    ConversationWorkingPlan,
)
from personal_agent.application.conversation.errors import ConversationTurnBlocked, ConversationTurnPending
from personal_agent.application.conversation.service import submitted_turn_id
from personal_agent.adapters.web.routes.entry_serializers import chunk_answer, sse_event
from personal_agent.application.conversation.models import InteractionTrace, KnowledgeDeleteConfirmation
from personal_agent.application.conversation.workspace_changes import (
    Decision as WorkspaceDecision, Digest as WorkspaceDigest, WorkspaceChangeConfirmation, WorkspaceChangeReceipt,
)
from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.policy import EntryPolicyDenied
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.adapters.web.routes._shared import require_entry_identity, resolve_requested_principal
from personal_agent.adapters.web.routes.artifacts import (
    ArtifactResourceView,
    artifact_resource_view,
)
from personal_agent.adapters.web.routes.conversation_errors import (
    conversation_failure_detail,
    conversation_failure_status_code,
)


logger = logging.getLogger(__name__)
TurnId = Annotated[str, Field(pattern=r"^(?:turn|irun)_[A-Za-z0-9_-]+$", max_length=128)]


class ConversationTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_artifact_refs: tuple[ResourceRef, ...] = ()
    session_id: str = Field(
        min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    text: str = Field(min_length=1)
    client_request_id: str = Field(min_length=1, max_length=200)
    create_session: bool = False
    user_id: str | None = Field(default=None, min_length=1, max_length=200)
    interaction_mode: ConversationInteractionMode = Field(
        default="default",
        description="Retained for existing callers. Plan review follows the user request and plan action.",
    )


class ConversationTurnResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, min_length=1, max_length=200)


class PendingConversationTurn(BaseModel):
    turn_id: TurnId
    session_id: str
    disposition: Literal["pending"] = "pending"


class ConversationKnowledgeSaveDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, min_length=1, max_length=200)
    decision: Literal["confirm", "reject"]
    confirmation_ref: str = Field(default="", max_length=500)


class WorkspaceChangeDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_digest: WorkspaceDigest
    decision: WorkspaceDecision


class ConversationTurnResponse(BaseModel):
    """HTTP projection of a turn with authenticated download paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resources: tuple[ArtifactResourceView, ...] = ()
    turn_id: TurnId
    session_id: str
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
        ConversationKnowledgeSaveOperation | KnowledgeDeleteConfirmation | WorkspaceChangeConfirmation | None
    ) = None
    working_plan: ConversationWorkingPlan | None = None


class ConversationTurnTraceResponse(InteractionTrace):
    interaction_run_ref: str = Field(serialization_alias="turn_id")
    conversation_id: str = Field(serialization_alias="session_id")


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
        turn_id=view.interaction_run_ref,
        session_id=view.conversation_id,
        disposition=view.disposition,
        message=view.message,
        pending_confirmation=view.pending_confirmation,
        working_plan=view.working_plan,
    )


def _observe_stream_completion(task: asyncio.Task) -> None:
    # A disconnected subscriber no longer awaits the result. The registered turn remains queryable.
    if not task.cancelled():
        task.exception()


def register_conversation_routes(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
) -> None:
    def require_turn(turn_id: str, principal: AuthenticatedPrincipal) -> InteractionTrace:
        trace = service.conversation_trace(turn_id, principal=principal)
        if trace is None:
            raise ConversationOperationNotFound("conversation turn not found")
        return trace

    @app.post("/api/conversation/turns/{turn_id}/workspace-changes/decision",
              response_model=WorkspaceChangeReceipt)
    def decide_workspace_changes(
        turn_id: TurnId, body: WorkspaceChangeDecisionRequest, request: Request,
    ) -> WorkspaceChangeReceipt:
        if getattr(request.state, "principal", None) is None:
            raise HTTPException(status_code=403, detail="工作区变更需要 Web 认证。")
        try:
            principal = resolve_requested_principal(request, settings, None)
            trace = require_turn(turn_id, principal)
            return service.decide_workspace_changes(
                conversation_id=trace.conversation_id, interaction_run_ref=turn_id,
                principal=principal, command_digest=body.command_digest, decision=body.decision,
            )
        except EntryPolicyDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (PermissionError, ConversationOperationNotFound):
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except ConversationOperationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def web_turn(
        body: ConversationTurnRequest | ConversationTurnResumeRequest,
        request: Request,
        *,
        turn_id: str | None = None,
        on_registered: Callable[[str], None] | None = None,
    ) -> ConversationTurnResponse | JSONResponse:
        try:
            require_entry_identity(request, settings)
            principal = resolve_requested_principal(
                request,
                settings,
                body.user_id,
            )
            if isinstance(body, ConversationTurnRequest):
                session_id = body.session_id
                turn_id = submitted_turn_id(principal, session_id, body.client_request_id)
                try:
                    message = ConversationMessage(role="user", content=body.text)
                except ValueError as exc:
                    raise ConversationInputError("当前用户消息不合法") from exc
                try:
                    view = service.converse(
                        conversation_id=session_id, message=message, client_request_id=body.client_request_id,
                        create_session=body.create_session, principal=principal, source_platform="web",
                        interaction_mode=body.interaction_mode, input_artifact_refs=body.input_artifact_refs,
                        on_registered=on_registered,
                    )
                except ConversationTurnPending:
                    pending = PendingConversationTurn(turn_id=turn_id, session_id=session_id)
                    return JSONResponse(status_code=202, content=pending.model_dump(mode="json"))
            else:
                if turn_id is None:
                    raise ConversationOperationNotFound("conversation turn not found")
                existing = require_turn(turn_id, principal)
                view = service.converse(
                    conversation_id=existing.conversation_id, interaction_run_ref=turn_id,
                    principal=principal, source_platform="web",
                )
            return conversation_turn_response(
                view, principal=principal, settings=settings
            )
        except ConversationInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ConversationTurnBlocked as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "turn_id": exc.turn_id}) from exc
        except ConversationOperationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EntryPolicyDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ConversationOperationNotFound, PermissionError):
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except ConversationFailure as exc:
            raise HTTPException(
                status_code=conversation_failure_status_code(exc),
                detail=conversation_failure_detail(exc),
            ) from exc
        except Exception as exc:
            logger.error("Conversation turn failed error_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=500, detail=conversation_failure_detail(exc)
            ) from exc

    @app.post("/api/conversation/turns", response_model=ConversationTurnResponse,
              response_model_exclude_none=True, responses={
                  200: {"content": {"text/event-stream": {}}},
                  202: {"model": PendingConversationTurn},
              })
    async def conversation_turn(body: ConversationTurnRequest, request: Request):
        if "text/event-stream" not in request.headers.get("accept", "").lower():
            return await asyncio.to_thread(web_turn, body, request)
        loop = asyncio.get_running_loop()
        registered: asyncio.Future[str] = loop.create_future()

        def record_registration(turn_id: str) -> None:
            if not registered.done():
                registered.set_result(turn_id)

        def registered_in_thread(turn_id: str) -> None:
            loop.call_soon_threadsafe(record_registration, turn_id)

        result = asyncio.create_task(asyncio.to_thread(web_turn, body, request, on_registered=registered_in_thread))
        result.add_done_callback(_observe_stream_completion)
        await asyncio.wait((registered, result), return_when=asyncio.FIRST_COMPLETED)
        if not registered.done():
            return await result

        async def events():
            turn_id = registered.result()
            yield sse_event("status", {"turn_id": turn_id, "session_id": body.session_id})
            try:
                response = await asyncio.shield(result)
            except HTTPException as exc:
                yield sse_event("error", {"status_code": exc.status_code, "detail": exc.detail})
                return
            if isinstance(response, JSONResponse):
                yield sse_event("pending", {"turn_id": turn_id, "session_id": body.session_id})
                return
            answer = response.message.content
            built_answer = ""
            for chunk in chunk_answer(answer):
                built_answer += chunk
                yield sse_event("answer_delta", {"delta": chunk, "answer": built_answer})
            yield sse_event("done", {
                "reply": answer, "answer": answer, "disposition": response.disposition,
                "turn_id": turn_id, "session_id": body.session_id,
                "pending_confirmation": (
                    response.pending_confirmation.model_dump(mode="json") if response.pending_confirmation else None
                ),
            })

        return StreamingResponse(events(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        })

    @app.post("/api/conversation/turns/{turn_id}/resume", response_model=ConversationTurnResponse,
              response_model_exclude_none=True)
    def resume_conversation_turn(turn_id: TurnId, body: ConversationTurnResumeRequest, request: Request):
        return web_turn(body, request, turn_id=turn_id)

    @app.get("/api/conversation/turns/{turn_id}", response_model=ConversationTurnTraceResponse)
    def conversation_trace(
        turn_id: TurnId,
        request: Request,
        user_id: str | None = None,
    ):
        try:
            require_entry_identity(request, settings)
            principal = resolve_requested_principal(request, settings, user_id)
            service.authorize_entry(principal, "web", preflight=True)
            trace = require_turn(turn_id, principal)
        except EntryPolicyDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ConversationOperationNotFound, PermissionError):
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        return ConversationTurnTraceResponse.model_validate(trace.model_dump())

    @app.post(
        "/api/conversation/turns/{turn_id}/knowledge-save-decision",
        response_model=ConversationKnowledgeSaveOperation,
    )
    def decide_conversation_knowledge_save(
        turn_id: TurnId,
        body: ConversationKnowledgeSaveDecisionRequest,
        request: Request,
    ) -> ConversationKnowledgeSaveOperation:
        try:
            require_entry_identity(request, settings)
            principal = resolve_requested_principal(request, settings, body.user_id)
            service.authorize_entry(principal, "web", preflight=True)
            return service.decide_conversation_knowledge_save(
                interaction_run_ref=turn_id,
                principal=principal,
                decision=body.decision,
                confirmation_ref=body.confirmation_ref,
            )
        except EntryPolicyDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ConversationOperationNotFound, PermissionError):
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except ConversationOperationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ConversationInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ConversationFailure as exc:
            raise HTTPException(
                status_code=conversation_failure_status_code(exc),
                detail=conversation_failure_detail(exc),
            ) from exc
        except Exception as exc:
            logger.error("Knowledge save decision failed error_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=500, detail=conversation_failure_detail(exc)
            ) from exc
