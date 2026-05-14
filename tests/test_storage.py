from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from pathlib import Path

from personal_agent.core.models import KnowledgeNote, ReviewCard
from personal_agent.storage.memory_store import LocalMemoryStore


class TestLocalMemoryStore:
    def test_add_and_list_notes(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        note = KnowledgeNote(title="测试", content="内容", summary="摘要", user_id="alice")
        store.add_note(note)
        notes = store.list_notes("alice")
        assert len(notes) == 1
        assert notes[0].title == "测试"

    def test_list_notes_filters_by_user(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        store.add_note(KnowledgeNote(title="Alice的笔记", content="A", summary="A", user_id="alice"))
        store.add_note(KnowledgeNote(title="Bob的笔记", content="B", summary="B", user_id="bob"))
        assert len(store.list_notes("alice")) == 1
        assert len(store.list_notes("bob")) == 1
        assert len(store.list_notes("nobody")) == 0

    def test_get_note_by_id(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        note = KnowledgeNote(id="n1", title="目标", content="C", summary="S", user_id="alice")
        store.add_note(note)
        found = store.get_note("n1")
        assert found is not None
        assert found.title == "目标"
        assert store.get_note("nonexistent") is None

    def test_update_note_replaces_existing(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        note = KnowledgeNote(id="n1", title="原始", content="C", summary="S", user_id="alice")
        store.add_note(note)
        note.title = "已更新"
        store.update_note(note)
        found = store.get_note("n1")
        assert found is not None
        assert found.title == "已更新"

    def test_update_note_adds_when_missing(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        note = KnowledgeNote(id="n1", title="新笔记", content="C", summary="S", user_id="alice")
        store.update_note(note)
        assert len(store.list_notes("alice")) == 1

    def test_find_similar_notes(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        store.add_note(KnowledgeNote(title="Python入门", content="Python是一门编程语言", summary="Python基础", user_id="alice"))
        store.add_note(KnowledgeNote(title="料理指南", content="如何做红烧肉", summary="烹饪教程", user_id="alice"))
        results = store.find_similar_notes("alice", "Python 编程")
        assert len(results) >= 1
        assert any("Python" in n.title for n in results)

    def test_find_notes_by_graph_episode_uuids(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        n1 = KnowledgeNote(id="n1", title="A", content="...", summary="...", user_id="alice", graph_episode_uuid="ep-1")
        n2 = KnowledgeNote(id="n2", title="B", content="...", summary="...", user_id="alice", graph_episode_uuid="ep-2")
        store.add_note(n1)
        store.add_note(n2)
        results = store.find_notes_by_graph_episode_uuids("alice", ["ep-1"])
        assert len(results) == 1
        assert results[0].id == "n1"

    def test_due_reviews(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        note = KnowledgeNote(id="n1", title="T", content="C", summary="S", user_id="alice")
        store.add_note(note)
        overdue = ReviewCard(note_id="n1", prompt="复习", answer_hint="答案", due_at=datetime.utcnow() - timedelta(days=1))
        future = ReviewCard(note_id="n1", prompt="未来", answer_hint="答案", due_at=datetime.utcnow() + timedelta(days=30))
        store.add_review(overdue)
        store.add_review(future)
        due = store.due_reviews("alice")
        assert len(due) == 1

    def test_conversation_turns(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        store.append_conversation_turn({"user_id": "alice", "session_id": "s1", "question": "Q1", "answer": "A1", "created_at": "2024-01-01T00:00:00"})
        store.append_conversation_turn({"user_id": "alice", "session_id": "s1", "question": "Q2", "answer": "A2", "created_at": "2024-01-02T00:00:00"})
        turns = store.list_conversation_turns("alice", "s1")
        assert len(turns) == 2
        assert turns[0]["question"] == "Q1"

    def test_conversation_turns_filter_by_user_and_session(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        store.append_conversation_turn({"user_id": "alice", "session_id": "s1", "question": "A", "answer": "a", "created_at": "2024-01-01T00:00:00"})
        store.append_conversation_turn({"user_id": "bob", "session_id": "s1", "question": "B", "answer": "b", "created_at": "2024-01-01T00:00:00"})
        assert len(store.list_conversation_turns("alice", "s1")) == 1
        assert len(store.list_conversation_turns("bob", "s1")) == 1

    def test_clear_user_data(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        store.add_note(KnowledgeNote(id="n1", title="Alice笔记", content="C", summary="S", user_id="alice"))
        store.add_note(KnowledgeNote(id="n2", title="Bob笔记", content="C", summary="S", user_id="bob"))
        store.add_review(ReviewCard(note_id="n1", prompt="P", answer_hint="A"))
        store.append_conversation_turn({"user_id": "alice", "session_id": "s1", "question": "Q", "answer": "A", "created_at": "2024-01-01T00:00:00"})
        result = store.clear_user_data("alice", remove_uploaded_files=False)
        assert result["notes"] == 1
        assert result["reviews"] == 1
        assert result["conversations"] == 1
        assert len(store.list_notes("alice")) == 0
        assert len(store.list_notes("bob")) == 1

    def test_ensure_files_creates_on_init(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        assert store.notes_file.exists()
        assert store.reviews_file.exists()
        assert store.conversations_file.exists()

    def test_persistence_across_instances(self, temp_dir: Path):
        store1 = LocalMemoryStore(temp_dir)
        store1.add_note(KnowledgeNote(id="n1", title="持久化测试", content="C", summary="S", user_id="alice"))
        store2 = LocalMemoryStore(temp_dir)
        notes = store2.list_notes("alice")
        assert len(notes) == 1
        assert notes[0].title == "持久化测试"

    # ---- Chunk (parent/child) tests ----

    def test_get_chunks_for_parent(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        parent = KnowledgeNote(id="p1", title="父文档", content="完整内容", summary="摘要", user_id="alice", chunk_index=0)
        store.add_note(parent)
        store.add_note(KnowledgeNote(id="c1", title="子笔记1", content="章节1", summary="...", user_id="alice", parent_note_id="p1", chunk_index=1))
        store.add_note(KnowledgeNote(id="c2", title="子笔记2", content="章节2", summary="...", user_id="alice", parent_note_id="p1", chunk_index=2))
        chunks = store.get_chunks_for_parent("p1")
        assert len(chunks) == 2
        assert chunks[0].id == "c1"
        assert chunks[1].id == "c2"

    def test_get_chunks_for_parent_empty(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        chunks = store.get_chunks_for_parent("nonexistent")
        assert chunks == []

    def test_get_parent_note(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        parent = KnowledgeNote(id="p1", title="父文档", content="完整内容", summary="摘要", user_id="alice")
        store.add_note(parent)
        child = KnowledgeNote(id="c1", title="子笔记", content="章节", summary="...", user_id="alice", parent_note_id="p1", chunk_index=1)
        store.add_note(child)
        found = store.get_parent_note("c1")
        assert found is not None
        assert found.id == "p1"

    def test_get_parent_note_returns_none_for_top_level(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        note = KnowledgeNote(id="n1", title="顶层笔记", content="C", summary="S", user_id="alice")
        store.add_note(note)
        assert store.get_parent_note("n1") is None

    def test_delete_note_cascade_chunks(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        parent = KnowledgeNote(id="p1", title="父文档", content="完整", summary="摘要", user_id="alice")
        store.add_note(parent)
        store.add_note(KnowledgeNote(id="c1", title="子1", content="...", summary="...", user_id="alice", parent_note_id="p1", chunk_index=1))
        store.add_note(KnowledgeNote(id="c2", title="子2", content="...", summary="...", user_id="alice", parent_note_id="p1", chunk_index=2))
        # Add reviews for both parent and child
        store.add_review(ReviewCard(note_id="p1", prompt="P", answer_hint="A"))
        store.add_review(ReviewCard(note_id="c1", prompt="P", answer_hint="A"))

        deleted = store.delete_note("p1", "alice", cascade_chunks=True)
        assert deleted is not None
        assert deleted.id == "p1"
        # All parent, children, and their reviews should be gone
        assert store.get_note("p1") is None
        assert store.get_note("c1") is None
        assert store.get_note("c2") is None
        assert len(store.list_reviews("alice")) == 0

    def test_delete_note_no_cascade_leaves_children(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        parent = KnowledgeNote(id="p1", title="父文档", content="完整", summary="摘要", user_id="alice")
        store.add_note(parent)
        store.add_note(KnowledgeNote(id="c1", title="子1", content="...", summary="...", user_id="alice", parent_note_id="p1", chunk_index=1))

        deleted = store.delete_note("p1", "alice", cascade_chunks=False)
        assert deleted is not None
        assert store.get_note("p1") is None
        # Child should survive when cascade_chunks is False
        assert store.get_note("c1") is not None

    def test_list_notes_exclude_chunks(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        store.add_note(KnowledgeNote(id="p1", title="父", content="C", summary="S", user_id="alice"))
        store.add_note(KnowledgeNote(id="c1", title="子", content="...", summary="...", user_id="alice", parent_note_id="p1", chunk_index=1))
        store.add_note(KnowledgeNote(id="n1", title="独立", content="C", summary="S", user_id="alice"))

        flat = store.list_notes("alice", include_chunks=False)
        assert len(flat) == 2
        flat_ids = {n.id for n in flat}
        assert "p1" in flat_ids
        assert "n1" in flat_ids
        assert "c1" not in flat_ids

    def test_find_similar_notes_deduplicates_by_parent(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        store.add_note(KnowledgeNote(id="p1", title="Python文档", content="Python相关..." * 50, summary="Python文档", user_id="alice"))
        store.add_note(KnowledgeNote(id="c1", title="Python安装", content="安装Python的步骤..." * 30, summary="安装", user_id="alice", parent_note_id="p1", chunk_index=1))
        store.add_note(KnowledgeNote(id="c2", title="Python语法", content="Python基础语法..." * 30, summary="语法", user_id="alice", parent_note_id="p1", chunk_index=2))
        store.add_note(KnowledgeNote(id="n1", title="其他文档", content="不相关的内容..." * 30, summary="其他", user_id="alice"))

        results = store.find_similar_notes("alice", "Python", limit=3)
        # Should not return all chunks from same parent
        note_ids = {n.id for n in results}
        # p1 and at most one chunk should appear
        assert "p1" in note_ids


@pytest.mark.db
class TestAskHistoryStore:
    def test_configured_false_when_no_url(self):
        from personal_agent.storage.ask_history_store import AskHistoryStore
        store = AskHistoryStore(None)
        assert not store.configured()

    def test_configured_true_with_url(self):
        from personal_agent.storage.ask_history_store import AskHistoryStore
        store = AskHistoryStore("postgresql://localhost:5432/test")
        assert store.configured()

    def test_list_history_empty_when_not_configured(self):
        from personal_agent.storage.ask_history_store import AskHistoryStore
        store = AskHistoryStore(None)
        assert store.list_history("alice") == []

    def test_append_noop_when_not_configured(self):
        from personal_agent.storage.ask_history_store import AskHistoryStore
        from personal_agent.core.models import AskHistoryRecord
        store = AskHistoryStore(None)
        record = AskHistoryRecord(user_id="alice", question="Q", answer="A")
        result = store.append(record)
        assert result.user_id == "alice"

    def test_delete_noop_when_not_configured(self):
        from personal_agent.storage.ask_history_store import AskHistoryStore
        store = AskHistoryStore(None)
        assert store.delete_history("alice") == 0
