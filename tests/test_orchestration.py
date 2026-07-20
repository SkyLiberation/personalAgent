"""Tests for orchestration models and entry orchestration graph."""

from __future__ import annotations

import pytest
from tests.conftest import (
    POSTGRES_URL,
    admitted_task_analysis_result,
    stub_task_analysis,
)
from langchain_core.messages import AIMessage, HumanMessage

from personal_agent.orchestration.orchestration_models import (
    AgentEvent,
    RunCheckpoint,
    AgentRunStatus,
    ExecutableInvocation,
    InvocationBatchState,
    ReactSubState,
    ToolTrackingSubState,
    _new_run_id,
    _new_thread_id,
    execution_trace_to_events,
)
from personal_agent.orchestration.orchestration_nodes._helpers import _dialogue_prompt_messages
from personal_agent.planning.task_analyzer import (
    GoalDraft,
    ResourceHint,
    SuccessCriterionDraft,
    TaskAnalysisProposalBody,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.models import EntryInput
from personal_agent.execution.contracts.invocation import InvocationAttemptState
from personal_agent.runtime.contracts.control import ControlTurnState
from personal_agent.runtime.run_manager import RunStateError


def _make_task_analysis_result(route="unknown", user_visible_message="", **kwargs):
    item_fields = {
        key: value for key, value in kwargs.items()
        if key in GoalDraft.model_fields
    }
    clarify = bool(kwargs.get("requires_clarification", False))
    item_fields.setdefault("description", str(kwargs.get("input") or user_visible_message or route))
    kind, domain, resource_types, operations = {
        "capture_text": ("external_state", "knowledge", ["text"], ["ingest"]),
        "capture_link": ("external_state", "knowledge", ["url"], ["ingest"]),
        "solidify_conversation": ("external_state", "conversation", ["thread"], ["ingest"]),
        "delete_knowledge": ("external_state", "knowledge", ["note"], ["delete"]),
        "ask": ("response", "knowledge", ["note"], ["search", "read"]),
        "summarize_thread": ("response", "conversation", ["thread"], ["read"]),
    }.get(route, ("response", "", [], []))
    item_fields.setdefault("result_contract", kind)
    item_fields.setdefault("success_criteria", [SuccessCriterionDraft(
        description=f"完成请求：{item_fields['description']}",
        origin="model_inferred",
    )])
    if kind == "external_state":
        item_fields.setdefault("side_effect_intent", "mutation")
    if domain:
        item_fields.setdefault("resource_hints", [ResourceHint(
            semantic_domain=domain,
            resource_types=resource_types,
            operations=operations,
        )])
    item = GoalDraft(**item_fields)
    return admitted_task_analysis_result(item.description, TaskAnalysisProposalBody(
        user_goal=item.description,
        outcome="clarify" if clarify else "ready",
        goals=[] if clarify else [item],
        clarification=(
            {
                "missing_information": list(kwargs.get("missing_information", [])) or ["details"],
                "prompt": str(kwargs.get("clarification_prompt", "请补充信息")),
            }
            if clarify else None
        ),
    ))


def TaskAnalysis(route="unknown", user_visible_message="", **kwargs):
    result = _make_task_analysis_result(route, user_visible_message, **kwargs)
    assert result.accepted is not None
    return result.accepted


def TaskAnalysisResult(route="unknown", user_visible_message="", **kwargs):
    return _make_task_analysis_result(route, user_visible_message, **kwargs)


# ---------------------------------------------------------------------------
# RunCheckpoint
# ---------------------------------------------------------------------------

class TestAgentGraphState:
    def test_default_state_has_run_id(self):
        state = RunCheckpoint()
        assert state.run_id
        assert len(state.run_id) == 12

    def test_state_serialization_roundtrip(self):
        state = RunCheckpoint(
            user_id="user-1",
            session_id="sess-1",
            entry_text="什么是服务降级？",
            accepted_task_analysis=TaskAnalysis(route="ask"),
            answer="服务降级是在系统压力过大时...",
            invocation_batch=InvocationBatchState(invocations=[
                {"step_id": "s1", "action_type": "retrieve", "attempt": {"status": "completed"}},
            ]),
            execution_trace=["检索知识库", "生成回答"],
            messages=[HumanMessage(content="你好"), AIMessage(content="你好，有什么可以帮你的？")],
            tool_tracking=ToolTrackingSubState(pending_step_id="s1", pending_call_id="r1:s1:0"),
        )
        data = state.model_dump(mode="json")
        restored = RunCheckpoint.model_validate(data)
        assert restored.run_id == state.run_id
        assert restored.user_id == "user-1"
        assert restored.answer == state.answer
        assert len(restored.invocation_batch.invocations) == 1
        assert restored.invocation_batch.invocations[0].step_id == "s1"
        assert [message.content for message in restored.messages] == [
            "你好",
            "你好，有什么可以帮你的？",
        ]
        assert restored.tool_tracking.pending_step_id == "s1"
        assert restored.tool_tracking.pending_call_id == "r1:s1:0"

    def test_add_event_appends_and_updates_timestamp(self):
        state = RunCheckpoint(run_id="r1")
        event = state.add_event("entry_started", {"text": "hello"})
        assert len(state.events) == 1
        assert state.events[0].type == "entry_started"
        assert state.events[0].payload == {"text": "hello"}
        assert event.run_id == "r1"

    def test_update_step_status(self):
        state = RunCheckpoint(
            invocation_batch=InvocationBatchState(invocations=[
                {"step_id": "s1", "attempt": {"status": "running"}},
                {"step_id": "s2", "attempt": {"status": "planned"}},
            ])
        )
        state.update_step_status("s1", "completed")
        assert state.invocation_batch.invocations[0].status == "completed"
        assert state.invocation_batch.invocations[1].status == "planned"

    def test_to_run_snapshot_pending(self):
        state = RunCheckpoint()
        snap = state.to_run_snapshot()
        assert snap.status == AgentRunStatus.created
        assert snap.run_id == state.run_id

    def test_to_run_snapshot_completed(self):
        state = RunCheckpoint(accepted_task_analysis=TaskAnalysis(route="ask"), answer="42")
        state.add_event("answer_completed", {"answer": "42"})
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


class TestDialogueMessageRendering:
    def test_dialogue_messages_keep_recent_visible_turns(self):
        messages = [
            HumanMessage(content=f"old-{index}-" + ("这是一段需要被预算裁剪的历史消息。" * 180))
            for index in range(8)
        ]
        messages.append(AIMessage(content="最新更正：使用新集群"))

        rendered = _dialogue_prompt_messages(messages)

        # 最近一条助手消息必须原样保留在窗口末尾。
        assert rendered[-1] == {"role": "assistant", "content": "最新更正：使用新集群"}
        # token 预算会淘汰最早的若干轮，但保留的是最近的连续后缀且按时序排列。
        assert len(rendered) < len(messages)
        kept_old = [m["content"] for m in rendered if m["content"].startswith("old-")]
        kept_indices = [int(c.split("-")[1]) for c in kept_old]
        assert kept_indices == sorted(kept_indices)  # 时序保持
        assert kept_indices[-1] == 7  # 最近的可见轮被保留
        assert kept_indices[0] > 0  # 最早的轮在预算下被淘汰


class TestNormalizeEntry:
    def test_new_run_clears_previous_thread_progress(self):
        from personal_agent.orchestration.orchestration_graph import _node_normalize_entry

        state = RunCheckpoint(
            run_id="new-run",
            entry_input=EntryInput(text="什么是DNS", user_id="u1", session_id="s1"),
            accepted_task_analysis=TaskAnalysis(route="ask"),
            answer="上一轮天气回答",
            control=ControlTurnState(pending_interaction={
                "kind": "clarification_required",
                "action_type": "clarify_entry",
                "step_id": "clarify_entry",
            }),
            execution_trace=["上一轮轨迹"],
            citations=[{"note_id": "old", "title": "旧证据", "snippet": "旧"}],
            errors=["上一轮错误"],
            messages=[
                HumanMessage(content="今天西安天气怎么样"),
                AIMessage(content="上一轮天气回答"),
            ],
            tool_messages=[AIMessage(content="", tool_calls=[{
                "name": "graph_search", "args": {}, "id": "old-call", "type": "tool_call",
            }])],
            tool_tracking=ToolTrackingSubState(pending_step_id="old-step", pending_call_id="old-call"),
        )
        state.add_event("run_completed", {"answer": state.answer})

        result = _node_normalize_entry(state)

        assert result["thread_id"] == "u1:s1"
        assert result["accepted_task_analysis"] is None
        assert result["answer"] is None
        assert state.answer_completed is False
        assert state.control.pending_interaction is None
        assert "pending_confirmation" not in result
        assert state.execution_trace == []
        assert result["citations"] == []
        assert result["errors"] == []
        assert result["tool_messages"] == []
        assert result["tool_tracking"].pending_step_id == ""
        assert result["tool_tracking"].pending_call_id == ""
        assert result["messages"][0].content == "什么是DNS"
        assert [message.content for message in state.messages] == [
            "今天西安天气怎么样",
            "上一轮天气回答",
        ]
        assert [event.type for event in result["events"]] == ["entry_started"]
        assert result["events"][0].run_id == "new-run"

# ---------------------------------------------------------------------------
# Event conversion helpers
# ---------------------------------------------------------------------------

class TestEventConversions:
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
            postgres_url=POSTGRES_URL,
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
        from personal_agent.memory.graphiti.store import GraphitiStore
        from personal_agent.orchestration.runtime import AgentRuntime

        store = PostgresMemoryStore(stub_settings.data_dir, stub_settings.postgres_url)
        runtime = AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
        )
        runtime._task_analyzer._analyze_with_model = stub_task_analysis
        return runtime

    def test_graph_builds_and_compiles(self, runtime):
        from personal_agent.orchestration.orchestration_graph import (
            build_action_execution_graph,
            build_executive_graph,
            build_react_graph,
        )

        graph = runtime._entry._get_orch_graph()
        assert graph is not None
        # Should be compiled with a checkpointer
        assert graph.checkpointer is not None
        assert "entry_graph" in graph.get_graph().nodes
        assert "executive_graph" in graph.get_graph().nodes
        assert "analyze_task" not in graph.get_graph().nodes

        step_graph = build_action_execution_graph(runtime.graph_contexts)
        assert "action_tool_node" in step_graph.get_graph().nodes
        assert "react_action" in step_graph.get_graph().nodes
        executive_graph = build_executive_graph(runtime.graph_contexts)
        assert "decide" in executive_graph.get_graph().nodes
        assert "verify_completion" in executive_graph.get_graph().nodes
        react_graph = build_react_graph(runtime.graph_contexts)
        assert "react_tool_node" in react_graph.get_graph().nodes

    def test_analyze_task_does_not_use_ask_history_when_thread_is_empty(self, runtime, monkeypatch):
        captured_messages: list[list[dict[str, str]]] = []

        def analyze(entry_input, conversation_messages=None):
            captured_messages.append(conversation_messages or [])
            return TaskAnalysisResult(route="respond", user_visible_message="回答。")

        monkeypatch.setattr(runtime._task_analyzer, "analyze", analyze)

        runtime.execute_entry(
            EntryInput(text="继续", user_id="test-user", session_id="persisted-context")
        )

        assert captured_messages == [[]]

    def test_model_unavailable_returns_control_status_without_business_message(self, runtime):
        entry = EntryInput(
            text="你好",
            user_id="test-user",
            session_id="orch-test",
        )
        result = runtime.execute_entry(entry)
        assert result.result_contracts == ["response"]
        assert result.reply_text
        latest = runtime._entry._get_orch_graph().get_state(
            {"configurable": {"thread_id": result.thread_id}}
        ).values
        contents = [message.content for message in latest["messages"]]
        assert contents == ["你好"]
        assert result.run_status in {"failed", "completed_degraded"}
        assert "model_unavailable" in result.reply_text

    def test_ask_through_orch_graph(self, runtime):
        """An ask intent should flow through the graph."""
        entry = EntryInput(
            text="什么是服务降级？",
            user_id="test-user",
            session_id="orch-test-ask",
        )
        result = runtime.execute_entry(entry)
        assert result.result_contracts == ["response"]
        assert result.reply_text
        latest = runtime._entry._get_orch_graph().get_state(
            {"configurable": {"thread_id": result.thread_id}}
        ).values
        assert "什么是服务降级？" in [message.content for message in latest["messages"]]

    def test_mixed_visible_branches_accumulate_checkpoint_messages(self, runtime):
        first = runtime.execute_entry(
            EntryInput(text="你好", user_id="test-user", session_id="mixed-dialogue")
        )
        second = runtime.execute_entry(
            EntryInput(
                text="什么是服务降级？",
                user_id="test-user",
                session_id="mixed-dialogue",
            )
        )

        assert first.thread_id == second.thread_id
        latest = runtime._entry._get_orch_graph().get_state(
            {"configurable": {"thread_id": second.thread_id}}
        ).values
        contents = [message.content for message in latest["messages"]]
        assert "你好" in contents
        assert "什么是服务降级？" in contents

    def test_capture_without_executive_model_does_not_mutate(self, runtime):
        entry = EntryInput(
            text="记一下：服务降级是在系统压力过大时主动关闭非核心能力。",
            user_id="test-user",
            session_id="orch-test-cap",
        )
        result = runtime.execute_entry(entry)
        assert result.result_contracts[-1] == "external_state"
        assert result.reply_text
        assert result.run_status == "completed_degraded"
        assert not any(event["type"] == "tool_result" for event in result.events)
        assert not runtime.store.list_notes("test-user")

    def test_summary_route_does_not_bypass_executive_model(self, runtime, monkeypatch):
        loaded: list[tuple[str, int]] = []

        def load_messages(entry_input, limit):
            loaded.append((entry_input.session_id, limit))
            return [{"role": "user", "content": "项目今天完成发布。"}]

        runtime.set_thread_message_loader(load_messages)
        monkeypatch.setattr(
            runtime,
            "summarize_chat",
            lambda messages, _user_id: f"总结结果：{messages}",
        )
        monkeypatch.setattr(
            runtime._task_analyzer,
            "analyze",
            lambda *_args, **_kwargs: TaskAnalysisResult(
                route="summarize_thread",
                user_visible_message="总结群聊内容。",
            ),
        )

        result = runtime.execute_entry(
            EntryInput(
                text="帮我总结一下今天群聊讨论了什么",
                user_id="test-user",
                session_id="feishu-summary",
                source_platform="feishu",
                metadata={"chat_id": "chat-1"},
            )
        )

        assert result.result_contracts == ["response"]
        assert loaded == []
        assert "项目今天完成发布" not in result.reply_text

    def test_non_summary_entry_does_not_load_platform_thread_context(self, runtime):
        loaded: list[str] = []
        runtime.set_thread_message_loader(
            lambda entry_input, _limit: loaded.append(entry_input.session_id) or []
        )

        runtime.execute_entry(
            EntryInput(
                text="你好",
                user_id="test-user",
                session_id="feishu-greeting",
                source_platform="feishu",
                metadata={"chat_id": "chat-1"},
            )
        )

        assert loaded == []

    def test_task_analyzer_requested_clarify_then_resume(self, runtime):
        """Task analysis requests clarification before compiling a GoalGraph."""
        entry = EntryInput(
            text="帮我",
            user_id="test-user",
            session_id="orch-test-clarify",
        )
        result = runtime.execute_entry(entry)
        assert result.run_status == "waiting"
        assert result.pending_confirmation
        assert result.pending_confirmation["kind"] == "clarification_required"
        event_types = [event["type"] for event in result.events]
        assert event_types.index("task_analyzed") < event_types.index("clarification_required")

        resumed = runtime.resume_entry(
            run_id=result.run_id or "",
            thread_id=result.thread_id or "",
            decision="clarify",
            user_id="test-user",
            text="记一下：澄清应由路由决策触发。",
            option_id="capture",
        )
        assert resumed.run_status == "completed_degraded"
        assert resumed.result_contracts == ["external_state"]
        assert resumed.reply_text
        assert not runtime.store.list_notes("test-user")

    def test_short_question_does_not_trigger_clarify(self, runtime):
        """Short but meaningful questions should become executable goals."""
        entry = EntryInput(
            text="你是谁",
            user_id="test-user",
            session_id="orch-test-short-question",
        )
        result = runtime.execute_entry(entry)
        assert result.run_status == "failed"
        assert result.pending_confirmation is None
        assert result.result_contracts == ["response"]
        assert result.reply_text
        snapshot = runtime.get_run_snapshot(result.run_id or "")
        assert snapshot is not None
        assert snapshot.status == AgentRunStatus.failed
        assert snapshot.last_event is not None
        assert snapshot.last_event.type == "run_failed"

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

    def test_run_history_lists_langgraph_checkpoints(self, runtime):
        entry = EntryInput(text="你好", user_id="test-user", session_id="history-get")
        result = runtime.execute_entry(entry)

        history = runtime.list_run_history(result.run_id or "", limit=20)

        assert history
        assert all(item["run_id"] == result.run_id for item in history)
        assert all(item["thread_id"] == result.thread_id for item in history)
        assert any(item["checkpoint_id"] for item in history)
        assert all(item["checkpoint_schema_version"] == "agentic_control_v2" for item in history)
        assert all("invocation_batch" in item for item in history)
        assert all("step_count" in item["invocation_batch"] for item in history)

    def test_replay_rejects_legacy_update_fields(self, runtime):
        entry = EntryInput(text="你好", user_id="test-user", session_id="replay-legacy-update")
        result = runtime.execute_entry(entry)
        history = runtime.list_run_history(result.run_id or "", limit=20)
        checkpoint_id = next(item["checkpoint_id"] for item in history if item["checkpoint_id"])

        with pytest.raises(ValueError, match="legacy checkpoint fields"):
            runtime.replay_from_checkpoint(
                thread_id=result.thread_id or "",
                checkpoint_id=checkpoint_id,
                updates={"plan": {"steps": []}},
            )

    def test_legacy_plan_checkpoint_schema_is_not_replayable(self):
        from personal_agent.orchestration.entry_orchestrator import _ensure_checkpoint_schema_supported

        with pytest.raises(ValueError, match="legacy plan schema"):
            _ensure_checkpoint_schema_supported({"plan": {"steps": []}}, "old-ckpt")

        with pytest.raises(ValueError, match="does not contain invocation_batch"):
            _ensure_checkpoint_schema_supported({"run_id": "abc"}, "partial-ckpt")

    def test_persisted_snapshots_are_visible_before_new_execution(self, temp_dir):
        from personal_agent.orchestration.runtime import AgentRuntime
        from personal_agent.memory.graphiti.store import GraphitiStore
        from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore

        settings = Settings(
            data_dir=temp_dir,
            postgres_url=POSTGRES_URL,
        )

        def create_runtime():
            return AgentRuntime(
                settings=settings,
                store=PostgresMemoryStore(settings.data_dir, settings.postgres_url),
                graph_store=GraphitiStore(settings),
            )

        original = create_runtime()
        result = original.execute_entry(
            EntryInput(text="你好", user_id="test-user", session_id="persisted-run")
        )
        original._entry._get_orch_graph().checkpointer.conn.close()

        restarted = create_runtime()
        try:
            assert restarted._entry._orch_graph is None
            listed = restarted.list_run_snapshots(user_id="test-user", limit=10)
            restored = restarted.get_run_snapshot(result.run_id or "")

            assert any(item.run_id == result.run_id for item in listed)
            assert restored is not None
            assert restored.thread_id == "test-user:persisted-run"
        finally:
            restarted._entry._get_orch_graph().checkpointer.conn.close()

    def test_cached_orchestration_graph_rebuilds_when_checkpointer_connection_closed(self, temp_dir):
        from personal_agent.orchestration.runtime import AgentRuntime
        from personal_agent.memory.graphiti.store import GraphitiStore
        from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore

        settings = Settings(
            data_dir=temp_dir,
            postgres_url=POSTGRES_URL,
        )
        runtime = AgentRuntime(
            settings=settings,
            store=PostgresMemoryStore(settings.data_dir, settings.postgres_url),
            graph_store=GraphitiStore(settings),
        )

        first_graph = runtime._entry._get_orch_graph()
        first_graph.checkpointer.conn.close()
        rebuilt_graph = runtime._entry._get_orch_graph()

        try:
            assert rebuilt_graph is not first_graph
            assert rebuilt_graph.checkpointer.conn.closed is False
        finally:
            rebuilt_graph.checkpointer.conn.close()

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
        latest = runtime._entry._get_orch_graph().get_state(
            {"configurable": {"thread_id": "test-user:shared-thread"}}
        ).values
        contents = [message.content for message in latest["messages"]]
        assert contents == ["你好", "你是谁"]

    def test_new_run_input_checkpoint_does_not_retain_previous_answer(self, runtime):
        runtime.execute_entry(
            EntryInput(text="你好", user_id="test-user", session_id="clean-input-checkpoint")
        )
        second = runtime.execute_entry(
            EntryInput(text="谢谢", user_id="test-user", session_id="clean-input-checkpoint")
        )

        config = {"configurable": {"thread_id": second.thread_id}}
        second_run_states = []
        for checkpoint in runtime._entry._get_orch_graph().checkpointer.list(config):
            values = checkpoint.checkpoint.get("channel_values", {})
            if values.get("run_id") == second.run_id:
                second_run_states.append(RunCheckpoint.model_validate(values))

        assert second_run_states
        assert any(state.answer is None for state in second_run_states)
        assert second.reply_text

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
        assert relevant[0].result_contracts == ["response"]


