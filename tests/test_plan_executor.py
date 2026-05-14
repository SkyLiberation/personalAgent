from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from personal_agent.agent.plan_executor import (
    ExecutionProgress,
    PlanExecutor,
    _topological_sort,
)
from personal_agent.agent.planner import PlanStep
from personal_agent.core.models import AgentState


class TestTopologicalSort:
    def test_empty_list(self):
        assert _topological_sort([]) == []

    def test_single_step(self):
        steps = [PlanStep(step_id="s1", action_type="retrieve", description="检索")]
        result = _topological_sort(steps)
        assert [s.step_id for s in result] == ["s1"]

    def test_linear_chain_preserves_order(self):
        steps = [
            PlanStep(step_id="s3", action_type="verify", description="校验",
                     depends_on=["s2"]),
            PlanStep(step_id="s2", action_type="compose", description="生成",
                     depends_on=["s1"]),
            PlanStep(step_id="s1", action_type="retrieve", description="检索"),
        ]
        result = _topological_sort(steps)
        assert [s.step_id for s in result] == ["s1", "s2", "s3"]

    def test_independent_steps_any_order(self):
        steps = [
            PlanStep(step_id="a", action_type="retrieve", description="检索A"),
            PlanStep(step_id="b", action_type="retrieve", description="检索B"),
        ]
        result = _topological_sort(steps)
        assert {s.step_id for s in result} == {"a", "b"}


class TestExecutionProgress:
    def test_initial_state(self):
        p = ExecutionProgress(total=5)
        assert p.total == 5
        assert p.completed == 0
        assert p.failed == 0
        assert p.skipped == 0
        assert p.running_count == 5

    def test_after_completions(self):
        p = ExecutionProgress(total=5)
        p.completed = 3
        p.failed = 1
        p.skipped = 1
        assert p.running_count == 0


