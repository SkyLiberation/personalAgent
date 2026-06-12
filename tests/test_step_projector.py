from __future__ import annotations

import pytest

from personal_agent.agent.step_projector import WorkflowStepProjector, ExecutionStep
from personal_agent.agent.router import DefaultIntentRouter, RouterDecision
from personal_agent.agent.runtime import EntryResult
from personal_agent.core.models import EntryInput


class TestStepProjectorEnrichedSteps:
    @pytest.fixture
    def projector(self):
        from personal_agent.core.config import OpenAIConfig, Settings

        return WorkflowStepProjector(
            Settings(openai=OpenAIConfig(api_key=None, base_url=None, small_model=""))
        )

    def test_project_delete_knowledge_heuristic(self, projector):
        steps = projector.project("delete_knowledge", "删除那条旧笔记")
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

    def test_project_solidify_conversation_heuristic(self, projector):
        steps = projector.project("solidify_conversation", "把讨论结论沉淀下来")
        assert len(steps) == 2
        action_types = [s.action_type for s in steps]
        assert action_types == ["compose", "tool_call"]
        assert steps[1].depends_on == ["sol-1"]
        assert steps[1].requires_confirmation is False
        assert steps[1].risk_level == "low"

    def test_project_ask_is_ordinary_workflow(self, projector):
        steps = projector.project("ask", "什么是服务降级？")
        assert steps == []

    def test_project_unknown_intent_has_no_projection(self, projector):
        steps = projector.project("unknown", "随便说点什么")
        assert steps == []

    def test_project_step_has_all_required_fields(self, projector):
        steps = projector.project("delete_knowledge", "删除旧笔记")
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

    def test_projector_projects_workflow_deterministically(self):
        """The projector projects a fixed WorkflowSpec into runtime step
        projections with no LLM call. Projection is deterministic: the same
        intent always yields the same topology, every step starting in
        ``planned`` status.
        """
        from personal_agent.core.config import OpenAIConfig, Settings

        projector = WorkflowStepProjector(
            Settings(openai=OpenAIConfig(api_key=None, base_url=None, small_model=""))
        )
        steps = projector.project("delete_knowledge", "删除旧笔记")
        assert len(steps) == 4
        for s in steps:
            assert isinstance(s, ExecutionStep)
            assert s.action_type in {"retrieve", "resolve", "tool_call", "compose", "verify"}
            assert s.status == "planned"
            assert s.workflow_id == "delete_knowledge"
            assert s.workflow_version == "v1"
            assert s.workflow_step_id == s.step_id
            assert s.projection_kind == "workflow_step"


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
        assert hasattr(decision, "requires_step_projection")
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


