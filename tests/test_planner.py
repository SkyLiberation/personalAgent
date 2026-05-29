from __future__ import annotations

from types import SimpleNamespace

import pytest

from personal_agent.agent.planner import DefaultTaskPlanner, PlanStep
from personal_agent.agent.router import DefaultIntentRouter, RouterDecision
from personal_agent.agent.runtime import EntryResult
from personal_agent.core.models import EntryInput


class TestPlannerEnrichedSteps:
    @pytest.fixture
    def planner(self):
        from personal_agent.core.config import OpenAIConfig, Settings

        return DefaultTaskPlanner(
            Settings(openai=OpenAIConfig(api_key=None, base_url=None, small_model=""))
        )

    def test_plan_delete_knowledge_heuristic(self, planner):
        steps = planner.plan("delete_knowledge", "删除那条旧笔记")
        assert len(steps) == 4
        action_types = [s.action_type for s in steps]
        assert action_types == ["retrieve", "resolve", "tool_call", "compose"]
        assert steps[2].risk_level == "high"
        assert steps[2].requires_confirmation is True
        assert steps[2].tool_name == "delete_note"
        # All steps have step_id
        for s in steps:
            assert s.step_id
            assert s.status == "planned"

    def test_plan_solidify_conversation_heuristic(self, planner):
        steps = planner.plan("solidify_conversation", "把讨论结论沉淀下来")
        assert len(steps) == 2
        action_types = [s.action_type for s in steps]
        assert action_types == ["compose", "tool_call"]
        assert steps[1].depends_on == ["sol-1"]
        assert steps[1].requires_confirmation is False
        assert steps[1].risk_level == "low"

    def test_plan_ask_heuristic(self, planner):
        steps = planner.plan("ask", "什么是服务降级？")
        assert len(steps) == 4  # retrieve, compose, verify, web_search fallback
        assert steps[0].action_type == "retrieve"
        assert steps[0].tool_name == "graph_search"
        assert steps[1].depends_on == ["ask-1"]
        assert steps[3].tool_name == "web_search"
        assert steps[3].on_failure == "skip"

    def test_plan_unknown_intent_fallback(self, planner):
        steps = planner.plan("unknown", "随便说点什么")
        assert len(steps) == 1
        assert steps[0].action_type == "compose"

    def test_plan_step_has_all_required_fields(self, planner):
        steps = planner.plan("ask", "测试问题")
        for s in steps:
            assert hasattr(s, "step_id")
            assert hasattr(s, "action_type")
            assert hasattr(s, "description")
            assert hasattr(s, "tool_name")
            assert hasattr(s, "tool_input")
            assert hasattr(s, "depends_on")
            assert hasattr(s, "expected_output")
            assert hasattr(s, "success_criteria")
            assert hasattr(s, "risk_level")
            assert hasattr(s, "requires_confirmation")
            assert hasattr(s, "on_failure")
            assert hasattr(s, "status")

    def test_planner_generates_but_does_not_execute_documented(self):
        """Baseline: planner generates PlanStep objects but they are not
        consumed by entry nodes or graph execution. This test documents the
        current Phase 2 behavior — plan execution will be added in later phases.
        """
        from personal_agent.core.config import OpenAIConfig, Settings

        planner = DefaultTaskPlanner(
            Settings(openai=OpenAIConfig(api_key=None, base_url=None, small_model=""))
        )
        steps = planner.plan("ask", "什么是服务降级？")
        assert len(steps) == 4
        for s in steps:
            assert isinstance(s, PlanStep)
            assert s.action_type in {"retrieve", "tool_call", "compose", "verify"}
            assert s.status == "planned"


