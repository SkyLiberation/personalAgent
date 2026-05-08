from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agent.service import AgentService
from ..core.config import Settings
from ..core.logging_utils import setup_logging
from ..core.models import AskHistoryRecord, Citation, KnowledgeNote, ReviewCard

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


class ResetUserDataRequest(BaseModel):
    user_id: str = "default"


class ResetUserDataResponse(BaseModel):
    user_id: str
    deleted_notes: int = 0
    deleted_reviews: int = 0
    deleted_conversations: int = 0
    deleted_upload_files: int = 0
    deleted_ask_history: int = 0
    deleted_graph_episodes: int = 0


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
    def get_ask_history(
        user_id: str = "default", limit: int = 20, session_id: str | None = None
    ) -> AskHistoryResponse:
        logger.info("Ask history requested for user=%s session=%s limit=%s", user_id, session_id, limit)
        return AskHistoryResponse(items=service.list_ask_history(user_id, limit, session_id))

    @app.post("/api/capture", response_model=CaptureResponse)
    def capture(request: CaptureRequest) -> CaptureResponse:
        logger.info("Text capture requested for user=%s source_type=%s", request.user_id, request.source_type)
        capture_text = request.text
        if request.source_type == "link":
            capture_text = _capture_text_from_url(request.text)
        result = service.capture(
            text=capture_text,
            source_type=request.source_type,
            user_id=request.user_id,
            source_ref=request.text if request.source_type == "link" else None,
        )
        return CaptureResponse(**result.model_dump())

    @app.get("/api/uploads/conflict", response_model=UploadConflictResponse)
    def check_upload_conflict(filename: str) -> UploadConflictResponse:
        normalized_name = _normalize_upload_filename(filename)
        uploads_dir = settings.data_dir / "uploads"
        target_path = uploads_dir / normalized_name
        return UploadConflictResponse(
            filename=normalized_name,
            exists=target_path.exists(),
            path=str(target_path),
        )

    @app.post("/api/capture/upload", response_model=CaptureResponse)
    def capture_upload(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        user_id: str = Form("default"),
        overwrite: bool = Form(False),
    ) -> CaptureResponse:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Missing file name.")

        uploads_dir = settings.data_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        original_name = _normalize_upload_filename(file.filename)
        stored_path = uploads_dir / original_name
        if stored_path.exists() and not overwrite:
            raise HTTPException(
                status_code=409,
                detail=f"File '{original_name}' already exists. Confirm overwrite to replace it.",
            )

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
        logger.info("Ask requested for user=%s session=%s", request.user_id, request.session_id)
        result = service.ask(request.question, request.user_id, request.session_id)
        return AskResponse(**result.model_dump())

    @app.get("/api/ask/stream")
    async def ask_stream(question: str, user_id: str = "default", session_id: str = "default") -> StreamingResponse:
        if not question.strip():
            raise HTTPException(status_code=400, detail="Question is required.")

        logger.info("Ask stream requested for user=%s session=%s", user_id, session_id)

        async def event_generator():
            yield _sse_event(
                "status",
                {
                    "message": "Searching your knowledge graph and local memory...",
                },
            )
            result = await asyncio.to_thread(service.ask, question, user_id, session_id)
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

    @app.post("/api/debug/reset-user-data", response_model=ResetUserDataResponse)
    def reset_user_data(request: ResetUserDataRequest) -> ResetUserDataResponse:
        logger.warning("Debug reset requested for user=%s", request.user_id)
        result = service.reset_user_data(request.user_id)
        return ResetUserDataResponse(**result.model_dump())

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


def _normalize_upload_filename(filename: str) -> str:
    normalized_name = Path(filename).name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Missing file name.")
    return normalized_name


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

    if suffix == ".pdf" or mime == "application/pdf":
        pdf_text = _extract_pdf_text(file_bytes)
        if pdf_text:
            return f"Uploaded PDF: {filename}\n\n{pdf_text[:12000]}"

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


def _capture_text_from_url(raw_url: str) -> str:
    url = raw_url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Only http/https URLs are supported for link capture.")

    request = Request(
        url,
        headers={
            "User-Agent": "personal-agent/0.1 (+https://local.agent)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        },
    )
    try:
        with urlopen(request, timeout=12) as response:
            body = response.read()
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: HTTP {exc.code}") from exc
    except URLError as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {exc.reason}") from exc

    text = body.decode(charset, errors="replace")
    if content_type == "text/plain":
        compact = text.strip()
        if not compact:
            raise HTTPException(status_code=400, detail="The URL returned an empty text document.")
        return f"Captured URL: {url}\n\n{compact[:12000]}"

    extracted = _extract_html_text(text)
    if not extracted:
        raise HTTPException(status_code=400, detail="No readable text content could be extracted from the URL.")
    return f"Captured URL: {url}\n\n{extracted[:12000]}"


def _extract_pdf_text(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf is not installed; PDF upload will fall back to metadata-only capture.")
        return ""

    try:
        reader = PdfReader(BytesIO(file_bytes))
    except Exception:
        logger.exception("Failed to parse uploaded PDF.")
        return ""

    parts: list[str] = []
    for page in reader.pages[:20]:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            logger.exception("Failed to extract text from PDF page.")
            continue
        cleaned = " ".join(page_text.split())
        if cleaned:
            parts.append(cleaned)
        if sum(len(part) for part in parts) >= 12000:
            break
    return "\n".join(parts).strip()


def _extract_html_text(html: str) -> str:
    parser = _ReadableHtmlParser()
    parser.feed(html)
    parser.close()
    lines = [line.strip() for line in parser.text_parts if line.strip()]
    deduped: list[str] = []
    for line in lines:
        if line not in deduped:
            deduped.append(line)
    return "\n".join(deduped)


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


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self._ignored_stack: list[str] = []
        self._block_tags = {
            "article",
            "br",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "footer",
            "li",
            "main",
            "p",
            "section",
            "title",
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored_stack.append(tag)
            return
        if tag in self._block_tags:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_stack and self._ignored_stack[-1] == tag:
            self._ignored_stack.pop()
            return
        if tag in self._block_tags:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_stack:
            return
        compact = " ".join(data.split())
        if compact:
            self.text_parts.append(compact)


app = create_app()