# ---------------------------------------------------------------------------
# Phase 3: HITL interrupt / resume
# ---------------------------------------------------------------------------

class TestPhase3RoutingFunctions:
    """Unit tests for the Phase 3 conditional edge functions."""

    def test_after_invocation_batch_routes_to_confirm_step(self):
        from personal_agent.orchestration.orchestration_graph import _after_invocation_batch

        state = RunCheckpoint(
            invocation_batch=InvocationBatchState(
                invocations=[
                    {"step_id": "s1", "action_type": "tool_call", "attempt": {"status": "awaiting_confirmation"}},
                ],
                current_step_index=0,
            ),
        )
        assert _after_invocation_batch(state) == "confirm_step"

    def test_after_invocation_batch_routes_to_handle_failure(self):
        from personal_agent.orchestration.orchestration_graph import _after_invocation_batch

        state = RunCheckpoint(
            invocation_batch=InvocationBatchState(
                invocations=[
                    {"step_id": "s1", "action_type": "tool_call", "attempt": {"status": "failed"}},
                ],
                current_step_index=0,
            ),
        )
        assert _after_invocation_batch(state) == "handle_failure"

    def test_after_invocation_batch_routes_to_handle_success(self):
        from personal_agent.orchestration.orchestration_graph import _after_invocation_batch

        state = RunCheckpoint(
            invocation_batch=InvocationBatchState(
                invocations=[
                    {"step_id": "s1", "action_type": "retrieve", "attempt": {"status": "completed"}},
                ],
                current_step_index=0,
            ),
        )
        assert _after_invocation_batch(state) == "handle_success"

    def test_after_confirm_step_confirmed(self):
        from personal_agent.orchestration.orchestration_graph import _after_confirm_step

        state = RunCheckpoint(control=ControlTurnState(interaction_decision="confirmed"))
        assert _after_confirm_step(state) == "tool_node"

    def test_after_confirm_step_rejected(self):
        from personal_agent.orchestration.orchestration_graph import _after_confirm_step

        state = RunCheckpoint(control=ControlTurnState(interaction_decision="rejected"))
        assert _after_confirm_step(state) == "handle_failure"

    def test_after_confirm_step_none_defaults_to_failure(self):
        from personal_agent.orchestration.orchestration_graph import _after_confirm_step

        state = RunCheckpoint()
        assert _after_confirm_step(state) == "handle_failure"

    def test_resolved_note_id_is_injected_through_verify_dependency(self):
        from personal_agent.orchestration.orchestration_nodes._graph_helpers import (
            _inject_note_id_into_steps,
        )

        steps = [
            ExecutableInvocation(step_id="del-1", action_type="resolve", attempt=InvocationAttemptState(status="completed")),
            ExecutableInvocation(
                step_id="del-2",
                action_type="verify",
                depends_on=["del-1"],
                attempt=InvocationAttemptState(status="completed"),
            ),
            ExecutableInvocation(
                step_id="del-3",
                action_type="tool_call",
                tool_name="delete_note",
                depends_on=["del-2"],
                attempt=InvocationAttemptState(status="planned"),
            ),
        ]

        _inject_note_id_into_steps("del-1", "note-dns", "alice", steps)

        assert steps[2].tool_input["note_id"] == "note-dns"
        assert steps[2].tool_input["user_id"] == "alice"


