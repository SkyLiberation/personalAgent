from __future__ import annotations

import pytest

from personal_agent.tools.base import BaseTool, ToolResult, ToolSpec
from personal_agent.tools.registry import ToolRegistry


class _EchoTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="echo",
            description="回显输入内容",
            input_schema={"message": "string"},
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
