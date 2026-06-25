"""Capture flow tests for the Unstructured-backed partition/chunk layer.

These tests do not call the real Unstructured parser. They patch the adapter so
the capture pipeline can exercise structure-aware chunk materialization without
external document parsing dependencies.
"""
from __future__ import annotations

from typing import Any

from personal_agent.orchestration.ingestion_pipeline import IngestionPipeline
from personal_agent.kernel.models import AgentState, ChunkDraft, RawIngestItem


def _run_local_pipeline(state: AgentState, store) -> AgentState:
    pipeline = object.__new__(IngestionPipeline)
    pipeline.memory = store
    return pipeline._run_local_pipeline(state)


class FakeStore:
    """Minimal in-memory stand-in for PostgresMemoryStore."""

    def __init__(self) -> None:
        self.notes: dict[str, Any] = {}
        self.reviews: list[Any] = []

    def add_note(self, note: Any) -> None:
        self.notes[note.id] = note

    def update_note(self, note: Any) -> None:
        self.notes[note.id] = note

    def add_review(self, review: Any) -> None:
        self.reviews.append(review)

    def find_similar_notes(self, _user_id: str, _query: str) -> list[Any]:
        return []


def _make_state(text: str) -> AgentState:
    return AgentState(
        mode="capture",
        user_id="test-user",
        raw_item=RawIngestItem(
            content=text,
            source_type="file",
            source_ref="design.pdf",
            user_id="test-user",
            metadata={"original_filename": "design.pdf"},
        ),
    )


def test_unstructured_chunks_materialize_child_notes(monkeypatch) -> None:
    store = FakeStore()
    drafts = [
        ChunkDraft(
            title="架构概览",
            content="系统入口、路由和编排说明。",
            source_span="chunk 1 | page 1 | 架构概览 | elements e1..e2",
            title_path=["架构概览"],
            page_number=1,
            element_ids=["e1", "e2"],
            category="CompositeElement",
            metadata={"languages": ["zho"], "page_number": 1},
        ),
        ChunkDraft(
            title="删除流程",
            content="删除需要 resolve、HITL 和幂等保护。",
            source_span="chunk 2 | page 2 | 删除流程 | elements e3..e4",
            title_path=["删除流程"],
            page_number=2,
            element_ids=["e3", "e4"],
            category="CompositeElement",
            metadata={"languages": ["zho"], "page_number": 2},
        ),
    ]

    monkeypatch.setattr(
        "personal_agent.application.document_partition.partition_to_chunk_drafts",
        lambda *args, **kwargs: drafts,
    )

    result = _run_local_pipeline(_make_state("ignored by patched adapter"), store)

    assert result.note is not None
    assert result.note.preextract.status is None
    assert result.note.source.metadata["chunking"]["provider"] == "unstructured"
    assert len(result.chunk_notes) == 2
    assert [chunk.body.title for chunk in result.chunk_notes] == ["架构概览", "删除流程"]
    assert result.chunk_notes[0].chunk.parent_note_id == result.note.id
    assert result.chunk_notes[0].chunk.title_path == ["架构概览"]
    assert result.chunk_notes[0].chunk.page_number == 1
    assert result.chunk_notes[0].chunk.element_ids == ["e1", "e2"]
    assert result.chunk_notes[0].source.metadata["chunking"]["provider"] == "unstructured"
    assert result.chunk_notes[0].preextract.status == "skipped"


def test_single_unstructured_chunk_keeps_parent_only(monkeypatch) -> None:
    store = FakeStore()
    drafts = [
        ChunkDraft(
            title="短文档",
            content="短内容。",
            source_span="document",
            metadata={"category": "NarrativeText"},
        )
    ]
    monkeypatch.setattr(
        "personal_agent.application.document_partition.partition_to_chunk_drafts",
        lambda *args, **kwargs: drafts,
    )

    result = _run_local_pipeline(_make_state("短内容。"), store)

    assert result.note is not None
    assert result.chunk_notes == []
    assert "unstructured" in result.note.source.metadata
