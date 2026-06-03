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
    metadata: dict[str, str] = Field(default_factory=dict)
    source_fingerprint: str | None = None


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


class NoteSource(BaseModel):
    type: str = "text"
    ref: str | None = None
    fingerprint: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class NoteBody(BaseModel):
    title: str
    content: str
    summary: str


class NoteChunk(BaseModel):
    parent_note_id: str | None = None
    index: int | None = None
    source_span: str | None = None


class ChunkDraft(BaseModel):
    title: str
    content: str
    source_span: str


class NotePreExtract(BaseModel):
    section_map: dict | None = None
    graph_worthy: bool | None = None
    status: Literal["ok", "skipped", "failed"] | None = None
    topic: str | None = None


class NoteGraphKnowledge(BaseModel):
    episode_uuid: str | None = None
    entity_names: list[str] = Field(default_factory=list)
    relation_facts: list[str] = Field(default_factory=list)
    node_refs: list[GraphNodeRef] = Field(default_factory=list)
    edge_refs: list[GraphEdgeRef] = Field(default_factory=list)
    fact_refs: list[GraphFactRef] = Field(default_factory=list)


class NoteGraphSync(BaseModel):
    status: Literal["idle", "pending", "synced", "failed", "skipped"] = "idle"
    error: str | None = None


class NoteGraphQuality(BaseModel):
    entity_count: int | None = None
    relation_count: int | None = None
    avg_fact_length: float | None = None
    zero_entities: bool | None = None
    weak_relations_only: bool | None = None


class KnowledgeNote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = "default"
    source: NoteSource = Field(default_factory=NoteSource)
    body: NoteBody
    tags: list[str] = Field(default_factory=list)
    related_note_ids: list[str] = Field(default_factory=list)
    chunk: NoteChunk = Field(default_factory=NoteChunk)
    preextract: NotePreExtract = Field(default_factory=NotePreExtract)
    graph: NoteGraphKnowledge = Field(default_factory=NoteGraphKnowledge)
    graph_sync: NoteGraphSync = Field(default_factory=NoteGraphSync)
    graph_quality: NoteGraphQuality = Field(default_factory=NoteGraphQuality)
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)

    @property
    def source_type(self) -> str:
        return self.source.type

    @source_type.setter
    def source_type(self, value: str) -> None:
        self.source.type = value

    @property
    def source_ref(self) -> str | None:
        return self.source.ref

    @source_ref.setter
    def source_ref(self, value: str | None) -> None:
        self.source.ref = value

    @property
    def source_fingerprint(self) -> str | None:
        return self.source.fingerprint

    @source_fingerprint.setter
    def source_fingerprint(self, value: str | None) -> None:
        self.source.fingerprint = value

    @property
    def metadata(self) -> dict[str, str]:
        return self.source.metadata

    @metadata.setter
    def metadata(self, value: dict[str, str]) -> None:
        self.source.metadata = value

    @property
    def title(self) -> str:
        return self.body.title

    @title.setter
    def title(self, value: str) -> None:
        self.body.title = value

    @property
    def content(self) -> str:
        return self.body.content

    @content.setter
    def content(self, value: str) -> None:
        self.body.content = value

    @property
    def summary(self) -> str:
        return self.body.summary

    @summary.setter
    def summary(self, value: str) -> None:
        self.body.summary = value

    @property
    def parent_note_id(self) -> str | None:
        return self.chunk.parent_note_id

    @parent_note_id.setter
    def parent_note_id(self, value: str | None) -> None:
        self.chunk.parent_note_id = value

    @property
    def chunk_index(self) -> int | None:
        return self.chunk.index

    @chunk_index.setter
    def chunk_index(self, value: int | None) -> None:
        self.chunk.index = value

    @property
    def source_span(self) -> str | None:
        return self.chunk.source_span

    @source_span.setter
    def source_span(self, value: str | None) -> None:
        self.chunk.source_span = value

    @property
    def graph_worthy(self) -> bool | None:
        return self.preextract.graph_worthy

    @graph_worthy.setter
    def graph_worthy(self, value: bool | None) -> None:
        self.preextract.graph_worthy = value

    @property
    def preextract_status(self) -> Literal["ok", "skipped", "failed"] | None:
        return self.preextract.status

    @preextract_status.setter
    def preextract_status(self, value: Literal["ok", "skipped", "failed"] | None) -> None:
        self.preextract.status = value

    @property
    def preextract_topic(self) -> str | None:
        return self.preextract.topic

    @preextract_topic.setter
    def preextract_topic(self, value: str | None) -> None:
        self.preextract.topic = value


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
    chunk_drafts: list[ChunkDraft] = Field(default_factory=list)
    chunk_notes: list[KnowledgeNote] = Field(default_factory=list)
    matches: list[KnowledgeNote] = Field(default_factory=list)
    review_card: ReviewCard | None = None
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    evidence: list = Field(default_factory=list)

