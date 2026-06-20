from __future__ import annotations

import logging
from typing import Callable

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .base import governance_extras, tool_failure, tool_response, tool_success

logger = logging.getLogger(__name__)


class ConsolidateNotesArgs(BaseModel):
    note_ids: list[str] = Field(
        ...,
        min_length=2,
        description="要整理为一篇综述的若干笔记 ID，至少两条。",
    )
    topic: str = Field(
        ...,
        min_length=1,
        description="本次整理的主题，用于生成综述标题和组织内容。",
    )
    user_id: str = Field(default="default", description="知识归属用户 ID。")


def build_consolidate_notes_tool(consolidate_executor: Callable) -> BaseTool:
    @tool(
        "consolidate_notes",
        description=(
            "将同一主题下的多条已有笔记整理成一篇结构化综述并写入知识库；"
            "原笔记被标记为已被综述取代（superseded），仍可恢复但默认退出检索。"
            "仅在用户明确要求归纳/整理/合并某主题的多条笔记时使用。"
            "返回 artifact.data.note_id（综述）、superseded（被取代的原笔记 ID 列表）和 failed（处理失败的原笔记）。"
        ),
        args_schema=ConsolidateNotesArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            risk_level="low",
            side_effects=("write_longterm",),
            permission_scope="memory:write",
            timeout_seconds=120.0,
            max_retries=0,
            rate_limit_per_minute=10,
        ),
    )
    def consolidate_notes(note_ids: list[str], topic: str, user_id: str = "default"):
        result = consolidate_executor(note_ids=note_ids, topic=topic, user_id=user_id)
        if not result.get("ok"):
            return tool_response(tool_failure(result.get("error") or "主题整理失败。"))
        return tool_response(tool_success({
            "note_id": result["note_id"],
            "title": result.get("title", ""),
            "summary": result.get("summary", ""),
            "superseded": result.get("superseded", []),
            "failed": result.get("failed", []),
        }))

    return consolidate_notes
