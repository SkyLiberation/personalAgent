from __future__ import annotations

import logging
from typing import Any

from .base import BaseTool, ToolResult, ToolSpec

logger = logging.getLogger(__name__)


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

    def execute(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"未找到工具：{name}")
        try:
            return tool.execute(**kwargs)
        except Exception as exc:
            logger.exception("Tool %s execution raised an unhandled exception", name)
            return ToolResult(ok=False, error=str(exc)[:500])

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
