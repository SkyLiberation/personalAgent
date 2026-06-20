from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def local_now() -> datetime:
    return datetime.now().astimezone()


class RawIngestItem(BaseModel):
    content: str
    source_type: Literal["text", "link", "pdf", "audio", "image", "note", "file"] = "text"
    source_ref: str | None = None
    user_id: str = "default"
    metadata: dict[str, Any] = Field(default_factory=dict)
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


class ThreadSummary(BaseModel):
    """Structured short-term summary persisted in the thread checkpoint.

    This is a dialogue cue, not a factual evidence source. Fields deliberately
    separate confirmed user state from assistant-side guesses and unverified
    claims so prompt rendering can preserve that boundary.
    """

    user_goals: list[str] = Field(default_factory=list)
    user_constraints: list[str] = Field(default_factory=list)
    confirmed_decisions: list[str] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    assistant_assumptions: list[str] = Field(default_factory=list)
    unverified_claims: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    context_notes: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=local_now)

    def is_empty(self) -> bool:
        return not any(
            (
                self.user_goals,
                self.user_constraints,
                self.confirmed_decisions,
                self.pending_tasks,
                self.open_questions,
                self.assistant_assumptions,
                self.unverified_claims,
                self.evidence_refs,
                self.context_notes,
            )
        )


class Citation(BaseModel):
    note_id: str = ""
    title: str
    snippet: str
    relation_fact: str | None = None
    url: str | None = None
    source_type: str = "note"  # "note" or "web"


class WebSearchResult(BaseModel):
    """A single web search hit from an external provider."""
    title: str
    url: str
    snippet: str
    source: str = "web_search"
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


class NoteProvenance(BaseModel):
    """Source provenance extracted at capture time.

    Drives ask-side metadata filtering and freshness judgement: ``published_at``
    lets recency no longer depend on capture time, ``doc_type`` lets filters
    distinguish a formal document from a chat fragment. All fields optional —
    the heuristic extractor fills what it can confidently derive.
    """

    author: str | None = None
    published_at: str | None = None
    doc_type: str | None = None
    language: str | None = None


class NoteSource(BaseModel):
    type: str = "text"
    ref: str | None = None
    fingerprint: str | None = None
    provenance: NoteProvenance = Field(default_factory=NoteProvenance)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NoteBody(BaseModel):
    title: str
    content: str
    summary: str


class NoteChunk(BaseModel):
    parent_note_id: str | None = None
    index: int | None = None
    source_span: str | None = None
    title_path: list[str] = Field(default_factory=list)
    page_number: int | None = None
    element_ids: list[str] = Field(default_factory=list)
    # Structure-faithful locator: bounding box of the chunk in the source page
    # (Unstructured coordinates), kept so citations can highlight the origin.
    coordinates: dict[str, Any] | None = None
    # Quality gate: low-information / noise chunks (headers, footers, nav, TOC)
    # stay retrievable=False so they never enter retrieval units but remain
    # recoverable via the parent note. Score is the heuristic density signal.
    retrievable: bool = True
    quality_score: float = 1.0


class ChunkDraft(BaseModel):
    title: str
    content: str
    source_span: str
    title_path: list[str] = Field(default_factory=list)
    page_number: int | None = None
    element_ids: list[str] = Field(default_factory=list)
    coordinates: dict[str, Any] | None = None
    category: str = "CompositeElement"
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    attempt_count: int = 0
    last_attempt_at: datetime | None = None
    last_synced_at: datetime | None = None
    last_reconciled_at: datetime | None = None


class NoteGraphQuality(BaseModel):
    entity_count: int | None = None
    relation_count: int | None = None
    avg_fact_length: float | None = None
    zero_entities: bool | None = None
    weak_relations_only: bool | None = None


class NoteVersion(BaseModel):
    version_id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = 1
    status: Literal["current", "superseded", "deprecated", "conflicted"] = "current"
    topic_key: str | None = None
    source_fingerprint: str | None = None
    supersedes_note_ids: list[str] = Field(default_factory=list)
    superseded_by_note_id: str | None = None
    conflict_note_ids: list[str] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    confidence: float = 1.0
    trust_level: Literal["low", "medium", "high"] = "medium"
    reason: str = ""

    @property
    def is_current(self) -> bool:
        return self.status == "current" and self.superseded_by_note_id is None


class GraphSyncTask(BaseModel):
    note_id: str
    user_id: str
    title: str = ""
    status: Literal["idle", "pending", "synced", "failed", "skipped"]
    error: str | None = None
    episode_uuid: str | None = None
    attempt_count: int = 0
    last_attempt_at: datetime | None = None
    last_synced_at: datetime | None = None
    updated_at: datetime | None = None
    quality: NoteGraphQuality = Field(default_factory=NoteGraphQuality)


class GraphReconcileIssue(BaseModel):
    issue_type: Literal[
        "pending_sync",
        "failed_sync",
        "missing_episode",
        "orphan_episode",
        "weak_quality",
        "delete_failed",
        "retry_failed",
    ]
    severity: Literal["info", "warning", "error"] = "warning"
    note_id: str | None = None
    episode_uuid: str | None = None
    message: str = ""
    action: Literal["none", "retry_sync", "delete_episode", "rebuild"] = "none"
    fixed: bool = False
    error: str | None = None


class GraphReconcileReport(BaseModel):
    user_id: str
    checked_notes: int = 0
    pending_count: int = 0
    failed_count: int = 0
    synced_count: int = 0
    skipped_count: int = 0
    orphan_episode_count: int = 0
    weak_quality_count: int = 0
    retried_count: int = 0
    cleaned_orphan_count: int = 0
    issues: list[GraphReconcileIssue] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=local_now)


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
    version: NoteVersion = Field(default_factory=NoteVersion)
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
    def metadata(self) -> dict[str, Any]:
        return self.source.metadata

    @metadata.setter
    def metadata(self, value: dict[str, Any]) -> None:
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


MemoryKind = Literal["semantic", "episodic", "procedural", "reflection"]
EpisodeOutcome = Literal["completed", "failed", "waiting_confirmation", "cancelled"]


class MemoryEpisode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    memory_type: MemoryKind = "episodic"
    user_id: str = "default"
    session_id: str = "default"
    thread_id: str = ""
    run_id: str = ""
    workflow: EntryIntent = "unknown"
    title: str = ""
    summary: str = ""
    outcome: EpisodeOutcome = "completed"
    entry_text: str = ""
    decisions: list[str] = Field(default_factory=list)
    open_items: list[str] = Field(default_factory=list)
    event_refs: list[str] = Field(default_factory=list)
    tool_refs: list[str] = Field(default_factory=list)
    note_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)


class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    memory_type: Literal["procedural", "reflection"]
    user_id: str = "default"
    session_id: str | None = None
    thread_id: str = ""
    title: str = ""
    content: str = ""
    status: Literal["candidate", "confirmed", "rejected", "superseded"] = "candidate"
    confidence: float = 0.5
    source_episode_ids: list[str] = Field(default_factory=list)
    source_run_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    applies_to: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)


class ReviewCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    note_id: str
    prompt: str
    answer_hint: str
    interval_days: int = 1
    due_at: datetime = Field(default_factory=lambda: local_now() + timedelta(days=1))
    last_reviewed_at: datetime | None = None


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

