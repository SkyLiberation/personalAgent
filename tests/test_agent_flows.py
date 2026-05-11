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
    svc.graph_store = MagicMock()
    svc.graph_store.configured.return_value = False
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
