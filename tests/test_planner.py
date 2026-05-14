from __future__ import annotations

import pytest

from personal_agent.agent.entry_nodes import heuristic_entry_intent
from personal_agent.agent.planner import DefaultTaskPlanner, PlanStep
from personal_agent.agent.router import DefaultIntentRouter
from personal_agent.agent.runtime import EntryResult
from personal_agent.core.models import EntryInput
from personal_agent.memory.working_memory import WorkingMemory


class TestWorkingMemoryPlanSteps:
    @pytest.fixture
    def wm(self):
        return WorkingMemory(max_steps=10, max_tool_cache=5)

    def test_context_snapshot_includes_plan_steps(self, wm):
        wm.set_goal("测试任务")
        wm.plan_steps = [
            {"action_type": "retrieve", "tool_name": "graph_search", "description": "检索知识库"},
            {"action_type": "compose", "tool_name": None, "description": "生成回答"},
            {"action_type": "verify", "tool_name": None, "description": "校验结果"},
        ]
        snapshot = wm.context_snapshot()
        assert "当前任务计划" in snapshot
        assert "retrieve" in snapshot
        assert "graph_search" in snapshot
        assert "compose" in snapshot
        assert "verify" in snapshot

    def test_context_snapshot_falls_back_to_old_field_names(self, wm):
        wm.set_goal("测试")
        wm.plan_steps = [
            {"step": "retrieve", "tool": "graph_search"},
        ]
        snapshot = wm.context_snapshot()
        assert "当前任务计划" in snapshot
        assert "retrieve" in snapshot

    def test_context_snapshot_without_plan_steps_omits_section(self, wm):
        wm.set_goal("测试任务")
        wm.plan_steps = []
        snapshot = wm.context_snapshot()
        assert "当前任务计划" not in snapshot


class TestHeuristicIntentDeleteKnowledge:
    def test_delete_note_with_context(self):
        intent, reason = heuristic_entry_intent("把刚才那条关于旧部署流程的笔记删掉")
        assert intent == "delete_knowledge"
        assert "删除" in reason

    def test_delete_outdated_conclusion(self):
        intent, reason = heuristic_entry_intent("这个结论已经过时，不要再保留，删除这条记录")
        assert intent == "delete_knowledge"

    def test_remove_knowledge_card(self):
        intent, _ = heuristic_entry_intent("删除那个关于供应商联系人信息的卡片")
        assert intent == "delete_knowledge"

    def test_delete_without_knowledge_context_falls_through(self):
        intent, _ = heuristic_entry_intent("删除")
        assert intent != "delete_knowledge"


class TestHeuristicIntentSolidifyConversation:
    def test_solidify_with_jixialai(self):
        intent, _ = heuristic_entry_intent("把我们刚才讨论的结论记下来")
        assert intent == "solidify_conversation"

    def test_solidify_with_chendian(self):
        intent, _ = heuristic_entry_intent("把这个方案沉淀成知识卡片")
        assert intent == "solidify_conversation"

    def test_solidify_with_guhua(self):
        intent, _ = heuristic_entry_intent("把关于缓存一致性的结论固化下来")
        assert intent == "solidify_conversation"

    def test_solidify_with_shoujin(self):
        intent, _ = heuristic_entry_intent("把这个结论收进知识库")
        assert intent == "solidify_conversation"


class TestPlannerEnrichedSteps:
    @pytest.fixture
    def planner(self):
        from personal_agent.core.config import Settings

        return DefaultTaskPlanner(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
        )

    def test_plan_delete_knowledge_heuristic(self, planner):
        steps = planner.plan("delete_knowledge", "删除那条旧笔记")
        assert len(steps) == 5
        action_types = [s.action_type for s in steps]
        assert action_types == ["retrieve", "resolve", "verify", "tool_call", "compose"]
        # Delete steps should be high risk
        assert steps[2].risk_level == "high"
        assert steps[2].requires_confirmation is True
        assert steps[3].risk_level == "high"
        # All steps have step_id
        for s in steps:
            assert s.step_id
            assert s.status == "planned"

    def test_plan_solidify_conversation_heuristic(self, planner):
        steps = planner.plan("solidify_conversation", "把讨论结论沉淀下来")
        assert len(steps) == 4
        action_types = [s.action_type for s in steps]
        assert action_types == ["retrieve", "compose", "verify", "tool_call"]
        # Solidify steps use depends_on for ordering
        assert steps[1].depends_on == ["sol-1"]

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
        from personal_agent.core.config import Settings

        planner = DefaultTaskPlanner(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
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

    def test_router_falls_back_to_heuristic_when_llm_unavailable(self):
        from personal_agent.core.config import Settings

        router_no_llm = DefaultIntentRouter(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
        )
        entry = EntryInput(text="把刚才讨论的结论记下来")
        decision = router_no_llm.classify(entry)
        assert decision.route == "solidify_conversation"

    def test_router_delete_knowledge_heuristic_fallback(self):
        from personal_agent.core.config import Settings

        router_no_llm = DefaultIntentRouter(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
        )
        entry = EntryInput(text="删除那条关于旧部署流程的笔记")
        decision = router_no_llm.classify(entry)
        assert decision.route == "delete_knowledge"
        assert decision.risk_level == "high"
        assert decision.requires_confirmation is True

    def test_router_decision_has_all_fields(self):
        from personal_agent.core.config import Settings

        router = DefaultIntentRouter(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
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
        from personal_agent.core.config import Settings

        router = DefaultIntentRouter(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
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

    def test_context_snapshot_includes_execution_trace(self):
        wm = WorkingMemory(max_steps=10, max_tool_cache=5)
        wm.set_goal("测试任务")
        wm.execution_trace = [
            "在知识库中检索",
            "生成回答",
            "校验结果",
        ]
        snapshot = wm.context_snapshot()
        assert "执行路径" in snapshot
        assert "在知识库中检索" in snapshot
        assert "生成回答" in snapshot
        assert "校验结果" in snapshot

    def test_context_snapshot_prefers_plan_steps_over_trace(self):
        wm = WorkingMemory(max_steps=10, max_tool_cache=5)
        wm.set_goal("测试任务")
        wm.plan_steps = [
            {"step_id": "del-1", "action_type": "retrieve", "description": "检索候选笔记", "tool_name": "graph_search"},
        ]
        wm.execution_trace = ["步骤1", "步骤2"]
        snapshot = wm.context_snapshot()
        assert "当前任务计划" in snapshot
        assert "执行路径" not in snapshot


class TestPlannerValidatorRoundtrip:
    @pytest.fixture
    def planner(self):
        from personal_agent.core.config import Settings

        return DefaultTaskPlanner(
            Settings(openai_api_key=None, openai_base_url=None, openai_small_model="")
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
