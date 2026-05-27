from __future__ import annotations

import logging
from datetime import datetime, timedelta

from langchain_core.tools import BaseTool, tool

from ..core.models import PendingAction, local_now
from ..graphiti.store import GraphitiStore
from ..storage.postgres_memory_store import PostgresMemoryStore
from ..storage.postgres_pending_action_store import PostgresPendingActionStore
from .base import tool_failure, tool_response, tool_success

logger = logging.getLogger(__name__)


def build_delete_note_tool(
    store: PostgresMemoryStore,
    graph_store: GraphitiStore,
    pending_store: PostgresPendingActionStore,
) -> BaseTool:
    @tool(
        "delete_note",
        description="根据笔记 ID 删除笔记、关联复习卡片和图谱映射。执行删除前需要用户确认。",
        response_format="content_and_artifact",
        extras={"risk_level": "high", "requires_confirmation": True, "writes_longterm": True},
    )
    def delete_note(
        note_id: str,
        user_id: str = "default",
        confirmed: bool = False,
        action_id: str = "",
        token: str = "",
    ):
        note = store.get_note(note_id)
        if note is None or note.user_id != user_id:
            return tool_response(tool_failure(f"笔记 {note_id} 不存在或不属于用户 {user_id}。"))

        if confirmed:
            if not action_id or not token:
                return tool_response(tool_failure("确认删除需要提供 action_id 和 token。"))
            action = pending_store.confirm(action_id, token, user_id)
            if action is None:
                return tool_response(tool_failure("确认失败：action_id 或 token 无效、已过期或已处理。"))
            try:
                chunks_before = store.get_chunks_for_parent(note_id)
                deleted_note = store.delete_note(note_id, user_id, cascade_chunks=bool(chunks_before))
                if deleted_note is None:
                    return tool_response(tool_failure(f"删除失败：笔记 {note_id} 不存在。"))
                graph_cleaned = 0
                graph_failed = 0
                if graph_store.configured():
                    for candidate in [deleted_note, *chunks_before]:
                        if not candidate.graph_episode_uuid:
                            continue
                        try:
                            if graph_store.delete_episode(candidate.graph_episode_uuid):
                                graph_cleaned += 1
                        except Exception:
                            logger.exception("Failed to delete graph episode for note %s", candidate.id)
                            graph_failed += 1
                graph_result = f"，已清理 {graph_cleaned} 个图谱 episode" if graph_cleaned else ""
                if graph_failed:
                    graph_result += f"，{graph_failed} 个图谱 episode 清理失败(已记录日志)"
                pending_store.mark_executed(action_id, user_id)
                return tool_response(tool_success({
                    "deleted_note_id": note_id,
                    "title": deleted_note.title,
                    "message": f"已删除笔记「{deleted_note.title}」{graph_result}。",
                }))
            except Exception as exc:
                logger.exception("delete_note execution failed for note_id=%s", note_id)
                return tool_response(tool_failure(str(exc)[:500]))

        chunks = store.get_chunks_for_parent(note_id)
        cascade_note = "及其所有子章节笔记" if chunks else ""
        pending = PendingAction(
            user_id=user_id,
            action_type="delete_note",
            target_id=note_id,
            title=f"删除笔记「{note.title}」{cascade_note}",
            description=(
                f"将删除笔记「{note.title}」{cascade_note}"
                + (f"（共 {len(chunks) + 1} 条笔记）" if chunks else "")
                + "及其关联的复习卡片"
                + ("和图谱映射。" if note.graph_episode_uuid else "。")
            ),
            payload={
                "note_id": note_id, "note_title": note.title,
                "note_summary": note.summary, "graph_episode_uuid": note.graph_episode_uuid,
            },
            expires_at=local_now() + timedelta(hours=1),
        )
        pending_store.create(pending)
        return tool_response(tool_success({
            "action_id": pending.id,
            "token": pending.token,
            "note_id": note_id,
            "title": note.title,
            "summary": note.summary,
            "pending_confirmation": True,
            "expires_at": pending.expires_at.isoformat(),
            "message": f"确认删除笔记「{note.title}」？",
        }))

    return delete_note
