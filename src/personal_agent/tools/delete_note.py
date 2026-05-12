from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from ..core.models import PendingAction
from ..graphiti.store import GraphitiStore
from ..storage.memory_store import LocalMemoryStore
from ..storage.pending_action_store import PendingActionStore
from .base import BaseTool, ToolResult, ToolSpec

logger = logging.getLogger(__name__)


class DeleteNoteTool(BaseTool):
    """Delete a note by ID with HITL confirmation via PendingActionStore.

    Phase 1 (confirmed=False): Create a PendingAction and return confirmation token.
    Phase 2 (confirmed=True, action_id, token): Execute the deletion.
    """

    def __init__(
        self,
        store: LocalMemoryStore,
        graph_store: GraphitiStore,
        pending_store: PendingActionStore,
    ) -> None:
        self._store = store
        self._graph_store = graph_store
        self._pending_store = pending_store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="delete_note",
            description="根据笔记 ID 删除笔记、关联的复习卡片和图谱映射。需要分两步确认：先返回 action_id 和 token，确认后再执行。",
            input_schema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "要删除的笔记 ID"},
                    "user_id": {"type": "string", "description": "用户标识，默认 'default'"},
                    "confirmed": {"type": "boolean", "description": "是否已确认删除，默认 false"},
                    "action_id": {"type": "string", "description": "确认时提供 action_id"},
                    "token": {"type": "string", "description": "确认时提供 token"},
                },
                "required": ["note_id"],
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        note_id = kwargs.get("note_id")
        if not note_id or not isinstance(note_id, str):
            return ToolResult(ok=False, error="缺少有效的 note_id 参数。")
        user_id = str(kwargs.get("user_id", "default"))
        confirmed = bool(kwargs.get("confirmed", False))

        note = self._store.get_note(note_id)
        if note is None or note.user_id != user_id:
            return ToolResult(ok=False, error=f"笔记 {note_id} 不存在或不属于用户 {user_id}。")

        # Phase 2: execute confirmed deletion
        if confirmed:
            action_id = str(kwargs.get("action_id", ""))
            token = str(kwargs.get("token", ""))
            if not action_id or not token:
                return ToolResult(ok=False, error="确认删除需要提供 action_id 和 token。")

            action = self._pending_store.confirm(action_id, token, user_id)
            if action is None:
                return ToolResult(ok=False, error="确认失败：action_id 或 token 无效、已过期或已处理。")

            try:
                deleted_note = self._store.delete_note(note_id, user_id)
                if deleted_note is None:
                    return ToolResult(ok=False, error=f"删除失败：笔记 {note_id} 不存在。")

                graph_result = ""
                if self._graph_store.configured() and deleted_note.graph_episode_uuid:
                    try:
                        if self._graph_store.delete_episode(deleted_note.graph_episode_uuid):
                            graph_result = f"，已清理图谱 episode {deleted_note.graph_episode_uuid}"
                    except Exception:
                        logger.exception("Failed to delete graph episode for note %s", note_id)
                        graph_result = "，图谱清理失败(已记录日志)"

                self._pending_store.mark_executed(action_id, user_id)
                return ToolResult(
                    ok=True,
                    data={
                        "deleted_note_id": note_id,
                        "title": deleted_note.title,
                        "message": f"已删除笔记「{deleted_note.title}」{graph_result}。",
                    },
                )
            except Exception as exc:
                logger.exception("DeleteNoteTool execution failed for note_id=%s", note_id)
                return ToolResult(ok=False, error=str(exc)[:500])

        # Phase 1: create pending action for confirmation
        pending = PendingAction(
            user_id=user_id,
            action_type="delete_note",
            target_id=note_id,
            title=f"删除笔记「{note.title}」",
            description=(
                f"将删除笔记「{note.title}」及其关联的复习卡片"
                + ("和图谱映射。" if note.graph_episode_uuid else "。")
            ),
            payload={
                "note_id": note_id,
                "note_title": note.title,
                "note_summary": note.summary,
                "graph_episode_uuid": note.graph_episode_uuid,
            },
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        self._pending_store.create(pending)

        return ToolResult(
            ok=True,
            data={
                "action_id": pending.id,
                "token": pending.token,
                "note_id": note_id,
                "title": note.title,
                "summary": note.summary,
                "pending_confirmation": True,
                "expires_at": pending.expires_at.isoformat(),
                "message": (
                    f"确认删除笔记「{note.title}」？"
                    f"请记录 action_id={pending.id} 和 token={pending.token}，"
                    f"然后以 confirmed=True 重新调用。有效期至 {pending.expires_at.isoformat()}。"
                ),
            },
        )
