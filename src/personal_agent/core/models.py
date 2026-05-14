from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class RawIngestItem(BaseModel):
    content: str
    source_type: Literal["text", "link", "pdf", "audio", "image", "note", "file"] = "text"
    source_ref: str | None = None
    user_id: str = "default"


EntryIntent = Literal[
    "capture_text", "capture_link", "capture_file",
    "ask", "summarize_thread",
    "delete_knowledge", "solidify_conversation",
    "direct_answer",
    "unknown",
]


class EntryInput(BaseModel):
    text: str = ""
    user_id: str = "default"
    session_id: str = "default"
    source_platform: str = "web"
    source_type: str = "text"
    source_ref: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class Citation(BaseModel):
    note_id: str = ""
    title: str
    snippet: str
    relation_fact: str | None = None
    url: str | None = None
    source_type: str = "note"  # "note" or "web"


class WebSearchResult(BaseModel):
    """A single web search hit from an external provider (Firecrawl, etc.)."""
    title: str
    url: str
    snippet: str
    source: str = "firecrawl"
    published_at: str | None = None


class GraphNodeRef(BaseModel):
    uuid: str
    name: str
    labels: list[str] = Field(default_factory=list)
    summary: str = ""


class GraphEdgeRef(BaseModel):
    uuid: str
    fact: str
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    source_node_name: str = ""
    target_node_name: str = ""
    episodes: list[str] = Field(default_factory=list)


class GraphFactRef(BaseModel):
    fact: str
    edge_uuid: str = ""
    source_node_name: str = ""
    target_node_name: str = ""
    episode_uuids: list[str] = Field(default_factory=list)


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
    graph_node_refs: list[GraphNodeRef] = Field(default_factory=list)
    graph_edge_refs: list[GraphEdgeRef] = Field(default_factory=list)
    graph_fact_refs: list[GraphFactRef] = Field(default_factory=list)
    parent_note_id: str | None = None
    chunk_index: int | None = None
    source_span: str | None = None
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
    mode: Literal["capture", "ask", "digest", "entry"] = "capture"
    user_id: str = "default"
    raw_item: RawIngestItem | None = None
    question: str | None = None
    entry_input: EntryInput | None = None
    intent: EntryIntent = "unknown"
    intent_reason: str | None = None
    note: KnowledgeNote | None = None
    chunk_notes: list[KnowledgeNote] = Field(default_factory=list)
    matches: list[KnowledgeNote] = Field(default_factory=list)
    review_card: ReviewCard | None = None
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class AuditEvent(BaseModel):
    """A single audit trail entry for HITL operations."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event: str  # created, confirmed, rejected, expired, retried
    actor: str = "system"
    detail: str = ""


class PendingAction(BaseModel):
    """Human-in-the-loop pending action with confirmation token and expiry."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = "default"
    action_type: str  # delete_note, solidify, etc.
    target_id: str  # note_id or similar
    title: str  # user-visible label
    description: str  # what will happen
    payload: dict[str, object] = Field(default_factory=dict)  # data needed to execute
    token: str = Field(default_factory=lambda: uuid4().hex[:8])  # short confirmation token
    status: Literal["pending", "confirmed", "rejected", "expired", "executed"] = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(
        default_factory=lambda: datetime.utcnow() + timedelta(hours=1)
    )
    resolved_at: datetime | None = None
    audit_log: list[AuditEvent] = Field(default_factory=list)