class TestPlanExecutorStepLifecycle:
    @pytest.fixture
    def runtime(self, settings):
        from unittest.mock import MagicMock

        from personal_agent.core.config import Settings

        rt = MagicMock()
        rt.settings = Settings(
            openai_api_key="sk-test", openai_base_url="https://api.test/v1",
            openai_model="gpt-test", openai_small_model="gpt-test-small",
        )
        rt.graph_store = MagicMock()
        rt.execute_ask = MagicMock(return_value=MagicMock(answer="test answer"))
        rt.execute_capture = MagicMock()
        return rt

    @pytest.fixture
    def memory(self):
        from unittest.mock import MagicMock

        mem = MagicMock()
        mem.working = MagicMock()
        mem.working.add_step = MagicMock()
        return mem

    @pytest.fixture
    def state(self):
        return AgentState(mode="entry", user_id="test-user")

    @pytest.fixture
    def executor(self, runtime, memory):
        return PlanExecutor(runtime, memory)

    def test_execute_empty_steps(self, executor, state):
        result = executor.execute([], state)
        assert result is state
        assert state.answer is None

    def test_step_status_transitions_to_completed(self, executor, runtime, memory, state):
        """Compose step completes and status goes planned→running→completed."""
        runtime.graph_store.ask.return_value = type("R", (), {
            "enabled": True, "answer": "graph answer",
            "entity_names": [], "relation_facts": [], "related_episode_uuids": [],
        })()
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     tool_name="graph_search", tool_input={"question": "test"}),
        ]
        result = executor.execute(steps, state)
        assert steps[0].status == "completed"

    def test_step_failed_with_skip(self, executor, runtime, memory, state):
        """Failed step with on_failure=skip does not abort."""
        runtime.graph_store.ask.side_effect = Exception("graph error")
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     on_failure="skip"),
        ]
        result = executor.execute(steps, state)
        assert steps[0].status == "failed"
        assert "失败" in result.answer

    def test_step_failed_with_abort_stops_execution(self, executor, runtime, memory, state):
        """Failed step with on_failure=abort stops the plan."""
        runtime.graph_store.ask.side_effect = Exception("graph error")
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     on_failure="abort"),
            PlanStep(step_id="s2", action_type="compose", description="生成",
                     depends_on=["s1"]),
        ]
        result = executor.execute(steps, state)
        assert steps[0].status == "failed"
        # s2 should remain planned (never executed)
        assert steps[1].status == "planned"
        assert "中断" in result.answer

    def test_dependency_failed_causes_dependent_skip(self, executor, runtime, memory, state):
        """When step A fails (on_failure=skip), step B (depends on A) is skipped."""
        runtime.graph_store.ask.side_effect = Exception("graph error")
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     on_failure="skip"),
            PlanStep(step_id="s2", action_type="compose", description="生成",
                     depends_on=["s1"]),
        ]
        result = executor.execute(steps, state)
        assert steps[0].status == "failed"
        assert steps[1].status == "skipped"

    def test_topological_order_respected(self, executor, runtime, memory, state):
        """Steps execute in dependency order regardless of input order."""
        executed_order: list[str] = []

        def _track_retrieve(step, st):
            executed_order.append(step.step_id)
            return {"answer": "result"}

        executor._execute_retrieve = _track_retrieve  # type: ignore[assignment]

        steps = [
            PlanStep(step_id="c", action_type="retrieve", description="C",
                     depends_on=["b"]),
            PlanStep(step_id="b", action_type="retrieve", description="B",
                     depends_on=["a"]),
            PlanStep(step_id="a", action_type="retrieve", description="A"),
        ]
        executor.execute(steps, state)
        assert executed_order == ["a", "b", "c"]

    def test_progress_callback_invoked(self, executor, runtime, memory, state):
        """Progress callback receives step_started, step_completed, plan_execution_complete."""
        events: list[tuple[str, dict]] = []

        def _on_progress(event: str, payload: dict) -> None:
            events.append((event, payload))

        runtime.graph_store.ask.return_value = type("R", (), {
            "enabled": True, "answer": "graph answer",
            "entity_names": [], "relation_facts": [], "related_episode_uuids": [],
        })()
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索"),
        ]
        executor.execute(steps, state, on_progress=_on_progress)

        event_names = [e for e, _ in events]
        assert "plan_step_started" in event_names
        assert "plan_step_completed" in event_names
        assert "plan_execution_complete" in event_names

    def test_unknown_action_type_fails(self, executor, runtime, memory, state):
        steps = [
            PlanStep(step_id="s1", action_type="unknown_action", description="test"),
        ]
        result = executor.execute(steps, state)
        assert steps[0].status == "failed"

    def test_compose_generates_answer(self, executor, runtime, memory, state):
        """Compose step calls execute_ask and sets state.answer."""
        runtime.execute_ask.return_value = type("R", (), {"answer": "这是回答"})()
        steps = [
            PlanStep(step_id="s1", action_type="compose", description="生成回答",
                     tool_input={"question": "test question"}),
        ]
        result = executor.execute(steps, state)
        assert "这是回答" in result.answer

    def test_default_answer_when_no_compose(self, executor, runtime, memory, state):
        """When no compose step runs, a default summary answer is generated."""
        runtime.graph_store.ask.return_value = type("R", (), {
            "enabled": True, "answer": "match",
            "entity_names": [], "relation_facts": [], "related_episode_uuids": [],
        })()
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索"),
        ]
        result = executor.execute(steps, state)
        assert "计划执行完成" in result.answer

    def test_plan_step_skipped_event(self, executor, runtime, memory, state):
        """Skipped steps emit plan_step_skipped event."""
        events: list[str] = []

        def _on_progress(event: str, _payload: dict) -> None:
            events.append(event)

        runtime.graph_store.ask.side_effect = Exception("fail")
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     on_failure="skip"),
            PlanStep(step_id="s2", action_type="compose", description="生成",
                     depends_on=["s1"]),
        ]
        executor.execute(steps, state, on_progress=_on_progress)
        assert "plan_step_skipped" in events

    def test_compose_falls_back_on_error(self, executor, runtime, memory, state):
        """When execute_ask fails, compose step generates a simple fallback."""
        runtime.execute_ask.side_effect = Exception("LLM error")
        steps = [
            PlanStep(step_id="s1", action_type="compose", description="生成"),
        ]
        result = executor.execute(steps, state)
        assert result.answer is not None


