from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.models import Citation, EntryIntent, KnowledgeNote, ReviewCard
from ..core.projections import MatchRef
from .verifier import VerificationResult


class CaptureResult(BaseModel):
    note: KnowledgeNote
    chunk_notes: list[KnowledgeNote] = Field(default_factory=list)
    related_notes: list[KnowledgeNote] = Field(default_factory=list)
    review_card: ReviewCard | None = None


class AskResult(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    matches: list[KnowledgeNote] = Field(default_factory=list)
    match_refs: list[MatchRef] = Field(default_factory=list)
    evidence: list = Field(default_factory=list)
    session_id: str = "default"


class DigestResult(BaseModel):
    message: str
    recent_notes: list[KnowledgeNote] = Field(default_factory=list)
    due_reviews: list[ReviewCard] = Field(default_factory=list)


class EntryResult(BaseModel):
    intents: list[EntryIntent] = Field(default_factory=list)
    reason: str
    reply_text: str
    capture_result: CaptureResult | None = None
    ask_result: AskResult | None = None
    plan: dict[str, object] | None = None
    steps: list[dict[str, object]] = Field(default_factory=list)
    execution_trace: list[str] = Field(default_factory=list)
    applied_reflection_ids: list[str] = Field(default_factory=list)
    # Phase 3: HITL interrupt/resume
    run_id: str | None = None
    thread_id: str | None = None
    pending_confirmation: dict[str, object] | None = None
    run_status: str | None = None  # "completed" | "waiting_confirmation"
    # Phase 5: structured events from the orchestration graph
    events: list[object] = Field(default_factory=list)


class RetryResult(BaseModel):
    """Result of a verification retry loop, carrying the final answer and verification."""
    answer: str
    verification: VerificationResult
    attempts: int = 0


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
