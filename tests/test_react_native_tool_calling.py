"""P5 验证：原生 tool-calling ReAct 路径的框架兼容性证据.

ReAct 迭代节点（``_react._node_react_iterate``）现在直接消费模型原生
``tool_calls`` 构造 ``AIMessage``，是唯一路径（无兼容旗标）。本文件保留两类
跨框架兼容性证据，供 P6（``ToolNode`` 替换 ``ToolGateway.invoke_graph``）决策：

1. 标准 langgraph ``ToolNode(messages_key='tool_messages')`` 能消费原生
   ``AIMessage`` 并完整保留 ``content_and_artifact`` 的 ``artifact`` 属性。
2. ``ToolNode`` 的 ``wrap_tool_call`` middleware 可作为治理/审计接入点。
3. 现有 ``ToolGateway.invoke_graph`` 能消费原生 ``AIMessage`` 并返回带
   ``artifact`` 的 ``ToolMessage``（治理边界不变）。
4. ``_node_consume_react_tool_result`` 能消费网关返回的 ``ToolMessage``，
   ReAct 推进正常。

ReAct 迭代节点本身的单元测试在 ``test_orchestration.py::TestPhase4ReActIterateNode``。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from personal_agent.governance import ToolExecutor
from personal_agent.governance.policy import PolicyEngine
from personal_agent.kernel.config import OpenAIConfig, Settings
from personal_agent.orchestration.orchestration_contexts import ReactContext
from personal_agent.orchestration.orchestration_models import (
    AgentGraphState,
    ReactSubState,
    StepExecutionState,
)
from personal_agent.tools.base import governance_extras


class _GraphSearchArgs(BaseModel):
    question: str = Field(..., min_length=1, description="检索问题。")
    user_id: str = Field(default="default", description="用户 ID。")


def _build_fake_graph_search_tool():
    @tool(
        "graph_search",
        description="在个人知识图谱中检索实体、关系、事实。只读，不访问外网。",
        args_schema=_GraphSearchArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="low",
            side_effects=("read_local",),
            permission_scope="memory:read",
            timeout_seconds=15.0,
            rate_limit_per_minute=60,
        ),
    )
    def graph_search(question: str, user_id: str = "default"):
        return (
            "graph-hit",
            {
                "ok": True,
                "data": {"answer": f"关于 {question} 的图谱证据", "entity_names": ["X"]},
                "error": None,
                "evidence": [],
            },
        )

    return graph_search


def _react_context(settings: Settings, tool_executor: ToolExecutor) -> ReactContext:
    return ReactContext(
        settings=settings,
        tool_executor=tool_executor,
        policy_engine=PolicyEngine(),
    )


def _settings() -> Settings:
    return Settings(
        data_dir="./data",
        openai=OpenAIConfig(
            api_key="sk-test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1-mini",
            small_model="gpt-4.1-nano",
        ),
    )


def _react_state(allowed_tools: list[str], prompt: str = "检索 X") -> AgentGraphState:
    return AgentGraphState(
        run_id="r-native",
        react=ReactSubState(
            step_id="ask-1",
            iteration_index=0,
            max_iterations=3,
            allowed_tools=allowed_tools,
            user_prompt=prompt,
            done=False,
        ),
        step_execution=StepExecutionState(
            steps=[{"step_id": "ask-1", "status": "running"}],
            current_step_index=0,
        ),
    )


# ---------------------------------------------------------------------------
# 1. 标准 ToolNode 兼容性（P6 方向）：消费原生 AIMessage 且保留 artifact
# ---------------------------------------------------------------------------


class TestStandardToolNodeCompat:
    def test_tool_node_consumes_native_aimessage_and_preserves_artifact(self):
        from langgraph.graph import END, START, StateGraph
        from langgraph.prebuilt import ToolNode

        graph_search = _build_fake_graph_search_tool()
        builder = StateGraph(dict)
        builder.add_node("tools", ToolNode([graph_search], messages_key="tool_messages"))
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)
        graph = builder.compile()

        native_call_id = "call_abc123"
        aim = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "graph_search",
                    "args": {"question": "服务降级"},
                    "id": native_call_id,
                    "type": "tool_call",
                }
            ],
        )
        out = graph.invoke({"tool_messages": [aim]})

        tm = out["tool_messages"][-1]
        assert isinstance(tm, ToolMessage)
        assert tm.tool_call_id == native_call_id
        artifact = getattr(tm, "artifact", None)
        assert artifact is not None
        assert artifact["ok"] is True
        assert artifact["data"]["answer"] == "关于 服务降级 的图谱证据"

    def test_tool_node_wrap_tool_call_can_intercept_for_audit(self):
        """证明治理可经 wrap_tool_call 以 middleware 形式接入（P6 路径）。"""
        from langgraph.graph import END, START, StateGraph
        from langgraph.prebuilt import ToolNode
        from langgraph.prebuilt.tool_node import ToolCallRequest

        graph_search = _build_fake_graph_search_tool()
        audit_log: list[dict[str, Any]] = []

        def audit_wrapper(request: ToolCallRequest, execute):
            outcome = execute(request)
            artifact = getattr(outcome, "artifact", None)
            audit_log.append({
                "tool": request.tool_call["name"],
                "id": request.tool_call["id"],
                "ok": artifact.get("ok") if isinstance(artifact, dict) else None,
            })
            return outcome

        builder = StateGraph(dict)
        builder.add_node(
            "tools",
            ToolNode([graph_search], messages_key="tool_messages", wrap_tool_call=audit_wrapper),
        )
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)
        graph = builder.compile()

        aim = AIMessage(
            content="",
            tool_calls=[{"name": "graph_search", "args": {"question": "q"}, "id": "c1", "type": "tool_call"}],
        )
        graph.invoke({"tool_messages": [aim]})

        assert len(audit_log) == 1
        assert audit_log[0]["tool"] == "graph_search"
        assert audit_log[0]["id"] == "c1"


# ---------------------------------------------------------------------------
# 2. ToolGateway 消费原生 AIMessage（治理/审计边界不变）
# ---------------------------------------------------------------------------


class TestGatewayConsumesNativeMessage:
    def test_gateway_invoke_graph_consumes_native_aimessage_and_artifact(self):
        tool_executor = ToolExecutor(policy_engine=PolicyEngine())
        tool_executor.register(_build_fake_graph_search_tool())
        gateway_node = tool_executor.graph_node()

        native_call_id = "call-native-gw"
        state = _react_state(["graph_search"])
        aim = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "graph_search",
                    "args": {"question": "服务降级"},
                    "id": native_call_id,
                    "type": "tool_call",
                }
            ],
        )
        state.tool_messages = [aim]
        state.tool_tracking = state.tool_tracking.model_copy(
            update={
                "active_context": "react",
                "pending_call_id": native_call_id,
                "pending_tool_name": "graph_search",
                "pending_tool_input": {"question": "服务降级"},
                "pending_step_id": "ask-1",
            }
        )

        out = gateway_node(state)

        tm = out["tool_messages"][0]
        assert isinstance(tm, ToolMessage)
        assert tm.tool_call_id == native_call_id
        artifact = getattr(tm, "artifact", None)
        assert artifact is not None
        assert artifact["ok"] is True
        assert "answer" in artifact["data"]

    def test_consume_react_tool_result_advances_loop(self):
        from personal_agent.orchestration.orchestration_nodes._react import _node_consume_react_tool_result

        tool_executor = ToolExecutor(policy_engine=PolicyEngine())
        ctx = _react_context(_settings(), tool_executor)
        native_call_id = "call-native-cons"
        state = _react_state(["graph_search"])
        state.react.pending_thought = "检索"
        state.react.pending_tool = "graph_search"
        state.react.pending_input = {"question": "X"}
        tm = ToolMessage(
            content="graph-hit",
            tool_call_id=native_call_id,
            artifact={
                "ok": True,
                "data": {"answer": "X 证据"},
                "error": None,
                "evidence": [],
            },
        )
        state.tool_messages = [tm]
        state.tool_tracking = state.tool_tracking.model_copy(
            update={
                "active_context": "react",
                "pending_call_id": native_call_id,
                "pending_tool_name": "graph_search",
                "pending_tool_input": {"question": "X"},
                "pending_step_id": "ask-1",
                "pending_react_iteration": 0,
            }
        )

        result = _node_consume_react_tool_result(state, deps=ctx)

        assert result["react"].iteration_index == 1
        assert result["react"].status == "running"
        obs = result["react"].iterations[-1].get("observation", "")
        assert "X 证据" in obs
        assert result["react"].pending_thought == ""


# ---------------------------------------------------------------------------
# 3. _begin_tool_call 透传原生 call_id
# ---------------------------------------------------------------------------


class TestBeginToolCallNativeId:
    def test_begin_tool_call_passes_native_call_id(self):
        from personal_agent.orchestration.orchestration_nodes._tooling import _begin_tool_call

        state = _react_state(["graph_search"])
        aim = _begin_tool_call(
            state,
            context="react",
            tool_name="graph_search",
            tool_input={"question": "X"},
            step_id="ask-1",
            suffix="react:ask-1:0",
            iteration=0,
            call_id="call_native_xyz",
        )

        assert aim.tool_calls[0]["id"] == "call_native_xyz"
        assert state.tool_tracking.pending_call_id == "call_native_xyz"

    def test_begin_tool_call_falls_back_to_synthetic_id(self):
        from personal_agent.orchestration.orchestration_nodes._tooling import _begin_tool_call

        state = _react_state(["graph_search"])
        aim = _begin_tool_call(
            state,
            context="react",
            tool_name="graph_search",
            tool_input={"question": "X"},
            step_id="ask-1",
            suffix="react:ask-1:0",
            iteration=0,
        )

        assert aim.tool_calls[0]["id"].startswith("r-native:")
        assert state.tool_tracking.pending_call_id == aim.tool_calls[0]["id"]
