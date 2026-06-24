from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from personal_agent.agent.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.models import KnowledgeNote
from personal_agent.web.routes._shared import resolve_user_id

logger = logging.getLogger(__name__)


class GraphSyncResponse(BaseModel):
    note: KnowledgeNote
    queued: bool = False


class RestoreNoteRequest(BaseModel):
    user_id: str | None = None
    snapshot_id: str = ""
    idempotency_key: str = ""


def register_note_routes(
    app: FastAPI,
    *,
    settings: Settings,
    service: AgentService,
) -> None:
    @app.get("/api/notes", response_model=list[dict[str, object]])
    def list_notes(
        request: Request,
        user_id: str | None = None,
        flat: bool = False,
    ) -> list[dict[str, object]]:
        resolved_user = user_id or resolve_user_id(request, settings)
        logger.info("Listing notes for user=%s flat=%s", resolved_user, flat)
        return [_note_response(note) for note in service.memory.list_notes(resolved_user, include_chunks=not flat)]

    @app.delete("/api/notes/{note_id}")
    def delete_note(
        note_id: str,
        request: Request,
        user_id: str | None = None,
        cascade: bool = False,
        delete_reason: str = "",
    ) -> dict[str, object]:
        resolved_user = user_id or resolve_user_id(request, settings)
        logger.info("Delete note id=%s user=%s cascade=%s", note_id, resolved_user, cascade)
        note = service.memory.get_note(note_id, user_id=resolved_user)
        if note is None:
            raise HTTPException(status_code=404, detail="Note not found or not owned by user.")

        result = service.memory.delete_note_confirmed(note_id, resolved_user, delete_reason=delete_reason)
        if not result.ok:
            raise HTTPException(status_code=404, detail=result.error or "Note not found or not owned by user.")
        return {
            "ok": True,
            "deleted_note_id": note_id,
            "snapshot_id": result.snapshot_id,
            "graph_cleaned": result.graph_cleaned,
            "graph_failed": result.graph_failed,
        }

    @app.post("/api/memory/notes/{note_id}/restore")
    def restore_note(
        note_id: str,
        body: RestoreNoteRequest,
        request: Request,
    ) -> dict[str, object]:
        resolved_user = body.user_id or resolve_user_id(request, settings)
        idempotency_key = body.idempotency_key or f"api-restore:{resolved_user}:{body.snapshot_id or note_id}"
        logger.info(
            "Restore note requested note_id=%s snapshot_id=%s user=%s",
            note_id,
            body.snapshot_id,
            resolved_user,
        )
        result = service.execute_tool(
            "restore_note",
            note_id=note_id,
            snapshot_id=body.snapshot_id,
            user_id=resolved_user,
            confirmed=True,
            idempotency_key=idempotency_key,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result.get("error") or "Restore failed.")
        return {"ok": True, "data": result.get("data")}

    @app.post("/api/memory/delete-snapshots/{snapshot_id}/restore")
    def restore_note_snapshot(
        snapshot_id: str,
        body: RestoreNoteRequest,
        request: Request,
    ) -> dict[str, object]:
        resolved_user = body.user_id or resolve_user_id(request, settings)
        idempotency_key = body.idempotency_key or f"api-restore:{resolved_user}:{snapshot_id}"
        logger.info("Restore snapshot requested snapshot_id=%s user=%s", snapshot_id, resolved_user)
        result = service.execute_tool(
            "restore_note",
            snapshot_id=snapshot_id,
            user_id=resolved_user,
            confirmed=True,
            idempotency_key=idempotency_key,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result.get("error") or "Restore failed.")
        return {"ok": True, "data": result.get("data")}

    @app.get("/api/notes/{note_id}/chunks", response_model=list[KnowledgeNote])
    def get_note_chunks(note_id: str, request: Request) -> list[KnowledgeNote]:
        resolved_user = resolve_user_id(request, settings)
        note = service.memory.get_note(note_id, user_id=resolved_user)
        if note is None:
            raise HTTPException(status_code=404, detail="Note not found.")
        return service.memory.list_chunks(note_id, user_id=resolved_user)

    @app.post("/api/notes/{note_id}/graph-sync", response_model=GraphSyncResponse)
    def retry_graph_sync(note_id: str) -> GraphSyncResponse:
        note = service.memory.get_note(note_id)
        if note is None:
            raise HTTPException(status_code=404, detail="Note not found.")

        if not service.graph_store.configured():
            logger.warning("Graph sync retry requested but graph is not configured note_id=%s", note_id)
            return GraphSyncResponse(note=note, queued=False)

        note = service.memory.mark_graph_sync_pending(note_id) or note
        logger.info("Starting manual graph sync retry note_id=%s", note_id)
        service.sync_note_to_graph(note_id)
        updated_note = service.memory.get_note(note_id) or note
        logger.info(
            "Finished manual graph sync retry note_id=%s graph_sync_status=%s",
            note_id,
            updated_note.graph_sync.status,
        )
        return GraphSyncResponse(note=updated_note, queued=False)


def _note_response(note: KnowledgeNote) -> dict[str, object]:
    payload = note.model_dump(mode="json")
    payload.update({
        "title": note.title,
        "content": note.content,
        "summary": note.summary,
        "source_type": note.source_type,
        "source_ref": note.source_ref,
        "source_fingerprint": note.source_fingerprint,
        "parent_note_id": note.parent_note_id,
        "chunk_index": note.chunk_index,
        "source_span": note.source_span,
    })
    return payload
