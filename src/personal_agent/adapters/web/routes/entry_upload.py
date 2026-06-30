from __future__ import annotations

import logging

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile

from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.models import EntryInput
from personal_agent.adapters.web.input_normalization import normalize_entry_text
from personal_agent.adapters.web.routes._shared import resolve_user_id
from personal_agent.adapters.web.routes.entry_serializers import entry_response_dict

logger = logging.getLogger(__name__)


def register_entry_upload_route(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
    capture_service: object | None = None,
) -> None:
    del capture_service

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

        resolved_user = user_id if user_id != "default" else resolve_user_id(request, settings)
        uploads_dir = settings.data_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        file_bytes = file.file.read()
        artifact = service.artifact_service.save_upload(
            filename=file.filename,
            content_type=file.content_type,
            file_bytes=file_bytes,
            uploads_dir=uploads_dir,
        )

        logger.info(
            "Entry artifact upload user=%s artifact_id=%s filename=%s size_bytes=%s",
            resolved_user, artifact.artifact_id, artifact.filename, len(file_bytes),
        )

        metadata: dict[str, str] = {
            "artifact_id": artifact.artifact_id,
            "file_path": artifact.file_path,
            "original_filename": artifact.filename,
            "filename": artifact.filename,
            "content_type": artifact.content_type or "",
            "source_type": artifact.source_type,
        }
        entry_text = normalize_entry_text(text) or "请概述上传附件的内容"

        entry_input = EntryInput(
            text=entry_text,
            user_id=resolved_user,
            session_id=session_id,
            source_platform="web",
            source_type="text",
            source_ref=artifact.artifact_id,
            metadata=metadata,
            artifacts=[artifact],
        )
        result = service.entry(entry_input)

        if result.capture_result and service.graph_store.configured():
            chunk_ids = [
                chunk.id
                for chunk in (result.capture_result.chunk_notes or [])
                if chunk.graph_sync.status == "pending"
            ]
            if chunk_ids:
                background_tasks.add_task(service.sync_notes_to_graph, chunk_ids)

        return entry_response_dict(result)
