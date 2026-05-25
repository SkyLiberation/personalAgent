"""Tests for orchestration models and entry orchestration graph."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from personal_agent.agent.orchestration_models import (
    AgentEvent,
    AgentGraphState,
    AgentRunSnapshot,
    AgentRunStatus,
    _new_run_id,
    _new_thread_id,
    execution_trace_to_events,
    plan_steps_to_plan_created_events,
)
from personal_agent.agent.orchestration_nodes import OrchestrationDeps
from personal_agent.agent.router import RouterDecision
from personal_agent.core.config import Settings
from personal_agent.core.models import EntryInput


# ---------------------------------------------------------------------------
# AgentGraphState
# ---------------------------------------------------------------------------

class TestAgentGraphState:
    def test_default_state_has_run_id(self):
        state = AgentGraphState()
        assert state.run_id
        assert len(state.run_id) == 12

    def test_state_serialization_roundtrip(self):
        state = AgentGraphState(
            user_id="user-1",
            session_id="sess-1",
            entry_text="什么是服务降级？",
            router_decision=RouterDecision(route="ask"),
            answer="服务降级是在系统压力过大时...",
            plan_steps=[
                {"step_id": "s1", "action_type": "retrieve", "status": "completed"},
            ],
            execution_trace=["检索知识库", "生成回答"],
            messages=[HumanMessage(content="你好"), AIMessage(content="你好，有什么可以帮你的？")],
        )
        data = state.model_dump(mode="json")
        restored = AgentGraphState.model_validate(data)
        assert restored.run_id == state.run_id
        assert restored.user_id == "user-1"
        assert restored.answer == state.answer
        assert len(restored.plan_steps) == 1
        assert restored.plan_steps[0].step_id == "s1"
        assert [message.content for message in restored.messages] == [
            "你好",
            "你好，有什么可以帮你的？",
        ]

    def test_add_event_appends_and_updates_timestamp(self):
        state = AgentGraphState(run_id="r1")
        event = state.add_event("entry_started", {"text": "hello"})
        assert len(state.events) == 1
        assert state.events[0].type == "entry_started"
        assert state.events[0].payload == {"text": "hello"}
        assert event.run_id == "r1"

    def test_update_step_status(self):
        state = AgentGraphState(
            plan_steps=[
                {"step_id": "s1", "status": "running"},
                {"step_id": "s2", "status": "planned"},
            ]
        )
        state.update_step_status("s1", "completed")
        assert state.plan_steps[0].status == "completed"
        assert state.plan_steps[1].status == "planned"

    def test_to_run_snapshot_pending(self):
        state = AgentGraphState()
        snap = state.to_run_snapshot()
        assert snap.status == AgentRunStatus.pending
        assert snap.run_id == state.run_id

    def test_to_run_snapshot_completed(self):
        state = AgentGraphState(router_decision=RouterDecision(route="ask"), answer="42", answer_completed=True)
        snap = state.to_run_snapshot()
        assert snap.status == AgentRunStatus.completed
        assert snap.answer == "42"


# ---------------------------------------------------------------------------
# AgentEvent
# ---------------------------------------------------------------------------

class TestAgentEvent:
    def test_default_factory_fields(self):
        event = AgentEvent(type="entry_started", payload={"text": "hi"})
        assert event.event_id
        assert event.timestamp

    def test_serialization_roundtrip(self):
        event = AgentEvent(
            run_id="r1", thread_id="t1", type="intent_classified",
            payload={"intent": "ask"},
        )
        data = event.model_dump(mode="json")
        restored = AgentEvent.model_validate(data)
        assert restored.type == "intent_classified"
        assert restored.payload["intent"] == "ask"


# ---------------------------------------------------------------------------
# AgentRunSnapshot
# ---------------------------------------------------------------------------

class TestAgentRunSnapshot:
    def test_snapshot_defaults(self):
        snap = AgentRunSnapshot(run_id="r1", thread_id="t1", user_id="u1", session_id="s1")
        assert snap.status == AgentRunStatus.pending
        assert snap.intent == "unknown"
        assert snap.plan_steps == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestRunIdHelpers:
    def test_new_run_id_is_unique(self):
        id1 = _new_run_id()
        id2 = _new_run_id()
        assert id1 != id2
        assert len(id1) == 12

    def test_new_thread_id_format(self):
        tid = _new_thread_id("user-1", "sess-1", "run-abc123")
        assert tid == "user-1:sess-1"


class TestNormalizeEntry:
    def test_new_run_clears_previous_thread_progress(self):
        from personal_agent.agent.orchestration_graph import _node_normalize_entry

        state = AgentGraphState(
            run_id="new-run",
            entry_input=EntryInput(text="什么是DNS", user_id="u1", session_id="s1"),
            router_decision=RouterDecision(route="ask"),
            answer="上一轮天气回答",
            answer_completed=True,
            pending_confirmation={"kind": "clarification_required"},
            execution_trace=["上一轮轨迹"],
            citations=[{"note_id": "old", "title": "旧证据", "snippet": "旧"}],
            errors=["上一轮错误"],
            messages=[
                HumanMessage(content="今天西安天气怎么样"),
                AIMessage(content="上一轮天气回答"),
            ],
        )
        state.add_event("run_completed", {"answer": state.answer})

        result = _node_normalize_entry(state)

        assert result["thread_id"] == "u1:s1"
        assert result["router_decision"] is None
        assert result["answer"] is None
        assert result["answer_completed"] is False
        assert result["pending_confirmation"] is None
        assert result["execution_trace"] == []
        assert result["citations"] == []
        assert result["errors"] == []
        assert result["messages"][0].content == "什么是DNS"
        assert [message.content for message in state.messages] == [
            "今天西安天气怎么样",
            "上一轮天气回答",
        ]
        assert [event.type for event in result["events"]] == ["entry_started"]
        assert result["events"][0].run_id == "new-run"

    def test_direct_answer_fallback_does_not_acknowledge_a_question(self):
        from personal_agent.agent.orchestration_nodes import _simple_direct_answer

        assert _simple_direct_answer("什么是DNS") == "我暂时无法生成这个问题的直接回答，请稍后重试。"


# ---------------------------------------------------------------------------
# Event conversion helpers
# ---------------------------------------------------------------------------

class TestEventConversions:
    def test_plan_steps_to_plan_created_events(self):
        steps = [
            {"step_id": "s1", "action_type": "retrieve", "status": "completed"},
            {"step_id": "s2", "action_type": "tool_call", "status": "planned"},
        ]
        events = plan_steps_to_plan_created_events(steps, "r1", "t1")
        assert len(events) == 1
        assert events[0].type == "plan_created"
        assert events[0].payload["plan_steps"] == steps

    def test_execution_trace_to_events(self):
        traces = ["检索知识库", "整合证据", "生成回答"]
        events = execution_trace_to_events(traces, "r1", "t1")
        # 3 step_started + 3 step_completed = 6
        assert len(events) == 6
        assert events[0].type == "step_started"
        assert events[-1].type == "step_completed"


# ---------------------------------------------------------------------------
# Orchestration graph integration tests
# ---------------------------------------------------------------------------

class TestOrchestrationGraphIntegration:
    """Test the orchestration graph end-to-end."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            langgraph_checkpoint_backend="memory",
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.storage.memory_store import LocalMemoryStore
        from personal_agent.storage.ask_history_store import AskHistoryStore
        from personal_agent.graphiti.store import GraphitiStore
        from personal_agent.agent.runtime import AgentRuntime

        store = LocalMemoryStore(stub_settings.data_dir)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
            ask_history_store=AskHistoryStore(postgres_url=None),
        )

    def test_graph_builds_and_compiles(self, runtime):
        graph = runtime._get_orch_graph()
        assert graph is not None
        # Should be compiled with a checkpointer
        assert graph.checkpointer is not None

    def test_direct_answer_through_orch_graph(self, runtime):
        """A simple direct_answer should flow through the graph and produce a result."""
        entry = EntryInput(
            text="你好",
            user_id="test-user",
            session_id="orch-test",
        )
        result = runtime.execute_entry(entry)
        assert result.intent in ("direct_answer", "unknown", "capture_text")
        assert result.reply_text

    def test_ask_through_orch_graph(self, runtime):
        """An ask intent should flow through the graph."""
        entry = EntryInput(
            text="什么是服务降级？",
            user_id="test-user",
            session_id="orch-test-ask",
        )
        result = runtime.execute_entry(entry)
        assert result.intent == "ask"
        assert result.reply_text

    def test_capture_through_orch_graph(self, runtime):
        """A capture_text intent should flow through the graph."""
        entry = EntryInput(
            text="记一下：服务降级是在系统压力过大时主动关闭非核心能力。",
            user_id="test-user",
            session_id="orch-test-cap",
        )
        result = runtime.execute_entry(entry)
        assert result.intent in ("capture_text", "unknown")
        assert result.reply_text

    def test_solidify_executes_plan_and_stores_composed_note(self, runtime, monkeypatch):
        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            lambda prompt, deps: (
                '{"done":true,"result":{"title":"DNS","content":'
                '"DNS 是域名系统，用于将域名解析为 IP 地址。"}}'
            ),
        )
        runtime.execute_entry(
            EntryInput(text="什么是DNS", user_id="test-user", session_id="solidify-session")
        )

        result = runtime.execute_entry(
            EntryInput(
                text="把DNS相关讨论结论固化下来",
                user_id="test-user",
                session_id="solidify-session",
            )
        )

        assert result.intent == "solidify_conversation"
        assert "DNS 是域名系统" in result.reply_text
        assert any("DNS 是域名系统" in note.content for note in runtime.store.list_notes("test-user"))
        assert runtime.memory.list_drafts("test-user", status="solidified")
        event_types = [event["type"] for event in result.events]
        assert "plan_created" in event_types
        assert "draft_ready" in event_types
        assert event_types.count("step_completed") >= 4

    def test_solidify_extracts_structured_note_body_before_capture(self, runtime, monkeypatch):
        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            lambda prompt, deps: (
                '{"thought":"整理正文","result":{"标题":"DNS（域名系统）",'
                '"正文":"DNS 用于将域名转换为 IP 地址。"}}'
            ),
        )
        runtime.execute_entry(
            EntryInput(text="什么是DNS", user_id="test-user", session_id="structured-solidify")
        )

        result = runtime.execute_entry(
            EntryInput(
                text="把DNS相关知识固化下来",
                user_id="test-user",
                session_id="structured-solidify",
            )
        )
        notes = runtime.store.list_notes("test-user")

        assert result.intent == "solidify_conversation"
        assert result.reply_text == "DNS（域名系统）\n\nDNS 用于将域名转换为 IP 地址。"
        assert any(note.content == result.reply_text for note in notes)
        assert not any(note.content == "把DNS相关知识固化下来" for note in notes)

    def test_solidify_delegates_topic_selection_to_llm(self, runtime, monkeypatch):
        prompts: list[str] = []

        def reply(prompt, deps):
            prompts.append(prompt)
            return (
                '{"thought":"只选择 DNS 轮次","done":true,"result":'
                '{"selected_turn_ids":["turn-2"],"title":"DNS","content":'
                '"DNS 是域名系统，用于将域名解析为 IP 地址。"}}'
            )

        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            reply,
        )
        for text in ("今天西安天气怎么样", "什么是DNS", "什么是JSON Schema"):
            runtime.execute_entry(
                EntryInput(text=text, user_id="test-user", session_id="focused-solidify")
            )

        runtime.execute_entry(
            EntryInput(
                text="把DNS相关知识固化下来",
                user_id="test-user",
                session_id="focused-solidify",
            )
        )

        solidify_prompt = prompts[-1]
        assert "什么是DNS" in solidify_prompt
        assert "西安" in solidify_prompt
        assert "JSON Schema" in solidify_prompt
        assert "必须根据当前保存请求进行语义选择" in solidify_prompt
        notes = runtime.store.list_notes("test-user")
        stored = next(note.content for note in notes if "DNS 是域名系统" in note.content)
        assert "西安" not in stored
        assert "JSON Schema" not in stored

    def test_solidify_streams_plan_progress_during_graph_execution(self, runtime, monkeypatch):
        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            lambda prompt, deps: (
                '{"done":true,"result":{"title":"DNS","content":'
                '"DNS 是域名系统，用于将域名解析为 IP 地址。"}}'
            ),
        )
        runtime.execute_entry(
            EntryInput(text="什么是DNS", user_id="test-user", session_id="stream-plan")
        )
        events: list[str] = []

        result = runtime.execute_entry(
            EntryInput(
                text="把DNS相关知识固化下来",
                user_id="test-user",
                session_id="stream-plan",
            ),
            on_progress=lambda event, payload: events.append(event),
        )

        assert result.intent == "solidify_conversation"
        assert "plan_created" in events
        assert "plan_step_started" in events
        assert "plan_step_completed" in events
        assert events.index("plan_created") < events.index("plan_step_started")
        assert "done" not in events

    def test_router_requested_clarify_then_resume(self, runtime):
        """Router requests clarification, then supplemental text is routed again."""
        entry = EntryInput(
            text="帮我",
            user_id="test-user",
            session_id="orch-test-clarify",
        )
        result = runtime.execute_entry(entry)
        assert result.run_status == "waiting_confirmation"
        assert result.pending_confirmation
        assert result.pending_confirmation["kind"] == "clarification_required"
        event_types = [event["type"] for event in result.events]
        assert event_types.index("intent_classified") < event_types.index("clarification_required")

        resumed = runtime.resume_entry(
            run_id=result.run_id or "",
            thread_id=result.thread_id or "",
            decision="clarify",
            user_id="test-user",
            text="记一下：澄清应由路由决策触发。",
            option_id="capture",
        )
        assert resumed.run_status == "completed"
        assert resumed.intent == "capture_text"
        assert resumed.reply_text

    def test_short_question_does_not_trigger_clarify(self, runtime):
        """Short but meaningful questions should route instead of pausing."""
        entry = EntryInput(
            text="你是谁",
            user_id="test-user",
            session_id="orch-test-short-question",
        )
        result = runtime.execute_entry(entry)
        assert result.run_status == "completed"
        assert result.pending_confirmation is None
        assert result.intent == "direct_answer"
        assert result.reply_text
        snapshot = runtime.get_run_snapshot(result.run_id or "")
        assert snapshot is not None
        assert snapshot.status == AgentRunStatus.completed
        assert snapshot.last_event is not None
        assert snapshot.last_event.type == "run_completed"

    def test_run_snapshots_list(self, runtime):
        """After executing entries, we should be able to list snapshots."""
        entry = EntryInput(text="你好", user_id="test-user", session_id="snap-test")
        runtime.execute_entry(entry)

        snapshots = runtime.list_run_snapshots(user_id="test-user", limit=10)
        # At least one snapshot from this test
        assert len(snapshots) >= 1
        snap = snapshots[0]
        assert snap.user_id == "test-user"
        assert snap.run_id

    def test_get_specific_run_snapshot(self, runtime):
        """Get a specific run snapshot by run_id."""
        entry = EntryInput(text="你好", user_id="test-user", session_id="snap-get")
        runtime.execute_entry(entry)

        # List to find the run_id (we don't get it back from EntryResult)
        snapshots = runtime.list_run_snapshots(user_id="test-user", limit=10)
        assert len(snapshots) > 0
        run_id = snapshots[0].run_id

        snapshot = runtime.get_run_snapshot(run_id)
        assert snapshot is not None
        assert snapshot.run_id == run_id

    def test_persisted_snapshots_are_visible_before_new_execution(self, temp_dir):
        from personal_agent.agent.runtime import AgentRuntime
        from personal_agent.graphiti.store import GraphitiStore
        from personal_agent.storage.ask_history_store import AskHistoryStore
        from personal_agent.storage.memory_store import LocalMemoryStore

        settings = Settings(
            data_dir=temp_dir,
            langgraph_checkpoint_backend="sqlite",
            langgraph_checkpoint_path=str(temp_dir / "checkpoint.sqlite"),
        )

        def create_runtime():
            return AgentRuntime(
                settings=settings,
                store=LocalMemoryStore(settings.data_dir),
                graph_store=GraphitiStore(settings),
                ask_history_store=AskHistoryStore(postgres_url=None),
            )

        original = create_runtime()
        result = original.execute_entry(
            EntryInput(text="你好", user_id="test-user", session_id="persisted-run")
        )
        original._get_orch_graph().checkpointer.conn.close()

        restarted = create_runtime()
        try:
            assert restarted._orch_graph is None
            listed = restarted.list_run_snapshots(user_id="test-user", limit=10)
            restored = restarted.get_run_snapshot(result.run_id or "")

            assert any(item.run_id == result.run_id for item in listed)
            assert restored is not None
            assert restored.thread_id == "test-user:persisted-run"
        finally:
            restarted._get_orch_graph().checkpointer.conn.close()

    def test_session_runs_share_thread_and_remain_queryable_by_run_id(self, runtime):
        first = runtime.execute_entry(
            EntryInput(text="你好", user_id="test-user", session_id="shared-thread")
        )
        second = runtime.execute_entry(
            EntryInput(text="你是谁", user_id="test-user", session_id="shared-thread")
        )

        assert first.run_id != second.run_id
        assert first.thread_id == second.thread_id == "test-user:shared-thread"
        assert runtime.get_run_snapshot(first.run_id or "") is not None
        assert runtime.get_run_snapshot(second.run_id or "") is not None
        listed_ids = {
            snapshot.run_id
            for snapshot in runtime.list_run_snapshots(user_id="test-user", limit=20)
        }
        assert first.run_id in listed_ids
        assert second.run_id in listed_ids
        latest = runtime._get_orch_graph().get_state(
            {"configurable": {"thread_id": "test-user:shared-thread"}}
        ).values
        contents = [message.content for message in latest["messages"]]
        assert contents[0] == "你好"
        assert contents[2] == "你是谁"
        assert len(contents) == 4

    def test_new_run_input_checkpoint_does_not_retain_previous_answer(self, runtime):
        first = runtime.execute_entry(
            EntryInput(text="你好", user_id="test-user", session_id="clean-input-checkpoint")
        )
        second = runtime.execute_entry(
            EntryInput(text="谢谢", user_id="test-user", session_id="clean-input-checkpoint")
        )

        config = {"configurable": {"thread_id": second.thread_id}}
        second_run_states = []
        for checkpoint in runtime._get_orch_graph().checkpointer.list(config):
            values = checkpoint.checkpoint.get("channel_values", {})
            if values.get("run_id") == second.run_id:
                second_run_states.append(AgentGraphState.model_validate(values))

        assert second_run_states
        assert all(state.answer != first.reply_text for state in second_run_states)

    def test_graph_state_after_execution(self, runtime):
        """After executing, the last state in the graph should have answer set."""
        entry = EntryInput(
            text="你好，今天天气不错",
            user_id="test-user",
            session_id="state-test",
        )
        runtime.execute_entry(entry)

        snapshots = runtime.list_run_snapshots(user_id="test-user", limit=10)
        relevant = [s for s in snapshots if s.session_id == "state-test"]
        assert len(relevant) >= 1
        assert relevant[0].intent in ("direct_answer", "unknown", "capture_text")


