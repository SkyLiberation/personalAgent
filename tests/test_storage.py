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
