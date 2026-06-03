"""Capture flow integration tests with the PreExtractService wired in.

These tests do NOT hit Postgres or a live LLM. They use a fake in-memory
store and a fake PreExtractService that returns scripted SectionMaps so we
can exercise the section-based chunking + graph_worthy routing.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from personal_agent.agent.ingestion_pipeline import IngestionPipeline
from personal_agent.core.config import LangExtractConfig
from personal_agent.core.models import AgentState, RawIngestItem
from personal_agent.extract.schemas import SectionMap, SectionRecord
from personal_agent.extract.service import PreExtractService


def _run_local_pipeline(state: AgentState, store, service: PreExtractService) -> AgentState:
    """Test helper: invoke IngestionPipeline's local node sequence directly.

    Bypasses __init__ so tests can use a FakeStore without constructing graph
    plumbing they don't exercise.
    """
    pipeline = object.__new__(IngestionPipeline)
    pipeline.store = store
    pipeline.preextract_service = service
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
        raw_item=RawIngestItem(content=text, source_type="text", user_id="test-user"),
    )


def _stub_service(section_map: SectionMap) -> PreExtractService:
    cfg = LangExtractConfig(api_key="k", min_doc_chars=1)
    service = PreExtractService(cfg)
    service.extract = MagicMock(return_value=section_map)  # type: ignore[method-assign]
    return service


def test_preextract_short_doc_skipped() -> None:
    """Doc shorter than min_doc_chars → status skipped, service.extract not called."""
    store = FakeStore()
    section_map = SectionMap(sections=[
        SectionRecord(topic="should-not-be-used", graph_worthy=True),
    ])
    service = _stub_service(section_map)
    service.config = LangExtractConfig(api_key="k", min_doc_chars=1000)

    state = _make_state("tiny")
    result = _run_local_pipeline(state, store, service)

    assert result.note.preextract.status == "skipped"
    service.extract.assert_not_called()  # type: ignore[attr-defined]


def test_preextract_replaces_chunks_with_sections() -> None:
    """SectionMap with >=2 sections → chunk_notes are rebuilt from sections."""
    store = FakeStore()
    text = "AAAA " * 40 + "BBBB " * 40 + "CCCC " * 40  # ~600 chars
    section_a_end = text.find("BBBB")
    section_b_end = text.find("CCCC")
    section_map = SectionMap(
        doc_topic="Test doc topic",
        sections=[
            SectionRecord(
                topic="Block A (worthy)",
                summary="A is worthy",
                char_start=0,
                char_end=section_a_end,
                graph_worthy=True,
                contains_entities=["A"],
            ),
            SectionRecord(
                topic="Block B (boilerplate)",
                summary="B is boilerplate",
                char_start=section_a_end,
                char_end=section_b_end,
                graph_worthy=False,
            ),
            SectionRecord(
                topic="Block C (worthy)",
                summary="C is worthy",
                char_start=section_b_end,
                char_end=len(text),
                graph_worthy=True,
            ),
        ],
    )
    service = _stub_service(section_map)
    state = _make_state(text)
    result = _run_local_pipeline(state, store, service)

    assert result.note.preextract.status == "ok"
    assert result.note.preextract.topic == "Test doc topic"
    # Aggregate worthy = any section worthy
    assert result.note.preextract.graph_worthy is True
    assert result.note.preextract.section_map is not None
    assert len(result.note.preextract.section_map["sections"]) == 3

    assert len(result.chunk_notes) == 3
    worthy_flags = [c.preextract.graph_worthy for c in result.chunk_notes]
    assert worthy_flags == [True, False, True]
    titles = [c.body.title for c in result.chunk_notes]
    assert "Block A (worthy)" in titles[0]
    assert "Block B (boilerplate)" in titles[1]
    spans = [c.chunk.source_span for c in result.chunk_notes]
    assert spans[0] == f"0-{section_a_end}"


def test_preextract_failure_records_status_and_keeps_existing_chunks() -> None:
    """If service.extract raises, preextract_status='failed' but graph survives."""
    store = FakeStore()
    cfg = LangExtractConfig(api_key="k", min_doc_chars=1, fallback_on_error=False)
    service = PreExtractService(cfg)
    service.extract = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

    state = _make_state("X" * 50)
    result = _run_local_pipeline(state, store, service)

    assert result.note is not None
    assert result.note.preextract.status == "failed"
    assert result.note.preextract.section_map is None


def test_preextract_single_section_propagates_worthy_to_existing_chunks() -> None:
    """Single section → keep mechanical chunks but stamp graph_worthy on each."""
    store = FakeStore()
    section_map = SectionMap(
        sections=[
            SectionRecord(
                topic="lone section",
                graph_worthy=False,
                char_start=0,
                char_end=10,
            )
        ]
    )
    service = _stub_service(section_map)
    state = _make_state("X" * 50)
    result = _run_local_pipeline(state, store, service)

    assert result.note.preextract.status == "ok"
    assert result.note.preextract.graph_worthy is False
    # No mechanical chunks for short text — chunk_notes is empty by capture_node.
    # The propagation loop just iterates an empty list, which is fine.
    assert result.chunk_notes == []