# ---------------------------------------------------------------------------
# Phase 3: HITL interrupt / resume
# ---------------------------------------------------------------------------

class TestPhase3RoutingFunctions:
    """Unit tests for the Phase 3 conditional edge functions."""

    def test_after_step_execution_routes_to_confirm_step(self):
        from personal_agent.agent.orchestration_graph import _after_step_execution

        state = AgentGraphState(
            plan_steps=[
                {"step_id": "s1", "action_type": "tool_call", "status": "awaiting_confirmation"},
            ],
            current_step_index=0,
        )
        assert _after_step_execution(state) == "confirm_step"

    def test_after_step_execution_routes_to_handle_failure(self):
        from personal_agent.agent.orchestration_graph import _after_step_execution

        state = AgentGraphState(
            plan_steps=[
                {"step_id": "s1", "action_type": "tool_call", "status": "failed"},
            ],
            current_step_index=0,
        )
        assert _after_step_execution(state) == "handle_failure"

    def test_after_step_execution_routes_to_handle_success(self):
        from personal_agent.agent.orchestration_graph import _after_step_execution

        state = AgentGraphState(
            plan_steps=[
                {"step_id": "s1", "action_type": "retrieve", "status": "completed"},
            ],
            current_step_index=0,
        )
        assert _after_step_execution(state) == "handle_success"

    def test_after_confirm_step_confirmed(self):
        from personal_agent.agent.orchestration_graph import _after_confirm_step

        state = AgentGraphState(confirmation_decision="confirmed")
        assert _after_confirm_step(state) == "handle_success"

    def test_after_confirm_step_rejected(self):
        from personal_agent.agent.orchestration_graph import _after_confirm_step

        state = AgentGraphState(confirmation_decision="rejected")
        assert _after_confirm_step(state) == "handle_failure"

    def test_after_confirm_step_none_defaults_to_failure(self):
        from personal_agent.agent.orchestration_graph import _after_confirm_step

        state = AgentGraphState()
        assert _after_confirm_step(state) == "handle_failure"


