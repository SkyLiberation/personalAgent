from __future__ import annotations

import pytest

from personal_agent.agent.plan_validator import PlanValidationResult, PlanValidator
from personal_agent.agent.planner import PlanStep
from personal_agent.agent.router import RouterDecision
from personal_agent.tools import ToolRegistry
from personal_agent.tools.base import BaseTool, ToolResult, ToolSpec


class TestPlanValidationResult:
    def test_valid_when_no_issues(self):
        result = PlanValidationResult(valid=True)
        assert result.valid is True
        assert result.ok is True

    def test_invalid_when_issues_exist(self):
        result = PlanValidationResult(valid=False, issues=["something wrong"])
        assert result.valid is False
        assert result.ok is False

    def test_ok_with_warnings_only(self):
        result = PlanValidationResult(valid=True, warnings=["just a heads-up"])
        assert result.valid is True
        assert result.ok is True  # warnings don't affect ok


class TestPlanValidatorStructural:
    @pytest.fixture
    def validator(self):
        return PlanValidator()

    @pytest.fixture
    def default_decision(self):
        return RouterDecision(route="ask")

    def test_empty_plan_is_invalid(self, validator, default_decision):
        result = validator.validate([], default_decision)
        assert not result.valid
        assert any("为空" in i or "至少" in i for i in result.issues)

    def test_valid_plan_passes(self, validator, default_decision):
        steps = [
            PlanStep(step_id="ask-1", action_type="retrieve", description="检索知识库",
                     tool_name="graph_search", expected_output="匹配笔记"),
            PlanStep(step_id="ask-2", action_type="compose", description="生成回答",
                     depends_on=["ask-1"]),
            PlanStep(step_id="ask-3", action_type="verify", description="校验结果",
                     depends_on=["ask-2"]),
        ]
        result = validator.validate(steps, default_decision)
        assert result.valid
        assert len(result.issues) == 0
        assert len(result.warnings) == 0

    def test_duplicate_step_ids_flagged(self, validator, default_decision):
        steps = [
            PlanStep(step_id="dup-1", action_type="retrieve", description="检索"),
            PlanStep(step_id="dup-1", action_type="compose", description="整理"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("重复" in i for i in result.issues)

    def test_empty_step_id_flagged(self, validator, default_decision):
        steps = [
            PlanStep(step_id="", action_type="retrieve", description="检索"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("为空" in i for i in result.issues)

    def test_whitespace_only_step_id_flagged(self, validator, default_decision):
        steps = [
            PlanStep(step_id="   ", action_type="retrieve", description="检索"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("为空" in i for i in result.issues)

    def test_invalid_action_type_rejected(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="invalid_action", description="test"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("无效" in i for i in result.issues)

    def test_empty_description_warns(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description=""),
        ]
        result = validator.validate(steps, default_decision)
        assert any("description" in w for w in result.warnings)

    def test_missing_tool_name_when_tool_call(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="调用工具",
                     tool_name=None),
        ]
        result = validator.validate(steps, default_decision)
        assert any("tool_name" in i for i in result.issues)

    def test_unknown_tool_name_warns(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="调用工具",
                     tool_name="nonexistent_tool"),
        ]
        result = validator.validate(steps, default_decision)
        # When no ToolRegistry is injected, unknown tool is a warning (not blocking)
        assert any("ToolRegistry" in w or "tool_name" in w for w in result.warnings)

    def test_invalid_risk_level_rejected(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     risk_level="critical"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("risk_level" in i for i in result.issues)

    def test_invalid_on_failure_rejected(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     on_failure="panic"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("on_failure" in i for i in result.issues)

    def test_non_planned_status_auto_corrected(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     status="running"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("已自动修正" in w for w in result.warnings)
        assert result.corrected_steps is not None
        assert result.corrected_steps[0].status == "planned"

    def test_confirm_with_low_risk_warns(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     requires_confirmation=True, risk_level="low"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("requires_confirmation" in w for w in result.warnings)


class TestPlanValidatorDependency:
    @pytest.fixture
    def validator(self):
        return PlanValidator()

    @pytest.fixture
    def default_decision(self):
        return RouterDecision(route="ask")

    def test_depends_on_nonexistent_step(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索"),
            PlanStep(step_id="s2", action_type="compose", description="生成",
                     depends_on=["missing-id"]),
        ]
        result = validator.validate(steps, default_decision)
        assert any("引用了不存在的" in i for i in result.issues)

    def test_circular_dependency_detected(self, validator, default_decision):
        steps = [
            PlanStep(step_id="a", action_type="retrieve", description="检索",
                     depends_on=["b"]),
            PlanStep(step_id="b", action_type="compose", description="生成",
                     depends_on=["a"]),
        ]
        result = validator.validate(steps, default_decision)
        assert any("循环依赖" in i for i in result.issues)

    def test_linear_chain_no_cycle_ok(self, validator, default_decision):
        steps = [
            PlanStep(step_id="a", action_type="retrieve", description="检索"),
            PlanStep(step_id="b", action_type="compose", description="生成",
                     depends_on=["a"]),
            PlanStep(step_id="c", action_type="verify", description="校验",
                     depends_on=["b"]),
        ]
        result = validator.validate(steps, default_decision)
        assert not any("循环" in i for i in result.issues)

    def test_self_dependency_is_cycle(self, validator, default_decision):
        steps = [
            PlanStep(step_id="a", action_type="retrieve", description="检索",
                     depends_on=["a"]),
        ]
        result = validator.validate(steps, default_decision)
        assert any("循环依赖" in i for i in result.issues)

    def test_verify_without_depends_warns(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索"),
            PlanStep(step_id="s2", action_type="verify", description="校验"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("depends_on 为空" in w for w in result.warnings)


class TestPlanValidatorCrossValidation:
    @pytest.fixture
    def validator(self):
        return PlanValidator()

    def test_router_requires_tools_but_no_tool_call(self, validator):
        decision = RouterDecision(route="ask", requires_tools=True)
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索"),
            PlanStep(step_id="s2", action_type="compose", description="生成"),
        ]
        result = validator.validate(steps, decision)
        assert any("requires_tools" in w for w in result.warnings)

    def test_router_requires_retrieval_but_no_retrieve(self, validator):
        decision = RouterDecision(route="ask", requires_retrieval=True)
        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="调用工具",
                     tool_name="graph_search"),
        ]
        result = validator.validate(steps, decision)
        assert any("requires_retrieval" in w for w in result.warnings)

    def test_router_requires_confirmation_but_none_in_steps(self, validator):
        decision = RouterDecision(route="delete_knowledge", requires_confirmation=True)
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索"),
        ]
        result = validator.validate(steps, decision)
        assert any("requires_confirmation" in i for i in result.issues)

    def test_router_requires_confirmation_satisfied(self, validator):
        decision = RouterDecision(route="delete_knowledge", requires_confirmation=True)
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索"),
            PlanStep(step_id="s2", action_type="verify", description="校验",
                     requires_confirmation=True, risk_level="high"),
        ]
        result = validator.validate(steps, decision)
        assert not any("requires_confirmation" in i for i in result.issues)

    def test_risk_escalation_warning(self, validator):
        decision = RouterDecision(route="ask", risk_level="low")
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     risk_level="high"),
        ]
        result = validator.validate(steps, decision)
        assert any("高于" in w for w in result.warnings)

    def test_risk_not_escalated_when_same_level(self, validator):
        decision = RouterDecision(route="ask", risk_level="high")
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索",
                     risk_level="high"),
        ]
        result = validator.validate(steps, decision)
        assert not any("高于" in w for w in result.warnings)


class TestPlanValidatorPlanLevel:
    @pytest.fixture
    def validator(self):
        return PlanValidator()

    @pytest.fixture
    def default_decision(self):
        return RouterDecision(route="ask")

    def test_plan_ends_with_retrieve_warns(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索"),
            PlanStep(step_id="s2", action_type="retrieve", description="再检索"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("最后一步" in w for w in result.warnings)

    def test_plan_ends_with_compose_ok(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="retrieve", description="检索"),
            PlanStep(step_id="s2", action_type="compose", description="生成回答"),
        ]
        result = validator.validate(steps, default_decision)
        assert not any("最后一步" in w for w in result.warnings)

    def test_all_verify_steps_warns(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="verify", description="校验A",
                     depends_on=["s0"]),
            PlanStep(step_id="s2", action_type="verify", description="校验B"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("都是 verify" in w for w in result.warnings)

    def test_delete_knowledge_heuristic_plan_passes(self, validator):
        decision = RouterDecision(route="delete_knowledge", risk_level="high",
                                  requires_confirmation=True, requires_planning=True)
        steps = [
            PlanStep(step_id="del-1", action_type="retrieve", description="检索待删除的候选笔记",
                     tool_name="graph_search", expected_output="匹配的候选笔记列表",
                     success_criteria="命中至少 1 条笔记"),
            PlanStep(step_id="del-2", action_type="verify", description="安全校验",
                     depends_on=["del-1"], risk_level="high", requires_confirmation=True,
                     expected_output="安全校验通过或返回待确认列表"),
            PlanStep(step_id="del-3", action_type="tool_call", description="执行删除",
                     tool_name="delete_note", depends_on=["del-2"], risk_level="high",
                     on_failure="abort"),
            PlanStep(step_id="del-4", action_type="compose", description="汇总删除结果",
                     depends_on=["del-3"]),
        ]
        result = validator.validate(steps, decision)
        assert result.valid

    def test_solidify_conversation_heuristic_plan_passes(self, validator):
        decision = RouterDecision(route="solidify_conversation", risk_level="low",
                                  requires_planning=True)
        steps = [
            PlanStep(step_id="sol-1", action_type="retrieve", description="获取最近对话记录",
                     expected_output="最近若干轮对话"),
            PlanStep(step_id="sol-2", action_type="compose", description="提取候选事实和结论",
                     depends_on=["sol-1"]),
            PlanStep(step_id="sol-3", action_type="verify", description="校验提取内容",
                     depends_on=["sol-2"]),
            PlanStep(step_id="sol-4", action_type="tool_call", description="写入知识库",
                     tool_name="capture_text", depends_on=["sol-3"]),
        ]
        result = validator.validate(steps, decision)
        assert result.valid


class _GovernanceHighRiskTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="dangerous_op",
            description="高风险操作",
            input_schema={
                "type": "object",
                "properties": {"target": {"type": "string"}},
                "required": ["target"],
            },
            risk_level="high",
            requires_confirmation=True,
        )

    def execute(self, **kwargs):
        return ToolResult(ok=True, data="done")


class _GovernanceWriteTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="write_op",
            description="写入操作",
            input_schema={
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
            },
            writes_longterm=True,
        )

    def execute(self, **kwargs):
        return ToolResult(ok=True, data="saved")


class _GovernanceExternalTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="external_op",
            description="外部操作",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            accesses_external=True,
        )

    def execute(self, **kwargs):
        return ToolResult(ok=True, data="fetched")


class _ReadOnlyGraphSearchTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="graph_search",
            description="只读图谱检索",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
            risk_level="low",
        )

    def execute(self, **kwargs):
        return ToolResult(ok=True, data={"results": []})


class TestPlanValidatorGovernance:
    @pytest.fixture
    def registry(self):
        reg = ToolRegistry()
        reg.register(_GovernanceHighRiskTool())
        reg.register(_GovernanceWriteTool())
        reg.register(_GovernanceExternalTool())
        return reg

    @pytest.fixture
    def validator(self, registry):
        return PlanValidator(tool_registry=registry)

    @pytest.fixture
    def default_decision(self):
        return RouterDecision(route="ask")

    def test_tool_requires_confirmation_but_step_does_not_warns(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="高风险操作",
                     tool_name="dangerous_op", risk_level="high"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("要求确认" in w for w in result.warnings)

    def test_tool_requires_confirmation_and_step_has_it_passes(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="高风险操作",
                     tool_name="dangerous_op", risk_level="high",
                     requires_confirmation=True),
        ]
        result = validator.validate(steps, default_decision)
        assert not any("要求确认" in w for w in result.warnings)

    def test_tool_writes_longterm_without_confirmation_warns(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="写入操作",
                     tool_name="write_op", risk_level="low"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("写入长期知识" in w for w in result.warnings)

    def test_tool_writes_longterm_with_high_risk_no_warning(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="写入操作",
                     tool_name="write_op", risk_level="high"),
        ]
        result = validator.validate(steps, default_decision)
        assert not any("写入长期知识" in w for w in result.warnings)

    def test_tool_accesses_external_warns(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="外部操作",
                     tool_name="external_op", risk_level="low"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("访问外部网络" in w for w in result.warnings)

    def test_tool_risk_higher_than_step_warns(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="高风险操作",
                     tool_name="dangerous_op", risk_level="low"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("固有风险等级" in w for w in result.warnings)

    def test_deep_param_validation_missing_required(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="高风险操作",
                     tool_name="dangerous_op", tool_input={}, risk_level="high"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("tool_input 参数校验失败" in i for i in result.issues)

    def test_deep_param_validation_passes_with_valid_input(self, validator, default_decision):
        steps = [
            PlanStep(step_id="s1", action_type="tool_call", description="高风险操作",
                     tool_name="dangerous_op",
                     tool_input={"target": "note-123"}, risk_level="high"),
        ]
        result = validator.validate(steps, default_decision)
        assert not any("tool_input 参数校验失败" in i for i in result.issues)


class TestReActValidation:
    """Validate ReAct-specific checks in PlanValidator."""

    @pytest.fixture
    def registry(self):
        reg = ToolRegistry()
        reg.register(_ReadOnlyGraphSearchTool())
        return reg

    @pytest.fixture
    def validator(self, registry):
        return PlanValidator(tool_registry=registry)

    @pytest.fixture
    def default_decision(self):
        return RouterDecision(route="ask")

    def test_react_blocks_high_risk(self, validator, default_decision):
        steps = [
            PlanStep(
                step_id="s1", action_type="retrieve", description="test",
                execution_mode="react", risk_level="high",
                allowed_tools=["graph_search"], max_iterations=3,
            ),
        ]
        result = validator.validate(steps, default_decision)
        assert any("execution_mode='react' 不允许 risk_level='high'" in i for i in result.issues)

    def test_react_blocks_requires_confirmation(self, validator, default_decision):
        steps = [
            PlanStep(
                step_id="s1", action_type="retrieve", description="test",
                execution_mode="react", requires_confirmation=True,
                allowed_tools=["graph_search"], max_iterations=3,
            ),
        ]
        result = validator.validate(steps, default_decision)
        assert any("execution_mode='react' 不允许 requires_confirmation=True" in i for i in result.issues)

    def test_react_validates_allowed_tools_registered(self, validator, default_decision):
        steps = [
            PlanStep(
                step_id="s1", action_type="retrieve", description="test",
                execution_mode="react",
                allowed_tools=["graph_search", "nonexistent_tool"],
                max_iterations=3,
            ),
        ]
        result = validator.validate(steps, default_decision)
        assert any("nonexistent_tool" in i and "未在 ToolRegistry 中注册" in i for i in result.issues)

    def test_react_warns_max_iterations_over_cap(self, validator, default_decision):
        steps = [
            PlanStep(
                step_id="s1", action_type="retrieve", description="test",
                execution_mode="react",
                allowed_tools=["graph_search"],
                max_iterations=10,
            ),
        ]
        result = validator.validate(steps, default_decision)
        assert any("max_iterations" in w and "超过上限" in w for w in result.warnings)

    def test_react_invalid_execution_mode(self, validator, default_decision):
        steps = [
            PlanStep(
                step_id="s1", action_type="retrieve", description="test",
                execution_mode="invalid",
                allowed_tools=[], max_iterations=3,
            ),
        ]
        result = validator.validate(steps, default_decision)
        assert any("execution_mode" in i and "无效" in i for i in result.issues)

    def test_react_valid_step_passes(self, validator, default_decision):
        steps = [
            PlanStep(
                step_id="s1", action_type="retrieve", description="检索",
                execution_mode="react",
                allowed_tools=["graph_search"],
                max_iterations=3,
            ),
        ]
        result = validator.validate(steps, default_decision)
        assert result.ok
