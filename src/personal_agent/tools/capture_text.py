from __future__ import annotations

import logging
from typing import Callable

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .base import governance_extras, tool_response, tool_success

logger = logging.getLogger(__name__)


class CaptureTextArgs(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        description="用户明确要求写入长期知识库的正文；不要传入临时检索结果、工具观察文本或占位符。",
    )
    user_id: str = Field(default="default", description="长期知识归属用户 ID。")
    source_type: str = Field(default="text", description="知识来源类型，普通文本使用 text。")


def build_capture_text_tool(capture_executor: Callable) -> BaseTool:
    @tool(
        "capture_text",
        description=(
            "将用户明确要求保存的文本写入长期知识库，并生成标题、摘要、复习卡片和图谱同步状态。"
            "仅在用户表达记录、保存、固化知识时使用；不要保存临时检索结果、工具观察、占位符或未确认的草稿。"
            "返回 artifact.data.note_id/title/summary/content_preview，可作为后续展示和引用依据。"
        ),
        args_schema=CaptureTextArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            risk_level="low",
            side_effects=("write_longterm",),
            permission_scope="memory:write",
            timeout_seconds=60.0,
            max_retries=0,
            rate_limit_per_minute=30,
        ),
    )
    def capture_text(text: str, user_id: str = "default", source_type: str = "text"):
        result = capture_executor(text=text, source_type=source_type, user_id=user_id)
        return tool_response(tool_success({
            "note_id": result.note.id,
            "title": result.note.body.title,
            "summary": result.note.body.summary,
            "content_preview": result.note.body.content[:800],
            "graph_sync_status": result.note.graph_sync.status,
        }))

    return capture_text