class TestDefaultIntentRouterNewIntents:
    @pytest.fixture
    def router(self, settings):
        return DefaultIntentRouter(settings)

    def test_router_applies_defaults_for_llm_solidify_decision(self, router, monkeypatch):
        monkeypatch.setattr(
            router,
            "_classify_with_llm",
            lambda _text, _context="": RouterDecision(
                route="solidify_conversation",
                requires_confirmation=True,
            ),
        )
        entry = EntryInput(text="把刚才讨论的结论记下来")
        decision = router.classify(entry)
        assert decision.route == "solidify_conversation"
        assert decision.requires_confirmation is False

    def test_router_applies_defaults_for_llm_delete_decision(self, router, monkeypatch):
        monkeypatch.setattr(
            router,
            "_classify_with_llm",
            lambda _text, _context="": RouterDecision(
                route="delete_knowledge",
                risk_level="high",
                requires_confirmation=True,
            ),
        )
        entry = EntryInput(text="删除那条关于旧部署流程的笔记")
        decision = router.classify(entry)
        assert decision.route == "delete_knowledge"
        assert decision.risk_level == "high"
        assert decision.requires_confirmation is True

    def test_router_decision_has_all_fields(self):
        from personal_agent.core.config import OpenAIConfig, Settings

        router = DefaultIntentRouter(
            Settings(openai=OpenAIConfig(api_key=None, base_url=None, small_model=""))
        )
        entry = EntryInput(text="什么是服务降级？")
        decision = router.classify(entry)
        assert hasattr(decision, "route")
        assert hasattr(decision, "confidence")
        assert hasattr(decision, "requires_tools")
        assert hasattr(decision, "requires_retrieval")
        assert hasattr(decision, "requires_planning")
        assert hasattr(decision, "risk_level")
        assert hasattr(decision, "requires_confirmation")
        assert hasattr(decision, "missing_information")
        assert hasattr(decision, "candidate_tools")
        assert hasattr(decision, "user_visible_message")

    def test_router_decision_file_source(self):
        from personal_agent.core.config import OpenAIConfig, Settings

        router = DefaultIntentRouter(
            Settings(openai=OpenAIConfig(api_key=None, base_url=None, small_model=""))
        )
        entry = EntryInput(source_type="file", text="test.pdf")
        decision = router.classify(entry)
        assert decision.route == "capture_file"


class TestEntryResultPlanSteps:
    def test_entry_result_includes_plan_steps(self):
        result = EntryResult(
            intent="ask",
            reason="用户提问",
            reply_text="回答内容",
            plan_steps=[
                {
                    "step_id": "ask-1", "action_type": "retrieve",
                    "description": "检索知识库", "tool_name": "graph_search",
                    "tool_input": {}, "depends_on": [],
                    "expected_output": "匹配笔记", "success_criteria": "命中笔记",
                    "risk_level": "low", "requires_confirmation": False,
                    "on_failure": "skip", "status": "planned",
                },
            ],
        )
        assert len(result.plan_steps) == 1
        assert result.plan_steps[0]["action_type"] == "retrieve"
        assert result.plan_steps[0]["description"] == "检索知识库"
        assert result.plan_steps[0]["status"] == "planned"

    def test_entry_result_plan_steps_defaults_empty(self):
        result = EntryResult(
            intent="unknown",
            reason="无法识别",
            reply_text="请重新输入",
        )
        assert result.plan_steps == []


class TestExecutionTrace:
    def test_entry_result_includes_execution_trace(self):
        result = EntryResult(
            intent="ask",
            reason="用户提问",
            reply_text="回答内容",
            execution_trace=[
                "在知识库和图谱中检索相关内容",
                "整合检索到的证据，生成自然语言回答",
                "校验回答的事实依据和引用完整性",
            ],
        )
        assert len(result.execution_trace) == 3
        assert "检索" in result.execution_trace[0]
        assert result.plan_steps == []

