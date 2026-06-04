from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool

from ..core.observability import record_tool_audit
from .base import tool_failure, tool_governance, tool_invocation_event

logger = logging.getLogger(__name__)


class ToolAuditSink(Protocol):
    def record(self, event: dict[str, Any]) -> None:
        """Persist or forward a normalized tool invocation event."""


@dataclass(slots=True)
class InMemoryToolAuditSink:
    events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, event: dict[str, Any]) -> None:
        self.events.append(event)


@dataclass(frozen=True, slots=True)
class ToolGatewayContext:
    execution_mode: str
    tool_call_id: str
    step_id: str | None = None
    thread_id: str | None = None
    user_id: str | None = None
    react_allowed_tools: frozenset[str] = frozenset()


class ToolGateway:
    """LangGraph-native boundary for policy, execution, and audit.

    The gateway keeps the same ``tool_messages`` contract expected by the
    graph, but centralizes project-specific governance before a real tool can
    touch storage or the network.
    """

    def __init__(self, audit_sink: ToolAuditSink | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        self.audit_sink = audit_sink

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def invoke(self, name: str, args: dict[str, Any], context: ToolGatewayContext) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return tool_failure(f"未找到工具：{name}")

        started = perf_counter()
        output: dict[str, Any]
        try:
            violation = self._validate_policy(tool, args, context)
            if violation is not None:
                output = tool_failure(violation)
            else:
                message = tool.invoke({
                    "name": name,
                    "args": args,
                    "id": context.tool_call_id,
                    "type": "tool_call",
                })
                artifact = getattr(message, "artifact", None)
                if isinstance(artifact, dict) and "ok" in artifact:
                    output = artifact
                else:
                    output = tool_failure(str(getattr(message, "content", "工具执行失败。")))
        except Exception as exc:
            logger.exception("Tool gateway execution failed for %s", name)
            output = tool_failure(str(exc)[:500])

        self._record_invocation(tool, args, output, context, (perf_counter() - started) * 1000)
        return output

    def invoke_graph(self, state: Any) -> dict[str, list[ToolMessage]]:
        call = self._latest_tool_call(state)
        if call is None:
            return {
                "tool_messages": [
                    ToolMessage(
                        content="工具节点未收到待执行的工具调用。",
                        tool_call_id="",
                        artifact=tool_failure("工具节点未收到待执行的工具调用。"),
                    )
                ]
            }

        name = str(call.get("name", ""))
        args = call.get("args", {})
        normalized_args = args if isinstance(args, dict) else {}
        call_id = str(call.get("id", ""))
        context = self._context_from_state(state, call_id)
        artifact = self.invoke(name, normalized_args, context)
        content = (
            str(artifact.get("data"))
            if artifact.get("ok")
            else str(artifact.get("error") or "工具执行失败。")
        )
        return {
            "tool_messages": [
                ToolMessage(content=content, tool_call_id=call_id, artifact=artifact)
            ]
        }

    def _validate_policy(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        context: ToolGatewayContext,
    ) -> str | None:
        governance = tool_governance(tool)
        if context.execution_mode == "react":
            if tool.name not in context.react_allowed_tools:
                return f"工具 {tool.name} 不在当前 ReAct 允许列表中。"
            blocked_effects = {"write_longterm", "delete_longterm", "send_external", "irreversible"}
            if (
                governance.risk_level == "high"
                or governance.requires_confirmation
                or blocked_effects.intersection(governance.side_effects)
            ):
                return f"工具 {tool.name} 不允许在 ReAct 自主执行中调用。"

        is_confirmed_execution = bool(args.get("confirmed"))
        if governance.requires_confirmation and governance.risk_level == "high" and is_confirmed_execution:
            if governance.idempotency_key_required and not str(args.get("idempotency_key", "")).strip():
                return f"工具 {tool.name} 执行高风险确认动作时缺少 idempotency_key。"
        return None

    def _record_invocation(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        output: dict[str, Any],
        context: ToolGatewayContext,
        latency_ms: float,
    ) -> None:
        event = tool_invocation_event(
            tool,
            tool_call_id=context.tool_call_id,
            input=args,
            output=output,
            execution_mode=context.execution_mode,
            step_id=context.step_id,
            thread_id=context.thread_id,
            user_id=context.user_id,
            latency_ms=latency_ms,
        )
        if self.audit_sink is not None:
            self.audit_sink.record(event)
        record_tool_audit(event)
        logger.info("Tool invocation completed", extra={"tool_invocation": event})

    def _context_from_state(self, state: Any, call_id: str) -> ToolGatewayContext:
        tracking = getattr(state, "tool_tracking", None)
        react = getattr(state, "react", None)
        active_context = getattr(tracking, "active_context", None)
        execution_mode = "react" if active_context == "react" else "deterministic"
        return ToolGatewayContext(
            execution_mode=execution_mode,
            tool_call_id=call_id,
            step_id=getattr(tracking, "pending_step_id", None),
            thread_id=getattr(state, "thread_id", None),
            user_id=getattr(state, "user_id", None),
            react_allowed_tools=frozenset(getattr(react, "allowed_tools", []) or []),
        )

    @staticmethod
    def _latest_tool_call(state: Any) -> dict[str, Any] | None:
        for message in reversed(getattr(state, "tool_messages", []) or []):
            if isinstance(message, AIMessage) and message.tool_calls:
                return message.tool_calls[-1]
        return None
