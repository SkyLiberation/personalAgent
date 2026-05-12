from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from .base import BaseTool, ToolResult, ToolSpec

if TYPE_CHECKING:
    from ..agent.runtime import AgentRuntime

logger = logging.getLogger(__name__)


class CaptureTextTool(BaseTool):
    """Capture plain text into a KnowledgeNote, reusing the capture pipeline."""

    def __init__(self, runtime: "AgentRuntime") -> None:
        self._runtime = runtime

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="capture_text",
            description="将文本内容采集为一条知识笔记，生成标题、摘要和复习卡片。",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要采集的文本内容"},
                    "user_id": {"type": "string", "description": "用户标识，默认 'default'"},
                    "source_type": {"type": "string", "description": "来源类型，默认 'text'"},
                },
                "required": ["text"],
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        text = kwargs.get("text")
        if not text or not isinstance(text, str):
            return ToolResult(ok=False, error="缺少有效的 text 参数。")
        user_id = str(kwargs.get("user_id", "default"))
        source_type = str(kwargs.get("source_type", "text"))
        try:
            result = self._runtime.execute_capture(
                text=text, source_type=source_type, user_id=user_id,
            )
            return ToolResult(ok=True, data={
                "note_id": result.note.id,
                "title": result.note.title,
                "summary": result.note.summary,
                "graph_enabled": result.graph_enabled,
            })
        except Exception as exc:
            logger.exception("CaptureTextTool failed")
            return ToolResult(ok=False, error=str(exc)[:500])