class TestPhase3ExecuteExecutionStep:
    """Tests for _node_execute_step with pending_confirmation handling."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            postgres_url=POSTGRES_URL,
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
        from personal_agent.memory.graphiti.store import GraphitiStore
        from personal_agent.orchestration.runtime import AgentRuntime

        store = PostgresMemoryStore(stub_settings.data_dir, stub_settings.postgres_url)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
        )

    def test_tool_result_without_execution_grant_is_rejected(self, runtime):
        from langchain_core.messages import ToolMessage
        from personal_agent.orchestration.orchestration_graph import _node_consume_step_tool_result

        state = RunCheckpoint(
            run_id="r1",
            user_id="u1",
            invocation_batch=InvocationBatchState(
                invocations=[
                    {
                        "step_id": "s1",
                        "action_type": "tool_call",
                        "tool_name": "capture_text",
                        "attempt": {"status": "running"},
                    },
                ],
                current_step_index=0,
            ),
            entry_text="test",
            tool_tracking=ToolTrackingSubState(
                active_context="invocation_batch",
                pending_step_id="s1",
                pending_call_id="r1:s1:0",
                pending_tool_name="capture_text",
                pending_tool_input={"text": "待保存正文", "user_id": "u1"},
            ),
            tool_messages=[
                ToolMessage(
                    content="待确认",
                    tool_call_id="r1:s1:0",
                    artifact={
                        "ok": True,
                        "data": {
                            "pending_confirmation": True,
                            "note_id": "n1",
                            "title": "测试笔记",
                            "summary": "删除测试",
                            "description": "删除说明",
                        },
                        "error": None,
                        "evidence": [],
                    },
                ),
            ],
        )
        result = _node_consume_step_tool_result(state, deps=runtime.graph_contexts.steps)
        assert result["invocation_batch"].invocations[0].status == "failed"
        assert "no bound ExecutionGrant" in state.errors[-1]
        assert not any(event.type == "confirmation_required" for event in state.events)

    def test_node_completes_normally_when_no_pending_confirmation(self, runtime):
        """Without pending_confirmation, the step should complete normally."""
        from personal_agent.orchestration.orchestration_graph import _node_execute_step

        state = RunCheckpoint(
            run_id="r1",
            user_id="u1",
            control=ControlTurnState(phase="preparing_dispatch"),
            invocation_batch=InvocationBatchState(
                invocations=[
                    {
                        "step_id": "s1",
                        "action_type": "retrieve",
                        "description": "检索",
                        "attempt": {"status": "running"},
                    },
                ],
                current_step_index=0,
            ),
            entry_text="test",
        )

        result = _node_execute_step(state, deps=runtime.graph_contexts.steps)
        assert result["invocation_batch"].invocations[0].status == "completed"

    def test_failure_records_step_retry_budget_and_reason(self, runtime):
        from personal_agent.orchestration.orchestration_graph import _node_execute_step

        state = RunCheckpoint(
            control=ControlTurnState(phase="preparing_dispatch"),
            invocation_batch=InvocationBatchState(
                invocations=[
                    ExecutableInvocation(
                        step_id="bad-1",
                        action_type="unsupported",
                        attempt=InvocationAttemptState(status="running", max_retries=1),
                        on_failure="retry",
                    ),
                ],
                current_step_index=0,
            ),
        )

        _node_execute_step(state, deps=runtime.graph_contexts.steps)

        step = state.invocation_batch.invocations[0]
        assert step.status == "failed"
        assert step.retry_count == 1
        assert step.max_retries == 1
        assert step.failure_reason
        assert step.recoverable is False

    def test_resolve_uses_llm_to_select_local_delete_candidate(self, runtime, monkeypatch):
        from personal_agent.orchestration.orchestration_nodes._steps import _execute_resolve_step
        from tests.note_factory import make_note

        runtime.store.add_note(
            make_note(
                id="note-dns",
                user_id="u1",
                title="DNS 基础概念",
                content="DNS 将域名解析为 IP 地址。",
                summary="DNS 说明",
            )
        )
        monkeypatch.setattr(
            "personal_agent.orchestration.orchestration_nodes._helpers._structured_llm_respond",
            lambda *_args, **_kwargs: (
                '{"thought":"匹配 DNS 主题","done":true,'
                '"result":{"note_id":"note-dns"}}'
            ),
        )
        state = RunCheckpoint(user_id="u1", entry_text="删除关于DNS的知识")

        result = _execute_resolve_step(
            ExecutableInvocation(
                step_id="resolve-1",
                action_type="resolve",
                llm_decision_node="delete_target_resolve",
            ),
            state,
            runtime.graph_contexts.steps,
        )

        assert result["note_id"] == "note-dns"
        assert result["source"] == "llm_candidate_selection"

    def test_unresolved_delete_target_fails_before_tool_call(self, runtime, monkeypatch):
        from personal_agent.orchestration.orchestration_nodes._steps import _node_execute_step
        from tests.note_factory import make_note

        runtime.store.add_note(
            make_note(
                id="note-other",
                user_id="u1",
                title="其他主题",
                content="与请求无关。",
                summary="其他知识",
            )
        )
        monkeypatch.setattr(
            "personal_agent.orchestration.orchestration_nodes._helpers._structured_llm_respond",
            lambda *_args, **_kwargs: (
                '{"thought":"无明显匹配","done":true,'
                '"result":{"note_id":null}}'
            ),
        )
        state = RunCheckpoint(
            user_id="u1",
            entry_text="删除关于DNS的知识",
            control=ControlTurnState(phase="preparing_dispatch"),
            invocation_batch=InvocationBatchState(
                invocations=[
                    ExecutableInvocation(
                        step_id="resolve-1",
                        action_type="resolve",
                        attempt=InvocationAttemptState(status="running"),
                        on_failure="skip",
                    ),
                    ExecutableInvocation(
                        step_id="delete-1",
                        action_type="tool_call",
                        tool_name="delete_note",
                        depends_on=["resolve-1"],
                    ),
                ],
                current_step_index=0,
            ),
        )
        deps = runtime.graph_contexts.steps

        _node_execute_step(state, deps=deps)

        assert state.invocation_batch.invocations[0].status == "failed"
        assert state.invocation_batch.invocations[1].status == "planned"
        assert not state.tool_results


class TestPhase3InterruptResumeIntegration:
    """Integration tests for LangGraph interrupt result handling and resume."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            postgres_url=POSTGRES_URL,
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
        from personal_agent.memory.graphiti.store import GraphitiStore
        from personal_agent.orchestration.runtime import AgentRuntime

        store = PostgresMemoryStore(stub_settings.data_dir, stub_settings.postgres_url)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
        )

    def test_execute_entry_returns_run_id_and_status(self, runtime):
        """After a normal execution, EntryResult should include run_id and run_status."""
        runtime._task_analyzer._analyze_with_model = stub_task_analysis
        entry = EntryInput(
            text="你好",
            user_id="u1",
            session_id="phase3-run-status",
        )
        result = runtime.execute_entry(entry)
        assert result.run_id is not None
        assert result.run_status == "failed"
        assert result.reply_text

    def test_resume_entry_rejects_unknown_run(self, runtime):
        """Resume is a control-plane operation and cannot create a run."""
        runtime._entry._get_orch_graph()
        with pytest.raises(RunStateError, match="unknown run"):
            runtime.resume_entry(
                run_id="fresh-run",
                thread_id="u1:default:fresh-run",
                decision="confirm",
                user_id="u1",
            )

    def test_confirmation_decision_field_roundtrip(self):
        """The control turn's interaction decision should survive serialization."""
        state = RunCheckpoint(
            control=ControlTurnState(
                interaction_decision="confirmed",
                pending_interaction={
                    "kind": "confirmation_required", "action_type": "test", "step_id": "s1",
                    "authorization_digest": "authorization-digest",
                },
            ),
        )
        data = state.model_dump(mode="json")
        restored = RunCheckpoint.model_validate(data)
        assert restored.control.interaction_decision == "confirmed"

    def test_to_run_snapshot_blocked_approval(self):
        """When pending_confirmation is set, _infer_status returns blocked_approval."""
        state = RunCheckpoint(
            accepted_task_analysis=TaskAnalysis(route="delete_knowledge"),
            control=ControlTurnState(pending_interaction={
                "kind": "confirmation_required", "step_id": "s1", "action_type": "delete_note",
                "authorization_digest": "authorization-digest",
            }),
        )
        snap = state.to_run_snapshot()
        assert snap.status == AgentRunStatus.blocked_approval

    def test_to_run_snapshot_keeps_resolved_confirmation_decision(self):
        state = RunCheckpoint(
            accepted_task_analysis=TaskAnalysis(route="delete_knowledge"),
            control=ControlTurnState(interaction_decision="confirmed"),
            answer="已删除。",
        )
        state.add_event("answer_completed", {"answer": "已删除。"})

        snap = state.to_run_snapshot()

        assert snap.status == AgentRunStatus.completed
        assert snap.confirmation_decision == "confirmed"

    def test_interrupt_payload_is_read_from_invoke_result(self):
        """LangGraph exposes interrupt payloads through the invoke result."""
        from personal_agent.orchestration.entry_orchestrator import _interrupt_payload_from_result

        class _Interrupt:
            value = {"step_id": "s1", "message": "确认？"}

        payload = _interrupt_payload_from_result({"__interrupt__": [_Interrupt()]})

        assert payload == {"step_id": "s1", "message": "确认？"}


