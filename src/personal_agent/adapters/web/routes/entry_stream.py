from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from personal_agent.adapters.web.input_normalization import normalize_entry_text
from personal_agent.adapters.web.routes._shared import resolve_requested_principal
from personal_agent.adapters.web.routes.entry_serializers import chunk_answer, sse_event
from personal_agent.application.conversation import ConversationMessage, ConversationUnavailable
from personal_agent.kernel.config import Settings
from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.contracts.scope import (
    SecurityScope,
)

logger = logging.getLogger(__name__)


def register_entry_stream_route(app: FastAPI, *, settings: Settings, service: AgentService) -> None:
    """Expose SSE as a protocol adapter over the canonical interaction loop."""

    @app.get("/api/entry/stream")
    async def entry_stream(
        request: Request,
        text: str = "",
        user_id: str = "default",
        session_id: str = "default",
    ) -> StreamingResponse:
        normalized_text = normalize_entry_text(text)
        if not normalized_text:
            raise HTTPException(status_code=400, detail="Text is required.")
        try:
            principal = resolve_requested_principal(
                request,
                settings,
                user_id if user_id != "default" else None,
            )
        except PermissionError:
            raise HTTPException(status_code=404, detail="Resource not found.")
        resolved_user = principal.user_id

        async def event_generator():
            yield sse_event("status", {"message": "正在处理请求..."})
            try:
                result = await asyncio.to_thread(
                    service.converse,
                    conversation_id=session_id,
                    messages=[ConversationMessage(role="user", content=normalized_text)],
                    principal=principal,
                    security_scope=SecurityScope(
                        tenant_id=principal.tenant_id,
                        workspace_id=session_id,
                    ),
                    source_platform="web",
                )
            except ConversationUnavailable:
                yield sse_event("error", {
                    "code": "conversation_model_unavailable",
                    "message": "对话模型暂不可用。",
                })
                return
            except Exception:
                logger.exception(
                    "Conversation stream failed user=%s session=%s",
                    resolved_user,
                    session_id,
                )
                yield sse_event("error", {
                    "code": "conversation_execution_failed",
                    "message": "请求执行失败，请稍后重试。",
                })
                return

            answer = result.message.content
            built_answer = ""
            for chunk in chunk_answer(answer):
                built_answer += chunk
                yield sse_event("answer_delta", {"delta": chunk, "answer": built_answer})
            yield sse_event("done", {
                "reply": answer,
                "answer": answer,
                "disposition": result.disposition,
                "interaction_run_ref": result.interaction_run_ref,
                "conversation_id": result.conversation_id,
                "pending_confirmation": (
                    result.pending_confirmation.model_dump(mode="json")
                    if result.pending_confirmation is not None
                    else None
                ),
                "project_reference": (
                    result.project_reference.model_dump(mode="json")
                    if result.project_reference is not None
                    else None
                ),
            })

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
