from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool

from ..core.models import EntryIntent
from .base import tool_failure

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

    Agent executions are dispatched by the ``ToolNode`` embedded in the main
    orchestration graph.  ``invoke_direct`` is retained for non-agent callers
    such as the debug API and legacy synchronous helpers.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            logger.warning("Tool %s is already registered, overwriting.", tool.name)
        self._tools[tool.name] = tool

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def invoke_direct(self, name: str, **kwargs: Any) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return tool_failure(f"未找到工具：{name}")
        try:
            message = tool.invoke({
                "name": name,
                "args": kwargs,
                "id": f"direct-{name}",
                "type": "tool_call",
            })
            artifact = getattr(message, "artifact", None)
            if isinstance(artifact, dict) and "ok" in artifact:
                return artifact
            return tool_failure(str(getattr(message, "content", "工具执行失败。")))
        except Exception as exc:
            logger.exception("Direct tool execution failed for %s", name)
            return tool_failure(str(exc)[:500])

    def match_tool(self, intent: EntryIntent, description: str = "") -> BaseTool | None:
        name = _INTENT_TOOL_MAP.get(intent)
        if name and name in self._tools:
            return self._tools[name]
        lowered = description.lower()
        return next((tool for name, tool in self._tools.items() if name in lowered), None)

    def invoke_with_fallback(self, intent: EntryIntent, description: str = "", **kwargs: Any) -> dict[str, Any]:
        primary = self.match_tool(intent, description)
        if primary is not None:
            result = self.invoke_direct(primary.name, **kwargs)
            if result["ok"]:
                return result
        for name, tool in self._tools.items():
            if primary is not None and tool.name == primary.name:
                continue
            result = self.invoke_direct(name, **kwargs)
            if result["ok"]:
                return result
        return tool_failure(f"所有工具均未成功处理意图 {intent}")

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
