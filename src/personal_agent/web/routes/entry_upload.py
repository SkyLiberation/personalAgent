from __future__ import annotations

import logging

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile

from personal_agent.agent.service import AgentService
from personal_agent.capture import CaptureService
from personal_agent.core.config import Settings
from personal_agent.core.models import EntryInput
from personal_agent.web.input_normalization import normalize_entry_text
from personal_agent.web.routes._shared import resolve_user_id
from personal_agent.web.routes.entry_serializers import entry_response_dict

logger = logging.getLogger(__name__)


def register_entry_upload_route(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
    capture_service: CaptureService,
) -> None:
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
        entry_text = normalize_entry_text(text) or original_name

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

        if result.capture_result and service.graph_store.configured():
            chunk_ids = [
                chunk.id
                for chunk in (result.capture_result.chunk_notes or [])
                if chunk.graph_sync.status == "pending"
            ]
            if chunk_ids:
                background_tasks.add_task(service.sync_notes_to_graph, chunk_ids)

        return entry_response_dict(result)