class TestPlanExecutorRetryReplan:
    @pytest.fixture
    def runtime(self, settings):
        from unittest.mock import MagicMock

        from personal_agent.core.config import Settings

        rt = MagicMock()
        rt.settings = Settings(
            openai_api_key="sk-test", openai_base_url="https://api.test/v1",
            openai_model="gpt-test", openai_small_model="gpt-test-small",
        )
        rt.graph_store = MagicMock()
        rt.execute_ask = MagicMock(return_value=MagicMock(answer="test answer"))
        rt.execute_capture = MagicMock()
        return rt

    @pytest.fixture
    def memory(self):
        from unittest.mock import MagicMock

        mem = MagicMock()
        mem.working = MagicMock()
        mem.working.add_step = MagicMock()
        return mem

    @pytest.fixture
    def state(self):
        return AgentState(mode="entry", user_id="test-user")

    def test_retry_on_failure_succeeds(self, runtime, memory, state):
        """Step fails once, retries, succeeds on 2nd attempt."""
        from unittest.mock import MagicMock

        from personal_agent.agent.replanner import Replanner

        replanner = Replanner(runtime.settings)
        executor = PlanExecutor(runtime, memory, replanner=replanner)

        call_count = [0]

        def _fake_retrieve(step, st):
            call_count[0] += 1
            if call_count[0] < 2:
                raise RuntimeError("transient error")
            return {"answer": "success"}

        executor._execute_retrieve = _fake_retrieve  # type: ignore[assignment]

        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     on_failure="retry"),
        ]
        result = executor.execute(steps, state)
        assert steps[0].status == "completed"
        assert steps[0].retry_count == 2
        assert call_count[0] == 2

    def test_retry_exhausted_falls_back_to_skip(self, runtime, memory, state):
        """Max retries exhausted without replanner: step stays failed, dependents skip."""
        executor = PlanExecutor(runtime, memory, replanner=None)  # no replanner

        def _always_fail(step, st):
            raise RuntimeError("persistent error")

        executor._execute_retrieve = _always_fail  # type: ignore[assignment]

        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     on_failure="retry"),
            PlanStep(step_id="s2", action_type="compose", description="生成",
                     depends_on=["s1"]),
        ]
        result = executor.execute(steps, state)
        assert steps[0].status == "failed"
        assert steps[0].retry_count == 3  # MAX_RETRIES
        assert steps[1].status == "skipped"
        # Verify dependents were properly skipped
        assert result is state

    def test_retry_count_incremented(self, runtime, memory, state):
        """PlanStep.retry_count increments correctly on each failure."""
        from unittest.mock import MagicMock

        from personal_agent.agent.replanner import Replanner

        replanner = Replanner(runtime.settings)
        executor = PlanExecutor(runtime, memory, replanner=replanner)

        call_count = [0]

        def _count_fails(step, st):
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError(f"fail {call_count[0]}")
            return {"answer": "ok"}

        executor._execute_retrieve = _count_fails  # type: ignore[assignment]

        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     on_failure="retry"),
        ]
        executor.execute(steps, state)
        assert steps[0].status == "completed"
        assert steps[0].retry_count == 3

    def test_on_failure_retry_preserves_completed_state(self, runtime, memory, state):
        """Completed steps stay completed, only the failed step is retried."""
        from unittest.mock import MagicMock

        from personal_agent.agent.replanner import Replanner

        replanner = Replanner(runtime.settings)
        executor = PlanExecutor(runtime, memory, replanner=replanner)

        call_count_s2 = [0]

        def _fake_retrieve_s2(step, st):
            call_count_s2[0] += 1
            if call_count_s2[0] < 2:
                raise RuntimeError("transient")
            return {"answer": "success"}

        # s1 succeeds, s2 fails then retries successfully
        original_retrieve = executor._execute_retrieve

        def _conditional_retrieve(step, st):
            if step.step_id == "s1":
                return {"answer": "step1 result"}
            return _fake_retrieve_s2(step, st)

        executor._execute_retrieve = _conditional_retrieve  # type: ignore[assignment]

        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索A"),
            PlanStep(step_id="s2", action_type="retrieve", description="检索B",
                     on_failure="retry", depends_on=["s1"]),
        ]
        result = executor.execute(steps, state)
        assert steps[0].status == "completed"
        assert steps[0].retry_count == 0
        assert steps[1].status == "completed"
        assert steps[1].retry_count == 2

    def test_replan_after_retry_exhausted(self, runtime, memory, state):
        """Retries exhausted, replanner generates new steps that execute."""
        from unittest.mock import MagicMock

        from personal_agent.agent.replanner import Replanner

        replanner = Replanner(runtime.settings)
        executor = PlanExecutor(runtime, memory, replanner=replanner)

        def _always_fail(step, st):
            raise RuntimeError("persistent error")

        executor._execute_retrieve = _always_fail  # type: ignore[assignment]

        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     on_failure="retry"),
            PlanStep(step_id="s2", action_type="compose", description="生成",
                     depends_on=["s1"]),
        ]
        result = executor.execute(steps, state)
        # s1 should be skipped (replaced by replanner)
        # Since replanner's heuristic adds a salvage compose, s2 might be skipped
        # The replanner should generate at least one new step
        assert steps[0].status in ("failed", "skipped")
        # Result should have an answer (from the salvage compose or default)
        assert result.answer is not None

    def test_progress_callback_receives_retry_event(self, runtime, memory, state):
        """Progress callback receives plan_step_retry events."""
        from personal_agent.agent.replanner import Replanner

        replanner = Replanner(runtime.settings)
        executor = PlanExecutor(runtime, memory, replanner=replanner)

        call_count = [0]

        def _fail_then_succeed(step, st):
            call_count[0] += 1
            if call_count[0] < 2:
                raise RuntimeError("transient")
            return {"answer": "ok"}

        executor._execute_retrieve = _fail_then_succeed  # type: ignore[assignment]

        events: list[str] = []

        def _on_progress(event: str, _payload: dict) -> None:
            events.append(event)

        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     on_failure="retry"),
        ]
        executor.execute(steps, state, on_progress=_on_progress)
        assert "plan_step_retry" in events
        assert "plan_step_completed" in events