# ---------------------------------------------------------------------------
# Phase 4: ReAct nodes in the main graph
# ---------------------------------------------------------------------------


class TestPhase4ReActHelpers:
    """Unit tests for ReAct helper functions."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            postgres_url=POSTGRES_URL,
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
        from personal_agent.memory.graphiti.store import GraphitiStore
        from personal_agent.orchestration.runtime import AgentRuntime

        store = PostgresMemoryStore(stub_settings.data_dir, stub_settings.postgres_url)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
        )

    def test_react_consumes_pre_resolved_tool_scope(self, runtime):
        from personal_agent.orchestration.orchestration_nodes._react import _node_react_init

        state = RunCheckpoint(
            invocation_batch=InvocationBatchState(invocations=[ExecutableInvocation(
                step_id="s1",
                action_type="retrieve",
                allowed_tools=["graph_search"],
                execution_mode="react",
            )]),
        )
        _node_react_init(state, deps=runtime.graph_contexts.react)
        assert state.react.allowed_tools == ["graph_search"]

    def test_is_react_tool_blocked_high_risk(self, runtime):
        from personal_agent.orchestration.orchestration_nodes._graph_helpers import _is_react_tool_blocked

        assert _is_react_tool_blocked("delete_note", runtime.graph_contexts.react)
        assert _is_react_tool_blocked("capture_text", runtime.graph_contexts.react)

    def test_is_react_tool_blocked_allows_safe_tools(self, runtime):
        from personal_agent.orchestration.orchestration_nodes._graph_helpers import _is_react_tool_blocked

        assert not _is_react_tool_blocked("graph_search", runtime.graph_contexts.react)

    def test_format_react_tools(self, runtime):
        from personal_agent.orchestration.orchestration_nodes._helpers import _format_react_tools

        text = _format_react_tools({"graph_search"}, runtime.graph_contexts.react)
        assert "graph_search" in text

    def test_summarize_react_tool_result(self):
        from personal_agent.orchestration.orchestration_nodes._helpers import _summarize_react_tool_result

        assert "hello" in _summarize_react_tool_result({"answer": "hello world"})
        assert "无返回数据" in _summarize_react_tool_result(None)
        assert "42" in _summarize_react_tool_result(42)


class TestPhase4ReActNodes:
    """Unit tests for ReAct main-graph node functions."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            postgres_url=POSTGRES_URL,
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
        from personal_agent.memory.graphiti.store import GraphitiStore
        from personal_agent.orchestration.runtime import AgentRuntime

        store = PostgresMemoryStore(stub_settings.data_dir, stub_settings.postgres_url)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
        )

    def test_react_init_seeds_state(self, runtime):
        from personal_agent.orchestration.orchestration_graph import _node_react_init

        state = RunCheckpoint(
            run_id="r1",
            invocation_batch=InvocationBatchState(
                invocations=[
                    {
                        "step_id": "ask-1",
                        "action_type": "retrieve",
                        "description": "检索知识库",
                        "execution_mode": "react",
                        "allowed_tools": ["graph_search"],
                        "max_iterations": 3,
                        "attempt": {"status": "running"},
                    },
                ],
                current_step_index=0,
            ),
        )
        result = _node_react_init(state, deps=runtime.graph_contexts.react)
        assert result["react"].step_id == "ask-1"
        assert result["react"].max_iterations == 3
        assert result["react"].allowed_tools == ["graph_search"]
        assert result["react"].iteration_index == 0
        assert result["react"].done is False
        assert not result["react"].result
        assert result["react"].status == "running"

    def test_should_continue_react_when_not_done(self):
        from personal_agent.orchestration.orchestration_graph import _should_continue_react

        state = RunCheckpoint(react=ReactSubState(done=False, iteration_index=0, max_iterations=3))
        assert _should_continue_react(state) == "iterate"

    def test_should_continue_react_when_done(self):
        from personal_agent.orchestration.orchestration_graph import _should_continue_react

        state = RunCheckpoint(react=ReactSubState(done=True, iteration_index=0, max_iterations=3))
        assert _should_continue_react(state) == "finalize"

    def test_should_continue_react_when_exhausted(self):
        from personal_agent.orchestration.orchestration_graph import _should_continue_react

        state = RunCheckpoint(react=ReactSubState(done=False, iteration_index=3, max_iterations=3))
        assert _should_continue_react(state) == "finalize"

    def test_react_finalize_writes_result_and_clears_state(self):
        from personal_agent.orchestration.orchestration_graph import _node_react_finalize

        state = RunCheckpoint(
            run_id="r1",
            react=ReactSubState(
                step_id="ask-1",
                result={"answer": "42", "react_iterations": 2},
                user_prompt="...",
                done=True,
                status="completed",
                stop_reason="llm_completed",
                iteration_index=2,
                max_iterations=3,
                allowed_tools=["graph_search"],
            ),
            invocation_batch=InvocationBatchState(
                invocations=[
                    {"step_id": "ask-1", "action_type": "retrieve", "attempt": {"status": "running"}},
                ],
                current_step_index=0,
            ),
        )
        result = _node_react_finalize(state)
        assert state.invocation_batch.results["ask-1"]["answer"] == "42"
        assert state.invocation_batch.results["ask-1"]["evidence_pack"]["evidence_sufficiency"] == "insufficient"
        assert state.invocation_batch.invocations[0].status == "completed"
        assert result["react"].step_id == ""
        assert result["react"].done is True
        assert result["react"].result == {"answer": "42", "react_iterations": 2}
        assert result["react"].status == "completed"
        assert result["react"].stop_reason == "llm_completed"

    def test_react_failed_outcome_is_a_failed_execution_step(self):
        from personal_agent.orchestration.orchestration_graph import (
            _after_react_graph,
            _node_react_finalize,
        )

        state = RunCheckpoint(
            react=ReactSubState(
                step_id="ask-1",
                result={"answer": "", "error": "LLM returned nothing"},
                done=True,
                status="failed",
                stop_reason="llm_unavailable",
            ),
            invocation_batch=InvocationBatchState(invocations=[
                ExecutableInvocation(
                    step_id="ask-1",
                    action_type="retrieve",
                    attempt=InvocationAttemptState(status="running", max_retries=1),
                    on_failure="retry",
                ),
            ]),
        )

        _node_react_finalize(state)

        assert state.invocation_batch.invocations[0].status == "failed"
        assert state.invocation_batch.invocations[0].failure_reason == "LLM returned nothing"
        assert state.invocation_batch.invocations[0].recoverable is False
        assert state.errors == ["[ask-1] LLM returned nothing"]
        assert _after_react_graph(state) == "action_done"


