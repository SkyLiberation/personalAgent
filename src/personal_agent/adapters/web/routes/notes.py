from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.models import KnowledgeNote, NoteBody
from personal_agent.application.workspace.models import KnowledgeStateEvent
from personal_agent.adapters.web.routes._shared import resolve_user_id

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
        items = service.workspace_service.store.list_knowledge_items(
            resolved_user,
            state="active",
            limit=200,
        )
        return [_workspace_note_response(item) for item in items]

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
        items = service.workspace_service.store.list_knowledge_items(resolved_user, limit=500)
        item = next((candidate for candidate in items if candidate.knowledge_item_id == note_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="Note not found or not owned by user.")
        previous_state = item.state
        item.state = "deleted"
        claims = []
        events = []
        for claim_id in item.claim_ids:
            claim = service.workspace_service.store.get_claim(claim_id)
            if claim is None:
                continue
            previous = claim.state
            claim.state = "deleted"
            claims.append(claim)
            events.append(KnowledgeStateEvent(
                workspace_id=resolved_user,
                target_id=claim.claim_id,
                from_state=previous,
                to_state="deleted",
                reason=delete_reason or "deleted from notes API",
                actor="user",
                evidence_span_ids=list(claim.evidence_span_ids),
                policy_result="user_delete",
            ))
        service.workspace_service.store.save_knowledge_items([item])
        if claims:
            service.workspace_service.store.save_claims(claims)
        if events:
            service.workspace_service.store.save_knowledge_state_events(events)
        return {
            "ok": True,
            "deleted_note_id": note_id,
            "snapshot_id": f"workspace:{resolved_user}:{note_id}:{previous_state}",
            "graph_cleaned": False,
            "graph_failed": False,
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
        items = service.workspace_service.store.list_knowledge_items(resolved_user, limit=500)
        item = next((candidate for candidate in items if candidate.knowledge_item_id == note_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="Restore failed.")
        item.state = "active"
        service.workspace_service.store.save_knowledge_items([item])
        return {"ok": True, "data": _workspace_note_response(item)}

    @app.post("/api/memory/delete-snapshots/{snapshot_id}/restore")
    def restore_note_snapshot(
        snapshot_id: str,
        body: RestoreNoteRequest,
        request: Request,
    ) -> dict[str, object]:
        resolved_user = body.user_id or resolve_user_id(request, settings)
        idempotency_key = body.idempotency_key or f"api-restore:{resolved_user}:{snapshot_id}"
        logger.info("Restore snapshot requested snapshot_id=%s user=%s", snapshot_id, resolved_user)
        parts = snapshot_id.split(":")
        if len(parts) >= 3 and parts[0] == "workspace":
            note_id = parts[2]
            items = service.workspace_service.store.list_knowledge_items(resolved_user, limit=500)
            item = next((candidate for candidate in items if candidate.knowledge_item_id == note_id), None)
            if item is not None:
                item.state = "active"
                service.workspace_service.store.save_knowledge_items([item])
                return {"ok": True, "data": _workspace_note_response(item)}
        raise HTTPException(status_code=404, detail="Restore failed.")

    @app.get("/api/notes/{note_id}/chunks", response_model=list[KnowledgeNote])
    def get_note_chunks(note_id: str, request: Request) -> list[KnowledgeNote]:
        resolved_user = resolve_user_id(request, settings)
        items = service.workspace_service.store.list_knowledge_items(resolved_user, limit=500)
        item = next((candidate for candidate in items if candidate.knowledge_item_id == note_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="Note not found.")
        chunks: list[KnowledgeNote] = []
        for span_id in item.evidence_span_ids:
            span = service.workspace_service.store.get_evidence_span(span_id)
            if span is None:
                continue
            chunks.append(KnowledgeNote(
                id=span.evidence_span_id,
                user_id=resolved_user,
                body=NoteBody(
                    title=f"{item.title} · evidence",
                    content=span.text_span,
                    summary=span.text_span[:240],
                ),
            ))
        return chunks

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


def _workspace_note_response(item) -> dict[str, object]:
    payload = item.model_dump(mode="json")
    payload.update({
        "id": item.knowledge_item_id,
        "title": item.title,
        "content": item.summary,
        "summary": item.summary,
        "source_type": "workspace_item",
        "source_ref": item.knowledge_item_id,
        "source_fingerprint": None,
        "parent_note_id": None,
        "chunk_index": None,
        "source_span": None,
        "claim_ids": list(item.claim_ids),
        "evidence_span_ids": list(item.evidence_span_ids),
    })
    return payload