class TestPlanExecutorResolve:
    """4-tier resolve fallback: graph episode → similarity → keyword → citations."""

    @pytest.fixture
    def runtime(self):
        from unittest.mock import MagicMock

        from personal_agent.core.config import Settings

        rt = MagicMock()
        rt.settings = Settings(
            openai_api_key="sk-test", openai_base_url="https://api.test/v1",
            openai_model="gpt-test", openai_small_model="gpt-test-small",
        )
        rt.store = MagicMock()
        rt.store.find_notes_by_graph_episode_uuids = MagicMock(return_value=[])
        rt.store.find_similar_notes = MagicMock(return_value=[])
        rt.store.list_notes = MagicMock(return_value=[])
        rt.graph_store = MagicMock()
        rt.execute_ask = MagicMock()
        return rt

    @pytest.fixture
    def memory(self):
        from unittest.mock import MagicMock

        mem = MagicMock()
        mem.working = MagicMock()
        mem.working.add_step = MagicMock()
        mem.recent_citations = MagicMock(return_value=[])
        return mem

    @pytest.fixture
    def state(self):
        from personal_agent.core.models import EntryInput

        return AgentState(
            mode="entry", user_id="test-user",
            entry_input=EntryInput(text="删除那条关于旧部署流程的笔记"),
        )

    @pytest.fixture
    def executor(self, runtime, memory):
        return PlanExecutor(runtime, memory)

    @pytest.fixture
    def resolve_step(self):
        return PlanStep(step_id="r1", action_type="resolve", description="确认删除目标")

    def test_resolve_via_graph_episode(self, executor, runtime, memory, state, resolve_step):
        """Tier 1: resolve candidates via graph episode UUIDs from prior retrieve."""
        from personal_agent.core.models import KnowledgeNote

        runtime.store.find_notes_by_graph_episode_uuids.return_value = [
            KnowledgeNote(id="n1", title="旧部署流程", content="旧部署流程的正文。", summary="旧部署摘要"),
        ]
        results = {
            "s1": {
                "answer": "found",
                "entity_names": ["部署"],
                "related_episode_uuids": ["uuid-ep-1"],
            },
        }
        result = executor._execute_resolve(resolve_step, state, results)
        assert result["note_id"] == "n1"
        assert result["source"] == "graph_episode"

    def test_resolve_fallback_to_similarity(self, executor, runtime, memory, state, resolve_step):
        """Tier 2: no graph episodes → fall back to text similarity search."""
        from personal_agent.core.models import KnowledgeNote

        runtime.store.find_similar_notes.return_value = [
            KnowledgeNote(id="n2", title="部署流程笔记", content="详细描述部署流程。", summary="部署流程"),
        ]
        # results have no related_episode_uuids → tier 1 skipped
        results: dict[str, object] = {}
        result = executor._execute_resolve(resolve_step, state, results)
        assert result["note_id"] == "n2"
        assert result["source"] == "text_similarity"

    def test_resolve_fallback_to_keyword(self, executor, runtime, memory, state, resolve_step):
        """Tier 3: no similarity hits → fall back to keyword match on title/content."""
        from personal_agent.core.models import KnowledgeNote

        # Both tier 1 and 2 return empty
        runtime.store.find_similar_notes.return_value = []
        runtime.store.list_notes.return_value = [
            KnowledgeNote(id="n3", title="旧部署流程文档", content="关于旧部署流程的记录。", summary="旧部署"),
            KnowledgeNote(id="n4", title="其他笔记", content="无关内容。", summary="其他"),
        ]
        # Keyword match uses full query substring-in-title/check — use a short query
        state.entry_input.text = "旧部署"
        results: dict[str, object] = {}
        result = executor._execute_resolve(resolve_step, state, results)
        assert result["note_id"] == "n3"
        assert result["source"] == "keyword_match"

    def test_resolve_fallback_to_citations(self, executor, runtime, memory, state, resolve_step):
        """Tier 4: all local searches fail → fall back to cross-session recent citations."""
        runtime.store.list_notes.return_value = []
        runtime.store.get_note.return_value = None  # note not found locally, use citation dict directly
        memory.recent_citations.return_value = [
            {"note_id": "n5", "title": "旧部署流程", "snippet": "之前引用过的笔记"},
        ]
        results: dict[str, object] = {}
        result = executor._execute_resolve(resolve_step, state, results)
        assert result["note_id"] == "n5"
        assert result["source"] == "recent_citation"

    def test_resolve_no_candidates_returns_error(self, executor, runtime, memory, state, resolve_step):
        """All 4 tiers fail → returns error dict with None note_id."""
        memory.recent_citations.return_value = []
        results: dict[str, object] = {}
        result = executor._execute_resolve(resolve_step, state, results)
        assert result["note_id"] is None
        assert "error" in result


