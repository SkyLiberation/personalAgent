from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from personal_agent.core.models import KnowledgeNote


class EvidenceSource(BaseModel):
    """Read model for answer evidence construction."""

    id: str
    title: str
    content: str
    summary: str
    source_type: str = "text"
    source_ref: str | None = None
    source_fingerprint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_note_id: str | None = None
    source_span: str | None = None


class RetrievalDocument(BaseModel):
    """Read model for lexical/vector/structural retrieval."""

    id: str
    user_id: str
    title: str
    content: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_type: str = "text"
    source_ref: str | None = None
    source_fingerprint: str | None = None
    parent_note_id: str | None = None
    chunk_index: int | None = None
    source_span: str | None = None
    preextract_topic: str | None = None
    entity_names: list[str] = Field(default_factory=list)
    relation_facts: list[str] = Field(default_factory=list)
    updated_at: datetime


class GraphIngestDocument(BaseModel):
    """Read model for Graphiti ingestion.

    It intentionally excludes local retrieval and answer-only fields so the KG
    ingestion layer does not depend on the full persistence schema.
    """

    id: str
    user_id: str
    title: str
    content: str
    summary: str
    source_type: str = "text"
    source_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MatchRef(BaseModel):
    """Minimal read model for citation validation and result matching."""

    id: str
    title: str = ""


def evidence_source_from_note(note: KnowledgeNote) -> EvidenceSource:
    return EvidenceSource(
        id=note.id,
        title=note.body.title,
        content=note.body.content,
        summary=note.body.summary,
        source_type=note.source.type,
        source_ref=note.source.ref,
        source_fingerprint=note.source.fingerprint,
        metadata=dict(note.source.metadata),
        parent_note_id=note.chunk.parent_note_id,
        source_span=note.chunk.source_span,
    )


def retrieval_document_from_note(note: KnowledgeNote) -> RetrievalDocument:
    return RetrievalDocument(
        id=note.id,
        user_id=note.user_id,
        title=note.body.title,
        content=note.body.content,
        summary=note.body.summary,
        tags=list(note.tags),
        metadata=dict(note.source.metadata),
        source_type=note.source.type,
        source_ref=note.source.ref,
        source_fingerprint=note.source.fingerprint,
        parent_note_id=note.chunk.parent_note_id,
        chunk_index=note.chunk.index,
        source_span=note.chunk.source_span,
        preextract_topic=note.preextract.topic,
        entity_names=list(note.graph.entity_names),
        relation_facts=list(note.graph.relation_facts),
        updated_at=note.updated_at,
    )


def graph_ingest_document_from_note(note: KnowledgeNote) -> GraphIngestDocument:
    return GraphIngestDocument(
        id=note.id,
        user_id=note.user_id,
        title=note.body.title,
        content=note.body.content,
        summary=note.body.summary,
        source_type=note.source.type,
        source_ref=note.source.ref,
        metadata=dict(note.source.metadata),
        created_at=note.created_at,
    )


def match_ref_from_note(note: KnowledgeNote) -> MatchRef:
    return MatchRef(id=note.id, title=note.body.title)