class TestPhase3ExecutePlanStep:
    """Tests for _node_execute_plan_step with pending_confirmation handling."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            langgraph_checkpoint_backend="memory",
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.storage.memory_store import LocalMemoryStore
        from personal_agent.storage.ask_history_store import AskHistoryStore
        from personal_agent.graphiti.store import GraphitiStore
        from personal_agent.agent.runtime import AgentRuntime

        store = LocalMemoryStore(stub_settings.data_dir)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
            ask_history_store=AskHistoryStore(postgres_url=None),
        )

    def test_node_sets_awaiting_confirmation_when_pending_confirmation_present(self, runtime, monkeypatch):
        """When a step dispatch sets pending_confirmation, step status becomes awaiting_confirmation."""
        from personal_agent.agent.orchestration_graph import _node_execute_plan_step

        state = AgentGraphState(
            run_id="r1",
            user_id="u1",
            plan_steps=[
                {
                    "step_id": "s1",
                    "action_type": "tool_call",
                    "tool_name": "capture_text",
                    "status": "running",
                },
            ],
            current_step_index=0,
            entry_text="test",
        )

        # Patch _dispatch_plan_step to simulate a tool returning pending_confirmation
        def _mock_dispatch(step, sd, st, rt):
            st.pending_confirmation = {
                "step_id": "s1",
                "action_id": "act-1",
                "token": "abc123",
                "action_type": "delete_note",
                "note_id": "n1",
                "title": "测试笔记",
                "summary": "删除测试",
            }

        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._dispatch_plan_step",
            _mock_dispatch,
        )

        result = _node_execute_plan_step(state, deps=OrchestrationDeps.from_runtime(runtime))
        assert result["plan_steps"][0].status == "awaiting_confirmation"
        assert state.events[-1].type == "confirmation_required"

    def test_node_completes_normally_when_no_pending_confirmation(self, runtime):
        """Without pending_confirmation, the step should complete normally."""
        from personal_agent.agent.orchestration_graph import _node_execute_plan_step

        state = AgentGraphState(
            run_id="r1",
            user_id="u1",
            plan_steps=[
                {
                    "step_id": "s1",
                    "action_type": "retrieve",
                    "description": "检索",
                    "status": "running",
                },
            ],
            current_step_index=0,
            entry_text="test",
        )

        result = _node_execute_plan_step(state, deps=OrchestrationDeps.from_runtime(runtime))
        assert result["plan_steps"][0].status == "completed"


class TestPhase3InterruptResumeIntegration:
    """Integration tests for LangGraph interrupt result handling and resume."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            langgraph_checkpoint_backend="memory",
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.storage.memory_store import LocalMemoryStore
        from personal_agent.storage.ask_history_store import AskHistoryStore
        from personal_agent.graphiti.store import GraphitiStore
        from personal_agent.agent.runtime import AgentRuntime

        store = LocalMemoryStore(stub_settings.data_dir)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
            ask_history_store=AskHistoryStore(postgres_url=None),
        )

    def test_execute_entry_returns_run_id_and_status(self, runtime):
        """After a normal execution, EntryResult should include run_id and run_status."""
        entry = EntryInput(text="你好", user_id="u1", session_id="s1")
        result = runtime.execute_entry(entry)
        assert result.run_id is not None
        assert result.run_status == "completed"

    def test_resume_entry_accepts_valid_decision(self, runtime):
        """resume_entry should be callable and return an EntryResult."""
        # Build the graph to ensure checkpointer is ready
        runtime._get_orch_graph()
        # Even without a prior interrupted run, resume_entry should
        # handle the graph invocation gracefully (LangGraph may start
        # a fresh run or return the final state).
        result = runtime.resume_entry(
            run_id="fresh-run",
            thread_id="u1:default:fresh-run",
            decision="confirm",
            user_id="u1",
        )
        assert isinstance(result.intent, str)
        assert result.run_id is not None
        assert result.run_status in ("completed", "waiting_confirmation")
        if result.run_status == "waiting_confirmation":
            assert result.pending_confirmation
            assert result.pending_confirmation["kind"] == "clarification_required"

    def test_confirmation_decision_field_roundtrip(self):
        """AgentGraphState.confirmation_decision should survive serialization."""
        state = AgentGraphState(
            confirmation_decision="confirmed",
            pending_confirmation={"step_id": "s1"},
        )
        data = state.model_dump(mode="json")
        restored = AgentGraphState.model_validate(data)
        assert restored.confirmation_decision == "confirmed"

    def test_to_run_snapshot_waiting_confirmation(self):
        """When pending_confirmation is set, _infer_status returns waiting_confirmation."""
        state = AgentGraphState(
            router_decision=RouterDecision(route="delete_knowledge"),
            pending_confirmation={"step_id": "s1", "action_type": "delete_note"},
            answer_completed=False,
        )
        snap = state.to_run_snapshot()
        assert snap.status == AgentRunStatus.waiting_confirmation

    def test_interrupt_payload_is_read_from_invoke_result(self):
        """LangGraph exposes interrupt payloads through the invoke result."""
        from personal_agent.agent.runtime import _interrupt_payload_from_result

        class _Interrupt:
            value = {"step_id": "s1", "message": "确认？"}

        payload = _interrupt_payload_from_result({"__interrupt__": [_Interrupt()]})

        assert payload == {"step_id": "s1", "message": "确认？"}


