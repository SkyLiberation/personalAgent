from __future__ import annotations

import logging
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.models import KnowledgeNote, NoteBody
from personal_agent.application.knowledge_lifecycle import (
    KnowledgeDeleteConflict,
    KnowledgeDeleteNotFound,
    KnowledgeDeleteOperationView,
    KnowledgeRestoreOperationView,
)
from personal_agent.adapters.web.routes._shared import (
    resolve_requested_principal,
    resolve_user_id,
)

logger = logging.getLogger(__name__)


class GraphSyncResponse(BaseModel):
    note: KnowledgeNote
    queued: bool = False


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrepareKnowledgeDeleteRequest(_StrictRequest):
    user_id: str | None = None
    reason: str = ""
    idempotency_key: str = Field(min_length=1, max_length=200)


class DecideKnowledgeDeleteRequest(_StrictRequest):
    user_id: str | None = None
    decision: Literal["confirm", "reject"]
    command_digest: str = Field(min_length=64, max_length=64)
    confirmation_ref: str = Field(default="", max_length=200)


class PrepareKnowledgeRestoreRequest(_StrictRequest):
    user_id: str | None = None
    reason: str = ""
    idempotency_key: str = Field(min_length=1, max_length=200)


class DecideKnowledgeRestoreRequest(_StrictRequest):
    user_id: str | None = None
    decision: Literal["confirm", "reject"]
    command_digest: str = Field(min_length=64, max_length=64)
    confirmation_ref: str = Field(default="", max_length=200)


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
        principal = resolve_requested_principal(request, settings, user_id)
        logger.info("Listing notes for user=%s flat=%s", principal.user_id, flat)
        items = service.knowledge_service.store.list_knowledge_items(
            principal.principal_id,
            state="active",
            limit=200,
        )
        return [_knowledge_note_response(item) for item in items]

    @app.post(
        "/api/notes/{note_id}/delete-commands",
        response_model=KnowledgeDeleteOperationView,
    )
    def prepare_note_delete(
        note_id: str,
        body: PrepareKnowledgeDeleteRequest,
        request: Request,
    ) -> KnowledgeDeleteOperationView:
        try:
            principal = resolve_requested_principal(
                request, settings, body.user_id
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        try:
            return service.knowledge_lifecycle_service.prepare_delete(
                owner_id=principal.principal_id,
                user_id=principal.user_id,
                target_note_id=note_id,
                reason=body.reason,
                idempotency_key=body.idempotency_key,
            )
        except KnowledgeDeleteNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except KnowledgeDeleteConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/api/knowledge-delete-commands/{command_id}/decision",
        response_model=KnowledgeDeleteOperationView,
    )
    def decide_note_delete(
        command_id: str,
        body: DecideKnowledgeDeleteRequest,
        request: Request,
    ) -> KnowledgeDeleteOperationView:
        try:
            principal = resolve_requested_principal(
                request, settings, body.user_id
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        try:
            return service.knowledge_lifecycle_service.decide_delete(
                command_id=command_id,
                user_id=principal.user_id,
                decision=body.decision,
                command_digest=body.command_digest,
                confirmation_ref=body.confirmation_ref,
            )
        except KnowledgeDeleteNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (KnowledgeDeleteConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/api/knowledge-delete-commands/{command_id}",
        response_model=KnowledgeDeleteOperationView,
    )
    def get_note_delete(
        command_id: str,
        request: Request,
        user_id: str | None = None,
    ) -> KnowledgeDeleteOperationView:
        resolved_user = user_id or resolve_user_id(request, settings)
        result = service.knowledge_lifecycle_service.get_delete(
            command_id,
            user_id=resolved_user,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="delete command not found")
        return result

    @app.post(
        "/api/knowledge-delete-commands/{delete_command_id}/restore-commands",
        response_model=KnowledgeRestoreOperationView,
    )
    def prepare_note_restore(
        delete_command_id: str,
        body: PrepareKnowledgeRestoreRequest,
        request: Request,
    ) -> KnowledgeRestoreOperationView:
        try:
            principal = resolve_requested_principal(
                request, settings, body.user_id
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        try:
            return service.knowledge_lifecycle_service.prepare_restore(
                owner_id=principal.principal_id,
                user_id=principal.user_id,
                delete_command_id=delete_command_id,
                reason=body.reason,
                idempotency_key=body.idempotency_key,
            )
        except KnowledgeDeleteNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (KnowledgeDeleteConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/api/knowledge-restore-commands/{command_id}/decision",
        response_model=KnowledgeRestoreOperationView,
    )
    def decide_note_restore(
        command_id: str,
        body: DecideKnowledgeRestoreRequest,
        request: Request,
    ) -> KnowledgeRestoreOperationView:
        try:
            resolved_user = resolve_requested_principal(
                request, settings, body.user_id
            ).user_id
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        try:
            return service.knowledge_lifecycle_service.decide_restore(
                command_id=command_id,
                user_id=resolved_user,
                decision=body.decision,
                command_digest=body.command_digest,
                confirmation_ref=body.confirmation_ref,
            )
        except KnowledgeDeleteNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (KnowledgeDeleteConflict, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/api/knowledge-restore-commands/{command_id}",
        response_model=KnowledgeRestoreOperationView,
    )
    def get_note_restore(
        command_id: str,
        request: Request,
        user_id: str | None = None,
    ) -> KnowledgeRestoreOperationView:
        resolved_user = user_id or resolve_user_id(request, settings)
        result = service.knowledge_lifecycle_service.get_restore(
            command_id,
            user_id=resolved_user,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="restore command not found")
        return result

    @app.get("/api/notes/{note_id}/chunks", response_model=list[KnowledgeNote])
    def get_note_chunks(note_id: str, request: Request) -> list[KnowledgeNote]:
        resolved_user = resolve_user_id(request, settings)
        items = service.knowledge_service.store.list_knowledge_items(resolved_user, limit=500)
        item = next((candidate for candidate in items if candidate.knowledge_item_id == note_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="Note not found.")
        chunks: list[KnowledgeNote] = []
        for span_id in item.evidence_span_ids:
            span = service.knowledge_service.store.get_evidence_span(span_id)
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


def _knowledge_note_response(item) -> dict[str, object]:
    payload = item.model_dump(mode="json")
    payload.update({
        "id": item.knowledge_item_id,
        "title": item.title,
        "content": item.summary,
        "summary": item.summary,
        "source_type": "knowledge_item",
        "source_ref": item.knowledge_item_id,
        "source_fingerprint": None,
        "parent_note_id": None,
        "chunk_index": None,
        "source_span": None,
        "claim_ids": list(item.claim_ids),
        "evidence_span_ids": list(item.evidence_span_ids),
    })
    return payload
