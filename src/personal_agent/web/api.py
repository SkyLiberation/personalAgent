from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agent.service import AgentService
from ..capture import CaptureService
from ..core.config import Settings
from ..core.logging_utils import setup_logging
from ..core.models import AskHistoryRecord, Citation, EntryInput, KnowledgeNote, ReviewCard
from ..feishu import FeishuService
from .auth import AuthMiddleware, RateLimiter
logger = logging.getLogger(__name__)


def _get_user_id(request: Request, settings: Settings) -> str:
    """Resolve authenticated user_id from middleware state, fall back to default."""
    return getattr(request.state, "user_id", settings.default_user)


class CaptureRequest(BaseModel):
    text: str = Field(min_length=1)
    source_type: str = "text"
    user_id: str = "default"


class CaptureResponse(BaseModel):
    note: KnowledgeNote
    related_notes: list[KnowledgeNote] = Field(default_factory=list)
    review_card: ReviewCard | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    user_id: str = "default"
    session_id: str = "default"


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    matches: list[KnowledgeNote] = Field(default_factory=list)
    session_id: str = "default"


class DigestResponse(BaseModel):
    message: str
    recent_notes: list[KnowledgeNote] = Field(default_factory=list)
    due_reviews: list[ReviewCard] = Field(default_factory=list)


class GraphSyncResponse(BaseModel):
    note: KnowledgeNote
    queued: bool = False


class AskHistoryResponse(BaseModel):
    items: list[AskHistoryRecord] = Field(default_factory=list)


class UploadConflictResponse(BaseModel):
    filename: str
    exists: bool
    path: str


class EntryRequest(BaseModel):
    text: str = Field(min_length=1)
    user_id: str = "default"
    session_id: str = "default"
    source_type: str = "text"
    source_ref: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class EntryResponse(BaseModel):
    intent: str
    reason: str
    reply_text: str
    capture_result: dict | None = None
    ask_result: dict | None = None


class ResetUserDataRequest(BaseModel):
    user_id: str = "default"


class ResetUserDataResponse(BaseModel):
    user_id: str
    deleted_notes: int = 0
    deleted_reviews: int = 0
    deleted_conversations: int = 0
    deleted_upload_files: int = 0


class ToolSpecResponse(BaseModel):
    name: str
    description: str


class ToolExecuteRequest(BaseModel):
    kwargs: dict[str, object] = Field(default_factory=dict)


class ToolExecuteResponse(BaseModel):
    ok: bool
    data: object = None
    error: str | None = None
    deleted_ask_history: int = 0
    deleted_graph_episodes: int = 0


