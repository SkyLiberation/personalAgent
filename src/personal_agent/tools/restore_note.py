from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field, model_validator

from personal_agent.tools.base import governance_extras, tool_failure, tool_response, tool_success

if TYPE_CHECKING:
    from personal_agent.memory import MemoryFacade

logger = logging.getLogger(__name__)


class RestoreNoteArgs(BaseModel):
    note_id: str = Field(default="", description="要恢复的长期知识笔记 ID；未提供 snapshot_id 时按该笔记最近删除快照恢复。")
    snapshot_id: str = Field(default="", description="删除快照 ID；提供后优先按快照恢复。")
    user_id: str = Field(default="default", description="笔记归属用户 ID。")
    confirmed: bool = Field(default=False, description="恢复属于高风险写入，执行时必须为 true。")
    idempotency_key: str = Field(
        default="",
        description="确认执行恢复时必须提供的幂等 key，用于避免重复恢复副作用。",
    )

    @model_validator(mode="after")
    def _has_restore_target(self) -> "RestoreNoteArgs":
        if not self.note_id.strip() and not self.snapshot_id.strip():
            raise ValueError("note_id or snapshot_id is required.")
        return self


def build_restore_note_tool(memory: MemoryFacade) -> BaseTool:
    @tool(
        "restore_note",
        description=(
            "从删除快照恢复长期知识笔记、子章节和关联复习卡片。"
            "这是高风险恢复工具，必须 confirmed=true 且提供 idempotency_key 后才执行。"
        ),
        args_schema=RestoreNoteArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            risk_level="high",
            requires_confirmation=True,
            side_effects=("write_longterm",),
            permission_scope="memory:write",
            idempotency_key_required=True,
            audit_required=True,
            timeout_seconds=20.0,
            max_retries=0,
            rate_limit_per_minute=10,
        ),
    )
    def restore_note(
        note_id: str = "",
        snapshot_id: str = "",
        user_id: str = "default",
        confirmed: bool = False,
        idempotency_key: str = "",
    ):
        if not confirmed:
            return tool_response(tool_failure("restore_note 必须在确认后执行。", error_kind="permission"))
        try:
            result = memory.restore_note_confirmed(
                note_id=note_id or None,
                snapshot_id=snapshot_id or None,
                user_id=user_id,
            )
            if not result.ok:
                return tool_response(tool_failure(result.error or "恢复失败。"))
            return tool_response(tool_success({
                "restored_note_id": result.note_id,
                "snapshot_id": result.snapshot_id,
                "title": result.title,
                "message": result.message,
                "restored_note_count": len(result.restored_notes),
                "restored_review_count": len(result.restored_reviews),
            }))
        except Exception as exc:
            logger.exception("restore_note execution failed note_id=%s snapshot_id=%s", note_id, snapshot_id)
            return tool_response(tool_failure(str(exc)[:500]))

    return restore_note
