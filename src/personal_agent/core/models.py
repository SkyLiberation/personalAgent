from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def local_now() -> datetime:
    return datetime.now().astimezone()


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
    graph_sync_status: Literal["idle", "pending", "synced", "failed", "skipped"] = "idle"
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
    section_map: dict | None = None
    graph_worthy: bool | None = None
    preextract_status: Literal["ok", "skipped", "failed"] | None = None
    preextract_topic: str | None = None
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)


class ReviewCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    note_id: str
    prompt: str
    answer_hint: str
    interval_days: int = 1
    due_at: datetime = Field(default_factory=lambda: local_now() + timedelta(days=1))


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
    evidence: list = Field(default_factory=list)

