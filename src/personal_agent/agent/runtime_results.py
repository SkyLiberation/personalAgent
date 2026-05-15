from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.models import Citation, EntryIntent, KnowledgeNote, ReviewCard
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
    evidence: list = Field(default_factory=list)
    session_id: str = "default"


class DigestResult(BaseModel):
    message: str
    recent_notes: list[KnowledgeNote] = Field(default_factory=list)
    due_reviews: list[ReviewCard] = Field(default_factory=list)


class EntryResult(BaseModel):
    intent: EntryIntent
    reason: str
    reply_text: str
    capture_result: CaptureResult | None = None
    ask_result: AskResult | None = None
    plan_steps: list[dict[str, object]] = Field(default_factory=list)
    execution_trace: list[str] = Field(default_factory=list)


class RetryResult(BaseModel):
    """Result of a verification retry loop, carrying the final answer and verification."""
    answer: str
    verification: VerificationResult
    attempts: int = 0


class ResetResult(BaseModel):
    user_id: str
    deleted_notes: int = 0
    deleted_reviews: int = 0
    deleted_conversations: int = 0
    deleted_upload_files: int = 0
    deleted_ask_history: int = 0
    deleted_graph_episodes: int = 0