# ---------------------------------------------------------------------------
# Phase 4: ReAct subgraph
# ---------------------------------------------------------------------------


class TestPhase4ReActHelpers:
    """Unit tests for ReAct helper functions."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            langgraph_checkpoint_backend="memory",
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.storage.memory_store import LocalMemoryStore
        from personal_agent.storage.ask_history_store import AskHistoryStore
        from personal_agent.graphiti.store import GraphitiStore
        from personal_agent.agent.runtime import AgentRuntime

        store = LocalMemoryStore(stub_settings.data_dir)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
            ask_history_store=AskHistoryStore(postgres_url=None),
        )

    def test_resolve_allowed_tools_for_step(self, runtime):
        from personal_agent.agent.orchestration_graph import _resolve_allowed_tools_for_step
        from personal_agent.agent.planner import PlanStep

        step = PlanStep(
            step_id="s1",
            action_type="retrieve",
            allowed_tools=["graph_search", "nonexistent_tool"],
            execution_mode="react",
        )
        resolved = _resolve_allowed_tools_for_step(step, OrchestrationDeps.from_runtime(runtime))
        assert "graph_search" in resolved
        assert "nonexistent_tool" not in resolved

    def test_is_react_tool_blocked_high_risk(self, runtime):
        from personal_agent.agent.orchestration_graph import _is_react_tool_blocked

        assert _is_react_tool_blocked("delete_note", OrchestrationDeps.from_runtime(runtime))
        assert _is_react_tool_blocked("capture_text", OrchestrationDeps.from_runtime(runtime))

    def test_is_react_tool_blocked_allows_safe_tools(self, runtime):
        from personal_agent.agent.orchestration_graph import _is_react_tool_blocked

        assert not _is_react_tool_blocked("graph_search", OrchestrationDeps.from_runtime(runtime))

    def test_build_react_context(self):
        from personal_agent.agent.orchestration_graph import _build_react_context
        from personal_agent.agent.planner import PlanStep

        step = PlanStep(step_id="s1", tool_input={"question": "什么是X？"})
        step_results = {
            "prev": {"answer": "X是一种技术", "hint": "fallback"},
        }
        ctx = _build_react_context(step, step_results)
        assert "什么是X" in ctx
        assert "X是一种技术" in ctx

    def test_format_react_tools(self, runtime):
        from personal_agent.agent.orchestration_graph import _format_react_tools

        text = _format_react_tools({"graph_search"}, OrchestrationDeps.from_runtime(runtime))
        assert "graph_search" in text

    def test_summarize_react_tool_result(self):
        from personal_agent.agent.orchestration_graph import _summarize_react_tool_result

        assert "hello" in _summarize_react_tool_result({"answer": "hello world"})
        assert "无返回数据" in _summarize_react_tool_result(None)
        assert "42" in _summarize_react_tool_result(42)


class TestPhase4ReActNodes:
    """Unit tests for ReAct subgraph node functions."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            langgraph_checkpoint_backend="memory",
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.storage.memory_store import LocalMemoryStore
        from personal_agent.storage.ask_history_store import AskHistoryStore
        from personal_agent.graphiti.store import GraphitiStore
        from personal_agent.agent.runtime import AgentRuntime

        store = LocalMemoryStore(stub_settings.data_dir)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
            ask_history_store=AskHistoryStore(postgres_url=None),
        )

    def test_react_init_seeds_state(self, runtime):
        from personal_agent.agent.orchestration_graph import _node_react_init

        state = AgentGraphState(
            run_id="r1",
            plan_steps=[
                {
                    "step_id": "ask-1",
                    "action_type": "retrieve",
                    "description": "检索知识库",
                    "execution_mode": "react",
                    "allowed_tools": ["graph_search"],
                    "max_iterations": 3,
                    "status": "running",
                },
            ],
            current_step_index=0,
        )
        result = _node_react_init(state, deps=OrchestrationDeps.from_runtime(runtime))
        assert result["react_step_id"] == "ask-1"
        assert result["react_max_iterations"] == 3
        assert result["react_allowed_tools"] == ["graph_search"]
        assert result["react_iteration_index"] == 0
        assert result["react_done"] is False
        assert not result["react_result"]

    def test_should_continue_react_when_not_done(self):
        from personal_agent.agent.orchestration_graph import _should_continue_react

        state = AgentGraphState(react_done=False, react_iteration_index=0, react_max_iterations=3)
        assert _should_continue_react(state) == "iterate"

    def test_should_continue_react_when_done(self):
        from personal_agent.agent.orchestration_graph import _should_continue_react

        state = AgentGraphState(react_done=True, react_iteration_index=0, react_max_iterations=3)
        assert _should_continue_react(state) == "finalize"

    def test_should_continue_react_when_exhausted(self):
        from personal_agent.agent.orchestration_graph import _should_continue_react

        state = AgentGraphState(react_done=False, react_iteration_index=3, react_max_iterations=3)
        assert _should_continue_react(state) == "finalize"

    def test_react_finalize_writes_result_and_clears_state(self):
        from personal_agent.agent.orchestration_graph import _node_react_finalize

        state = AgentGraphState(
            run_id="r1",
            react_step_id="ask-1",
            react_result={"answer": "42", "react_iterations": 2},
            react_user_prompt="...",
            react_done=True,
            react_iteration_index=2,
            react_max_iterations=3,
            react_allowed_tools=["graph_search"],
            plan_steps=[
                {"step_id": "ask-1", "action_type": "retrieve", "status": "running"},
            ],
            current_step_index=0,
        )
        result = _node_react_finalize(state)
        assert state.step_results["ask-1"] == {"answer": "42", "react_iterations": 2}
        assert state.plan_steps[0].status == "completed"
        assert result["react_step_id"] == ""
        assert result["react_done"] is False
        assert result["react_result"] == {}


