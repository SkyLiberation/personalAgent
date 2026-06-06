from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool

from ..core.models import EntryIntent
from .base import tool_failure
from .gateway import ToolAuditSink, ToolGateway, ToolGatewayContext

logger = logging.getLogger(__name__)

_INTENT_TOOL_MAP: dict[EntryIntent, str] = {
    "capture_text": "capture_text",
    "capture_link": "capture_url",
    "capture_file": "capture_upload",
    "ask": "graph_search",
    "delete_knowledge": "delete_note",
    "solidify_conversation": "capture_text",
}


class ToolExecutor:
    """Registered LangChain tools and non-graph administrative invocation.

    Agent executions are dispatched by the LangGraph-native ``ToolGateway`` node
    embedded in the orchestration graph. ``invoke_direct`` uses the same gateway
    so non-agent callers share policy and audit behavior.
    """

    def __init__(self, audit_sink: ToolAuditSink | None = None) -> None:
        self._gateway = ToolGateway(audit_sink=audit_sink)

    def register(self, tool: BaseTool) -> None:
        if tool.name in self:
            logger.warning("Tool %s is already registered, overwriting.", tool.name)
        self._gateway.register(tool)

    def list_tools(self) -> list[BaseTool]:
        return self._gateway.list_tools()

    def get(self, name: str) -> BaseTool | None:
        return self._gateway.get(name)

    def graph_node(self):
        return self._gateway.invoke_graph

    def invoke_direct(self, name: str, **kwargs: Any) -> dict[str, Any]:
        if name not in self:
            return tool_failure(f"未找到工具：{name}").model_dump(mode="json")
        tool_call_id = f"direct-{name}"
        return self._gateway.invoke(
            name,
            kwargs,
            ToolGatewayContext(
                execution_mode="direct",
                tool_call_id=tool_call_id,
                user_id=kwargs.get("user_id"),
            ),
        )

    def match_tool(self, intent: EntryIntent, description: str = "") -> BaseTool | None:
        name = _INTENT_TOOL_MAP.get(intent)
        if name:
            matched = self.get(name)
            if matched is not None:
                return matched
        lowered = description.lower()
        return next((tool for tool in self.list_tools() if tool.name in lowered), None)

    def invoke_with_fallback(self, intent: EntryIntent, description: str = "", **kwargs: Any) -> dict[str, Any]:
        primary = self.match_tool(intent, description)
        if primary is not None:
            result = self.invoke_direct(primary.name, **kwargs)
            if result["ok"]:
                return result
        for tool in self.list_tools():
            if primary is not None and tool.name == primary.name:
                continue
            result = self.invoke_direct(tool.name, **kwargs)
            if result["ok"]:
                return result
        return tool_failure(f"所有工具均未成功处理意图 {intent}").model_dump(mode="json")

    def __len__(self) -> int:
        return len(self.list_tools())

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None
