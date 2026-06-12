from __future__ import annotations

from pathlib import Path

import pytest

from personal_agent.core.models import ReviewCard
from personal_agent.memory.facade import MemoryFacade
from personal_agent.storage.postgres_memory_store import PostgresMemoryStore
from tests.conftest import POSTGRES_URL
from tests.note_factory import make_note

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


class TestMemoryFacade:
    @pytest.fixture
    def store(self, temp_dir: Path):
        return PostgresMemoryStore(temp_dir, POSTGRES_URL)

    @pytest.fixture
    def facade(self, store):
        return MemoryFacade(local_store=store)

    def test_bind_session_tracks_current_key(self, facade):
        facade.bind_session("user1", "session1")
        assert facade._session_key == "user1:session1"
        facade.bind_session("user1", "session1")
        assert facade._session_key == "user1:session1"
        facade.bind_session("user1", "session2")
        assert facade._session_key == "user1:session2"

    def test_delete_soft_deletes_and_restore_recovers_snapshot(self, facade):
        parent = make_note(id="restore-parent", user_id="u1", title="DNS", content="DNS 是域名系统")
        chunk = make_note(
            id="restore-chunk",
            user_id="u1",
            title="DNS chunk",
            content="DNS maps names to IPs",
            parent_note_id=parent.id,
            chunk_index=1,
        )
        review = ReviewCard(note_id=parent.id, prompt="DNS 是什么？", answer_hint="域名系统")
        facade.add_note(parent, user_id="u1")
        facade.add_note(chunk, user_id="u1")
        facade.add_review(review)

        deleted = facade.delete_note_confirmed(parent.id, "u1", delete_reason="用户确认删除 DNS")

        assert deleted.ok
        assert deleted.snapshot_id
        assert facade.get_note(parent.id, user_id="u1") is None
        assert facade.list_chunks(parent.id, user_id="u1") == []
        assert facade.list_reviews("u1") == []

        restored = facade.restore_note_confirmed(snapshot_id=deleted.snapshot_id, user_id="u1")

        assert restored.ok
        assert restored.note_id == parent.id
        assert {note.id for note in restored.restored_notes} == {parent.id, chunk.id}
        assert [card.id for card in restored.restored_reviews] == [review.id]
        assert facade.get_note(parent.id, user_id="u1") is not None
        assert [item.id for item in facade.list_chunks(parent.id, user_id="u1")] == [chunk.id]
        assert [card.id for card in facade.list_reviews("u1")] == [review.id]
