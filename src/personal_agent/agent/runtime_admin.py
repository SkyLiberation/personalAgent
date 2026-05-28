from __future__ import annotations

import logging

from ..core.models import AskHistoryRecord, KnowledgeNote
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
        checkpointer = self._get_orch_graph().checkpointer
        counts = PostgresDebugResetStore(self.settings.postgres_url).clear_all_data()
        checkpointer.setup()
        deleted_upload_files = clear_upload_files(self.settings.data_dir)
        return ResetResult(
            deleted_notes=counts["notes"],
            deleted_reviews=counts["reviews"],
            deleted_upload_files=deleted_upload_files,
            deleted_ask_history=counts["ask_history"],
            deleted_graph_nodes=deleted_graph_nodes,
            deleted_checkpoints=counts["checkpoints"],
            deleted_checkpoint_blobs=counts["checkpoint_blobs"],
            deleted_checkpoint_writes=counts["checkpoint_writes"],
            deleted_checkpoint_migrations=counts["checkpoint_migrations"],
            truncated_postgres_tables=counts["postgres_tables"],
            deleted_postgres_rows=counts["postgres_rows"],
        )
