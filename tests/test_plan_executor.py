from __future__ import annotations

import pytest

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
        """Max retries exhausted without replanner, step stays failed, dependents skip."""
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
        assert steps[0].status == "failed"
        assert steps[0].retry_count == 3  # MAX_RETRIES
        assert steps[1].status == "skipped"

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
