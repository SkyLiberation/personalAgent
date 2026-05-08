from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class RawIngestItem(BaseModel):
    content: str
    source_type: Literal["text", "link", "pdf", "audio", "image", "note"] = "text"
    source_ref: str | None = None
    user_id: str = "default"


class Citation(BaseModel):
    note_id: str
    title: str
    snippet: str
    relation_fact: str | None = None


class KnowledgeNote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = "default"
    source_type: str = "text"
    source_ref: str | None = None
    graph_sync_status: Literal["idle", "pending", "synced", "failed"] = "idle"
    graph_sync_error: str | None = None
    title: str
    content: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    related_note_ids: list[str] = Field(default_factory=list)
    graph_episode_uuid: str | None = None
    entity_names: list[str] = Field(default_factory=list)
    relation_facts: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ReviewCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    note_id: str
    prompt: str
    answer_hint: str
    interval_days: int = 1
    due_at: datetime = Field(default_factory=lambda: datetime.utcnow() + timedelta(days=1))


class AskHistoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = "default"
    session_id: str = "default"
    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    graph_enabled: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentState(BaseModel):
    mode: Literal["capture", "ask", "digest"] = "capture"
    user_id: str = "default"
    raw_item: RawIngestItem | None = None
    question: str | None = None
    note: KnowledgeNote | None = None
    matches: list[KnowledgeNote] = Field(default_factory=list)
    review_card: ReviewCard | None = None
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