class TestPhase4ReActIterateNode:
    """Tests for _node_react_iterate with mocked LLM."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            langgraph_checkpoint_backend="memory",
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.storage.memory_store import LocalMemoryStore
        from personal_agent.storage.ask_history_store import AskHistoryStore
        from personal_agent.graphiti.store import GraphitiStore
        from personal_agent.agent.runtime import AgentRuntime

        store = LocalMemoryStore(stub_settings.data_dir)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
            ask_history_store=AskHistoryStore(postgres_url=None),
        )

    def test_react_iterate_done_sets_flag(self, runtime, monkeypatch):
        from personal_agent.agent.orchestration_graph import _node_react_iterate

        state = AgentGraphState(
            run_id="r1",
            react_step_id="ask-1",
            react_iteration_index=0,
            react_max_iterations=3,
            react_allowed_tools=["graph_search"],
            react_user_prompt="搜索X相关的内容",
            react_done=False,
            plan_steps=[{"step_id": "ask-1", "status": "running"}],
            current_step_index=0,
        )

        def _mock_llm(prompt, rt):
            return '{"thought": "已经找到答案","done": true,"result": {"answer": "X是一种技术"}}'

        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            _mock_llm,
        )

        result = _node_react_iterate(state, deps=OrchestrationDeps.from_runtime(runtime))
        assert result["react_done"] is True
        assert result["react_result"]["answer"] == "X是一种技术"
        assert len(result["react_iterations"]) >= 1
        assert result["react_iterations"][-1]["done"] is True

    def test_react_iterate_parse_failure_increments_index(self, runtime, monkeypatch):
        from personal_agent.agent.orchestration_graph import _node_react_iterate

        state = AgentGraphState(
            run_id="r1",
            react_step_id="ask-1",
            react_iteration_index=0,
            react_max_iterations=3,
            react_allowed_tools=["graph_search"],
            react_user_prompt="搜索",
            react_done=False,
            plan_steps=[{"step_id": "ask-1", "status": "running"}],
            current_step_index=0,
        )

        def _mock_llm(prompt, rt):
            return "not valid json {{{"

        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            _mock_llm,
        )

        result = _node_react_iterate(state, deps=OrchestrationDeps.from_runtime(runtime))
        # Parse failure: index increments, not done yet
        assert result["react_iteration_index"] == 1
        assert result.get("react_done") is not True

    def test_react_iterate_parse_failure_exhausts(self, runtime, monkeypatch):
        from personal_agent.agent.orchestration_graph import _node_react_iterate

        state = AgentGraphState(
            run_id="r1",
            react_step_id="ask-1",
            react_iteration_index=2,  # last iteration (0-based, max=3 → index 2 is the 3rd)
            react_max_iterations=3,
            react_allowed_tools=["graph_search"],
            react_user_prompt="搜索",
            react_done=False,
            plan_steps=[{"step_id": "ask-1", "status": "running"}],
            current_step_index=0,
        )

        def _mock_llm(prompt, rt):
            return "bad json"

        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            _mock_llm,
        )

        result = _node_react_iterate(state, deps=OrchestrationDeps.from_runtime(runtime))
        assert result["react_done"] is True

    def test_react_iterate_blocked_tool(self, runtime, monkeypatch):
        from personal_agent.agent.orchestration_graph import _node_react_iterate

        state = AgentGraphState(
            run_id="r1",
            react_step_id="ask-1",
            react_iteration_index=0,
            react_max_iterations=3,
            react_allowed_tools=["graph_search", "delete_note"],
            react_user_prompt="删除笔记",
            react_done=False,
            plan_steps=[{"step_id": "ask-1", "status": "running"}],
            current_step_index=0,
        )

        def _mock_llm(prompt, rt):
            return '{"thought": "需要删除","tool": "delete_note","input": {"note_id": "n1"}}'

        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            _mock_llm,
        )

        result = _node_react_iterate(state, deps=OrchestrationDeps.from_runtime(runtime))
        # Tool is blocked — observation should indicate error
        assert len(result["react_iterations"]) >= 1
        obs = result["react_iterations"][-1].get("observation", "")
        assert "高风险" in obs or "不允许" in obs
        assert result["react_iteration_index"] == 1

    def test_react_iterate_llm_returns_none(self, runtime, monkeypatch):
        from personal_agent.agent.orchestration_graph import _node_react_iterate

        state = AgentGraphState(
            run_id="r1",
            react_step_id="ask-1",
            react_iteration_index=0,
            react_max_iterations=3,
            react_allowed_tools=["graph_search"],
            react_user_prompt="搜索",
            react_done=False,
            plan_steps=[{"step_id": "ask-1", "status": "running"}],
            current_step_index=0,
        )

        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            lambda prompt, rt: None,
        )

        result = _node_react_iterate(state, deps=OrchestrationDeps.from_runtime(runtime))
        assert result["react_done"] is True
        assert "react_iterations" in result.get("react_result", {})


class TestPhase4ReActSubgraphIntegration:
    """Integration tests for the ReAct subgraph end-to-end."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            langgraph_checkpoint_backend="memory",
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.storage.memory_store import LocalMemoryStore
        from personal_agent.storage.ask_history_store import AskHistoryStore
        from personal_agent.graphiti.store import GraphitiStore
        from personal_agent.agent.runtime import AgentRuntime

        store = LocalMemoryStore(stub_settings.data_dir)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
            ask_history_store=AskHistoryStore(postgres_url=None),
        )

    def test_react_subgraph_builds_and_compiles(self, runtime):
        from personal_agent.agent.orchestration_graph import _build_react_subgraph
        from langgraph.graph.state import CompiledStateGraph

        subgraph = _build_react_subgraph(OrchestrationDeps.from_runtime(runtime))
        assert subgraph is not None
        assert isinstance(subgraph, CompiledStateGraph)
        assert subgraph.checkpointer is not None

    def test_react_subgraph_single_iteration_done(self, runtime, monkeypatch):
        """Subgraph runs one iteration then LLM declares done."""
        from personal_agent.agent.orchestration_graph import _build_react_subgraph

        def _mock_llm(prompt, rt):
            return '{"thought": "已完成","done": true,"result": {"answer": "X是..."}}'

        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            _mock_llm,
        )

        subgraph = _build_react_subgraph(OrchestrationDeps.from_runtime(runtime))

        state = AgentGraphState(
            run_id="r1",
            react_step_id="ask-1",
            react_max_iterations=3,
            react_allowed_tools=["graph_search"],
            react_iteration_index=0,
            react_done=False,
            plan_steps=[{
                "step_id": "ask-1",
                "action_type": "retrieve",
                "description": "检索知识库",
                "tool_name": "graph_search",
                "execution_mode": "react",
                "allowed_tools": ["graph_search"],
                "max_iterations": 3,
                "status": "running",
            }],
            current_step_index=0,
        )

        config = {"configurable": {"thread_id": "test-react-sub"}}
        result = AgentGraphState.model_validate(subgraph.invoke(state, config))
        # react_done is cleared by finalize; check step_results and plan_steps instead
        assert result.step_results.get("ask-1", {}).get("answer") == "X是..."
        assert result.plan_steps[0].status == "completed"
        assert len(result.react_iterations) >= 1

    def test_react_subgraph_respects_max_iterations(self, runtime, monkeypatch):
        """Subgraph terminates after max_iterations even without done."""
        from personal_agent.agent.orchestration_graph import _build_react_subgraph

        call_count = [0]

        def _mock_llm(prompt, rt):
            call_count[0] += 1
            return f'{{"thought": "思考{call_count[0]}","tool": "graph_search","input": {{"query": "X"}}}}'

        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            _mock_llm,
        )

        # Also mock tool execution to avoid real graph_search calls
        def _mock_tool_execute(tool_name, **kwargs):
            from personal_agent.tools.base import ToolResult
            return ToolResult(data={"answer": "搜索结果"}, ok=True)

        monkeypatch.setattr(
            runtime._tool_registry, "execute", _mock_tool_execute,
        )

        subgraph = _build_react_subgraph(OrchestrationDeps.from_runtime(runtime))

        state = AgentGraphState(
            run_id="r1",
            react_step_id="ask-1",
            react_max_iterations=2,
            react_allowed_tools=["graph_search"],
            react_iteration_index=0,
            react_done=False,
            plan_steps=[{
                "step_id": "ask-1",
                "action_type": "retrieve",
                "description": "检索",
                "tool_name": "graph_search",
                "execution_mode": "react",
                "allowed_tools": ["graph_search"],
                "max_iterations": 2,
                "status": "running",
            }],
            current_step_index=0,
        )

        config = {"configurable": {"thread_id": "test-react-max"}}
        result = AgentGraphState.model_validate(subgraph.invoke(state, config))
        # react_done is cleared by finalize; check step_results and plan_steps instead
        assert result.plan_steps[0].status == "completed"
        assert call_count[0] <= 2

    def test_main_graph_routes_react_through_subgraph(self, runtime, monkeypatch):
        """An ask entry with plan steps should route the ReAct step through the subgraph."""
        from personal_agent.agent.orchestration_graph import build_entry_orchestration_graph, _build_checkpointer

        def _mock_llm(prompt, rt):
            return '{"thought": "已检索","done": true,"result": {"answer": "服务降级是指在系统压力过大时主动关闭非核心能力"}}'

        monkeypatch.setattr(
            "personal_agent.agent.orchestration_nodes._react_llm_respond",
            _mock_llm,
        )

        checkpointer = _build_checkpointer(runtime.settings)
        graph = build_entry_orchestration_graph(OrchestrationDeps.from_runtime(runtime), checkpointer=checkpointer)

        state = AgentGraphState(
            run_id="r-ask",
            user_id="u1",
            entry_text="什么是服务降级？",
            router_decision=RouterDecision(route="ask", requires_planning=True),
            plan_steps=[
                {
                    "step_id": "ask-1",
                    "action_type": "retrieve",
                    "description": "在知识库中检索相关内容",
                    "tool_name": "graph_search",
                    "execution_mode": "react",
                    "allowed_tools": ["graph_search", "web_search"],
                    "max_iterations": 3,
                    "status": "planned",
                },
                {
                    "step_id": "ask-2",
                    "action_type": "compose",
                    "description": "整合生成回答",
                    "depends_on": ["ask-1"],
                    "status": "planned",
                },
            ],
            current_step_index=0,
        )

        config = {"configurable": {"thread_id": "test-main-react"}}
        result = AgentGraphState.model_validate(graph.invoke(state, config))
        # The graph should complete with answer set
        assert result.answer or result.plan_steps[0].status == "completed"

    def test_after_step_execution_routes_to_react_step(self):
        from personal_agent.agent.orchestration_graph import _after_step_execution

        state = AgentGraphState(
            plan_steps=[
                {
                    "step_id": "ask-1",
                    "execution_mode": "react",
                    "status": "running",
                },
            ],
            current_step_index=0,
        )
        assert _after_step_execution(state) == "react_step"

    def test_react_state_serialization_roundtrip(self):
        """Verify the new ReAct fields survive JSON serialization."""
        state = AgentGraphState(
            react_step_id="ask-1",
            react_iteration_index=2,
            react_max_iterations=3,
            react_allowed_tools=["graph_search"],
            react_user_prompt="...",
            react_done=True,
            react_result={"answer": "42"},
        )
        data = state.model_dump(mode="json")
        restored = AgentGraphState.model_validate(data)
        assert restored.react_step_id == "ask-1"
        assert restored.react_iteration_index == 2
        assert restored.react_max_iterations == 3
        assert restored.react_allowed_tools == ["graph_search"]
        assert restored.react_done is True
        assert restored.react_result == {"answer": "42"}


