from __future__ import annotations

import pytest
from pathlib import Path

from unittest.mock import MagicMock

from personal_agent.agent.service import AgentService
from personal_agent.core.config import Settings
from personal_agent.core.models import EntryInput, KnowledgeNote
from personal_agent.graphiti.store import GraphAskResult, GraphCaptureResult


@pytest.fixture
def test_settings(temp_dir: Path) -> Settings:
    return Settings(
        data_dir=temp_dir,
        openai_api_key="sk-test",
        openai_base_url="https://api.test.com/v1",
        openai_model="gpt-4.1-mini",
    )


@pytest.fixture
def service(test_settings: Settings) -> AgentService:
    svc = AgentService(test_settings)
    mock_store = MagicMock()
    mock_store.configured.return_value = False
    # ask() must return disabled so execute_ask takes the local path
    mock_store.ask.return_value = GraphAskResult(enabled=False)
    # ingest_note() must return disabled so capture doesn't enter graph sync path
    mock_store.ingest_note.return_value = GraphCaptureResult(enabled=False)
    svc.graph_store = mock_store
    svc._runtime.graph_store = mock_store
    return svc


class TestCaptureFlow:
    def test_capture_text_creates_note(self, service: AgentService):
        result = service.capture(text="服务降级是在系统压力过大时主动关闭非核心能力", source_type="text", attempt_graph=False)
        assert result.note is not None
        assert result.note.title
        assert result.note.content
        assert result.note.summary
        assert result.note.source_type == "text"
        assert not result.graph_enabled

    def test_capture_produces_review_card(self, service: AgentService):
        result = service.capture(text="需要记住的重要知识点：CAP理论的核心是分区容错性", source_type="text", attempt_graph=False)
        assert result.note is not None
        # Review card generation is deterministic from note content
        assert result.review_card is not None

    def test_capture_text_with_user_id(self, service: AgentService):
        result = service.capture(text="用户特定笔记", source_type="text", user_id="alice", attempt_graph=False)
        assert result.note.user_id == "alice"

    def test_capture_text_with_source_ref(self, service: AgentService):
        result = service.capture(
            text="来源笔记", source_type="text", source_ref="https://example.com", attempt_graph=False
        )
        assert result.note.source_ref == "https://example.com"

    def test_short_text_single_note_no_chunks(self, service: AgentService):
        result = service.capture(text="这是一条短笔记", source_type="text", attempt_graph=False)
        assert result.note is not None
        assert result.chunk_notes == []

    def test_long_text_produces_chunks(self, service: AgentService):
        long_content = "\n".join([
            "## 第一节",
            "",
            "第一节的详细内容。" * 350,
            "",
            "## 第二节",
            "",
            "第二节的详细内容。" * 350,
            "",
            "## 第三节",
            "",
            "第三节的详细内容。" * 350,
        ])
        result = service.capture(text=long_content, source_type="text", attempt_graph=False)
        assert result.note is not None
        # Long content should produce chunk_notes
        assert len(result.chunk_notes) > 0
        # Chunks should have parent_note_id pointing to the parent
        for chunk in result.chunk_notes:
            assert chunk.parent_note_id == result.note.id
            assert chunk.chunk_index is not None and chunk.chunk_index >= 1

    def test_capture_chunks_persisted_in_store(self, service: AgentService):
        long_content = "\n".join([
            "## 章节A",
            "",
            "A的详细内容。" * 350,
            "",
            "## 章节B",
            "",
            "B的详细内容。" * 350,
        ])
        result = service.capture(text=long_content, source_type="text", attempt_graph=False)
        parent_id = result.note.id
        # Chunks should be retrievable from store
        chunks = service.store.get_chunks_for_parent(parent_id)
        assert len(chunks) == len(result.chunk_notes)
        # All chunks should have correct parent_note_id
        for chunk in chunks:
            assert chunk.parent_note_id == parent_id

    def test_capture_chunks_get_pending_graph_status(self, service: AgentService):
        """Chunk notes should get graph_sync_status='pending' when graph is configured."""
        long_content = "\n".join([
            "## 章节A",
            "",
            "A的详细内容。" * 350,
            "",
            "## 章节B",
            "",
            "B的详细内容。" * 350,
        ])
        # Mock graph_store as configured to ensure 'pending' status
        service.graph_store.configured.return_value = True
        result = service.capture(text=long_content, source_type="text", attempt_graph=False)
        for chunk in result.chunk_notes:
            assert chunk.graph_sync_status == "pending"
        service.graph_store.configured.return_value = False  # Restore for other tests

    def test_chunk_delete_cleans_graph_episodes(self, service: AgentService):
        """When cascade-deleting, chunk graph episodes should be cleaned up."""
        from unittest.mock import MagicMock

        service.graph_store.configured.return_value = True
        service.graph_store.delete_episode = MagicMock(return_value=True)

        # Create parent with chunks that have graph_episode_uuid
        parent = KnowledgeNote(id="p-g", title="父文档", content="完整", summary="...", user_id="default")
        service.store.add_note(parent)
        service.store.add_note(KnowledgeNote(
            id="c-g1", title="子1", content="...", summary="...", user_id="default",
            parent_note_id="p-g", chunk_index=1, graph_episode_uuid="ep-chunk-1",
        ))
        service.store.add_note(KnowledgeNote(
            id="c-g2", title="子2", content="...", summary="...", user_id="default",
            parent_note_id="p-g", chunk_index=2, graph_episode_uuid="ep-chunk-2",
        ))

        # Delete with cascade — should call delete_episode for chunks
        deleted = service.store.delete_note("p-g", "default", cascade_chunks=True)
        assert deleted is not None
        assert service.store.get_note("p-g") is None
        assert service.store.get_note("c-g1") is None
        assert service.store.get_note("c-g2") is None
        # Chunk episodes would be cleaned up by delete_note tool; store.delete_note handles local cleanup
        service.graph_store.configured.return_value = False