class TestPlanExecutorEvents:
    """draft_ready, pending_action_created, and inject helpers."""

    @pytest.fixture
    def runtime(self):
        from unittest.mock import MagicMock

        from personal_agent.core.config import Settings

        rt = MagicMock()
        rt.settings = Settings(
            openai_api_key="sk-test", openai_base_url="https://api.test/v1",
            openai_model="gpt-test", openai_small_model="gpt-test-small",
        )
        rt.store = MagicMock()
        rt.graph_store = MagicMock()
        rt.execute_ask = MagicMock(return_value=MagicMock(answer="composed answer"))
        rt.execute_capture = MagicMock()
        return rt

    @pytest.fixture
    def memory(self):
        from unittest.mock import MagicMock

        mem = MagicMock()
        mem.working = MagicMock()
        mem.working.add_step = MagicMock()
        mem.recent_citations = MagicMock(return_value=[])
        mem.save_draft = MagicMock(return_value=None)
        return mem

    @pytest.fixture
    def state(self):
        from personal_agent.core.models import EntryInput

        return AgentState(
            mode="entry", user_id="test-user",
            entry_input=EntryInput(text="把讨论结论固化下来"),
            intent="solidify_conversation",
        )

    def test_draft_ready_event_emitted(self, runtime, memory, state):
        """Compose step with non-empty answer emits draft_ready event."""
        executor = PlanExecutor(runtime, memory)
        events: list[tuple[str, dict]] = []

        def _on_progress(event: str, payload: dict) -> None:
            events.append((event, payload))

        steps = [
            PlanStep(step_id="s1", action_type="compose", description="生成草稿",
                     tool_input={"question": "总结讨论"}),
        ]
        executor.execute(steps, state, on_progress=_on_progress)

        draft_events = [(e, p) for e, p in events if e == "draft_ready"]
        assert len(draft_events) == 1
        assert draft_events[0][1]["draft_text"] == "composed answer"

    def test_pending_action_created_event_emitted(self, runtime, memory, state):
        """tool_call returning pending_confirmation emits pending_action_created event."""
        executor = PlanExecutor(runtime, memory)

        def _fake_tool_call(step):
            return {
                "pending_confirmation": True,
                "action_id": "act-1",
                "token": "tok-abc",
                "note_id": "n10",
                "title": "待删除笔记",
                "message": "确认删除？",
            }

        executor._execute_tool_call = _fake_tool_call  # type: ignore[assignment]

        events: list[tuple[str, dict]] = []

        def _on_progress(event: str, payload: dict) -> None:
            events.append((event, payload))

        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="删除笔记",
                     tool_name="delete_note"),
        ]
        executor.execute(steps, state, on_progress=_on_progress)

        pending_events = [(e, p) for e, p in events if e == "pending_action_created"]
        assert len(pending_events) == 1
        assert pending_events[0][1]["action_id"] == "act-1"
        assert pending_events[0][1]["note_id"] == "n10"

    def test_no_draft_ready_when_compose_empty(self, runtime, memory, state):
        """Empty compose answer does NOT emit draft_ready."""
        from unittest.mock import MagicMock

        runtime.execute_ask.return_value = MagicMock(answer="")
        executor = PlanExecutor(runtime, memory)
        events: list[str] = []

        def _on_progress(event: str, _payload: dict) -> None:
            events.append(event)

        steps = [
            PlanStep(step_id="s1", action_type="compose", description="生成草稿"),
        ]
        executor.execute(steps, state, on_progress=_on_progress)
        assert "draft_ready" not in events

    def test_inject_note_id_populates_dependent_tool_input(self, runtime, memory, state):
        """After resolve, note_id is injected into dependent delete_note tool_call step."""
        executor = PlanExecutor(runtime, memory)

        # Mock resolve to return a note_id and skip actual LLM compose
        def _fake_resolve(step, st, results):
            return {"note_id": "n99", "title": "目标笔记", "source": "keyword_match"}

        executor._execute_resolve = _fake_resolve  # type: ignore[assignment]
        executor._execute_tool_call = lambda step: {"ok": True}  # type: ignore[assignment]
        executor._execute_compose = lambda step, st, results: "done"  # type: ignore[assignment]

        steps = [
            PlanStep(step_id="r1", action_type="resolve", description="确认删除目标"),
            PlanStep(step_id="t1", action_type="tool_call", description="执行删除",
                     tool_name="delete_note", depends_on=["r1"]),
        ]
        executor.execute(steps, state)

        # The tool_call step should have had note_id injected
        tool_step = next(s for s in steps if s.step_id == "t1")
        assert tool_step.tool_input.get("note_id") == "n99"


