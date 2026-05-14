from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from personal_agent.agent.service import AgentService
from personal_agent.core.config import Settings
from personal_agent.core.models import EntryInput, KnowledgeNote, PendingAction


@pytest.fixture
def test_settings(temp_dir: Path) -> Settings:
    return Settings(
        data_dir=temp_dir,
        openai_api_key="sk-test",
        openai_base_url="https://api.test.com/v1",
        openai_model="gpt-4.1-mini",
        openai_small_model="gpt-4.1-nano",
    )


@pytest.fixture
def service(test_settings: Settings) -> AgentService:
    svc = AgentService(test_settings)
    svc.graph_store = MagicMock()
    svc.graph_store.configured.return_value = False
    return svc


# ── Entry pipeline tests ────────────────────────────────────────────

class TestEntryPipeline:
    """Full entry -> router -> planner -> executor integration tests."""

    def test_entry_capture_text(self, service: AgentService):
        entry = EntryInput(text="记一下：支付系统重构项目第一阶段主要是拆分核心链路", user_id="alice")
        result = service.entry(entry)
        assert result.intent in ("capture_text", "direct_answer")
        assert result.reply_text
        # Capture should produce a note
        if result.capture_result:
            assert result.capture_result.note.title is not None
        # Plan steps should be populated
        assert isinstance(result.plan_steps, list)

    def test_entry_ask_intent(self, service: AgentService):
        # Prime knowledge base
        service.capture(text="服务降级是在系统压力过大时主动关闭非核心能力", source_type="text", attempt_graph=False)
        entry = EntryInput(text="什么是服务降级？", user_id="default")
        result = service.entry(entry)
        assert result.intent in ("ask", "direct_answer")
        assert result.reply_text

    def test_entry_direct_answer_routing(self, service: AgentService):
        entry = EntryInput(text="你好", user_id="default")
        result = service.entry(entry)
        # Should route to direct_answer for greetings
        assert result.intent in ("direct_answer", "capture_text")
        assert result.reply_text

    def test_entry_has_execution_trace(self, service: AgentService):
        entry = EntryInput(text="请帮我总结一下这段时间的笔记", user_id="default")
        result = service.entry(entry)
        # Non-planning intents produce execution_trace instead of plan_steps
        assert isinstance(result.execution_trace, list)
        assert len(result.execution_trace) > 0
        for trace in result.execution_trace:
            assert isinstance(trace, str)

    def test_entry_unknown_intent(self, service: AgentService):
        entry = EntryInput(text="", user_id="default")
        result = service.entry(entry)
        assert result.intent == "unknown"
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

        alice_notes = service.list_notes("alice")
        bob_notes = service.list_notes("bob")
        assert len(alice_notes) > 0
        assert len(bob_notes) > 0
        # Each user should only see their own notes
        alice_ids = {n.id for n in alice_notes}
        bob_ids = {n.id for n in bob_notes}
        assert alice_ids != bob_ids


# ── HITL Pending Action tests ───────────────────────────────────────