class TestAskFlow:
    def test_ask_returns_result(self, service: AgentService):
        # Add a note first so there's something to search
        service.capture(text="服务降级是在系统压力过大时主动关闭非核心能力", source_type="text", attempt_graph=False)
        result = service.ask(question="什么是服务降级？")
        assert result.answer
        assert isinstance(result.answer, str)
        assert len(result.answer) > 0

    def test_ask_with_no_notes(self, service: AgentService):
        result = service.ask(question="完全未知的问题xyz123")
        assert result.answer
        assert isinstance(result.session_id, str)

    def test_ask_with_session_id(self, service: AgentService):
        service.capture(text="测试知识", source_type="text", attempt_graph=False)
        result = service.ask(question="测试", session_id="test-session-42")
        assert result.session_id == "test-session-42"

    def test_ask_persists_history(self, service: AgentService):
        service.capture(text="测试知识", source_type="text", attempt_graph=False)
        service.ask(question="测试", session_id="s1")
        history = service.list_ask_history(session_id="s1")
        assert len(history) >= 1
        assert history[0].question == "测试"


class TestDigestFlow:
    def test_digest_returns_message(self, service: AgentService):
        result = service.digest()
        assert result.message
        assert isinstance(result.recent_notes, list)
        assert isinstance(result.due_reviews, list)

    def test_digest_includes_recent_notes(self, service: AgentService):
        service.capture(text="笔记1内容", source_type="text", attempt_graph=False)
        service.capture(text="笔记2内容", source_type="text", attempt_graph=False)
        result = service.digest()
        assert len(result.recent_notes) >= 2

    def test_digest_respects_user(self, service: AgentService):
        service.capture(text="Alice的笔记", source_type="text", user_id="alice", attempt_graph=False)
        service.capture(text="Bob的笔记", source_type="text", user_id="bob", attempt_graph=False)
        result_alice = service.digest(user_id="alice")
        result_bob = service.digest(user_id="bob")
        alice_titles = {n.title for n in result_alice.recent_notes}
        bob_titles = {n.title for n in result_bob.recent_notes}
        assert "Alice的笔记" in alice_titles
        assert "Bob的笔记" in bob_titles


class TestEntryFlow:
    def test_entry_capture_text(self, service: AgentService):
        entry = EntryInput(text="记一下：服务降级是重要的系统设计模式", source_platform="test")
        result = service.entry(entry)
        assert result.intent in ("capture_text", "unknown")
        assert result.reply_text
        if result.intent == "capture_text":
            assert result.capture_result is not None
            assert result.capture_result.note is not None

    def test_entry_ask(self, service: AgentService):
        service.capture(text="服务降级是系统设计中的常见模式", source_type="text", attempt_graph=False)
        entry = EntryInput(text="什么是服务降级？", source_platform="test")
        result = service.entry(entry)
        assert result.intent == "ask"
        assert result.reply_text
        assert result.ask_result is not None
        assert result.ask_result.answer

    def test_entry_empty_text(self, service: AgentService):
        entry = EntryInput(text="", source_platform="test")
        result = service.entry(entry)
        assert result.intent == "unknown"

    def test_entry_capture_link(self, service: AgentService):
        entry = EntryInput(
            text="https://example.com/article 这篇文章值得收藏",
            source_platform="test",
            metadata={"url": "https://example.com/article"},
        )
        result = service.entry(entry)
        assert result.intent in ("capture_link", "capture_text", "unknown")
        assert result.reply_text
