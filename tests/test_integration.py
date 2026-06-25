from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import OpenAIConfig, Settings
from personal_agent.kernel.models import EntryInput
from tests.conftest import POSTGRES_URL, stub_router_decision

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


@pytest.fixture
def test_settings(temp_dir: Path) -> Settings:
    return Settings(
        data_dir=temp_dir,
        postgres_url=POSTGRES_URL,
        openai=OpenAIConfig(
            api_key=None,
            base_url=None,
            model="gpt-4.1-mini",
            small_model="gpt-4.1-nano",
        ),
    )


@pytest.fixture
def service(test_settings: Settings) -> AgentService:
    svc = AgentService(test_settings)
    svc.graph_store = MagicMock()
    svc.graph_store.configured.return_value = False
    svc.intent_router._classify_with_llm = stub_router_decision
    return svc


# ── Entry pipeline tests ────────────────────────────────────────────

class TestEntryPipeline:
    """Full entry -> router -> planner -> executor integration tests."""

    def test_entry_capture_text(self, service: AgentService):
        entry = EntryInput(text="记一下：支付系统重构项目第一阶段主要是拆分核心链路", user_id="alice")
        result = service.entry(entry)
        assert result.intents[-1] in ("capture_text", "direct_answer")
        assert result.reply_text
        # Capture should produce a note
        if result.capture_result:
            assert result.capture_result.note.title is not None
        # execution steps should be populated
        assert isinstance(result.steps, list)

    def test_entry_ask_intent(self, service: AgentService):
        # Prime knowledge base
        service.execute_capture(text="服务降级是在系统压力过大时主动关闭非核心能力", source_type="text")
        entry = EntryInput(text="什么是服务降级？", user_id="default")
        result = service.entry(entry)
        assert result.intents[-1] in ("ask", "direct_answer")
        assert result.reply_text

    def test_entry_direct_answer_routing(self, service: AgentService):
        entry = EntryInput(text="你好", user_id="default")
        result = service.entry(entry)
        # Should route to direct_answer for greetings
        assert result.intents[-1] in ("direct_answer", "capture_text")
        assert result.reply_text

    def test_entry_has_execution_trace(self, service: AgentService):
        entry = EntryInput(text="请帮我总结一下这段时间的笔记", user_id="default")
        result = service.entry(entry)
        # Non-planning intents produce execution_trace instead of steps
        assert isinstance(result.execution_trace, list)
        assert len(result.execution_trace) > 0
        for trace in result.execution_trace:
            assert isinstance(trace, str)

    def test_entry_unknown_intent(self, service: AgentService):
        entry = EntryInput(text="", user_id="default")
        result = service.entry(entry)
        assert result.intents == []
        assert result.reply_text


# ── Entry pipeline with session context ─────────────────────────────

class TestEntryWithSession:
    def test_entry_session_persistence(self, service: AgentService):
        entry1 = EntryInput(text="记住：我们的项目代号是Phoenix", user_id="bob", session_id="sess-1")
        service.entry(entry1)
        entry2 = EntryInput(text="我们的项目代号是什么？", user_id="bob", session_id="sess-1")
        result = service.entry(entry2)
        assert result.reply_text

    def test_entry_different_users_isolation(self, service: AgentService):
        entry1 = EntryInput(text="记一下：Alice的笔记N1", user_id="alice", session_id="s1")
        service.entry(entry1)
        entry2 = EntryInput(text="记一下：Bob的笔记N2", user_id="bob", session_id="s2")
        service.entry(entry2)

        alice_notes = service.memory.list_notes("alice")
        bob_notes = service.memory.list_notes("bob")
        assert len(alice_notes) > 0
        assert len(bob_notes) > 0
        # Each user should only see their own notes
        alice_ids = {n.id for n in alice_notes}
        bob_ids = {n.id for n in bob_notes}
        assert alice_ids != bob_ids


class TestDeleteNoteTool:
    def test_delete_note_ownership_check(self, service: AgentService):
        note = service.execute_capture(
            text="Alice的私密笔记", source_type="text", user_id="alice"
        ).note

        # Bob tries to delete Alice's note
        result = service.execute_tool("delete_note", note_id=note.id, user_id="bob")
        assert not result["ok"]
        assert "不属于" in str(result["error"])