class TestReActStepDispatch:
    """Test that execution_mode='react' steps are dispatched to ReActStepRunner."""

    @pytest.fixture
    def executor_with_react(self, settings):
        from personal_agent.agent.react_runner import ReActStepRunner
        from personal_agent.core.config import Settings

        rt = MagicMock()
        rt.settings = Settings(
            openai_api_key="sk-test", openai_base_url="https://api.test/v1",
            openai_model="gpt-test", openai_small_model="gpt-test-small",
        )
        rt.graph_store = MagicMock()
        rt.execute_ask = MagicMock(return_value=MagicMock(answer="test answer"))

        mem = MagicMock()
        mem.working = MagicMock()
        mem.working.add_step = MagicMock()

        react_runner = MagicMock(spec=ReActStepRunner)
        react_runner.run.return_value = {"answer": "react result", "entity_names": ["test"]}
        return PlanExecutor(rt, mem, react_runner=react_runner), react_runner, mem

    def test_react_step_dispatched_to_runner(self, executor_with_react):
        executor, react_runner, _ = executor_with_react

        state = AgentState(mode="entry", user_id="test-user")
        steps = [
            PlanStep(
                step_id="r1", action_type="retrieve",
                description="查找笔记",
                execution_mode="react",
                allowed_tools=["graph_search"],
                max_iterations=3,
            ),
        ]
        executor.execute(steps, state)

        assert steps[0].status == "completed"
        react_runner.run.assert_called_once()
        assert state.answer is not None

    def test_react_step_emits_execution_mode(self, executor_with_react):
        executor, react_runner, _ = executor_with_react

        events: list[tuple[str, dict]] = []
        def on_progress(event: str, payload: dict) -> None:
            events.append((event, payload))

        state = AgentState(mode="entry", user_id="test-user")
        steps = [
            PlanStep(
                step_id="r1", action_type="retrieve",
                description="查找",
                execution_mode="react",
                allowed_tools=["graph_search"],
                max_iterations=2,
            ),
        ]
        executor.execute(steps, state, on_progress=on_progress)

        completed_events = [(e, p) for e, p in events if e == "plan_step_completed"]
        assert len(completed_events) == 1
        assert completed_events[0][1].get("execution_mode") == "react"

    def test_react_falls_back_without_runner(self, settings):
        """When no runner configured, react step falls back to deterministic handler."""
        rt = MagicMock()
        rt.graph_store.ask.return_value = type("R", (), {
            "enabled": True, "answer": "graph answer",
            "entity_names": [], "relation_facts": [], "related_episode_uuids": [],
        })()

        mem = MagicMock()
        mem.working = MagicMock()
        mem.working.add_step = MagicMock()

        executor = PlanExecutor(rt, mem)
        state = AgentState(mode="entry", user_id="test-user")

        steps = [
            PlanStep(
                step_id="r1", action_type="retrieve",
                description="检索",
                execution_mode="react",
                allowed_tools=["graph_search"],
                max_iterations=3,
                tool_input={"question": "test"},
            ),
        ]
        executor.execute(steps, state)
        # Should have fallen back to deterministic retrieve and completed
        assert steps[0].status == "completed"
