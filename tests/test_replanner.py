from __future__ import annotations

import pytest

from personal_agent.agent.planner import PlanStep
from personal_agent.agent.replanner import Replanner


class TestReplannerHeuristic:
    @pytest.fixture
    def settings(self):
        from personal_agent.core.config import Settings

        return Settings(
            openai_api_key="", openai_base_url="", openai_model="",
            openai_small_model="",
        )

    @pytest.fixture
    def replanner(self, settings):
        return Replanner(settings)

    def test_empty_remaining_returns_none(self, replanner):
        """When all steps are completed, replan returns None."""
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索", status="completed"),
        ]
        failed = PlanStep(step_id="s2", action_type="compose", description="生成", status="failed")
        result = replanner.replan(steps, failed, "error", {}, "ask")
        assert result is None

    def test_heuristic_replaces_failed_retrieve_with_compose(self, replanner):
        """When a retrieve step fails and no compose exists, add a salvage compose step."""
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索", status="failed"),
            PlanStep(step_id="s2", action_type="verify", description="校验", status="planned",
                     depends_on=["s1"]),
        ]
        failed = steps[0]
        result = replanner.replan(steps, failed, "graph error", {}, "ask")
        assert result is not None
        # s2 depends on s1, so it should be filtered out; salvage compose added
        action_types = {s.action_type for s in result}
        assert "compose" in action_types

    def test_heuristic_filters_dependent_steps(self, replanner):
        """Steps depending on the failed step are removed from the revised plan."""
        steps = [
            PlanStep(step_id="a", action_type="retrieve", description="A", status="completed"),
            PlanStep(step_id="b", action_type="tool_call", description="B", status="failed",
                     tool_name="capture_text"),
            PlanStep(step_id="c", action_type="compose", description="C", status="planned",
                     depends_on=["b"]),
            PlanStep(step_id="d", action_type="verify", description="D", status="planned"),
        ]
        failed = steps[1]
        result = replanner.replan(steps, failed, "tool error", {}, "capture_text")
        assert result is not None
        step_ids = {s.step_id for s in result}
        # 'c' depends on failed 'b', so it should be removed
        assert "c" not in step_ids
        # 'd' is independent, should remain
        assert "d" in step_ids

    def test_returns_none_when_no_alternative(self, replanner):
        """When no independent remaining steps exist, returns None."""
        steps = [
            PlanStep(step_id="x", action_type="tool_call", description="X", status="failed",
                     tool_name="capture_text"),
            PlanStep(step_id="y", action_type="compose", description="Y", status="planned",
                     depends_on=["x"]),
        ]
        failed = steps[0]
        result = replanner.replan(steps, failed, "fatal error", {}, "capture_text")
        # y depends on x, and y is a compose step so no salvage compose is added.
        # All remaining steps depend on the failed step, so nothing can proceed.
        assert result is None

    def test_heuristic_preserves_completed_steps(self, replanner):
        """Completed steps are not included in the revised plan."""
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索", status="completed"),
            PlanStep(step_id="s2", action_type="tool_call", description="调用", status="failed",
                     tool_name="graph_search"),
        ]
        failed = steps[1]
        result = replanner.replan(steps, failed, "error", {"s1": {"answer": "found"}}, "ask")
        assert result is not None
        # Completed step s1 should not be in the result
        step_ids = {s.step_id for s in result}
        assert "s1" not in step_ids
