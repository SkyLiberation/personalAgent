from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .logging_utils import setup_logging
from .models import AskHistoryRecord, Citation, KnowledgeNote, ReviewCard
from .service import AgentService

TEXT_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".csv",
    ".tsv",
    ".log",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".html",
    ".css",
    ".sql",
    ".yaml",
    ".yml",
    ".xml",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
logger = logging.getLogger(__name__)


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


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    matches: list[KnowledgeNote] = Field(default_factory=list)


class DigestResponse(BaseModel):
    message: str
    recent_notes: list[KnowledgeNote] = Field(default_factory=list)
    due_reviews: list[ReviewCard] = Field(default_factory=list)


class GraphSyncResponse(BaseModel):
    note: KnowledgeNote
    queued: bool = False


class AskHistoryResponse(BaseModel):
    items: list[AskHistoryRecord] = Field(default_factory=list)


def create_app() -> FastAPI:
    settings = Settings.from_env()
    log_file = setup_logging(settings.log_level)
    service = AgentService(settings)
    logger.info("Logging initialized at %s", log_file)
    app = FastAPI(
        title="Personal Agent API",
        version="0.2.0",
        description="FastAPI backend for the personal knowledge management agent.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, object]:
        logger.debug("Health check requested")
        return service.health()

    @app.get("/api/notes", response_model=list[KnowledgeNote])
    def list_notes(user_id: str = "default") -> list[KnowledgeNote]:
        logger.info("Listing notes for user=%s", user_id)
        return service.list_notes(user_id)

    @app.get("/api/digest", response_model=DigestResponse)
    def get_digest(user_id: str = "default") -> DigestResponse:
        logger.info("Digest requested for user=%s", user_id)
        result = service.digest(user_id)
        return DigestResponse(**result.model_dump())

    @app.get("/api/ask-history", response_model=AskHistoryResponse)
    def get_ask_history(user_id: str = "default", limit: int = 20) -> AskHistoryResponse:
        logger.info("Ask history requested for user=%s limit=%s", user_id, limit)
        return AskHistoryResponse(items=service.list_ask_history(user_id, limit))

    @app.post("/api/capture", response_model=CaptureResponse)
    def capture(request: CaptureRequest) -> CaptureResponse:
        logger.info("Text capture requested for user=%s source_type=%s", request.user_id, request.source_type)
        result = service.capture(
            text=request.text,
            source_type=request.source_type,
            user_id=request.user_id,
        )
        return CaptureResponse(**result.model_dump())

    @app.post("/api/capture/upload", response_model=CaptureResponse)
    def capture_upload(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        user_id: str = Form("default"),
    ) -> CaptureResponse:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Missing file name.")

        uploads_dir = settings.data_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        original_name = Path(file.filename).name
        suffix = Path(original_name).suffix.lower()
        stored_name = f"{uuid4().hex}{suffix}"
        stored_path = uploads_dir / stored_name

        file_bytes = file.file.read()
        stored_path.write_bytes(file_bytes)

        source_type = _source_type_from_upload(original_name, file.content_type)
        logger.info(
            "File upload received user=%s filename=%s source_type=%s size_bytes=%s stored_path=%s",
            user_id,
            original_name,
            source_type,
            len(file_bytes),
            stored_path,
        )
        capture_text = _capture_text_from_upload(original_name, file.content_type, file_bytes, source_type)

        result = service.capture(
            text=capture_text,
            source_type=source_type,
            user_id=user_id,
            source_ref=str(stored_path),
            attempt_graph=False,
        )
        if service.graph_store.configured():
            background_tasks.add_task(service.sync_note_to_graph, result.note.id)
            logger.info("Queued background graph sync note_id=%s", result.note.id)
        logger.info("File upload captured note_id=%s source_ref=%s", result.note.id, result.note.source_ref)
        return CaptureResponse(**result.model_dump())

    @app.post("/api/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse:
        logger.info("Ask requested for user=%s", request.user_id)
        result = service.ask(request.question, request.user_id)
        return AskResponse(**result.model_dump())

    @app.get("/api/ask/stream")
    async def ask_stream(question: str, user_id: str = "default") -> StreamingResponse:
        if not question.strip():
            raise HTTPException(status_code=400, detail="Question is required.")

        logger.info("Ask stream requested for user=%s", user_id)

        async def event_generator():
            yield _sse_event(
                "status",
                {
                    "message": "Searching your knowledge graph and local memory...",
                },
            )
            result = await asyncio.to_thread(service.ask, question, user_id)
            yield _sse_event(
                "metadata",
                {
                    "citations": [citation.model_dump(mode="json") for citation in result.citations],
                    "matches": [note.model_dump(mode="json") for note in result.matches],
                    "graph_enabled": result.graph_enabled,
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
    def retry_graph_sync(note_id: str, background_tasks: BackgroundTasks) -> GraphSyncResponse:
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
        background_tasks.add_task(service.sync_note_to_graph, note_id)
        logger.info("Queued manual graph sync retry note_id=%s", note_id)
        return GraphSyncResponse(note=note, queued=True)

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


def _source_type_from_upload(filename: str, content_type: str | None) -> str:
    suffix = Path(filename).suffix.lower()
    mime = (content_type or "").lower()
    if suffix == ".pdf" or mime == "application/pdf":
        return "pdf"
    if suffix in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return "image"
    if suffix in AUDIO_EXTENSIONS or mime.startswith("audio/"):
        return "audio"
    return "note"


def _capture_text_from_upload(
    filename: str,
    content_type: str | None,
    file_bytes: bytes,
    source_type: str,
) -> str:
    suffix = Path(filename).suffix.lower()
    mime = (content_type or "").lower()

    if suffix in TEXT_FILE_EXTENSIONS or mime.startswith("text/") or mime in {
        "application/json",
        "application/xml",
    }:
        text_content = _preprocess_uploaded_text(file_bytes.decode("utf-8", errors="replace").strip())
        if text_content:
            return f"Uploaded file: {filename}\n\n{text_content[:12000]}"

    size_kb = max(1, len(file_bytes) // 1024) if file_bytes else 0
    return (
        f"Uploaded file: {filename}\n"
        f"Source type: {source_type}\n"
        f"Media type: {content_type or 'unknown'}\n"
        f"Size: {size_kb} KB\n\n"
        "This file was uploaded through the web UI. Automatic content extraction for this file type "
        "is not implemented yet, so the knowledge note currently stores file metadata only."
    )


def _preprocess_uploaded_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r", "").split("\n")]
    filtered_lines: list[str] = []
    for line in lines:
        if not line:
            continue
        if line.startswith("*Exported from "):
            continue
        if line.startswith("**Date**:") or line.startswith("**Turns**:") or line.startswith("**Source**:"):
            continue
        if line.startswith("---"):
            continue
        filtered_lines.append(line)

    normalized = "\n".join(filtered_lines)
    normalized = normalized.replace("### 👤 User", "User")
    normalized = normalized.replace("### 🤖 Assistant", "Assistant")
    normalized = normalized.replace("## Turn 1", "")
    return normalized.strip()


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