class TestPendingActionLifecycle:
    """Test the full HITL pending action create -> confirm -> execute lifecycle."""

    def test_create_pending_action_for_delete(self, service: AgentService):
        note = service.capture(
            text="需要删除的测试笔记", source_type="text", user_id="alice", attempt_graph=False
        ).note
        actions = service.list_pending_actions("alice")
        initial_count = len(actions)

        result = service.execute_tool("delete_note", note_id=note.id, user_id="alice")
        assert result.ok
        assert result.data is not None
        data = result.data if isinstance(result.data, dict) else {}
        assert data.get("pending_confirmation") is True
        assert "action_id" in data
        assert "token" in data
        assert note.id == data.get("note_id")

        # Verify action is persisted
        actions = service.list_pending_actions("alice")
        assert len(actions) == initial_count + 1
        assert actions[0].status == "pending"

    def test_confirm_pending_action_executes_delete(self, service: AgentService):
        note = service.capture(
            text="即将被删除的笔记", source_type="text", user_id="alice", attempt_graph=False
        ).note
        note_id = note.id

        # Phase 1: create pending action
        result = service.execute_tool("delete_note", note_id=note_id, user_id="alice")
        data = result.data if isinstance(result.data, dict) else {}
        action_id = str(data["action_id"])
        token = str(data["token"])

        # Phase 2: confirm
        confirmed = service.confirm_pending_action(action_id, token, "alice")
        assert confirmed is not None
        assert confirmed.status == "executed"

        # Note should be deleted
        deleted_note = service.store.get_note(note_id)
        assert deleted_note is None

    def test_reject_pending_action(self, service: AgentService):
        note = service.capture(
            text="不会被删除的笔记", source_type="text", user_id="alice", attempt_graph=False
        ).note

        result = service.execute_tool("delete_note", note_id=note.id, user_id="alice")
        data = result.data if isinstance(result.data, dict) else {}
        action_id = str(data["action_id"])

        rejected = service.reject_pending_action(action_id, "alice", "不需要删除")
        assert rejected is not None
        assert rejected.status == "rejected"
        assert len(rejected.audit_log) >= 2  # created + rejected

        # Note should still exist
        existing = service.store.get_note(note.id)
        assert existing is not None

    def test_wrong_token_rejected(self, service: AgentService):
        note = service.capture(
            text="带Token的笔记", source_type="text", user_id="alice", attempt_graph=False
        ).note

        result = service.execute_tool("delete_note", note_id=note.id, user_id="alice")
        data = result.data if isinstance(result.data, dict) else {}
        action_id = str(data["action_id"])

        confirmed = service.confirm_pending_action(action_id, "wrong-token", "alice")
        assert confirmed is None  # Wrong token

    def test_expired_action_auto_rejected(self, service: AgentService, temp_dir: Path):
        pending_store = service._runtime.pending_action_store
        now = datetime.utcnow()
        expired_action = PendingAction(
            user_id="alice",
            action_type="delete_note",
            target_id="note-x",
            title="过期操作",
            description="已过期",
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        pending_store.create(expired_action)

        # Listing actions should mark expired ones
        actions = pending_store.list_by_user("alice", status="pending")
        # Expired actions should have been reclassified
        pending_ids = {a.id for a in actions}
        assert expired_action.id not in pending_ids

    def test_cross_user_isolation(self, service: AgentService):
        note = service.capture(
            text="Alice的笔记", source_type="text", user_id="alice", attempt_graph=False
        ).note

        result = service.execute_tool("delete_note", note_id=note.id, user_id="alice")
        data = result.data if isinstance(result.data, dict) else {}
        action_id = str(data["action_id"])
        token = str(data["token"])

        # Bob tries to confirm Alice's action
        confirmed = service.confirm_pending_action(action_id, token, "bob")
        assert confirmed is None

        # Alice can still confirm
        confirmed_alice = service.confirm_pending_action(action_id, token, "alice")
        assert confirmed_alice is not None
        assert confirmed_alice.status == "executed"

    def test_delete_note_ownership_check(self, service: AgentService):
        note = service.capture(
            text="Alice的私密笔记", source_type="text", user_id="alice", attempt_graph=False
        ).note

        # Bob tries to delete Alice's note
        result = service.execute_tool("delete_note", note_id=note.id, user_id="bob")
        assert not result.ok
        assert "不属于" in str(result.error)


# ── PendingActionStore unit tests ───────────────────────────────────

class TestPendingActionStore:
    def test_create_and_retrieve(self, temp_dir: Path):
        from personal_agent.storage.pending_action_store import PendingActionStore
        store = PendingActionStore(temp_dir)

        action = PendingAction(
            user_id="alice",
            action_type="delete_note",
            target_id="note-1",
            title="删除笔记",
            description="测试",
        )
        created = store.create(action)
        assert created.id == action.id
        assert created.token

        retrieved = store.get(action.id, "alice")
        assert retrieved is not None
        assert retrieved.status == "pending"

    def test_confirm_flow(self, temp_dir: Path):
        from personal_agent.storage.pending_action_store import PendingActionStore
        store = PendingActionStore(temp_dir)

        action = store.create(PendingAction(
            user_id="alice", action_type="delete_note", target_id="n1",
            title="Delete", description="Test",
        ))
        confirmed = store.confirm(action.id, action.token, "alice")
        assert confirmed is not None
        assert confirmed.status == "confirmed"
        assert confirmed.resolved_at is not None

        executed = store.mark_executed(action.id, "alice")
        assert executed is not None
        assert executed.status == "executed"
        assert len(executed.audit_log) == 3  # created + confirmed + executed

    def test_expiry_on_load(self, temp_dir: Path):
        from personal_agent.storage.pending_action_store import PendingActionStore
        store = PendingActionStore(temp_dir)

        now = datetime.utcnow()
        store.create(PendingAction(
            id="exp-1", user_id="alice", action_type="delete_note", target_id="n1",
            title="Expired", description="Test",
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        ))
        store.create(PendingAction(
            id="exp-2", user_id="alice", action_type="delete_note", target_id="n2",
            title="Still valid", description="Test",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        ))

        # List should auto-expire the first one
        pending = store.list_by_user("alice", status="pending")
        # expired-1 should be gone from "pending"
        pending_ids = {a.id for a in pending}
        assert "exp-1" not in pending_ids
        assert "exp-2" in pending_ids

        # Explicit get of expired should show it as expired
        expired = store.get("exp-1", "alice")
        assert expired is not None
        assert expired.status == "expired"
