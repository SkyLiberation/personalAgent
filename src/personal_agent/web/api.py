from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from ..core.models import local_now
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agent.orchestration_models import AgentRunStatus, _new_thread_id
from ..agent.service import AgentService
from ..capture import CaptureService
from ..core.config import Settings
from ..core.logging_utils import setup_logging
from ..core.models import AskHistoryRecord, EntryInput, KnowledgeNote, ReviewCard
from ..feishu import FeishuService
from .auth import AuthMiddleware, RateLimiter
logger = logging.getLogger(__name__)


def _chunk_answer(answer: str, chunk_size: int = 40):
    for i in range(0, len(answer), chunk_size):
        yield answer[i:i + chunk_size]


def _get_user_id(request: Request, settings: Settings) -> str:
    """Resolve authenticated user_id from middleware state, fall back to default."""
    return getattr(request.state, "user_id", settings.default_user)


class DigestResponse(BaseModel):
    message: str
    recent_notes: list[KnowledgeNote] = Field(default_factory=list)
    due_reviews: list[ReviewCard] = Field(default_factory=list)


class GraphSyncResponse(BaseModel):
    note: KnowledgeNote
    queued: bool = False


class AskHistoryResponse(BaseModel):
    items: list[AskHistoryRecord] = Field(default_factory=list)



class EntryResponse(BaseModel):
    intent: str
    reason: str
    reply_text: str
    capture_result: dict | None = None
    ask_result: dict | None = None
    plan_steps: list[dict[str, object]] = Field(default_factory=list)
    execution_trace: list[str] = Field(default_factory=list)
    # Phase 3: HITL interrupt/resume
    run_id: str | None = None
    pending_confirmation: dict[str, object] | None = None
    run_status: str | None = None


class ResetDebugDataResponse(BaseModel):
    deleted_notes: int = 0
    deleted_reviews: int = 0
    deleted_upload_files: int = 0
    deleted_ask_history: int = 0
    deleted_graph_nodes: int = 0
    deleted_checkpoints: int = 0
    deleted_checkpoint_blobs: int = 0
    deleted_checkpoint_writes: int = 0
    deleted_checkpoint_migrations: int = 0
    truncated_postgres_tables: int = 0
    deleted_postgres_rows: int = 0


class ToolDescriptionResponse(BaseModel):
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