class TestEntryResultExecutionSteps:
    def test_entry_result_includes_steps(self):
        result = EntryResult(
            intent="ask",
            reason="用户提问",
            reply_text="回答内容",
            steps=[
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
        assert len(result.steps) == 1
        assert result.steps[0]["action_type"] == "retrieve"
        assert result.steps[0]["description"] == "检索知识库"
        assert result.steps[0]["status"] == "planned"

    def test_entry_result_steps_defaults_empty(self):
        result = EntryResult(
            intent="unknown",
            reason="无法识别",
            reply_text="请重新输入",
        )
        assert result.steps == []


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
        assert result.steps == []

class TestStepProjectorValidatorRoundtrip:
    @pytest.fixture
    def projector(self):
        from personal_agent.core.config import OpenAIConfig, Settings

        return WorkflowStepProjector(
            Settings(openai=OpenAIConfig(api_key=None, base_url=None, small_model=""))
        )

    def test_heuristic_projections_pass_validation(self, projector):
        from personal_agent.agent.step_projection_validator import StepProjectionValidator
        from personal_agent.agent.router import _default_router_decision

        validator = StepProjectionValidator()

        for intent in ("delete_knowledge", "solidify_conversation"):
            decision = _default_router_decision(intent)
            steps = projector.project(intent, "测试输入")
            result = validator.validate(steps, decision)
            # Step-projecting workflows should pass validation cleanly.
            assert result.valid, f"Intent {intent} projection failed: {result.issues}"
            assert len(steps) > 0

    def test_ordinary_workflows_do_not_enter_step_projection_validation_path(self, projector):
        for intent in ("ask", "capture_text", "capture_link", "capture_file", "unknown"):
            assert projector.project(intent, "测试输入") == []

    def test_delete_note_id_may_be_supplied_by_transitive_resolve_step(self):
        from personal_agent.agent.step_projection_validator import StepProjectionValidator
        from personal_agent.agent.router import _default_router_decision
        from langchain_core.tools import tool
        from personal_agent.tools import ToolExecutor, governance_extras, tool_response, tool_success

        @tool(
            "delete_note",
            description="delete",
            response_format="content_and_artifact",
            extras=governance_extras(
                risk_level="high",
                requires_confirmation=True,
                side_effects=("delete_longterm",),
            ),
        )
        def delete_note(note_id: str):
            return tool_response(tool_success(note_id))

        executor = ToolExecutor()
        executor.register(delete_note)
        steps = [
            ExecutionStep(step_id="del-0", action_type="retrieve", description="检索候选"),
            ExecutionStep(step_id="del-1", action_type="resolve", description="定位目标", depends_on=["del-0"]),
            ExecutionStep(
                step_id="del-2",
                action_type="tool_call",
                description="删除目标",
                tool_name="delete_note",
                risk_level="high",
                requires_confirmation=True,
                depends_on=["del-1"],
            ),
            ExecutionStep(step_id="del-3", action_type="compose", description="生成结果", depends_on=["del-2"]),
        ]

        result = StepProjectionValidator(tool_executor=executor).validate(
            steps, _default_router_decision("delete_knowledge")
        )

        assert result.valid

    def test_delete_note_without_upstream_resolve_still_requires_note_id(self):
        from personal_agent.agent.step_projection_validator import StepProjectionValidator
        from personal_agent.agent.router import _default_router_decision
        from langchain_core.tools import tool
        from personal_agent.tools import ToolExecutor, governance_extras, tool_response, tool_success

        @tool(
            "delete_note",
            description="delete",
            response_format="content_and_artifact",
            extras=governance_extras(
                risk_level="high",
                requires_confirmation=True,
                side_effects=("delete_longterm",),
            ),
        )
        def delete_note(note_id: str):
            return tool_response(tool_success(note_id))

        executor = ToolExecutor()
        executor.register(delete_note)
        steps = [
            ExecutionStep(
                step_id="del-1",
                action_type="tool_call",
                description="删除目标",
                tool_name="delete_note",
            ),
        ]

        result = StepProjectionValidator(tool_executor=executor).validate(
            steps, _default_router_decision("delete_knowledge")
        )

        assert not result.valid
        assert any("note_id" in issue for issue in result.issues)


class TestWorkflowRegistry:
    def test_delete_knowledge_requires_projection(self):
        from personal_agent.agent.workflow import WORKFLOW_REGISTRY

        spec = WORKFLOW_REGISTRY.select("delete_knowledge")
        assert spec.requires_projection is True
        assert spec.intent == "delete_knowledge"

    def test_solidify_requires_projection(self):
        from personal_agent.agent.workflow import WORKFLOW_REGISTRY

        spec = WORKFLOW_REGISTRY.select("solidify_conversation")
        assert spec.requires_projection is True

    def test_branch_workflows_do_not_require_projection(self):
        from personal_agent.agent.workflow import WORKFLOW_REGISTRY

        for intent in ("ask", "capture_text", "summarize_thread", "direct_answer"):
            assert WORKFLOW_REGISTRY.select(intent).requires_projection is False
            assert WORKFLOW_REGISTRY.project(intent) == []

    def test_workflow_specs_expose_governance_metadata(self):
        from personal_agent.agent.workflow import WORKFLOW_REGISTRY

        delete_spec = WORKFLOW_REGISTRY.select("delete_knowledge")
        assert delete_spec.allows_llm_decision_node is True
        assert delete_spec.allows_tools is True
        assert delete_spec.has_high_risk_side_effect is True
        assert delete_spec.hitl_policy == "required_for_delete"
        assert delete_spec.recovery_policy == "checkpoint_step"

        ask_spec = WORKFLOW_REGISTRY.select("ask")
        assert ask_spec.requires_projection is False
        assert ask_spec.allows_llm_decision_node is True
        assert ask_spec.recovery_policy == "branch"

    def test_workflow_specs_have_node_level_contracts(self):
        from personal_agent.agent.workflow import WORKFLOW_REGISTRY, WorkflowStepSpec

        ask_spec = WORKFLOW_REGISTRY.select("ask")
        assert ask_spec.steps
        assert all(isinstance(step, WorkflowStepSpec) for step in ask_spec.steps)
        assert any(step.llm_decision_node == "query_understanding" for step in ask_spec.steps)
        assert any(step.allowed_tools == ("graph_search", "web_search") for step in ask_spec.steps)
        assert WORKFLOW_REGISTRY.project("ask") == []

        delete_spec = WORKFLOW_REGISTRY.select("delete_knowledge")
        delete_step = next(step for step in delete_spec.steps if step.step_id == "del-3")
        assert delete_step.side_effects == ("delete_longterm",)
        assert delete_step.hitl_policy == "required_for_delete"
        assert delete_step.recovery_policy == "abort"

    def test_unknown_intent_falls_back_to_unknown_spec(self):
        from personal_agent.agent.workflow import WORKFLOW_REGISTRY

        spec = WORKFLOW_REGISTRY.select("does-not-exist")
        assert spec.intent == "unknown"

    def test_projections_are_independent(self):
        """Each projection returns fresh steps so concurrent runs never share
        mutable execution state.
        """
        from personal_agent.agent.workflow import WORKFLOW_REGISTRY

        first = WORKFLOW_REGISTRY.project("delete_knowledge")
        second = WORKFLOW_REGISTRY.project("delete_knowledge")
        assert [s.step_id for s in first] == [s.step_id for s in second]
        # Mutating one projection must not leak into the next.
        first[0].status = "running"
        first[2].tool_input["note_id"] = "n-1"
        assert second[0].status == "planned"
        assert "note_id" not in second[2].tool_input
        third = WORKFLOW_REGISTRY.project("delete_knowledge")
        assert third[0].status == "planned"
        assert "note_id" not in third[2].tool_input
