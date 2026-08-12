from __future__ import annotations

from pydantic import BaseModel, Field

from personal_agent.kernel.models import KnowledgeNote, ReviewCard


class CaptureResult(BaseModel):
    note: KnowledgeNote
    chunk_notes: list[KnowledgeNote] = Field(default_factory=list)
    related_notes: list[KnowledgeNote] = Field(default_factory=list)
    review_card: ReviewCard | None = None


class DigestResult(BaseModel):
    message: str
    recent_notes: list[KnowledgeNote] = Field(default_factory=list)
    due_reviews: list[ReviewCard] = Field(default_factory=list)


class EntryResult(BaseModel):
    result_contracts: list[str] = Field(default_factory=list)
    reason: str
    reply_text: str
    capture_result: CaptureResult | None = None
    plan: dict[str, object] | None = None
    steps: list[dict[str, object]] = Field(default_factory=list)
    execution_trace: list[str] = Field(default_factory=list)
    applied_reflection_ids: list[str] = Field(default_factory=list)
    run_id: str | None = None
    thread_id: str | None = None
    pending_confirmation: dict[str, object] | None = None
    run_status: str | None = None
    events: list[object] = Field(default_factory=list)


class ResetResult(BaseModel):
    deleted_notes: int = 0
    deleted_reviews: int = 0
    deleted_upload_files: int = 0
    deleted_graph_nodes: int = 0
    deleted_checkpoints: int = 0
    deleted_checkpoint_blobs: int = 0
    deleted_checkpoint_writes: int = 0
    deleted_checkpoint_migrations: int = 0
    truncated_postgres_tables: int = 0
    deleted_postgres_rows: int = 0
