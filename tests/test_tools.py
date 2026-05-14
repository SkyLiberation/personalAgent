from __future__ import annotations

import pytest

from personal_agent.tools.base import BaseTool, ToolResult, ToolSpec, validate_tool_input
from personal_agent.tools.registry import ToolRegistry


class _EchoTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="echo",
            description="回显输入内容",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "要回显的消息"},
                },
                "required": ["message"],
            },
        )

    def execute(self, **kwargs):
        message = kwargs.get("message", "")
        return ToolResult(ok=True, data=f"echo: {message}")


class _FailingTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="failer", description="总是失败")

    def execute(self, **kwargs):
        raise RuntimeError("工具执行失败")


class TestToolSpec:
    def test_creates_with_required_fields(self):
        spec = ToolSpec(name="test", description="测试工具")
        assert spec.name == "test"
        assert spec.description == "测试工具"
        assert spec.input_schema == {}

    def test_creates_with_input_schema(self):
        schema = {"url": "string", "depth": "int"}
        spec = ToolSpec(name="scraper", description="网页抓取", input_schema=schema)
        assert spec.input_schema == schema


class TestToolResult:
    def test_ok_result(self):
        result = ToolResult(ok=True, data="success")
        assert result.ok is True
        assert result.data == "success"
        assert result.error is None

    def test_error_result(self):
        result = ToolResult(ok=False, error="something went wrong")
        assert result.ok is False
        assert result.error == "something went wrong"
        assert result.data is None


class TestToolRegistry:
    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    @pytest.fixture
    def echo_tool(self):
        return _EchoTool()

    def test_register_adds_tool(self, registry, echo_tool):
        registry.register(echo_tool)
        assert len(registry) == 1
        assert "echo" in registry

    def test_list_returns_specs(self, registry, echo_tool):
        registry.register(echo_tool)
        specs = registry.list_tools()
        assert len(specs) == 1
        assert specs[0].name == "echo"

    def test_get_returns_tool(self, registry, echo_tool):
        registry.register(echo_tool)
        assert registry.get("echo") is echo_tool

    def test_get_missing_returns_none(self, registry):
        assert registry.get("nonexistent") is None

    def test_execute_calls_tool(self, registry, echo_tool):
        registry.register(echo_tool)
        result = registry.execute("echo", message="hello")
        assert result.ok is True
        assert result.data == "echo: hello"

    def test_execute_missing_returns_error(self, registry):
        result = registry.execute("nonexistent")
        assert result.ok is False
        assert "未找到工具" in result.error

    def test_execute_catches_exceptions(self, registry):
        registry.register(_FailingTool())
        result = registry.execute("failer")
        assert result.ok is False
        assert "工具执行失败" in result.error

    def test_len_counts_registered_tools(self, registry, echo_tool):
        assert len(registry) == 0
        registry.register(echo_tool)
        assert len(registry) == 1

    def test_overwrite_logs_warning(self, registry, echo_tool):
        registry.register(echo_tool)
        registry.register(echo_tool)  # overwrite
        assert len(registry) == 1

    def test_execute_with_schema_validation_rejects_missing_required(self, registry, echo_tool):
        registry.register(echo_tool)
        result = registry.execute("echo", validate_schema=True)
        assert result.ok is False
        assert "缺少必需参数" in result.error

    def test_execute_with_schema_validation_rejects_wrong_type(self, registry, echo_tool):
        registry.register(echo_tool)
        result = registry.execute("echo", message=123, validate_schema=True)
        assert result.ok is False
        assert "类型错误" in result.error

    def test_execute_skip_schema_validation(self, registry, echo_tool):
        registry.register(echo_tool)
        result = registry.execute("echo", message=123, validate_schema=False)
        assert result.ok is True

    def test_execute_with_schema_validation_passes_valid_input(self, registry, echo_tool):
        registry.register(echo_tool)
        result = registry.execute("echo", message="hello", validate_schema=True)
        assert result.ok is True
        assert result.data == "echo: hello"


class TestValidateToolInput:
    def test_empty_schema_returns_no_errors(self):
        errors = validate_tool_input({}, {"key": "value"})
        assert errors == []

    def test_non_object_schema_returns_no_errors(self):
        errors = validate_tool_input({"type": "array"}, {"key": "value"})
        assert errors == []

    def test_missing_required_field(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        errors = validate_tool_input(schema, {})
        assert any("缺少必需参数: name" in e for e in errors)

    def test_null_value_on_required_field(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        errors = validate_tool_input(schema, {"name": None})
        assert any("缺少必需参数: name" in e for e in errors)

    def test_type_mismatch_string_vs_number(self):
        schema = {
            "type": "object",
            "properties": {"age": {"type": "integer"}},
        }
        errors = validate_tool_input(schema, {"age": "twenty"})
        assert any("类型错误" in e for e in errors)

    def test_type_mismatch_boolean_vs_string(self):
        schema = {
            "type": "object",
            "properties": {"confirmed": {"type": "boolean"}},
        }
        errors = validate_tool_input(schema, {"confirmed": "yes"})
        assert any("类型错误" in e for e in errors)

    def test_valid_input_passes(self):
        schema = {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "count": {"type": "integer"},
                "enabled": {"type": "boolean"},
            },
            "required": ["text"],
        }
        errors = validate_tool_input(schema, {"text": "hello", "count": 5, "enabled": True})
        assert errors == []

    def test_extra_keys_are_ignored(self):
        schema = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        }
        errors = validate_tool_input(schema, {"text": "hello", "extra": "ignored"})
        assert errors == []

    def test_number_accepts_int_and_float(self):
        schema = {
            "type": "object",
            "properties": {"value": {"type": "number"}},
        }
        assert validate_tool_input(schema, {"value": 42}) == []
        assert validate_tool_input(schema, {"value": 3.14}) == []

    def test_null_on_optional_field_is_ok(self):
        schema = {
            "type": "object",
            "properties": {"optional": {"type": "string"}},
        }
        errors = validate_tool_input(schema, {"optional": None})
        assert errors == []
