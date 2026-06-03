from __future__ import annotations

from typing import Any

from personal_agent.core.models import (
    KnowledgeNote,
    NoteBody,
    NoteChunk,
    NoteGraphKnowledge,
    NoteGraphQuality,
    NoteGraphSync,
    NotePreExtract,
    NoteSource,
)


def make_note(
    *,
    title: str = "Title",
    content: str = "Content",
    summary: str = "Summary",
    source_type: str = "text",
    source_ref: str | None = None,
    source_fingerprint: str | None = None,
    metadata: dict[str, str] | None = None,
    parent_note_id: str | None = None,
    chunk_index: int | None = None,
    source_span: str | None = None,
    graph_episode_uuid: str | None = None,
    entity_names: list[str] | None = None,
    relation_facts: list[str] | None = None,
    graph_node_refs: list[Any] | None = None,
    graph_edge_refs: list[Any] | None = None,
    graph_fact_refs: list[Any] | None = None,
    graph_sync_status: str = "idle",
    graph_sync_error: str | None = None,
    section_map: dict | None = None,
    graph_worthy: bool | None = None,
    preextract_status: str | None = None,
    preextract_topic: str | None = None,
    graph_quality_entity_count: int | None = None,
    graph_quality_relation_count: int | None = None,
    graph_quality_avg_fact_length: float | None = None,
    graph_quality_zero_entities: bool | None = None,
    graph_quality_weak_relations_only: bool | None = None,
    **kwargs: Any,
) -> KnowledgeNote:
    return KnowledgeNote(
        **kwargs,
        source=NoteSource(
            type=source_type,
            ref=source_ref,
            fingerprint=source_fingerprint,
            metadata=dict(metadata or {}),
        ),
        body=NoteBody(title=title, content=content, summary=summary),
        chunk=NoteChunk(
            parent_note_id=parent_note_id,
            index=chunk_index,
            source_span=source_span,
        ),
        preextract=NotePreExtract(
            section_map=section_map,
            graph_worthy=graph_worthy,
            status=preextract_status,
            topic=preextract_topic,
        ),
        graph=NoteGraphKnowledge(
            episode_uuid=graph_episode_uuid,
            entity_names=list(entity_names or []),
            relation_facts=list(relation_facts or []),
            node_refs=list(graph_node_refs or []),
            edge_refs=list(graph_edge_refs or []),
            fact_refs=list(graph_fact_refs or []),
        ),
        graph_sync=NoteGraphSync(status=graph_sync_status, error=graph_sync_error),
        graph_quality=NoteGraphQuality(
            entity_count=graph_quality_entity_count,
            relation_count=graph_quality_relation_count,
            avg_fact_length=graph_quality_avg_fact_length,
            zero_entities=graph_quality_zero_entities,
            weak_relations_only=graph_quality_weak_relations_only,
        ),
    )
