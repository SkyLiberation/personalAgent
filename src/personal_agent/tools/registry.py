from __future__ import annotations

import logging
from typing import Any

from ..core.models import EntryIntent
from .base import BaseTool, ToolResult, ToolSpec, validate_tool_input

logger = logging.getLogger(__name__)

_INTENT_TOOL_MAP: dict[EntryIntent, str] = {
    "capture_text": "capture_text",
    "capture_link": "capture_url",
    "capture_file": "capture_upload",
    "ask": "graph_search",
    "delete_knowledge": "delete_note",
    "solidify_conversation": "capture_text",
}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        name = tool.spec.name
        if name in self._tools:
            logger.warning("Tool %s is already registered, overwriting.", name)
        self._tools[name] = tool

    def list_tools(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def execute(self, name: str, validate_schema: bool = True, **kwargs: Any) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"未找到工具：{name}")
        if validate_schema:
            schema_errors = validate_tool_input(tool.spec.input_schema, kwargs)
            if schema_errors:
                return ToolResult(ok=False, error="参数校验失败: " + "; ".join(schema_errors))
        try:
            return tool.execute(**kwargs)
        except Exception as exc:
            logger.exception("Tool %s execution raised an unhandled exception", name)
            return ToolResult(ok=False, error=str(exc)[:500])

    def match_tool(self, intent: EntryIntent, description: str = "") -> BaseTool | None:
        """Select the best tool for a given intent.

        Uses an explicit intent→tool mapping first, then falls back to
        keyword matching against tool names and descriptions.
        """
        tool_name = _INTENT_TOOL_MAP.get(intent)
        if tool_name and tool_name in self._tools:
            return self._tools[tool_name]

        # Keyword-based fallback
        desc_lower = description.lower()
        for name, tool in self._tools.items():
            if name in desc_lower:
                return tool
        return None

    def execute_with_fallback(self, intent: EntryIntent, description: str = "", **kwargs: Any) -> ToolResult:
        """Execute the best-matching tool, falling back to alternatives on failure.

        Tries the primary tool matched by intent, then tries any other
        registered tool as fallback. Returns the first successful result.
        """
        primary = self.match_tool(intent, description)
        if primary is not None:
            result = self._safe_execute(primary, **kwargs)
            if result.ok:
                return result
            logger.warning("Primary tool %s failed for intent=%s: %s", primary.spec.name, intent, result.error)
        else:
            logger.warning("No primary tool matched for intent=%s", intent)

        # Fallback: try any other tool
        for name, tool in self._tools.items():
            if primary is not None and name == primary.spec.name:
                continue
            result = self._safe_execute(tool, **kwargs)
            if result.ok:
                logger.info("Fallback tool %s succeeded for intent=%s", name, intent)
                return result

        return ToolResult(ok=False, error=f"所有工具均未成功处理意图 {intent}")

    def _safe_execute(self, tool: BaseTool, **kwargs: Any) -> ToolResult:
        try:
            return tool.execute(**kwargs)
        except Exception as exc:
            logger.exception("Tool %s execution raised an unhandled exception", tool.spec.name)
            return ToolResult(ok=False, error=str(exc)[:500])

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