# ============================================================================
# Phase 5: Entry unification — event helpers, EntryResult.events, SSE conversion
# ============================================================================


class TestPhase5EventHelpers:
    """Unit tests for execution_trace_from_events and events_to_sse_tuples."""

    def test_execution_trace_from_step_started_events(self):
        from personal_agent.agent.orchestration_models import (
            AgentEvent,
            execution_trace_from_events,
        )

        events = [
            AgentEvent(type="step_started", payload={"step_id": "s1", "description": "检索相关笔记"}),
            AgentEvent(type="step_started", payload={"step_id": "s2", "description": "调用删除工具"}),
            AgentEvent(type="step_completed", payload={"step_id": "s1"}),
        ]
        trace = execution_trace_from_events(events)
        assert "检索相关笔记" in trace
        assert "调用删除工具" in trace
        assert len(trace) == 2

    def test_execution_trace_deduplicates(self):
        from personal_agent.agent.orchestration_models import (
            AgentEvent,
            execution_trace_from_events,
        )

        events = [
            AgentEvent(type="step_started", payload={"description": "检索"}),
            AgentEvent(type="step_started", payload={"description": "检索"}),
        ]
        trace = execution_trace_from_events(events)
        assert trace == ["检索"]

    def test_execution_trace_empty_for_no_events(self):
        from personal_agent.agent.orchestration_models import execution_trace_from_events

        assert execution_trace_from_events([]) == []

    def test_events_to_sse_tuples_maps_types(self):
        from personal_agent.agent.orchestration_models import (
            AgentEvent,
            events_to_sse_tuples,
        )

        events = [
            AgentEvent(type="plan_created", payload={"plan_steps": []}),
            AgentEvent(type="step_started", payload={"description": "测试"}),
            AgentEvent(type="run_completed", payload={"answer": "ok"}),
        ]
        tuples = events_to_sse_tuples(events)
        assert len(tuples) == 3
        assert tuples[0][0] == "plan_created"
        assert tuples[1][0] == "plan_step_started"
        assert tuples[2][0] == "done"
        # Each payload gets _event_id and _event_type metadata
        for _, payload in tuples:
            assert "_event_id" in payload
            assert "_event_type" in payload

    def test_events_to_sse_tuples_empty(self):
        from personal_agent.agent.orchestration_models import events_to_sse_tuples

        assert events_to_sse_tuples([]) == []


