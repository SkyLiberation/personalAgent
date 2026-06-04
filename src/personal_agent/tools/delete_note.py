from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool

from ..graphiti.store import GraphitiStore
from ..storage.postgres_memory_store import PostgresMemoryStore
from .base import governance_extras, tool_failure, tool_response, tool_success

logger = logging.getLogger(__name__)


def build_delete_note_tool(
    store: PostgresMemoryStore,
    graph_store: GraphitiStore,
) -> BaseTool:
    @tool(
        "delete_note",
        description="根据笔记 ID 删除笔记、关联复习卡片和图谱映射。必须先返回确认 payload，只有用户确认后才能在 confirmed=True 时执行删除。",
        response_format="content_and_artifact",
        extras=governance_extras(
            risk_level="high",
            requires_confirmation=True,
            side_effects=("delete_longterm",),
            permission_scope="memory:delete",
            idempotency_key_required=True,
            audit_required=True,
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