class ResumeEntryRequest(BaseModel):
    decision: str = Field(min_length=1)  # "confirm" | "reject" | "clarify"
    user_id: str = "default"
    text: str = ""
    option_id: str = ""


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
    app.state.service = service

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

    @app.get("/api/tools", response_model=list[ToolDescriptionResponse])
    def list_tools() -> list[dict[str, object]]:
        specs = service.list_tools()
        return [{"name": s.name, "description": s.description} for s in specs]

    @app.post("/api/tools/{name}/execute", response_model=ToolExecuteResponse)
    def execute_tool(name: str, body: ToolExecuteRequest) -> dict[str, object]:
        result = service.execute_tool(name, **body.kwargs)
        return {"ok": result.get("ok", False), "data": result.get("data"), "error": result.get("error")}

    @app.get("/api/notes", response_model=list[KnowledgeNote])
    def list_notes(
        request: Request,
        user_id: str | None = None,
        flat: bool = False,
    ) -> list[KnowledgeNote]:
        resolved_user = user_id or _get_user_id(request, settings)
        logger.info("Listing notes for user=%s flat=%s", resolved_user, flat)
        return service.store.list_notes(resolved_user, include_chunks=not flat)

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

    @app.delete("/api/notes/{note_id}")
    def delete_note(
        note_id: str,
        request: Request,
        user_id: str | None = None,
        cascade: bool = False,
    ) -> dict[str, object]:
        resolved_user = user_id or _get_user_id(request, settings)
        logger.info("Delete note id=%s user=%s cascade=%s", note_id, resolved_user, cascade)
        note = service.store.get_note(note_id)
        if note is None or note.user_id != resolved_user:
            raise HTTPException(status_code=404, detail="Note not found or not owned by user.")
        graph_episode_uuid = note.graph_episode_uuid

        has_chunks = bool(service.store.get_chunks_for_parent(note_id))
        cascade_chunks = cascade or has_chunks
        service.store.delete_note(note_id, resolved_user, cascade_chunks=cascade_chunks)

        if service.graph_store.configured() and graph_episode_uuid:
            try:
                service.graph_store.delete_episode(str(graph_episode_uuid))
            except Exception:
                logger.exception("Graph episode deletion failed for note %s", note_id)
        return {"ok": True, "deleted_note_id": note_id}

    @app.get("/api/notes/{note_id}/chunks", response_model=list[KnowledgeNote])
    def get_note_chunks(note_id: str, request: Request) -> list[KnowledgeNote]:
        resolved_user = _get_user_id(request, settings)
        note = service.store.get_note(note_id)
        if note is None or note.user_id != resolved_user:
            raise HTTPException(status_code=404, detail="Note not found.")
        return service.store.get_chunks_for_parent(note_id)

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
        note.updated_at = local_now()
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
        thread_id = _new_thread_id(resolved_user, session_id)
        logger.info(
            "Entry stream requested for user=%s session=%s thread_id=%s text=%s",
            resolved_user, session_id, thread_id, text[:120],
        )

        async def event_generator():
            entry_input = EntryInput(
                text=text.strip(),
                user_id=resolved_user,
                session_id=session_id,
                source_platform="web",
            )
            yield _sse_event("status", {"message": "正在理解并执行请求..."})

            # All entry intents use the LangGraph orchestration pipeline so
            # their state, events and thread checkpoints stay consistent.
            progress_queue: asyncio.Queue[tuple[str, dict[str, object]]] = asyncio.Queue()
            loop = asyncio.get_running_loop()
            streamed_graph_events = False

            def _on_progress(event: str, payload: dict[str, object]) -> None:
                loop.call_soon_threadsafe(progress_queue.put_nowait, (event, payload))

            execution_task = asyncio.create_task(
                asyncio.to_thread(service.entry, entry_input, on_progress=_on_progress)
            )
            while not execution_task.done() or not progress_queue.empty():
                try:
                    evt, payload = await asyncio.wait_for(progress_queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
                streamed_graph_events = True
                yield _sse_event(evt, payload)
            result = await execution_task

            # Phase 3: if the graph was interrupted for confirmation,
            # emit the confirmation payload and return early.
            if result.pending_confirmation:
                yield _sse_event("intent", {
                    "intent": result.intent,
                    "reason": result.reason,
                })
                yield _sse_event("confirmation_required", {
                    "run_id": result.run_id,
                    "pending_confirmation": result.pending_confirmation,
                })
                yield _sse_event("done", {
                    "reply": result.reply_text,
                    "waiting_confirmation": True,
                    "run_id": result.run_id,
                })
                return

            # Phase 5: when graph events are available, derive SSE from them
            if result.events and not streamed_graph_events:
                from ..agent.orchestration_models import (
                    events_to_sse_tuples,
                    execution_trace_from_events,
                )
                from ..agent.orchestration_models import AgentEvent

                parsed_events = [AgentEvent.model_validate(e) for e in result.events]
                for sse_type, payload in events_to_sse_tuples(parsed_events):
                    # Each result branch emits one terminal event below with
                    # its full payload (citations, matches, reply text).
                    if sse_type == "done":
                        continue
                    yield _sse_event(sse_type, payload)

                # Emit plan_steps and execution_trace derived from events
                if result.plan_steps:
                    yield _sse_event("plan_created", {
                        "plan_steps": result.plan_steps,
                    })
                derived_trace = execution_trace_from_events(parsed_events)
                if derived_trace:
                    yield _sse_event("execution_trace", {
                        "execution_trace": derived_trace,
                    })
            elif not result.events and not streamed_graph_events:
                # Legacy path: use result fields directly
                if result.plan_steps:
                    yield _sse_event("plan_created", {
                        "plan_steps": result.plan_steps,
                    })

                if result.execution_trace:
                    yield _sse_event("execution_trace", {
                        "execution_trace": result.execution_trace,
                    })

            if streamed_graph_events and result.execution_trace:
                yield _sse_event("execution_trace", {
                    "execution_trace": result.execution_trace,
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

        if result.capture_result and service.graph_store.configured():
            for chunk in (result.capture_result.chunk_notes or []):
                background_tasks.add_task(service.sync_note_to_graph, chunk.id)

        return {
            "intent": result.intent,
            "reason": result.reason,
            "reply_text": result.reply_text,
            "capture_result": result.capture_result.model_dump(mode="json") if result.capture_result else None,
            "ask_result": result.ask_result.model_dump(mode="json") if result.ask_result else None,
            "plan_steps": result.plan_steps,
            "execution_trace": result.execution_trace,
        }

    @app.post("/api/entry/runs/{run_id}/resume", response_model=EntryResponse)
    def resume_entry(
        run_id: str, body: ResumeEntryRequest, http_request: Request,
    ) -> EntryResponse:
        """Resume a graph run that was interrupted for HITL or clarification."""
        resolved_user = body.user_id if body.user_id != "default" else _get_user_id(http_request, settings)

        snapshot = service.get_run_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        if snapshot.status != AgentRunStatus.waiting_confirmation:
            raise HTTPException(
                status_code=400,
                detail=f"Run is not in a resumable state (current: {snapshot.status.value}).",
            )

        if body.decision not in ("confirm", "reject", "clarify"):
            raise HTTPException(
                status_code=400,
                detail="decision must be 'confirm', 'reject' or 'clarify'.",
            )
        if body.decision == "clarify" and not body.text.strip():
            raise HTTPException(
                status_code=400,
                detail="text is required when decision is 'clarify'.",
            )

        thread_id = snapshot.thread_id
        logger.info(
            "Resuming entry run_id=%s thread_id=%s decision=%s user=%s",
            run_id, thread_id, body.decision, resolved_user,
        )
        result = service._runtime.resume_entry(
            run_id=run_id,
            thread_id=thread_id,
            decision=body.decision,
            user_id=resolved_user,
            text=body.text,
            option_id=body.option_id,
        )

        return EntryResponse(
            intent=result.intent,
            reason=result.reason,
            reply_text=result.reply_text,
            capture_result=result.capture_result.model_dump(mode="json") if result.capture_result else None,
            ask_result=result.ask_result.model_dump(mode="json") if result.ask_result else None,
            plan_steps=result.plan_steps,
            execution_trace=result.execution_trace,
            run_id=result.run_id,
            pending_confirmation=result.pending_confirmation,
            run_status=result.run_status,
        )

    @app.get("/api/ask-history/search", response_model=AskHistoryResponse)
    def search_ask_history(
        request: Request,
        q: str = "",
        user_id: str | None = None,
        limit: int = 20,
        session_id: str | None = None,
    ) -> AskHistoryResponse:
        resolved_user = user_id or _get_user_id(request, settings)
        if not q.strip():
            return AskHistoryResponse(items=[])
        logger.info("Ask history search for user=%s query=%s", resolved_user, q[:80])
        return AskHistoryResponse(items=service.search_ask_history(resolved_user, q, limit, session_id))

    @app.delete("/api/ask-history/{record_id}")
    def delete_ask_history_record(
        record_id: str, request: Request, user_id: str | None = None
    ) -> dict[str, object]:
        resolved_user = user_id or _get_user_id(request, settings)
        logger.info("Delete ask history record id=%s user=%s", record_id, resolved_user)
        deleted = service.delete_ask_record(resolved_user, record_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Record not found or not owned by user.")
        return {"ok": True, "deleted_id": record_id}

    @app.post("/api/debug/reset-database", response_model=ResetDebugDataResponse)
    def reset_debug_data() -> ResetDebugDataResponse:
        logger.warning("Full debug data reset requested")
        result = service.reset_debug_data()
        return ResetDebugDataResponse(**result.model_dump())

    # ---- Run snapshot API (orchestration graph checkpoint queries) ----

    class RunSnapshotResponse(BaseModel):
        run_id: str
        thread_id: str
        user_id: str
        session_id: str
        status: str
        intent: str
        entry_text: str
        plan_steps: list[dict[str, object]] = Field(default_factory=list)
        execution_trace: list[str] = Field(default_factory=list)
        answer: str | None = None
        pending_confirmation: dict[str, object] | None = None
        confirmation_decision: str | None = None
        errors: list[str] = Field(default_factory=list)
        created_at: str | None = None
        updated_at: str | None = None
        last_event: dict[str, object] | None = None

    class RunSnapshotListResponse(BaseModel):
        items: list[RunSnapshotResponse] = Field(default_factory=list)

    def _run_snapshot_to_response(snapshot) -> RunSnapshotResponse:
        last_evt = None
        if snapshot.last_event:
            last_evt = snapshot.last_event.model_dump(mode="json")
        return RunSnapshotResponse(
            run_id=snapshot.run_id,
            thread_id=snapshot.thread_id,
            user_id=snapshot.user_id,
            session_id=snapshot.session_id,
            status=snapshot.status.value,
            intent=snapshot.intent,
            entry_text=snapshot.entry_text,
            plan_steps=snapshot.plan_steps,
            execution_trace=snapshot.execution_trace,
            answer=snapshot.answer,
            pending_confirmation=snapshot.pending_confirmation,
            confirmation_decision=snapshot.confirmation_decision,
            errors=snapshot.errors,
            created_at=snapshot.created_at.isoformat() if snapshot.created_at else None,
            updated_at=snapshot.updated_at.isoformat() if snapshot.updated_at else None,
            last_event=last_evt,
        )

    @app.get("/api/entry/runs", response_model=RunSnapshotListResponse)
    def list_run_snapshots(
        request: Request, user_id: str | None = None, limit: int = 50
    ) -> RunSnapshotListResponse:
        resolved_user = user_id or _get_user_id(request, settings)
        snapshots = service.list_run_snapshots(resolved_user, limit)
        return RunSnapshotListResponse(
            items=[_run_snapshot_to_response(s) for s in snapshots]
        )

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
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


def _sse_event(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"



    thread.join(timeout=5)


app = create_app()