class TestPhase5EntryResultEvents:
    """Tests for EntryResult.events passthrough from graph state."""

    def test_entry_result_accepts_events(self):
        from personal_agent.agent.runtime_results import EntryResult

        result = EntryResult(
            intent="ask",
            reason="测试",
            reply_text="答案",
            events=[{"type": "entry_started", "payload": {}}],
        )
        assert len(result.events) == 1
        assert result.events[0]["type"] == "entry_started"

    def test_entry_result_events_default_empty(self):
        from personal_agent.agent.runtime_results import EntryResult

        result = EntryResult(intent="direct_answer", reason="测试", reply_text="你好")
        assert result.events == []

    def test_entry_result_events_serialization_roundtrip(self):
        from personal_agent.agent.orchestration_models import AgentEvent
        from personal_agent.agent.runtime_results import EntryResult

        result = EntryResult(
            intent="ask",
            reason="测试",
            reply_text="答案",
            events=[
                AgentEvent(type="intent_classified", payload={"intent": "ask"}).model_dump(mode="json"),
                AgentEvent(type="answer_completed", payload={"answer": "答案"}).model_dump(mode="json"),
            ],
        )
        data = result.model_dump(mode="json")
        restored = EntryResult.model_validate(data)
        assert len(restored.events) == 2
        assert restored.events[0]["type"] == "intent_classified"


