from __future__ import annotations

from tests.note_factory import make_note
from personal_agent.core.projections import (
    evidence_source_from_note,
    graph_ingest_document_from_note,
    match_ref_from_note,
    retrieval_document_from_note,
)


def test_projection_views_limit_knowledge_note_surface_area():
    note = make_note(
        id="n1",
        user_id="u1",
        title="Title",
        content="Full content",
        summary="Summary",
        source_type="file",
        source_ref="D:/notes/a.md",
        source_fingerprint="fp",
        metadata={"author": "alice"},
        parent_note_id="p1",
        chunk_index=2,
        source_span="10-20",
        preextract_topic="Topic",
        entity_names=["Redis"],
        relation_facts=["Redis caches orders"],
        graph_episode_uuid="ep-1",
        graph_sync_status="synced",
    )

    evidence = evidence_source_from_note(note)
    retrieval = retrieval_document_from_note(note)
    graph = graph_ingest_document_from_note(note)
    match = match_ref_from_note(note)

    assert evidence.model_dump().keys() <= {
        "id",
        "title",
        "content",
        "summary",
        "source_type",
        "source_ref",
        "source_fingerprint",
        "metadata",
        "parent_note_id",
        "source_span",
    }
    assert retrieval.preextract_topic == "Topic"
    assert retrieval.entity_names == ["Redis"]
    assert graph.model_dump().keys() <= {
        "id",
        "user_id",
        "title",
        "content",
        "summary",
        "source_type",
        "source_ref",
        "metadata",
        "created_at",
    }
    assert "graph_episode_uuid" not in graph.model_dump()
    assert "graph_sync_status" not in graph.model_dump()
    assert match.model_dump() == {"id": "n1", "title": "Title"}
