from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from personal_agent.agent.planner import PlanStep
from personal_agent.agent.react_runner import (
    ReActIteration,
    ReActStepRunner,
    DEFAULT_ALLOWED_TOOLS,
)
from personal_agent.core.models import AgentState
from personal_agent.tools.base import ToolResult, ToolSpec


def _make_runner(tools: dict[str, ToolSpec] | None = None) -> ReActStepRunner:
    registry = MagicMock()
    if tools:
        specs = [ToolSpec(name=n, **kwargs) for n, kwargs in tools.items()]
        registry.list_tools.return_value = specs
        tool_map = {}
        for spec in specs:
            mock_tool = MagicMock()
            mock_tool.spec = spec
            tool_map[spec.name] = mock_tool
        registry.get.side_effect = lambda name: tool_map.get(name)
    else:
        registry.list_tools.return_value = []

    memory = MagicMock()
    memory.working.add_step = MagicMock()

    settings = MagicMock()
    settings.openai_api_key = "test-key"
    settings.openai_base_url = "http://test"
    settings.openai_small_model = "test-model"

    return ReActStepRunner(tool_registry=registry, memory=memory, settings=settings)


def _state() -> AgentState:
    return AgentState(user_id="test")


class TestReActSingleIteration:
    def test_done_immediately(self):
        """LLM returns done=true on first iteration."""
        runner = _make_runner({
            "graph_search": {"description": "search graph"},
        })
        step = PlanStep(
            step_id="r1", action_type="retrieve",
            description="查找关于 Redis 的笔记",
            allowed_tools=["graph_search"],
            max_iterations=3,
        )

        llm_response = json.dumps({
            "thought": "已找到足够信息",
            "done": True,
            "result": {"answer": "Redis 是内存数据库", "entity_names": ["Redis"]},
        })
        with patch.object(runner, "_llm_respond", return_value=llm_response):
            result = runner.run(step, _state(), {}, None)

        assert result["answer"] == "Redis 是内存数据库"
        assert result["entity_names"] == ["Redis"]


class TestReActMaxIterations:
    def test_caps_at_max(self):
        """Loop stops after max_iterations even if LLM never says done."""
        runner = _make_runner({
            "graph_search": {"description": "search graph"},
        })
        registry = runner._registry
        registry.execute.return_value = ToolResult(ok=True, data={"answer": "some data"})

        step = PlanStep(
            step_id="r1", action_type="retrieve",
            description="查找笔记",
            allowed_tools=["graph_search"],
            max_iterations=2,
        )

        # LLM never returns done
        llm_response = json.dumps({
            "thought": "继续搜索",
            "tool": "graph_search",
            "input": {"question": "更多"},
        })
        with patch.object(runner, "_llm_respond", return_value=llm_response):
            result = runner.run(step, _state(), {}, None)

        assert result.get("react_iterations") == 2


class TestReActDisallowedTool:
    def test_rejects_unlisted_tool(self):
        """Tool not in allowed_tools gets rejected observation."""
        runner = _make_runner({
            "graph_search": {"description": "search graph"},
            "delete_note": {"description": "delete", "risk_level": "high", "requires_confirmation": True},
        })

        step = PlanStep(
            step_id="r1", action_type="retrieve",
            description="查找笔记",
            allowed_tools=["graph_search"],
            max_iterations=3,
        )

        responses = [
            # First: try disallowed tool
            json.dumps({"thought": "试试删除", "tool": "delete_note", "input": {"note_id": "x"}}),
            # Second: done
            json.dumps({"thought": "ok", "done": True, "result": {"answer": "done"}}),
        ]
        with patch.object(runner, "_llm_respond", side_effect=responses):
            result = runner.run(step, _state(), {}, None)

        assert result["answer"] == "done"


class TestReActObservationInjected:
    def test_observation_appears_in_next_prompt(self):
        """Each observation is appended to the user prompt for next iteration."""
        runner = _make_runner({
            "graph_search": {"description": "search graph"},
        })
        registry = runner._registry
        registry.execute.return_value = ToolResult(ok=True, data={"answer": "Redis is fast"})

        step = PlanStep(
            step_id="r1", action_type="retrieve",
            description="查找笔记",
            allowed_tools=["graph_search"],
            max_iterations=3,
        )

        prompts_seen: list[str] = []

        def mock_llm(prompt: str) -> str:
            prompts_seen.append(prompt)
            if len(prompts_seen) == 1:
                return json.dumps({"thought": "搜一次", "tool": "graph_search", "input": {"question": "Redis"}})
            return json.dumps({"thought": "够了", "done": True, "result": {"answer": "ok"}})

        with patch.object(runner, "_llm_respond", side_effect=mock_llm):
            runner.run(step, _state(), {}, None)

        # Second prompt should contain the observation from the first iteration
        assert len(prompts_seen) == 2
        assert "Redis is fast" in prompts_seen[1]


class TestReActProgressEvents:
    def test_emits_iteration_events(self):
        runner = _make_runner({
            "graph_search": {"description": "search graph"},
        })
        registry = runner._registry
        registry.execute.return_value = ToolResult(ok=True, data={"answer": "data"})

        step = PlanStep(
            step_id="r1", action_type="retrieve",
            description="查找",
            allowed_tools=["graph_search"],
            max_iterations=3,
        )

        responses = [
            json.dumps({"thought": "搜", "tool": "graph_search", "input": {"question": "q"}}),
            json.dumps({"thought": "done", "done": True, "result": {"answer": "ok"}}),
        ]
        events: list[tuple] = []
        def on_progress(event: str, payload: dict) -> None:
            events.append((event, payload))

        with patch.object(runner, "_llm_respond", side_effect=responses):
            runner.run(step, _state(), {}, on_progress)

        react_events = [(e, p) for e, p in events if e == "react_iteration"]
        assert len(react_events) == 1
        assert react_events[0][1]["action_tool"] == "graph_search"
        assert react_events[0][1]["step_id"] == "r1"


class TestReActDefaultAllowedTools:
    def test_empty_allowed_defaults_to_readonly(self):
        """When allowed_tools is empty, defaults to DEFAULT_ALLOWED_TOOLS."""
        runner = _make_runner({
            "graph_search": {"description": "search"},
            "web_search": {"description": "web"},
        })
        step = PlanStep(step_id="r1", description="test", max_iterations=1)
        resolved = runner._resolve_allowed_tools(step)
        assert resolved == set(DEFAULT_ALLOWED_TOOLS)

    def test_intersects_with_registered(self):
        """Only registered tools pass the intersection."""
        runner = _make_runner({
            "graph_search": {"description": "search"},
        })
        step = PlanStep(
            step_id="r1", description="test",
            allowed_tools=["graph_search", "nonexistent"],
            max_iterations=1,
        )
        resolved = runner._resolve_allowed_tools(step)
        assert resolved == {"graph_search"}


class TestReActBlockedTool:
    def test_blocks_high_risk_tool(self):
        runner = _make_runner({
            "delete_note": {"description": "delete", "risk_level": "high"},
        })
        assert runner._is_blocked_tool("delete_note") is True

    def test_blocks_capture_tool(self):
        runner = _make_runner({
            "capture_text": {"description": "capture"},
        })
        assert runner._is_blocked_tool("capture_text") is True

    def test_allows_readonly_tool(self):
        runner = _make_runner({
            "graph_search": {"description": "search", "risk_level": "low"},
        })
        assert runner._is_blocked_tool("graph_search") is False

    def test_blocks_unregistered(self):
        runner = _make_runner({})
        assert runner._is_blocked_tool("anything") is True
