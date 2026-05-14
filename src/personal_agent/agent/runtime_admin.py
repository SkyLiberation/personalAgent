from __future__ import annotations

import logging

from ..core.models import AskHistoryRecord, KnowledgeNote, PendingAction
from .runtime_results import ResetResult

logger = logging.getLogger(__name__)


class RuntimeAdminMixin:
    def list_notes(self, user_id: str | None = None) -> list[KnowledgeNote]:
        normalized_user = user_id or self.settings.default_user
        return list(reversed(self.store.list_notes(normalized_user)))

    def list_ask_history(
        self, user_id: str | None = None, limit: int = 20, session_id: str | None = None
    ) -> list[AskHistoryRecord]:
        normalized_user = user_id or self.settings.default_user
        normalized_session = session_id or None
        if self.ask_history_store.configured():
            return self.ask_history_store.list_history(normalized_user, limit, normalized_session)
        local_records = self.store.list_conversation_turns(normalized_user, normalized_session or "default", limit)
        return [AskHistoryRecord.model_validate(item) for item in reversed(local_records)]

    def search_ask_history(
        self, user_id: str | None = None, query: str = "", limit: int = 20, session_id: str | None = None
    ) -> list[AskHistoryRecord]:
        normalized_user = user_id or self.settings.default_user
        if self.ask_history_store.configured():
            return self.ask_history_store.search_history(normalized_user, query, limit, session_id)
        local_records = self.store.list_conversation_turns(normalized_user, session_id or "default", limit)
        if not query.strip():
            return [AskHistoryRecord.model_validate(item) for item in reversed(local_records)]
        query_lower = query.strip().lower()
        filtered = [
            r for r in local_records
            if query_lower in r.get("question", "").lower() or query_lower in r.get("answer", "").lower()
        ]
        return [AskHistoryRecord.model_validate(item) for item in reversed(filtered)]

    def delete_ask_record(self, user_id: str | None, record_id: str) -> bool:
        normalized_user = user_id or self.settings.default_user
        if self.ask_history_store.configured():
            return self.ask_history_store.delete_record(normalized_user, record_id)
        return self.store.delete_conversation_turn(normalized_user, record_id)

    def delete_ask_session(self, user_id: str | None, session_id: str) -> int:
        normalized_user = user_id or self.settings.default_user
        if self.ask_history_store.configured():
            return self.ask_history_store.delete_session(normalized_user, session_id)
        return self.store.delete_session_turns(normalized_user, session_id)

    def list_pending_actions(
        self, user_id: str | None = None, status: str | None = None
    ) -> list[PendingAction]:
        return self.pending_action_store.list_by_user(user_id or self.settings.default_user, status)

    def confirm_pending_action(self, action_id: str, token: str, user_id: str | None = None) -> PendingAction | None:
        normalized_user = user_id or self.settings.default_user
        action = self.pending_action_store.confirm(action_id, token, normalized_user)
        if action is None:
            return None
        if action.action_type == "delete_note":
            graph_episode_uuid = action.payload.get("graph_episode_uuid")
            chunks_before = self.store.get_chunks_for_parent(action.target_id)
            has_chunks = bool(chunks_before)
            self.store.delete_note(action.target_id, normalized_user, cascade_chunks=has_chunks)
            if self.graph_store.configured():
                if graph_episode_uuid:
                    try:
                        self.graph_store.delete_episode(str(graph_episode_uuid))
                    except Exception:
                        logger.exception("Graph episode deletion failed for pending action %s", action_id)
                for chunk in chunks_before:
                    if chunk.graph_episode_uuid:
                        try:
                            self.graph_store.delete_episode(chunk.graph_episode_uuid)
                        except Exception:
                            logger.exception("Graph episode deletion failed for chunk %s", chunk.id)
            action = self.pending_action_store.mark_executed(action_id, normalized_user) or action
        return action

    def reject_pending_action(
        self, action_id: str, user_id: str | None = None, reason: str = ""
    ) -> PendingAction | None:
        return self.pending_action_store.reject(action_id, user_id or self.settings.default_user, reason)

    def health(self) -> dict[str, object]:
        graph_status = self.graph_store.status()
        return {
            "status": "ok",
            "graphiti": graph_status,
            "ask_history": {"configured": self.ask_history_store.configured()},
        }

    def reset_user_data(self, user_id: str | None = None) -> ResetResult:
        normalized_user = user_id or self.settings.default_user
        logger.warning("Resetting user data for user=%s", normalized_user)
        deleted_graph_episodes = 0
        if self.graph_store.configured():
            deleted_graph_episodes = self.graph_store.clear_user_group(normalized_user)
        local_result = self.store.clear_user_data(normalized_user, remove_uploaded_files=True)
        self._cross_session.clear_user(normalized_user)
        deleted_ask_history = 0
        if self.ask_history_store.configured():
            try:
                deleted_ask_history = self.ask_history_store.delete_history(normalized_user)
            except Exception:
                logger.exception("Failed to delete ask history for user=%s", normalized_user)
        return ResetResult(
            user_id=normalized_user,
            deleted_notes=local_result["notes"],
            deleted_reviews=local_result["reviews"],
            deleted_conversations=local_result["conversations"],
            deleted_upload_files=local_result["uploads"],
            deleted_ask_history=deleted_ask_history,
            deleted_graph_episodes=deleted_graph_episodes,
        )


