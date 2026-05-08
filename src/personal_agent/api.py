from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .models import Citation, KnowledgeNote, ReviewCard
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


def create_app() -> FastAPI:
    settings = Settings.from_env()
    service = AgentService(settings)
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
        return service.health()

    @app.get("/api/notes", response_model=list[KnowledgeNote])
    def list_notes(user_id: str = "default") -> list[KnowledgeNote]:
        return service.list_notes(user_id)

    @app.get("/api/digest", response_model=DigestResponse)
    def get_digest(user_id: str = "default") -> DigestResponse:
        result = service.digest(user_id)
        return DigestResponse(**result.model_dump())

    @app.post("/api/capture", response_model=CaptureResponse)
    def capture(request: CaptureRequest) -> CaptureResponse:
        result = service.capture(
            text=request.text,
            source_type=request.source_type,
            user_id=request.user_id,
        )
        return CaptureResponse(**result.model_dump())

    @app.post("/api/capture/upload", response_model=CaptureResponse)
    def capture_upload(
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
        capture_text = _capture_text_from_upload(original_name, file.content_type, file_bytes, source_type)

        result = service.capture(
            text=capture_text,
            source_type=source_type,
            user_id=user_id,
        )
        result.note.source_ref = str(stored_path)
        service.store.update_note(result.note)
        return CaptureResponse(**result.model_dump())

    @app.post("/api/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse:
        result = service.ask(request.question, request.user_id)
        return AskResponse(**result.model_dump())

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
        text_content = file_bytes.decode("utf-8", errors="replace").strip()
        if text_content:
            return f"Uploaded file: {filename}\n\n{text_content[:20000]}"

    size_kb = max(1, len(file_bytes) // 1024) if file_bytes else 0
    return (
        f"Uploaded file: {filename}\n"
        f"Source type: {source_type}\n"
        f"Media type: {content_type or 'unknown'}\n"
        f"Size: {size_kb} KB\n\n"
        "This file was uploaded through the web UI. Automatic content extraction for this file type "
        "is not implemented yet, so the knowledge note currently stores file metadata only."
    )


app = create_app()
