from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from personal_agent.memory.facade import MemoryFacade
from personal_agent.memory.working_memory import WorkingMemory
from personal_agent.storage.memory_store import LocalMemoryStore


class TestWorkingMemory:
    @pytest.fixture
    def wm(self):
        return WorkingMemory(max_steps=10, max_tool_cache=5)

    def test_set_and_clear_goal(self, wm):
        assert wm.task_goal is None
        wm.set_goal("测试目标")
        assert wm.task_goal == "测试目标"
        wm.clear_goal()
        assert wm.task_goal is None

    def test_add_and_retrieve_steps(self, wm):
        wm.add_step("步骤1：初始化")
        wm.add_step("步骤2：执行")
        steps = wm.recent_steps(limit=10)
        assert len(steps) == 2
        assert steps[0] == "步骤1：初始化"
        assert steps[1] == "步骤2：执行"

    def test_recent_steps_respects_limit(self, wm):
        for i in range(15):
            wm.add_step(f"步骤{i}")
        steps = wm.recent_steps(limit=3)
        assert len(steps) == 3
        assert steps[0] == "步骤12"
        assert steps[-1] == "步骤14"

    def test_max_steps_truncates_oldest(self, wm):
        small = WorkingMemory(max_steps=3)
        for i in range(5):
            small.add_step(f"步骤{i}")
        steps = small.recent_steps(limit=10)
        assert len(steps) == 3
        assert steps[0] == "步骤2"

    def test_cache_and_retrieve_tool_result(self, wm):
        wm.cache_tool_result("search", {"results": [1, 2, 3]})
        assert wm.get_cached_result("search") == {"results": [1, 2, 3]}

    def test_cache_miss_returns_none(self, wm):
        assert wm.get_cached_result("nonexistent") is None

    def test_cache_evicts_oldest_when_full(self, wm):
        small = WorkingMemory(max_tool_cache=3)
        for i in range(5):
            small.cache_tool_result(f"tool_{i}", i)
        # Oldest (tool_0, tool_1) should be evicted
        assert small.get_cached_result("tool_0") is None
        assert small.get_cached_result("tool_1") is None
        assert small.get_cached_result("tool_2") == 2
        assert small.get_cached_result("tool_4") == 4

    def test_conversation_summary(self, wm):
        assert wm.conversation_summary is None
        wm.set_conversation_summary("用户问了3个问题")
        assert wm.conversation_summary == "用户问了3个问题"

    def test_context_snapshot_includes_all_parts(self, wm):
        wm.set_goal("知识问答")
        wm.set_conversation_summary("会话摘要内容")
        wm.add_step("推理步骤A")
        snapshot = wm.context_snapshot()
        assert "知识问答" in snapshot
        assert "会话摘要内容" in snapshot
        assert "推理步骤A" in snapshot

    def test_context_snapshot_empty_when_no_data(self, wm):
        assert wm.context_snapshot() == ""

    def test_reset_clears_all(self, wm):
        wm.set_goal("目标")
        wm.add_step("步骤")
        wm.cache_tool_result("k", "v")
        wm.set_conversation_summary("摘要")
        wm.reset()
        assert wm.task_goal is None
        assert wm.conversation_summary is None
        assert wm.recent_steps() == []
        assert wm.get_cached_result("k") is None


class TestMemoryFacade:
    @pytest.fixture
    def store(self):
        tmp = tempfile.mkdtemp()
        data_dir = Path(tmp) / "data"
        s = LocalMemoryStore(data_dir)
        yield s
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    @pytest.fixture
    def ask_history(self):
        from personal_agent.storage.ask_history_store import AskHistoryStore

        return AskHistoryStore(postgres_url=None)

    @pytest.fixture
    def facade(self, store, ask_history):
        return MemoryFacade(local_store=store, ask_history_store=ask_history)

    def test_bind_session_resets_on_different_key(self, facade):
        facade.working.set_goal("旧目标")
        facade.bind_session("user1", "session1")
        # Working memory still has the old goal because no session change yet
        # Different session should reset
        facade.bind_session("user1", "session2")
        assert facade.working.task_goal is None

    def test_bind_session_same_key_no_reset(self, facade):
        # First bind — initialises from None, so this WILL reset
        facade.bind_session("user1", "session1")
        facade.working.set_goal("目标")
        assert facade.working.task_goal == "目标"
        # Same key should not reset
        facade.bind_session("user1", "session1")
        assert facade.working.task_goal == "目标"

    def test_record_turn_appends_and_updates_summary(self, facade):
        facade.record_turn("user1", "sess1", "问题？", "答案。")
        turns = facade.local.list_conversation_turns("user1", "sess1", limit=10)
        assert len(turns) == 1
        assert turns[0]["question"] == "问题？"
        assert turns[0]["answer"] == "答案。"

    def test_record_turn_adds_working_memory_step(self, facade):
        facade.record_turn("user1", "sess1", "Q", "A")
        steps = facade.working.recent_steps()
        assert any("Q" in s and "A" in s for s in steps)

    def test_refresh_conversation_summary_with_no_history(self, facade):
        result = facade.refresh_conversation_summary("user1", "sess1")
        assert result == ""
        assert "暂无对话历史" in (facade.working.conversation_summary or "")

    def test_refresh_conversation_summary_with_history(self, facade):
        facade.record_turn("user1", "sess1", "Q1", "A1")
        facade.record_turn("user1", "sess1", "Q2", "A2")
        summary = facade.refresh_conversation_summary("user1", "sess1")
        assert "Q1" in summary
        assert "A1" in summary
        assert "Q2" in summary