class TestPhase4ReActIterateNode:
    """Tests for _node_react_iterate with mocked LLM."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            postgres_url=POSTGRES_URL,
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
        from personal_agent.memory.graphiti.store import GraphitiStore
        from personal_agent.orchestration.runtime import AgentRuntime

        store = PostgresMemoryStore(stub_settings.data_dir, stub_settings.postgres_url)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
        )

    def test_react_iterate_done_sets_flag(self, runtime, monkeypatch):
        from personal_agent.orchestration.orchestration_graph import _node_react_iterate
        from personal_agent.orchestration.orchestration_nodes._helpers import _NativeReactOutcome

        state = RunCheckpoint(
            run_id="r1",
            react=ReactSubState(
                step_id="ask-1",
                iteration_index=0,
                max_iterations=3,
                allowed_tools=["graph_search"],
                user_prompt="搜索X相关的内容",
                done=False,
            ),
            invocation_batch=InvocationBatchState(
                invocations=[{"step_id": "ask-1", "attempt": {"status": "running"}}],
                current_step_index=0,
            ),
        )

        def _mock_native(prompt, deps, allowed):
            return _NativeReactOutcome(
                done=True,
                thought="已经找到答案",
                result={"answer": "X是一种技术"},
            )

        monkeypatch.setattr(
            "personal_agent.orchestration.orchestration_nodes._helpers._react_llm_native",
            _mock_native,
        )

        result = _node_react_iterate(state, deps=runtime.graph_contexts.react)
        assert result["react"].done is True
        assert result["react"].result["answer"] == "X是一种技术"
        assert len(result["react"].iterations) >= 1
        assert result["react"].iterations[-1]["done"] is True
        assert result["react"].status == "completed"

    def test_react_iterate_parse_failure_increments_index(self, runtime, monkeypatch):
        from personal_agent.orchestration.orchestration_graph import _node_react_iterate
        from personal_agent.orchestration.orchestration_nodes._helpers import _NativeReactOutcome

        state = RunCheckpoint(
            run_id="r1",
            react=ReactSubState(
                step_id="ask-1",
                iteration_index=0,
                max_iterations=3,
                allowed_tools=["graph_search"],
                user_prompt="搜索",
                done=False,
            ),
            invocation_batch=InvocationBatchState(
                invocations=[{"step_id": "ask-1", "attempt": {"status": "running"}}],
                current_step_index=0,
            ),
        )

        # 模型未返回 tool_calls（解析失败）
        monkeypatch.setattr(
            "personal_agent.orchestration.orchestration_nodes._helpers._react_llm_native",
            lambda prompt, deps, allowed: _NativeReactOutcome(parse_failed=True),
        )

        result = _node_react_iterate(state, deps=runtime.graph_contexts.react)
        # Parse failure: index increments, not done yet
        assert result["react"].iteration_index == 1
        assert result["react"].done is not True

    def test_react_iterate_parse_failure_exhausts(self, runtime, monkeypatch):
        from personal_agent.orchestration.orchestration_graph import _node_react_iterate
        from personal_agent.orchestration.orchestration_nodes._helpers import _NativeReactOutcome

        state = RunCheckpoint(
            run_id="r1",
            react=ReactSubState(
                step_id="ask-1",
                iteration_index=2,  # last iteration (0-based, max=3 → index 2 is the 3rd)
                max_iterations=3,
                allowed_tools=["graph_search"],
                user_prompt="搜索",
                done=False,
            ),
            invocation_batch=InvocationBatchState(
                invocations=[{"step_id": "ask-1", "attempt": {"status": "running"}}],
                current_step_index=0,
            ),
        )

        monkeypatch.setattr(
            "personal_agent.orchestration.orchestration_nodes._helpers._react_llm_native",
            lambda prompt, deps, allowed: _NativeReactOutcome(parse_failed=True),
        )

        result = _node_react_iterate(state, deps=runtime.graph_contexts.react)
        assert result["react"].done is True
        assert result["react"].status == "exhausted"
        assert result["react"].stop_reason == "parse_failures_exhausted"

    def test_react_iterate_blocked_tool(self, runtime, monkeypatch):
        from personal_agent.orchestration.orchestration_graph import _node_react_iterate
        from personal_agent.orchestration.orchestration_nodes._helpers import _NativeReactOutcome

        state = RunCheckpoint(
            run_id="r1",
            react=ReactSubState(
                step_id="ask-1",
                iteration_index=0,
                max_iterations=3,
                allowed_tools=["graph_search", "delete_note"],
                user_prompt="删除笔记",
                done=False,
            ),
            invocation_batch=InvocationBatchState(
                invocations=[{"step_id": "ask-1", "attempt": {"status": "running"}}],
                current_step_index=0,
            ),
        )

        monkeypatch.setattr(
            "personal_agent.orchestration.orchestration_nodes._helpers._react_llm_native",
            lambda prompt, deps, allowed: _NativeReactOutcome(
                thought="需要删除",
                tool_name="delete_note",
                tool_input={"note_id": "n1"},
                native_call_id="c-del",
            ),
        )

        result = _node_react_iterate(state, deps=runtime.graph_contexts.react)
        # Tool is blocked — observation should indicate error
        assert len(result["react"].iterations) >= 1
        obs = result["react"].iterations[-1].get("observation", "")
        assert "高风险" in obs or "不允许" in obs
        assert result["react"].iteration_index == 1

    def test_react_iterate_llm_returns_none(self, runtime, monkeypatch):
        from personal_agent.orchestration.orchestration_graph import _node_react_iterate

        state = RunCheckpoint(
            run_id="r1",
            react=ReactSubState(
                step_id="ask-1",
                iteration_index=0,
                max_iterations=3,
                allowed_tools=["graph_search"],
                user_prompt="搜索",
                done=False,
            ),
            invocation_batch=InvocationBatchState(
                invocations=[{"step_id": "ask-1", "attempt": {"status": "running"}}],
                current_step_index=0,
            ),
        )

        monkeypatch.setattr(
            "personal_agent.orchestration.orchestration_nodes._helpers._react_llm_native",
            lambda prompt, deps, allowed: None,
        )

        result = _node_react_iterate(state, deps=runtime.graph_contexts.react)
        assert result["react"].done is True
        assert "react_iterations" in result["react"].result
        assert result["react"].status == "failed"
        assert result["react"].stop_reason == "llm_unavailable"


class TestPhase4ReActMainGraphIntegration:
    """Integration tests for ReAct execution through the main graph ToolGateway."""

    @pytest.fixture
    def stub_settings(self, temp_dir):
        return Settings(
            data_dir=temp_dir,
            postgres_url=POSTGRES_URL,
        )

    @pytest.fixture
    def runtime(self, stub_settings):
        from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
        from personal_agent.memory.graphiti.store import GraphitiStore
        from personal_agent.orchestration.runtime import AgentRuntime

        store = PostgresMemoryStore(stub_settings.data_dir, stub_settings.postgres_url)
        return AgentRuntime(
            settings=stub_settings,
            store=store,
            graph_store=GraphitiStore(stub_settings),
        )

    def test_react_consumes_shared_tool_node_observation(self, runtime):
        from langchain_core.messages import ToolMessage
        from personal_agent.orchestration.orchestration_graph import _node_consume_react_tool_result

        state = RunCheckpoint(
            react=ReactSubState(
                step_id="ask-1",
                max_iterations=2,
                pending_thought="检索",
                pending_tool="graph_search",
                pending_input={"query": "X"},
            ),
            tool_tracking=ToolTrackingSubState(
                active_context="react",
                pending_step_id="ask-1",
                pending_call_id="r1:react:ask-1:0:0",
                pending_tool_name="graph_search",
                pending_tool_input={"query": "X"},
                pending_react_iteration=0,
            ),
            tool_messages=[ToolMessage(
                content="找到结果",
                tool_call_id="r1:react:ask-1:0:0",
                artifact={"ok": True, "data": {"answer": "X是..."}, "error": None, "evidence": []},
            )],
        )

        result = _node_consume_react_tool_result(state, deps=runtime.graph_contexts.react)

        assert result["tool_tracking"].active_context is None
        assert result["tool_tracking"].pending_call_id == ""
        assert state.react.iteration_index == 1
        assert "X是" in state.react.iterations[0]["observation"]
        tool_result_event = next(event for event in state.events if event.type == "tool_result")
        assert tool_result_event.payload["context"] == "react"
        assert tool_result_event.payload["invocation"]["execution_mode"] == "react"
        assert tool_result_event.payload["invocation"]["permission_scope"] == "memory:read"

    def test_after_invocation_batch_routes_to_react_step(self):
        from personal_agent.orchestration.orchestration_graph import _after_invocation_batch

        state = RunCheckpoint(
            invocation_batch=InvocationBatchState(
                invocations=[
                    {
                        "step_id": "ask-1",
                        "execution_mode": "react",
                        "attempt": {"status": "running"},
                    },
                ],
                current_step_index=0,
            ),
        )
        assert _after_invocation_batch(state) == "react_step"

    def test_react_state_serialization_roundtrip(self):
        """Verify the new ReAct fields survive JSON serialization."""
        state = RunCheckpoint(
            react=ReactSubState(
                step_id="ask-1",
                iteration_index=2,
                max_iterations=3,
                allowed_tools=["graph_search"],
                user_prompt="...",
                done=True,
                result={"answer": "42"},
                status="completed",
                stop_reason="llm_completed",
            ),
        )
        data = state.model_dump(mode="json")
        restored = RunCheckpoint.model_validate(data)
        assert restored.react.step_id == "ask-1"
        assert restored.react.iteration_index == 2
        assert restored.react.max_iterations == 3
        assert restored.react.allowed_tools == ["graph_search"]
        assert restored.react.done is True
        assert restored.react.result == {"answer": "42"}
        assert restored.react.status == "completed"
        assert restored.react.stop_reason == "llm_completed"


# ============================================================================
# Phase 5: Entry unification — event helpers, EntryResult.events, SSE conversion
# ============================================================================


class TestPhase5EventHelpers:
    """Unit tests for execution_trace_from_events and events_to_sse_tuples."""

    def test_execution_trace_from_step_started_events(self):
        from personal_agent.orchestration.orchestration_models import (
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
        from personal_agent.orchestration.orchestration_models import (
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
        from personal_agent.orchestration.orchestration_models import execution_trace_from_events

        assert execution_trace_from_events([]) == []

    def test_events_to_sse_tuples_maps_types(self):
        from personal_agent.orchestration.orchestration_models import (
            AgentEvent,
            events_to_sse_tuples,
        )

        events = [
            AgentEvent(type="goal_graph_compiled", payload={"goal_count": 1}),
            AgentEvent(type="step_started", payload={"description": "测试"}),
            AgentEvent(type="run_completed", payload={"answer": "ok"}),
        ]
        tuples = events_to_sse_tuples(events)
        assert len(tuples) == 3
        assert tuples[0][0] == "goal_graph_compiled"
        assert tuples[1][0] == "step_started"
        assert tuples[2][0] == "done"
        # Each payload gets _event_id and _event_type metadata
        for _, payload in tuples:
            assert "_event_id" in payload
            assert "_event_type" in payload

    def test_events_to_sse_tuples_empty(self):
        from personal_agent.orchestration.orchestration_models import events_to_sse_tuples

        assert events_to_sse_tuples([]) == []


pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")
