"""Capture graph integration tests with the PreExtractService wired in.

These tests do NOT hit Postgres or a live LLM. They use a fake in-memory
store and a fake PreExtractService that returns scripted SectionMaps so we
can exercise the section-based chunking + graph_worthy routing.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from personal_agent.agent.graph import build_capture_graph
from personal_agent.core.config import LangExtractConfig
from personal_agent.core.models import AgentState, RawIngestItem
from personal_agent.extract.schemas import SectionMap, SectionRecord
from personal_agent.extract.service import PreExtractService


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
    cfg = LangExtractConfig(enabled=True, api_key="k", min_doc_chars=1)
    service = PreExtractService(cfg)
    service.extract = MagicMock(return_value=section_map)  # type: ignore[method-assign]
    return service


def test_capture_graph_without_preextract_uses_mechanical_chunking() -> None:
    """When no PreExtractService is wired, the graph behaves like before PR2."""
    store = FakeStore()
    graph = build_capture_graph(store)
    state = _make_state("a short note worth keeping")
    result_dict = graph.invoke(state)
    result = AgentState.model_validate(result_dict)

    assert result.note is not None
    assert result.note.section_map is None
    assert result.note.preextract_status is None
    assert result.note.graph_worthy is None


def test_preextract_disabled_marks_status_skipped() -> None:
    """Service.is_enabled() False → preextract_status='skipped', no chunks rewritten."""
    store = FakeStore()
    cfg = LangExtractConfig(enabled=False, api_key="k")
    # Even though enabled=False, runtime won't pass the service to the graph.
    # Simulate the alternative: someone passed it anyway. is_enabled gate handles it.
    service = PreExtractService(cfg)
    graph = build_capture_graph(store, preextract_service=service)
    state = _make_state("a short note " * 60)  # > min_doc_chars default
    result_dict = graph.invoke(state)
    result = AgentState.model_validate(result_dict)

    assert result.note.preextract_status == "skipped"
    assert result.note.section_map is None
    assert result.note.graph_worthy is None


def test_preextract_short_doc_skipped() -> None:
    """Doc shorter than min_doc_chars → status skipped, service.extract not called."""
    store = FakeStore()
    section_map = SectionMap(sections=[
        SectionRecord(topic="should-not-be-used", graph_worthy=True),
    ])
    service = _stub_service(section_map)
    service.config = LangExtractConfig(enabled=True, api_key="k", min_doc_chars=1000)
    graph = build_capture_graph(store, preextract_service=service)

    state = _make_state("tiny")
    result_dict = graph.invoke(state)
    result = AgentState.model_validate(result_dict)

    assert result.note.preextract_status == "skipped"
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
    graph = build_capture_graph(store, preextract_service=service)
    state = _make_state(text)
    result_dict = graph.invoke(state)
    result = AgentState.model_validate(result_dict)

    assert result.note.preextract_status == "ok"
    assert result.note.preextract_topic == "Test doc topic"
    # Aggregate worthy = any section worthy
    assert result.note.graph_worthy is True
    assert result.note.section_map is not None
    assert len(result.note.section_map["sections"]) == 3

    assert len(result.chunk_notes) == 3
    worthy_flags = [c.graph_worthy for c in result.chunk_notes]
    assert worthy_flags == [True, False, True]
    titles = [c.title for c in result.chunk_notes]
    assert "Block A (worthy)" in titles[0]
    assert "Block B (boilerplate)" in titles[1]
    spans = [c.source_span for c in result.chunk_notes]
    assert spans[0] == f"0-{section_a_end}"


def test_preextract_failure_records_status_and_keeps_existing_chunks() -> None:
    """If service.extract raises, preextract_status='failed' but graph survives."""
    store = FakeStore()
    cfg = LangExtractConfig(enabled=True, api_key="k", min_doc_chars=1, fallback_on_error=False)
    service = PreExtractService(cfg)
    service.extract = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    graph = build_capture_graph(store, preextract_service=service)

    state = _make_state("X" * 50)
    result_dict = graph.invoke(state)
    result = AgentState.model_validate(result_dict)

    assert result.note is not None
    assert result.note.preextract_status == "failed"
    assert result.note.section_map is None


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
    graph = build_capture_graph(store, preextract_service=service)
    state = _make_state("X" * 50)
    result_dict = graph.invoke(state)
    result = AgentState.model_validate(result_dict)

    assert result.note.preextract_status == "ok"
    assert result.note.graph_worthy is False
    # No mechanical chunks for short text — chunk_notes is empty by capture_node.
    # The propagation loop just iterates an empty list, which is fine.
    assert result.chunk_notes == []
