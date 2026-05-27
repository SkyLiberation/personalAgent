from __future__ import annotations

import pytest
from langchain_core.tools import tool

from personal_agent.tools import ToolExecutor, tool_failure, tool_property, tool_response, tool_schema, tool_success


@tool("echo", description="回显输入内容", response_format="content_and_artifact")
def echo(message: str):
    return tool_response(tool_success(f"echo: {message}"))


@tool("failer", description="总是失败", response_format="content_and_artifact")
def failer():
    return tool_response(tool_failure("工具执行失败"))


@tool(
    "dangerous",
    description="高风险操作",
    response_format="content_and_artifact",
    extras={"risk_level": "high", "requires_confirmation": True},
)
def dangerous(target: str):
    return tool_response(tool_success(target))


class TestToolExecutor:
    @pytest.fixture
    def executor(self):
        return ToolExecutor()

    def test_registers_langchain_tool(self, executor):
        executor.register(echo)
        assert len(executor) == 1
        assert executor.get("echo") is echo
        assert executor.list_tools()[0].name == "echo"

    def test_tool_schema_is_inferred_from_annotation(self):
        schema = tool_schema(echo)
        assert schema["properties"]["message"]["type"] == "string"
        assert schema["required"] == ["message"]

    def test_tool_metadata_carries_governance(self):
        assert tool_property(dangerous, "risk_level") == "high"
        assert tool_property(dangerous, "requires_confirmation") is True

    def test_invokes_directly_for_non_graph_callers(self, executor):
        executor.register(echo)
        result = executor.invoke_direct("echo", message="hello")
        assert result["ok"] is True
        assert result["data"] == "echo: hello"

    def test_missing_tool_returns_error(self, executor):
        result = executor.invoke_direct("nonexistent")
        assert result["ok"] is False
        assert "未找到工具" in result["error"]

    def test_tool_failure_artifact_is_returned(self, executor):
        executor.register(failer)
        result = executor.invoke_direct("failer")
        assert result["ok"] is False
        assert "工具执行失败" in result["error"]

    def test_direct_invocation_validates_required_argument(self, executor):
        executor.register(echo)
        result = executor.invoke_direct("echo")
        assert result["ok"] is False
        assert "message" in result["error"]

    def test_overwrite_keeps_single_tool(self, executor):
        executor.register(echo)
        executor.register(echo)
        assert len(executor) == 1
