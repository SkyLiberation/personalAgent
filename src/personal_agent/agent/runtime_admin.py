from __future__ import annotations

import logging

from ..core.models import AskHistoryRecord, KnowledgeNote, PendingAction
from ..storage.postgres_debug_reset_store import PostgresDebugResetStore, clear_upload_files
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
        return self.ask_history_store.list_history(normalized_user, limit, normalized_session)

    def search_ask_history(
        self, user_id: str | None = None, query: str = "", limit: int = 20, session_id: str | None = None
    ) -> list[AskHistoryRecord]:
        normalized_user = user_id or self.settings.default_user
        return self.ask_history_store.search_history(normalized_user, query, limit, session_id)

    def delete_ask_record(self, user_id: str | None, record_id: str) -> bool:
        normalized_user = user_id or self.settings.default_user
        return self.ask_history_store.delete_record(normalized_user, record_id)

    def delete_ask_session(self, user_id: str | None, session_id: str) -> int:
        normalized_user = user_id or self.settings.default_user
        return self.ask_history_store.delete_session(normalized_user, session_id)

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

    def reset_debug_data(self) -> ResetResult:
        logger.warning("Resetting all development data stores")
        deleted_graph_nodes = self.graph_store.clear_all_data()
        self.store.ensure_schema()
        self.ask_history_store.ensure_schema()
        self.pending_action_store.ensure_schema()
        self._cross_session.ensure_schema()
        checkpointer = self._get_orch_graph().checkpointer
        counts = PostgresDebugResetStore(self.settings.postgres_url).clear_all_data()
        checkpointer.setup()
        deleted_upload_files = clear_upload_files(self.settings.data_dir)
        self.memory.working.reset()
        return ResetResult(
            deleted_notes=counts["notes"],
            deleted_reviews=counts["reviews"],
            deleted_upload_files=deleted_upload_files,
            deleted_ask_history=counts["ask_history"],
            deleted_graph_nodes=deleted_graph_nodes,
            deleted_pending_actions=counts["pending_actions"],
            deleted_cross_session_artifacts=counts["cross_session_artifacts"],
            deleted_checkpoints=counts["checkpoints"],
            deleted_checkpoint_blobs=counts["checkpoint_blobs"],
            deleted_checkpoint_writes=counts["checkpoint_writes"],
            deleted_checkpoint_migrations=counts["checkpoint_migrations"],
            truncated_postgres_tables=counts["postgres_tables"],
            deleted_postgres_rows=counts["postgres_rows"],
        )
