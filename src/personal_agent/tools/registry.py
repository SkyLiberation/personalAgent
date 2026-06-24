from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool

from personal_agent.core.models import EntryIntent
from personal_agent.policy import PolicyEngine
from personal_agent.tools.base import ToolExposure, tool_failure, tool_governance
from personal_agent.tools.gateway import IdempotencyStore, ToolAuditSink, ToolGateway, ToolGatewayContext

logger = logging.getLogger(__name__)

_INTENT_TOOL_MAP: dict[EntryIntent, str] = {
    "capture_text": "capture_text",
    "capture_link": "capture_url",
    "capture_file": "capture_upload",
    "ask": "graph_search",
    "delete_knowledge": "delete_note",
    "solidify_conversation": "capture_text",
    "review_digest": "review_digest",
    "consolidate_knowledge": "consolidate_knowledge",
    "inspect_knowledge_gaps": "inspect_knowledge_gaps",
    "create_research_subscription": "create_research_subscription",
    "manage_research": "list_research_subscriptions",
    "maintain_knowledge": "find_similar_notes",
    "inspect_operations": "inspect_worker_queue",
    "inspect_workflow": "inspect_workflow_run",
}


class ToolExecutor:
    """Registered LangChain tools and non-graph administrative invocation.

    Agent executions are dispatched by the LangGraph-native ``ToolGateway`` node
    embedded in the orchestration graph. ``invoke_direct`` uses the same gateway
    so non-agent callers share policy and audit behavior.
    """

    def __init__(
        self,
        audit_sink: ToolAuditSink | None = None,
        *,
        idempotency_store: IdempotencyStore | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._gateway = ToolGateway(
            audit_sink=audit_sink,
            idempotency_store=idempotency_store,
            policy_engine=policy_engine,
        )

    def register(self, tool: BaseTool) -> None:
        if tool.name in self:
            logger.warning("Tool %s is already registered, overwriting.", tool.name)
        self._gateway.register(tool)

    def list_tools(self, *, exposures: set[ToolExposure] | None = None) -> list[BaseTool]:
        tools = self._gateway.list_tools()
        if exposures is None:
            return tools
        return [
            tool for tool in tools
            if tool_governance(tool).exposure in exposures
        ]

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
                run_id=kwargs.get("run_id"),
                user_id=kwargs.get("user_id"),
                session_id=kwargs.get("session_id"),
                source_platform=kwargs.get("source_platform"),
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