def create_app() -> FastAPI:
    settings = Settings.from_env()
    log_file = setup_logging(settings.log_level)
    capture_service = CaptureService(settings, logger)
    service = AgentService(settings, capture_service=capture_service)
    feishu_service = FeishuService(settings, service)
    logger.info("Logging initialized at %s", log_file)
    app = FastAPI(
        title="Personal Agent API",
        version="0.2.0",
        description="FastAPI backend for the personal knowledge management agent.",
    )

    # Auth + rate limiting (applied before CORS)
    api_keys = settings.api_keys
    if api_keys:
        rate_limiter = RateLimiter(
            max_requests=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
        app.add_middleware(AuthMiddleware, api_keys=api_keys, rate_limiter=rate_limiter)
        logger.info("Auth enabled with %d API keys and rate limiting", len(api_keys))
    else:
        logger.info("Auth disabled — no API keys configured")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup_feishu_listener() -> None:
        feishu_service.start_event_listener()

    @app.get("/api/health")
    def health() -> dict[str, object]:
        logger.debug("Health check requested")
        return service.health()

    @app.get("/api/tools", response_model=list[ToolSpecResponse])
    def list_tools() -> list[dict[str, object]]:
        specs = service.list_tools()
        return [{"name": s.name, "description": s.description} for s in specs]

    @app.post("/api/tools/{name}/execute", response_model=ToolExecuteResponse)
    def execute_tool(name: str, body: ToolExecuteRequest) -> dict[str, object]:
        result = service.execute_tool(name, **body.kwargs)
        return {"ok": result.ok, "data": result.data, "error": result.error}

    @app.get("/api/notes", response_model=list[KnowledgeNote])
    def list_notes(request: Request, user_id: str | None = None) -> list[KnowledgeNote]:
        resolved_user = user_id or _get_user_id(request, settings)
        logger.info("Listing notes for user=%s", resolved_user)
        return service.list_notes(resolved_user)

    @app.get("/api/digest", response_model=DigestResponse)
    def get_digest(request: Request, user_id: str | None = None) -> DigestResponse:
        resolved_user = user_id or _get_user_id(request, settings)
        logger.info("Digest requested for user=%s", resolved_user)
        result = service.digest(resolved_user)
        return DigestResponse(**result.model_dump())

    @app.get("/api/ask-history", response_model=AskHistoryResponse)
    def get_ask_history(
        request: Request, user_id: str | None = None, limit: int = 20, session_id: str | None = None
    ) -> AskHistoryResponse:
        resolved_user = user_id or _get_user_id(request, settings)
        logger.info("Ask history requested for user=%s session=%s limit=%s", resolved_user, session_id, limit)
        return AskHistoryResponse(items=service.list_ask_history(resolved_user, limit, session_id))

    @app.post("/api/capture", response_model=CaptureResponse)
    def capture(http_request: Request, body: CaptureRequest) -> CaptureResponse:
        resolved_user = body.user_id or _get_user_id(http_request, settings)
        logger.info("Text capture requested for user=%s source_type=%s", resolved_user, body.source_type)
        capture_text = body.text
        if body.source_type == "link":
            capture_text = capture_service.capture_text_from_url(body.text)
        result = service.capture(
            text=capture_text,
            source_type=body.source_type,
            user_id=resolved_user,
            source_ref=body.text if body.source_type == "link" else None,
        )
        return CaptureResponse(**result.model_dump())

    @app.get("/api/uploads/conflict", response_model=UploadConflictResponse)
    def check_upload_conflict(filename: str) -> UploadConflictResponse:
        normalized_name = capture_service.normalize_upload_filename(filename)
        uploads_dir = settings.data_dir / "uploads"
        target_path = uploads_dir / normalized_name
        return UploadConflictResponse(
            filename=normalized_name,
            exists=target_path.exists(),
            path=str(target_path),
        )

    @app.post("/api/capture/upload", response_model=CaptureResponse)
    def capture_upload(
        request: Request,
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        user_id: str = Form("default"),
        overwrite: bool = Form(False),
    ) -> CaptureResponse:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Missing file name.")

        resolved_user = user_id if user_id != "default" else _get_user_id(request, settings)

        uploads_dir = settings.data_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        original_name = capture_service.normalize_upload_filename(file.filename)
        stored_path = uploads_dir / original_name
        if stored_path.exists() and not overwrite:
            raise HTTPException(
                status_code=409,
                detail=f"File '{original_name}' already exists. Confirm overwrite to replace it.",
            )

        file_bytes = file.file.read()
        stored_path.write_bytes(file_bytes)

        source_type = capture_service.source_type_from_upload(original_name, file.content_type)
        logger.info(
            "File upload received user=%s filename=%s source_type=%s size_bytes=%s stored_path=%s",
            resolved_user,
            original_name,
            source_type,
            len(file_bytes),
            stored_path,
        )
        capture_text = capture_service.capture_text_from_upload(
            original_name, file.content_type, file_bytes, source_type
        )

        result = service.capture(
            text=capture_text,
            source_type=source_type,
            user_id=resolved_user,
            source_ref=str(stored_path),
            attempt_graph=False,
        )
        if service.graph_store.configured():
            background_tasks.add_task(service.sync_note_to_graph, result.note.id)
            logger.info("Queued background graph sync note_id=%s", result.note.id)
        logger.info("File upload captured note_id=%s source_ref=%s", result.note.id, result.note.source_ref)
        return CaptureResponse(**result.model_dump())

    @app.post("/api/ask", response_model=AskResponse)
    def ask(http_request: Request, body: AskRequest) -> AskResponse:
        resolved_user = body.user_id if body.user_id != "default" else _get_user_id(http_request, settings)
        logger.info("Ask requested for user=%s session=%s", resolved_user, body.session_id)
        result = service.ask(body.question, resolved_user, body.session_id)
        return AskResponse(**result.model_dump())

    @app.get("/api/ask/stream")
    async def ask_stream(
        request: Request, question: str, user_id: str = "default", session_id: str = "default"
    ) -> StreamingResponse:
        if not question.strip():
            raise HTTPException(status_code=400, detail="Question is required.")

        resolved_user = user_id if user_id != "default" else _get_user_id(request, settings)
        logger.info("Ask stream requested for user=%s session=%s", resolved_user, session_id)

        async def event_generator():
            yield _sse_event(
                "status",
                {
                    "message": "Searching your knowledge graph and local memory...",
                },
            )
            result = await asyncio.to_thread(service.ask, question, resolved_user, session_id)
            yield _sse_event(
                "metadata",
                {
                    "citations": [citation.model_dump(mode="json") for citation in result.citations],
                    "matches": [note.model_dump(mode="json") for note in result.matches],
                    "graph_enabled": result.graph_enabled,
                    "session_id": result.session_id,
                },
            )

            built_answer = ""
            for chunk in _chunk_answer(result.answer):
                built_answer += chunk
                yield _sse_event(
                    "answer_delta",
                    {
                        "delta": chunk,
                        "answer": built_answer,
                    },
                )
                await asyncio.sleep(0.02)

            yield _sse_event(
                "done",
                {
                    "answer": result.answer,
                    "citations": [citation.model_dump(mode="json") for citation in result.citations],
                    "matches": [note.model_dump(mode="json") for note in result.matches],
                    "graph_enabled": result.graph_enabled,
                    "session_id": result.session_id,
                },
            )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/notes/{note_id}/graph-sync", response_model=GraphSyncResponse)
    def retry_graph_sync(note_id: str) -> GraphSyncResponse:
        note = service.store.get_note(note_id)
        if note is None:
            raise HTTPException(status_code=404, detail="Note not found.")

        if not service.graph_store.configured():
            logger.warning("Graph sync retry requested but graph is not configured note_id=%s", note_id)
            return GraphSyncResponse(note=note, queued=False)

        note.graph_sync_status = "pending"
        note.graph_sync_error = None
        note.updated_at = datetime.utcnow()
        service.store.update_note(note)
        logger.info("Starting manual graph sync retry note_id=%s", note_id)
        service.sync_note_to_graph(note_id)
        updated_note = service.store.get_note(note_id) or note
        logger.info(
            "Finished manual graph sync retry note_id=%s graph_sync_status=%s",
            note_id,
            updated_note.graph_sync_status,
        )
        return GraphSyncResponse(note=updated_note, queued=False)

    @app.get("/api/entry/stream")
    async def entry_stream(
        request: Request,
        text: str = "",
        user_id: str = "default",
        session_id: str = "default",
    ) -> StreamingResponse:
        if not text.strip():
            raise HTTPException(status_code=400, detail="Text is required.")

        resolved_user = user_id if user_id != "default" else _get_user_id(request, settings)
        logger.info("Entry stream requested for user=%s session=%s text=%s", resolved_user, session_id, text[:120])

        async def event_generator():
            entry_input = EntryInput(
                text=text.strip(),
                user_id=resolved_user,
                session_id=session_id,
                source_platform="web",
            )
            result = await asyncio.to_thread(service.entry, entry_input)
            yield _sse_event("intent", {
                "intent": result.intent,
                "reason": result.reason,
            })

            if result.intent in ("capture_text", "capture_link", "capture_file"):
                capture_data = result.capture_result.model_dump(mode="json") if result.capture_result else None
                yield _sse_event("capture_result", {
                    "note": capture_data.get("note") if capture_data else None,
                    "reply": result.reply_text,
                })
                yield _sse_event("done", {"reply": result.reply_text})

            elif result.intent == "ask":
                ask_data = result.ask_result.model_dump(mode="json") if result.ask_result else {}
                yield _sse_event("status", {"message": "正在检索你的个人记忆..."})
                yield _sse_event("metadata", {
                    "citations": ask_data.get("citations", []),
                    "matches": ask_data.get("matches", []),
                    "graph_enabled": ask_data.get("graph_enabled", False),
                    "session_id": session_id,
                })
                answer_text = result.reply_text
                built_answer = ""
                for chunk in _chunk_answer(answer_text):
                    built_answer += chunk
                    yield _sse_event("answer_delta", {
                        "delta": chunk,
                        "answer": built_answer,
                    })
                    await asyncio.sleep(0.02)
                yield _sse_event("done", {
                    "answer": answer_text,
                    "citations": ask_data.get("citations", []),
                    "matches": ask_data.get("matches", []),
                    "graph_enabled": ask_data.get("graph_enabled", False),
                    "session_id": session_id,
                })

            else:
                yield _sse_event("status", {"message": result.reason})
                yield _sse_event("done", {"reply": result.reply_text})

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/entry/upload")
    async def entry_upload(
        request: Request,
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        user_id: str = Form("default"),
        session_id: str = Form("default"),
        text: str = Form(""),
    ) -> dict[str, object]:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Missing file name.")

        resolved_user = user_id if user_id != "default" else _get_user_id(request, settings)
        uploads_dir = settings.data_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        original_name = capture_service.normalize_upload_filename(file.filename)
        stored_path = uploads_dir / original_name
        file_bytes = file.file.read()
        stored_path.write_bytes(file_bytes)

        logger.info(
            "Entry upload user=%s filename=%s size_bytes=%s",
            resolved_user, original_name, len(file_bytes),
        )

        metadata: dict[str, str] = {
            "file_path": str(stored_path),
            "original_filename": original_name,
        }
        entry_text = text.strip() or original_name

        entry_input = EntryInput(
            text=entry_text,
            user_id=resolved_user,
            session_id=session_id,
            source_platform="web",
            source_type="file",
            source_ref=str(stored_path),
            metadata=metadata,
        )
        result = service.entry(entry_input)

        if result.capture_result and result.capture_result.note and service.graph_store.configured():
            background_tasks.add_task(service.sync_note_to_graph, result.capture_result.note.id)

        return {
            "intent": result.intent,
            "reason": result.reason,
            "reply_text": result.reply_text,
            "capture_result": result.capture_result.model_dump(mode="json") if result.capture_result else None,
            "ask_result": result.ask_result.model_dump(mode="json") if result.ask_result else None,
        }

    @app.post("/api/entry", response_model=EntryResponse)
    def entry_sync(http_request: Request, body: EntryRequest) -> EntryResponse:
        resolved_user = body.user_id if body.user_id != "default" else _get_user_id(http_request, settings)
        logger.info("Entry sync requested for user=%s session=%s", resolved_user, body.session_id)

        entry_input = EntryInput(
            text=body.text.strip(),
            user_id=resolved_user,
            session_id=body.session_id,
            source_platform="web",
            source_type=body.source_type,
            source_ref=body.source_ref or None,
            metadata=body.metadata,
        )
        result = service.entry(entry_input)
        return EntryResponse(
            intent=result.intent,
            reason=result.reason,
            reply_text=result.reply_text,
            capture_result=result.capture_result.model_dump(mode="json") if result.capture_result else None,
            ask_result=result.ask_result.model_dump(mode="json") if result.ask_result else None,
        )

    @app.post("/api/debug/reset-user-data", response_model=ResetUserDataResponse)
    def reset_user_data(http_request: Request, body: ResetUserDataRequest) -> ResetUserDataResponse:
        resolved_user = body.user_id if body.user_id != "default" else _get_user_id(http_request, settings)
        logger.warning("Debug reset requested for user=%s", resolved_user)
        result = service.reset_user_data(resolved_user)
        return ResetUserDataResponse(**result.model_dump())

    @app.post("/api/integrations/feishu/webhook")
    async def feishu_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, object]:
        logger.info(
            "Feishu webhook request received client=%s user_agent=%s content_type=%s",
            request.client.host if request.client else "unknown",
            request.headers.get("user-agent", ""),
            request.headers.get("content-type", ""),
        )
        try:
            payload = await request.json()
        except Exception as exc:
            logger.warning("Feishu webhook request contains invalid JSON")
            raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

        try:
            result = feishu_service.parse_webhook(payload, dict(request.headers))
        except PermissionError as exc:
            logger.warning("Feishu webhook rejected: %s", exc)
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except RuntimeError as exc:
            logger.exception("Feishu webhook failed before enqueue")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        if result.incoming_message is not None:
            incoming_message = result.incoming_message

            def _process_feishu_message() -> None:
                try:
                    feishu_service.process_incoming_message(incoming_message)
                except Exception:
                    logger.exception(
                        "Feishu background processing failed event_id=%s message_id=%s",
                        incoming_message.event_id,
                        incoming_message.message_id,
                    )

            background_tasks.add_task(_process_feishu_message)

        return result.body

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
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _sse_event(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chunk_answer(answer: str, chunk_size: int = 20) -> list[str]:
    compact = answer.strip()
    if not compact:
        return ["暂时没有生成答案。"]

    chunks: list[str] = []
    current = ""
    for char in compact:
        current += char
        if len(current) >= chunk_size or char in {"\n", "。", "！", "？", ".", "!", "?"}:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks


app = create_app()
