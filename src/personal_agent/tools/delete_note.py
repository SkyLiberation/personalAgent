from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from ..memory import MemoryFacade
from .base import governance_extras, tool_failure, tool_response, tool_success

logger = logging.getLogger(__name__)


class DeleteNoteArgs(BaseModel):
    note_id: str = Field(..., min_length=1, description="要删除的长期知识笔记 ID，必须由 resolve 步骤解析得到。")
    user_id: str = Field(default="default", description="笔记归属用户 ID。")
    confirmed: bool = Field(default=False, description="首次调用必须为 false；用户确认后由恢复流程设为 true。")
    idempotency_key: str = Field(
        default="",
        description="确认执行删除时必须提供的幂等 key，用于避免重复删除副作用。",
    )


def build_delete_note_tool(
    memory: MemoryFacade,
) -> BaseTool:
    @tool(
        "delete_note",
        description=(
            "根据 note_id 删除长期知识笔记、关联复习卡片和图谱映射。"
            "这是高风险删除工具，不能在 ReAct 自主探索中调用。首次调用必须 confirmed=false，只返回确认 payload；"
            "只有用户确认后，恢复流程才允许以 confirmed=true 和 idempotency_key 执行真实删除。"
            "返回 artifact.data.pending_confirmation 表示需要暂停等待确认，真实删除后返回 deleted_note_id/title/message。"
        ),
        args_schema=DeleteNoteArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            risk_level="high",
            requires_confirmation=True,
            side_effects=("delete_longterm",),
            permission_scope="memory:delete",
            idempotency_key_required=True,
            audit_required=True,
            timeout_seconds=20.0,
            max_retries=0,
            rate_limit_per_minute=10,
        ),
    )
    def delete_note(
        note_id: str,
        user_id: str = "default",
        confirmed: bool = False,
        idempotency_key: str = "",
    ):
        if confirmed:
            try:
                result = memory.delete_note_confirmed(note_id, user_id)
                if not result.ok:
                    return tool_response(tool_failure(result.error or f"删除失败：笔记 {note_id} 不存在。"))
                return tool_response(tool_success({
                    "deleted_note_id": note_id,
                    "title": result.title,
                    "message": result.message,
                    "graph_cleaned": result.graph_cleaned,
                    "graph_failed": result.graph_failed,
                }))
            except Exception as exc:
                logger.exception("delete_note execution failed for note_id=%s", note_id)
                return tool_response(tool_failure(str(exc)[:500]))

        result = memory.build_delete_confirmation(note_id, user_id)
        if not result.ok:
            return tool_response(tool_failure(result.error or f"笔记 {note_id} 不存在或不属于用户 {user_id}。"))
        return tool_response(tool_success({
            "note_id": note_id,
            "title": result.title,
            "summary": result.summary,
            "description": result.description,
            "pending_confirmation": True,
            "message": result.message,
        }))

    return delete_note