class TestPlannerValidatorRoundtrip:
    @pytest.fixture
    def planner(self):
        from personal_agent.core.config import OpenAIConfig, Settings

        return DefaultTaskPlanner(
            Settings(openai=OpenAIConfig(api_key=None, base_url=None, small_model=""))
        )

    def test_heuristic_plans_pass_validation(self, planner):
        from personal_agent.agent.plan_validator import PlanValidator
        from personal_agent.agent.router import _default_router_decision

        validator = PlanValidator()

        for intent in ("ask", "capture_text", "delete_knowledge", "solidify_conversation"):
            decision = _default_router_decision(intent)
            steps = planner.plan(intent, "测试输入")
            result = validator.validate(steps, decision)
            # Heuristic plans should pass validation cleanly
            assert result.valid, f"Intent {intent} plan failed: {result.issues}"
            assert len(steps) > 0

    def test_empty_plan_text_produces_valid_plan(self, planner):
        from personal_agent.agent.plan_validator import PlanValidator
        from personal_agent.agent.router import _default_router_decision

        validator = PlanValidator()
        decision = _default_router_decision("unknown")
        steps = planner.plan("unknown", "")
        result = validator.validate(steps, decision)
        # unknown intent produces a single compose step — should pass
        assert result.valid

    def test_delete_note_id_may_be_supplied_by_transitive_resolve_step(self):
        from personal_agent.agent.plan_validator import PlanValidator
        from personal_agent.agent.router import _default_router_decision
        from langchain_core.tools import tool
        from personal_agent.tools import ToolExecutor, tool_response, tool_success

        @tool("delete_note", description="delete", response_format="content_and_artifact")
        def delete_note(note_id: str):
            return tool_response(tool_success(note_id))

        executor = ToolExecutor()
        executor.register(delete_note)
        steps = [
            PlanStep(step_id="del-0", action_type="retrieve", description="检索候选"),
            PlanStep(step_id="del-1", action_type="resolve", description="定位目标", depends_on=["del-0"]),
            PlanStep(
                step_id="del-2",
                action_type="tool_call",
                description="删除目标",
                tool_name="delete_note",
                risk_level="high",
                requires_confirmation=True,
                depends_on=["del-1"],
            ),
            PlanStep(step_id="del-3", action_type="compose", description="生成结果", depends_on=["del-2"]),
        ]

        result = PlanValidator(tool_executor=executor).validate(
            steps, _default_router_decision("delete_knowledge")
        )

        assert result.valid

    def test_delete_note_without_upstream_resolve_still_requires_note_id(self):
        from personal_agent.agent.plan_validator import PlanValidator
        from personal_agent.agent.router import _default_router_decision
        from langchain_core.tools import tool
        from personal_agent.tools import ToolExecutor, tool_response, tool_success

        @tool("delete_note", description="delete", response_format="content_and_artifact")
        def delete_note(note_id: str):
            return tool_response(tool_success(note_id))

        executor = ToolExecutor()
        executor.register(delete_note)
        steps = [
            PlanStep(
                step_id="del-1",
                action_type="tool_call",
                description="删除目标",
                tool_name="delete_note",
            ),
        ]

        result = PlanValidator(tool_executor=executor).validate(
            steps, _default_router_decision("delete_knowledge")
        )

        assert not result.valid
        assert any("note_id" in issue for issue in result.issues)


class TestPlannerLlmContract:
    def test_llm_plan_parses_object_contract_and_react_fields(self, monkeypatch):
        from personal_agent.core.config import OpenAIConfig, Settings

        request: dict[str, object] = {}

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=self._create)
                )

            def _create(self, **kwargs):
                request.update(kwargs)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=(
                        '{"steps":['
                        '{"step_id":"del-1","action_type":"retrieve","description":"检索候选",'
                        '"tool_name":null,"tool_input":{},"depends_on":[],'
                        '"risk_level":"low","requires_confirmation":false,"on_failure":"retry",'
                        '"execution_mode":"react","allowed_tools":["graph_search"],"max_iterations":2},'
                        '{"step_id":"del-2","action_type":"resolve","description":"定位目标",'
                        '"tool_name":null,"tool_input":{},"depends_on":["del-1"],'
                        '"risk_level":"low","requires_confirmation":false,"on_failure":"abort"},'
                        '{"step_id":"del-3","action_type":"tool_call","description":"请求确认删除",'
                        '"tool_name":"delete_note","tool_input":{},"depends_on":["del-2"],'
                        '"risk_level":"high","requires_confirmation":true,"on_failure":"abort"},'
                        '{"step_id":"del-4","action_type":"compose","description":"汇总结果",'
                        '"tool_name":null,"tool_input":{},"depends_on":["del-3"],'
                        '"risk_level":"low","requires_confirmation":false,"on_failure":"skip"}'
                        ']}'
                    )))]
                )

        monkeypatch.setattr("personal_agent.agent.planner.OpenAI", FakeOpenAI)
        planner = DefaultTaskPlanner(
            Settings(openai=OpenAIConfig(api_key="k", base_url="http://llm", small_model="small"))
        )

        steps = planner.plan("delete_knowledge", "删除 DNS 笔记")

        assert request["response_format"] == {"type": "json_object"}
        assert steps[0].execution_mode == "react"
        assert steps[0].allowed_tools == ["graph_search"]
        assert steps[0].max_iterations == 2

    def test_llm_array_output_falls_back_to_safe_workflow(self, monkeypatch):
        from personal_agent.core.config import OpenAIConfig, Settings

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(
                        create=lambda **_kwargs: SimpleNamespace(
                            choices=[SimpleNamespace(message=SimpleNamespace(content="[]"))]
                        )
                    )
                )

        monkeypatch.setattr("personal_agent.agent.planner.OpenAI", FakeOpenAI)
        planner = DefaultTaskPlanner(
            Settings(openai=OpenAIConfig(api_key="k", base_url="http://llm", small_model="small"))
        )

        steps = planner.plan("solidify_conversation", "固化该结论")

        assert [step.action_type for step in steps] == ["compose", "tool_call"]
