from __future__ import annotations

import json

from pydantic import BaseModel, Field


class EntryResponse(BaseModel):
    intent: str
    reason: str
    reply_text: str
    capture_result: dict | None = None
    ask_result: dict | None = None
    steps: list[dict[str, object]] = Field(default_factory=list)
    execution_trace: list[str] = Field(default_factory=list)
    run_id: str | None = None
    pending_confirmation: dict[str, object] | None = None
    run_status: str | None = None


class ResumeEntryRequest(BaseModel):
    decision: str = Field(min_length=1)
    user_id: str = "default"
    text: str = ""
    option_id: str = ""


class ReplayCheckpointRequest(BaseModel):
    updates: dict[str, object] = Field(default_factory=dict)
    as_node: str | None = None


class RunSnapshotResponse(BaseModel):
    run_id: str
    thread_id: str
    user_id: str
    session_id: str
    status: str
    intent: str
    entry_text: str
    steps: list[dict[str, object]] = Field(default_factory=list)
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


class RunCheckpointHistoryResponse(BaseModel):
    items: list[dict[str, object]] = Field(default_factory=list)


def chunk_answer(answer: str, chunk_size: int = 40):
    for i in range(0, len(answer), chunk_size):
        yield answer[i:i + chunk_size]


def sse_event(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def entry_response(result) -> EntryResponse:
    return EntryResponse(**entry_response_dict(result))


def entry_response_dict(result) -> dict[str, object]:
    return {
        "intent": result.intent,
        "reason": result.reason,
        "reply_text": result.reply_text,
        "capture_result": result.capture_result.model_dump(mode="json") if result.capture_result else None,
        "ask_result": result.ask_result.model_dump(mode="json") if result.ask_result else None,
        "steps": result.steps,
        "execution_trace": result.execution_trace,
        "run_id": result.run_id,
        "pending_confirmation": result.pending_confirmation,
        "run_status": result.run_status,
    }


def run_snapshot_to_response(snapshot) -> RunSnapshotResponse:
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
        steps=snapshot.steps,
        execution_trace=snapshot.execution_trace,
        answer=snapshot.answer,
        pending_confirmation=snapshot.pending_confirmation,
        confirmation_decision=snapshot.confirmation_decision,
        errors=snapshot.errors,
        created_at=snapshot.created_at.isoformat() if snapshot.created_at else None,
        updated_at=snapshot.updated_at.isoformat() if snapshot.updated_at else None,
        last_event=last_evt,
    )
