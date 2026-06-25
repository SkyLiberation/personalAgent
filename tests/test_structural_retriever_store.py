from __future__ import annotations

from personal_agent.kernel.models import KnowledgeNote, local_now
from personal_agent.memory.structural_retriever import StructuralRetrieverStore
from tests.note_factory import make_note


class FakeStore:
    def __init__(self, notes: list[KnowledgeNote]) -> None:
        self.notes = notes
        self.calls = 0

    def list_notes(self, user_id: str, *, include_chunks: bool = True) -> list[KnowledgeNote]:
        self.calls += 1
        return [note for note in self.notes if note.user_id == user_id]


def test_structural_retriever_ranks_child_and_reuses_cache():
    parent = make_note(
        id="parent",
        user_id="u1",
        title="Redis cache architecture",
        content="Long document.",
        summary="Redis cache design.",
    )
    child = make_note(
        id="child",
        user_id="u1",
        parent_note_id="parent",
        chunk_index=0,
        title="Redis cache architecture",
        content="Redis stores hot order data and reduces database pressure.",
        summary="Redis stores hot order data.",
    )
    other = make_note(
        id="other",
        user_id="u1",
        title="Payment UI",
        content="Buttons and colors are evaluated.",
        summary="Payment user interface.",
    )
    fake_store = FakeStore([parent, child, other])
    store = StructuralRetrieverStore(fake_store)  # type: ignore[arg-type]

    first = store.search_notes("How does Redis reduce database pressure?", "u1", limit=3)
    second = store.search_notes("How does Redis reduce database pressure?", "u1", limit=3)

    assert first[0].id in {"child", "parent"}
    assert [note.id for note in first] == [note.id for note in second]
    assert fake_store.calls == 2


def test_structural_retriever_invalidates_cache_when_note_updates():
    note = make_note(
        id="n1",
        user_id="u1",
        title="Old deployment",
        content="Blue deployment.",
        summary="Blue deployment.",
    )
    fake_store = FakeStore([note])
    store = StructuralRetrieverStore(fake_store)  # type: ignore[arg-type]

    assert store.search_notes("blue deployment", "u1", limit=1)[0].id == "n1"

    fake_store.notes[0] = note.model_copy(
        update={
            "content": "Green deployment.",
            "summary": "Green deployment.",
            "updated_at": local_now(),
        }
    )

    assert store.search_notes("green deployment", "u1", limit=1)[0].id == "n1"
