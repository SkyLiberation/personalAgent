from __future__ import annotations

import logging
from typing import Callable

from langchain_core.tools import BaseTool, tool

from .base import tool_failure, tool_response, tool_success

logger = logging.getLogger(__name__)


def build_capture_text_tool(capture_executor: Callable) -> BaseTool:
    @tool(
        "capture_text",
        description="将文本内容采集为一条知识笔记，生成标题、摘要和复习卡片。",
        response_format="content_and_artifact",
        extras={"risk_level": "low", "writes_longterm": True},
    )
    def capture_text(text: str, user_id: str = "default", source_type: str = "text"):
        try:
            result = capture_executor(text=text, source_type=source_type, user_id=user_id)
            return tool_response(tool_success({
                "note_id": result.note.id,
                "title": result.note.body.title,
                "summary": result.note.body.summary,
                "content_preview": result.note.body.content[:800],
                "graph_sync_status": result.note.graph_sync.status,
            }))
        except Exception as exc:
            logger.exception("capture_text failed")
            return tool_response(tool_failure(str(exc)[:500]))

    return capture_text
