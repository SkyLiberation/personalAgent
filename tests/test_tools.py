from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from personal_agent.agent.orchestration_models import AgentGraphState, ReactSubState, ToolTrackingSubState
from personal_agent.tools import (
    InMemoryToolAuditSink,
    ToolExecutor,
    governance_extras,
    tool_failure,
    tool_governance,
    tool_invocation_event,
    tool_response,
    tool_schema,
    tool_success,
)


@tool(
    "echo",
    description="回显输入内容",
    response_format="content_and_artifact",
    extras=governance_extras(side_effects=("none",), permission_scope="test:read"),
)
def echo(message: str):
    return tool_response(tool_success(f"echo: {message}"))


@tool(
    "failer",
    description="总是失败",
    response_format="content_and_artifact",
    extras=governance_extras(side_effects=("none",), permission_scope="test:read"),
)
def failer():
    return tool_response(tool_failure("工具执行失败"))


@tool("ungoverned", description="缺少治理元数据", response_format="content_and_artifact")
def ungoverned():
    return tool_response(tool_success("ok"))


@tool(
    "dangerous",
    description="高风险操作",
    response_format="content_and_artifact",
    extras=governance_extras(
        risk_level="high",
        requires_confirmation=True,
        side_effects=("irreversible",),
        permission_scope="dangerous:execute",
        idempotency_key_required=True,
    ),
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
        governance = tool_governance(dangerous)
        assert governance.risk_level == "high"
        assert governance.requires_confirmation is True
        assert governance.side_effects == ("irreversible",)
        assert governance.permission_scope == "dangerous:execute"
        assert governance.idempotency_key_required is True

    def test_tool_without_governance_is_rejected(self):
        with pytest.raises(ValueError):
            tool_governance(ungoverned)

    def test_tool_invocation_event_has_audit_shape(self):
        event = tool_invocation_event(
            dangerous,
            tool_call_id="call-1",
            input={"target": "note-1", "idempotency_key": "idem-1"},
            output=tool_success({"deleted": True}),
            execution_mode="direct",
            step_id="step-1",
            thread_id="thread-1",
            user_id="user-1",
            latency_ms=12.3,
        )

        assert event["tool_name"] == "dangerous"
        assert event["artifact_ok"] is True
        assert event["risk_level"] == "high"
        assert event["requires_confirmation"] is True
        assert event["side_effects"] == ["irreversible"]
        assert event["permission_scope"] == "dangerous:execute"
        assert event["side_effect_id"] == "idem-1"

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

    def test_direct_invocation_records_gateway_audit(self):
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(echo)

        result = executor.invoke_direct("echo", message="hello", user_id="u1")

        assert result["ok"] is True
        assert len(sink.events) == 1
        assert sink.events[0]["tool_name"] == "echo"
        assert sink.events[0]["execution_mode"] == "direct"
        assert sink.events[0]["user_id"] == "u1"

    def test_high_risk_confirmed_execution_requires_idempotency_key(self):
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(dangerous)

        result = executor.invoke_direct("dangerous", target="note-1", confirmed=True)

        assert result["ok"] is False
        assert "idempotency_key" in result["error"]
        assert sink.events[0]["artifact_ok"] is False

    def test_gateway_blocks_react_write_tool_even_if_prompt_allows_it(self):
        sink = InMemoryToolAuditSink()
        executor = ToolExecutor(audit_sink=sink)
        executor.register(dangerous)

        state = AgentGraphState(
            react=ReactSubState(allowed_tools=["dangerous"]),
            tool_tracking=ToolTrackingSubState(active_context="react", pending_call_id="call-1"),
            tool_messages=[
                AIMessage(content="", tool_calls=[{
                    "name": "dangerous",
                    "args": {"target": "note-1", "confirmed": True, "idempotency_key": "idem-1"},
                    "id": "call-1",
                    "type": "tool_call",
                }])
            ],
        )
        message = executor.graph_node()(state)["tool_messages"][0]
        result = message.artifact

        assert result["ok"] is False
        assert "不允许在 ReAct" in result["error"]
        assert sink.events[0]["execution_mode"] == "react"
