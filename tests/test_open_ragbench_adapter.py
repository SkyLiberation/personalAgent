from __future__ import annotations

import pytest

from evals.open_ragbench.adapter import corpus_to_notes
from evals.open_ragbench.loader import RAGBenchDoc


def _docs() -> dict[str, RAGBenchDoc]:
    return {
        "doc-1": RAGBenchDoc(
            doc_id="doc-1",
            title="Paper title",
            abstract="Paper abstract",
            sections=["Section one", "Section two"],
        )
    }


def test_corpus_to_notes_parent_sections_default():
    notes = corpus_to_notes(_docs())

    assert [note.id for note in notes] == [
        "ragbench_doc-1",
        "ragbench_doc-1_sec_0",
        "ragbench_doc-1_sec_1",
    ]


def test_corpus_to_notes_parent_only():
    notes = corpus_to_notes(_docs(), mode="parent_only")

    assert [note.id for note in notes] == ["ragbench_doc-1"]
    assert notes[0].content == "Paper abstract"


def test_corpus_to_notes_section_only():
    notes = corpus_to_notes(_docs(), mode="section_only")

    assert [note.id for note in notes] == ["ragbench_doc-1_sec_0", "ragbench_doc-1_sec_1"]
    assert all(note.parent_note_id == "ragbench_doc-1" for note in notes)


def test_corpus_to_notes_unknown_mode():
    with pytest.raises(ValueError, match="Unknown corpus note mode"):
        corpus_to_notes(_docs(), mode="missing")