class TestPhase5ExecutionTraceDerivation:
    """Integration tests verifying execution_trace is derived from events."""

    def test_finalize_plan_execution_derives_trace(self, monkeypatch):
        from personal_agent.agent.orchestration_graph import (
            _node_finalize_plan_execution,
        )
        from personal_agent.agent.orchestration_models import AgentGraphState

        state = AgentGraphState(
            run_id="test-trace",
            plan_steps=[
                {"step_id": "s1", "action_type": "retrieve", "status": "completed"},
            ],
            step_results={"s1": {"notes": []}},
            answer="完成",
            events=[
                AgentEvent(type="entry_started", payload={}),
                AgentEvent(type="step_started", payload={"step_id": "s1", "description": "检索相关笔记"}),
                AgentEvent(type="step_started", payload={"step_id": "s2", "description": "生成回答"}),
            ],
        )

        result = _node_finalize_plan_execution(state)
        assert result["execution_trace"] == ["检索相关笔记", "生成回答"]
        assert state.execution_trace == ["检索相关笔记", "生成回答"]
        assert result["events"][-1].type == "answer_completed"

    def test_finalize_plan_no_events_produces_empty_trace(self):
        from personal_agent.agent.orchestration_graph import (
            _node_finalize_plan_execution,
        )
        from personal_agent.agent.orchestration_models import AgentGraphState

        state = AgentGraphState(
            run_id="test-empty",
            plan_steps=[
                {"step_id": "s1", "action_type": "retrieve", "status": "completed"},
            ],
            answer="完成",
        )

        result = _node_finalize_plan_execution(state)
        assert result["execution_trace"] == []


class TestPhase5FinalizeEntryState:
    """Final result nodes must persist their status markers to checkpoints."""

    def test_successful_finalize_persists_completion_events(self):
        from personal_agent.agent.orchestration_graph import _node_finalize_entry_result

        state = AgentGraphState(
            run_id="test-finalize",
            router_decision=RouterDecision(route="direct_answer"),
            answer="你好",
        )

        result = _node_finalize_entry_result(state)

        assert result["answer_completed"] is True
        assert [event.type for event in result["events"]] == [
            "answer_completed",
            "run_completed",
        ]
        assert result["updated_at"] == state.updated_at
        assert result["messages"][0].content == "你好"

    def test_finalize_does_not_duplicate_existing_answer_completed_event(self):
        from personal_agent.agent.orchestration_graph import _node_finalize_entry_result

        state = AgentGraphState(
            run_id="test-plan-finalize",
            router_decision=RouterDecision(route="ask"),
            answer="完成",
            answer_completed=True,
        )
        state.add_event("answer_completed", {"answer": "完成"})

        result = _node_finalize_entry_result(state)
        event_types = [event.type for event in result["events"]]

        assert event_types.count("answer_completed") == 1
        assert event_types[-1] == "run_completed"


class TestPhase5GraphToEntryResultEvents:
    """End-to-end tests verifying entry results carry events from graph execution."""

    def test_graph_entry_result_has_events(self, monkeypatch):
        """Verify that execute_entry returns events when graph is enabled."""
        from personal_agent.agent.orchestration_models import AgentGraphState
        from personal_agent.agent.runtime_results import EntryResult

        # Simulate what happens in execute_entry after graph.invoke()
        state = AgentGraphState(
            run_id="test-events",
            router_decision=RouterDecision(route="direct_answer", user_visible_message="用户打招呼"),
            answer="你好！有什么可以帮助你的？",
            answer_completed=True,
            execution_trace=["生成直接回复"],
        )
        state.add_event("entry_started", {"text": "你好"})
        state.add_event("intent_classified", {"intent": "direct_answer"})
        state.add_event("answer_completed", {"answer": "你好！有什么可以帮助你的？"})
        state.add_event("run_completed", {})

        result = EntryResult(
            intent=state.router_decision.route if state.router_decision else "unknown",
            reason=state.router_decision.user_visible_message if state.router_decision else "",
            reply_text=state.answer or "",
            execution_trace=state.execution_trace,
            run_id=state.run_id,
            run_status="completed",
            events=[e.model_dump(mode="json") for e in state.events],
        )

        assert len(result.events) == 4
        event_types = [e["type"] for e in result.events]
        assert "entry_started" in event_types
        assert "intent_classified" in event_types
        assert "answer_completed" in event_types
        assert "run_completed" in event_types

    def test_interrupted_result_has_events(self):
        """Verify that interrupted (waiting_confirmation) results carry accumulated events."""
        from personal_agent.agent.runtime_results import EntryResult

        result = EntryResult(
            intent="unknown",
            reason="操作需要用户确认",
            reply_text="确认删除？",
            run_id="r1",
            thread_id="t1",
            pending_confirmation={"step_id": "s2"},
            run_status="waiting_confirmation",
            events=[
                {"type": "entry_started", "payload": {}},
                {"type": "step_started", "payload": {"step_id": "s1"}},
            ],
        )

        assert result.run_status == "waiting_confirmation"
        assert len(result.events) == 2
