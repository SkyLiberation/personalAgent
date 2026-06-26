from __future__ import annotations

import pytest

from personal_agent.planning.step_projection_validator import StepProjectionValidationResult, StepProjectionValidator
from personal_agent.kernel.contracts.execution import ExecutionStep
from langchain_core.tools import tool

from personal_agent.governance import ToolExecutor

from personal_agent.tools import governance_extras, tool_response, tool_success


def RouterDecision(route="unknown", **_kwargs):
    return route


class TestStepProjectionValidationResult:
    def test_valid_when_no_issues(self):
        result = StepProjectionValidationResult(valid=True)
        assert result.valid is True
        assert result.ok is True

    def test_invalid_when_issues_exist(self):
        result = StepProjectionValidationResult(valid=False, issues=["something wrong"])
        assert result.valid is False
        assert result.ok is False

    def test_ok_with_warnings_only(self):
        result = StepProjectionValidationResult(valid=True, warnings=["just a heads-up"])
        assert result.valid is True
        assert result.ok is True  # warnings don't affect ok


@tool(
    "dangerous_op",
    description="高风险操作",
    response_format="content_and_artifact",
    extras=governance_extras(
        risk_level="high",
        requires_confirmation=True,
        side_effects=("irreversible",),
    ),
)
def _governance_high_risk(target: str):
    return tool_response(tool_success("done"))


@tool(
    "write_op",
    description="写入操作",
    response_format="content_and_artifact",
    extras=governance_extras(side_effects=("write_longterm",)),
)
def _governance_write(content: str):
    return tool_response(tool_success("saved"))


@tool(
    "capture_text",
    description="保存生成后的草稿",
    response_format="content_and_artifact",
    extras=governance_extras(side_effects=("write_longterm",)),
)
def _deferred_capture_text(text: str):
    return tool_response(tool_success("saved"))


@tool(
    "external_op",
    description="外部操作",
    response_format="content_and_artifact",
    extras=governance_extras(side_effects=("external_network",)),
)
def _governance_external(url: str):
    return tool_response(tool_success("fetched"))


@tool(
    "graph_search",
    description="只读图谱检索",
    response_format="content_and_artifact",
    extras=governance_extras(side_effects=("read_local",)),
)
def _read_only_graph_search(query: str = ""):
    return tool_response(tool_success({"results": []}))


