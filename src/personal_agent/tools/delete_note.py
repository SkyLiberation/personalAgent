from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from ..graphiti.store import GraphitiStore
from ..storage.postgres_memory_store import PostgresMemoryStore
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
    store: PostgresMemoryStore,
    graph_store: GraphitiStore,
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
        note = store.get_note(note_id)
        if note is None or note.user_id != user_id:
            return tool_response(tool_failure(f"笔记 {note_id} 不存在或不属于用户 {user_id}。"))

        if confirmed:
            try:
                chunks_before = store.get_chunks_for_parent(note_id)
                deleted_note = store.delete_note(note_id, user_id, cascade_chunks=bool(chunks_before))
                if deleted_note is None:
                    return tool_response(tool_failure(f"删除失败：笔记 {note_id} 不存在。"))
                graph_cleaned = 0
                graph_failed = 0
                if graph_store.configured():
                    for candidate in [deleted_note, *chunks_before]:
                        if not candidate.graph.episode_uuid:
                            continue
                        try:
                            if graph_store.delete_episode(candidate.graph.episode_uuid):
                                graph_cleaned += 1
                        except Exception:
                            logger.exception("Failed to delete graph episode for note %s", candidate.id)
                            graph_failed += 1
                graph_result = f"，已清理 {graph_cleaned} 个图谱 episode" if graph_cleaned else ""
                if graph_failed:
                    graph_result += f"，{graph_failed} 个图谱 episode 清理失败(已记录日志)"
                return tool_response(tool_success({
                    "deleted_note_id": note_id,
                    "title": deleted_note.body.title,
                    "message": f"已删除笔记「{deleted_note.body.title}」{graph_result}。",
                }))
            except Exception as exc:
                logger.exception("delete_note execution failed for note_id=%s", note_id)
                return tool_response(tool_failure(str(exc)[:500]))

        chunks = store.get_chunks_for_parent(note_id)
        cascade_note = "及其所有子章节笔记" if chunks else ""
        description = (
            f"将删除笔记「{note.body.title}」{cascade_note}"
            + (f"（共 {len(chunks) + 1} 条笔记）" if chunks else "")
            + "及其关联的复习卡片"
            + ("和图谱映射。" if note.graph.episode_uuid else "。")
        )
        return tool_response(tool_success({
            "note_id": note_id,
            "title": note.body.title,
            "summary": note.body.summary,
            "description": description,
            "pending_confirmation": True,
            "message": f"确认删除笔记「{note.body.title}」？",
        }))

    return delete_note
