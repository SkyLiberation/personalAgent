from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from personal_agent.orchestration.orchestration_models import AgentRunStatus
from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.adapters.web.input_normalization import normalize_entry_text
from personal_agent.adapters.web.routes._shared import resolve_user_id
from personal_agent.adapters.web.routes.entry_serializers import (
    EntryResponse,
    ReplayCheckpointRequest,
    ResumeEntryRequest,
    RunCheckpointHistoryResponse,
    RunSnapshotListResponse,
    entry_response,
    run_snapshot_to_response,
)

logger = logging.getLogger(__name__)


class RunControlRequest(BaseModel):
    command: str
    user_id: str = "default"


class RecoverEntryRequest(BaseModel):
    user_id: str = "default"


def register_entry_run_routes(app: FastAPI, *, settings: Settings, service: AgentService) -> None:
    @app.post("/api/entry/runs/{run_id}/control")
    def control_run(run_id: str, body: RunControlRequest, request: Request) -> dict:
        resolved_user = body.user_id if body.user_id != "default" else resolve_user_id(request, settings)
        snapshot = service.get_run_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        if snapshot.user_id != resolved_user:
            raise HTTPException(status_code=403, detail="Run scope denied.")
        if body.command not in {"cancel", "pause", "resume"}:
            raise HTTPException(status_code=400, detail="Unsupported control command.")
        try:
            run = service.control_run(run_id, body.command)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "run_id": run.run_id,
            "status": run.status,
            "revision": run.revision,
            "fencing_token": run.fencing_token,
        }

    @app.post("/api/entry/runs/{run_id}/resume", response_model=EntryResponse)
    def resume_entry(
        run_id: str, body: ResumeEntryRequest, http_request: Request,
    ) -> EntryResponse:
        resolved_user = body.user_id if body.user_id != "default" else resolve_user_id(http_request, settings)

        snapshot = service.get_run_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        if snapshot.status not in {AgentRunStatus.waiting, AgentRunStatus.blocked_approval}:
            raise HTTPException(
                status_code=400,
                detail=f"Run is not in a resumable state (current: {snapshot.status.value}).",
            )

        if body.decision not in ("confirm", "reject", "clarify"):
            raise HTTPException(
                status_code=400,
                detail="decision must be 'confirm', 'reject' or 'clarify'.",
            )
        normalized_text = normalize_entry_text(body.text)
        if body.decision == "clarify" and not normalized_text:
            raise HTTPException(
                status_code=400,
                detail="text is required when decision is 'clarify'.",
            )

        thread_id = snapshot.thread_id
        logger.info(
            "Resuming entry run_id=%s thread_id=%s decision=%s user=%s",
            run_id, thread_id, body.decision, resolved_user,
        )
        result = service.resume_entry(
            run_id=run_id,
            thread_id=thread_id,
            decision=body.decision,
            user_id=resolved_user,
            text=normalized_text,
            option_id=body.option_id,
        )

        return entry_response(result)

    @app.post("/api/entry/runs/{run_id}/recover", response_model=EntryResponse)
    def recover_entry(
        run_id: str, body: RecoverEntryRequest, http_request: Request,
    ) -> EntryResponse:
        resolved_user = (
            body.user_id
            if body.user_id != "default" else resolve_user_id(http_request, settings)
        )
        snapshot = service.get_run_snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        if snapshot.user_id != resolved_user:
            raise HTTPException(status_code=403, detail="Run scope denied.")
        try:
            result = service.recover_entry(run_id, resolved_user)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return entry_response(result)

    @app.get("/api/entry/runs", response_model=RunSnapshotListResponse)
    def list_run_snapshots(
        request: Request, user_id: str | None = None, limit: int = 50
    ) -> RunSnapshotListResponse:
        resolved_user = user_id or resolve_user_id(request, settings)
        snapshots = service.list_run_snapshots(resolved_user, limit)
        return RunSnapshotListResponse(
            items=[run_snapshot_to_response(s) for s in snapshots]
        )

    @app.get("/api/entry/runs/{run_id}/history", response_model=RunCheckpointHistoryResponse)
    def list_run_history(run_id: str, limit: int = 100) -> RunCheckpointHistoryResponse:
        history = service.list_run_history(run_id, limit=limit)
        if not history:
            raise HTTPException(status_code=404, detail="Run history not found.")
        return RunCheckpointHistoryResponse(items=history)

    @app.post("/api/entry/threads/{thread_id}/checkpoints/{checkpoint_id}/replay", response_model=EntryResponse)
    def replay_checkpoint(
        thread_id: str,
        checkpoint_id: str,
        body: ReplayCheckpointRequest,
    ) -> EntryResponse:
        try:
            result = service.replay_from_checkpoint(
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                updates=body.updates,
                as_node=body.as_node,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return entry_response(result)