class TestStepProjectionValidatorGovernance:
    @pytest.fixture
    def registry(self):
        reg = ToolExecutor()
        reg.register(_governance_high_risk)
        reg.register(_governance_write)
        reg.register(_governance_external)
        reg.register(_deferred_capture_text)
        return reg

    @pytest.fixture
    def validator(self, registry):
        return StepProjectionValidator(tool_executor=registry)

    @pytest.fixture
    def default_decision(self):
        return RouterDecision(route="ask")

    def test_tool_call_missing_tool_name_is_blocking(self, validator, default_decision):
        steps = [
            ExecutionStep(step_id="s1", action_type="tool_call", description="调用工具"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("tool_name" in issue for issue in result.issues)

    def test_unregistered_tool_is_blocking_when_executor_is_available(self, validator, default_decision):
        steps = [
            ExecutionStep(
                step_id="s1",
                action_type="tool_call",
                description="调用工具",
                tool_name="missing_tool",
            ),
        ]
        result = validator.validate(steps, default_decision)
        assert any("missing_tool" in issue and "未在 ToolExecutor 中注册" in issue for issue in result.issues)

    def test_tool_requires_confirmation_but_step_does_not_warns(self, validator, default_decision):
        steps = [
            ExecutionStep(step_id="s1", action_type="tool_call", description="高风险操作",
                     tool_name="dangerous_op", risk_level="high"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("要求确认" in w for w in result.warnings)

    def test_tool_requires_confirmation_and_step_has_it_passes(self, validator, default_decision):
        steps = [
            ExecutionStep(step_id="s1", action_type="tool_call", description="高风险操作",
                     tool_name="dangerous_op", risk_level="high",
                     requires_confirmation=True),
        ]
        result = validator.validate(steps, default_decision)
        assert not any("要求确认" in w for w in result.warnings)

    def test_tool_writes_longterm_without_confirmation_warns(self, validator, default_decision):
        steps = [
            ExecutionStep(step_id="s1", action_type="tool_call", description="写入操作",
                     tool_name="write_op", risk_level="low"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("修改长期知识" in w for w in result.warnings)

    def test_tool_writes_longterm_with_high_risk_no_warning(self, validator, default_decision):
        steps = [
            ExecutionStep(step_id="s1", action_type="tool_call", description="写入操作",
                     tool_name="write_op", risk_level="high"),
        ]
        result = validator.validate(steps, default_decision)
        assert not any("修改长期知识" in w for w in result.warnings)

    def test_tool_accesses_external_warns(self, validator, default_decision):
        steps = [
            ExecutionStep(step_id="s1", action_type="tool_call", description="外部操作",
                     tool_name="external_op", risk_level="low"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("访问外部网络" in w for w in result.warnings)

    def test_tool_risk_higher_than_step_warns(self, validator, default_decision):
        steps = [
            ExecutionStep(step_id="s1", action_type="tool_call", description="高风险操作",
                     tool_name="dangerous_op", risk_level="low"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("固有风险等级" in w for w in result.warnings)

    def test_deep_param_validation_missing_required(self, validator, default_decision):
        steps = [
            ExecutionStep(step_id="s1", action_type="tool_call", description="高风险操作",
                     tool_name="dangerous_op", tool_input={}, risk_level="high"),
        ]
        result = validator.validate(steps, default_decision)
        assert any("tool_input 参数校验失败" in i for i in result.issues)

    def test_deep_param_validation_passes_with_valid_input(self, validator, default_decision):
        steps = [
            ExecutionStep(step_id="s1", action_type="tool_call", description="高风险操作",
                     tool_name="dangerous_op",
                     tool_input={"target": "note-123"}, risk_level="high"),
        ]
        result = validator.validate(steps, default_decision)
        assert not any("tool_input 参数校验失败" in i for i in result.issues)

    def test_capture_text_may_receive_text_from_upstream_compose(self, validator):
        decision = RouterDecision(route="solidify_conversation")
        steps = [
            ExecutionStep(step_id="sol-1", action_type="compose", description="生成知识草稿"),
            ExecutionStep(
                step_id="sol-2", action_type="tool_call", description="保存草稿",
                tool_name="capture_text", depends_on=["sol-1"],
            ),
        ]

        result = validator.validate(steps, decision)

        assert result.valid
        assert not any("tool_input 参数校验失败" in issue for issue in result.issues)

    def test_solidify_allows_intermediate_verify_step_when_dag_is_valid(self, validator):
        decision = RouterDecision(route="solidify_conversation")
        steps = [
            ExecutionStep(step_id="sol-1", action_type="compose", description="生成知识草稿"),
            ExecutionStep(step_id="sol-2", action_type="verify", description="校验是否已写入",
                     depends_on=["sol-1"]),
            ExecutionStep(step_id="sol-3", action_type="tool_call", description="保存草稿",
                     tool_name="capture_text", depends_on=["sol-2"]),
        ]

        result = validator.validate(steps, decision)

        assert result.valid


class TestReActValidation:
    """Validate ReAct-specific checks in StepProjectionValidator."""

    @pytest.fixture
    def registry(self):
        reg = ToolExecutor()
        reg.register(_read_only_graph_search)
        return reg

    @pytest.fixture
    def validator(self, registry):
        return StepProjectionValidator(tool_executor=registry)

    @pytest.fixture
    def default_decision(self):
        return RouterDecision(route="ask")

    def test_react_validates_allowed_tools_registered(self, validator, default_decision):
        steps = [
            ExecutionStep(
                step_id="s1", action_type="retrieve", description="test",
                execution_mode="react",
                allowed_tools=["graph_search", "nonexistent_tool"],
                max_iterations=3,
            ),
        ]
        result = validator.validate(steps, default_decision)
        assert any("nonexistent_tool" in i and "未在 ToolExecutor 中注册" in i for i in result.issues)

    def test_react_warns_max_iterations_over_cap(self, validator, default_decision):
        steps = [
            ExecutionStep(
                step_id="s1", action_type="retrieve", description="test",
                execution_mode="react",
                allowed_tools=["graph_search"],
                max_iterations=10,
            ),
        ]
        result = validator.validate(steps, default_decision)
        assert any("max_iterations" in w and "超过上限" in w for w in result.warnings)

    def test_react_valid_step_passes(self, validator, default_decision):
        steps = [
            ExecutionStep(
                step_id="s1", action_type="retrieve", description="检索",
                execution_mode="react",
                allowed_tools=["graph_search"],
                max_iterations=3,
            ),
        ]
        result = validator.validate(steps, default_decision)
        assert result.ok
