from __future__ import annotations

import json
import logging
from pathlib import Path

from ..core.models import KnowledgeNote
from ..storage.postgres_debug_reset_store import PostgresDebugResetStore, clear_upload_files
from .runtime_results import ResetResult

logger = logging.getLogger(__name__)


class RuntimeAdminMixin:
    def list_notes(self, user_id: str | None = None) -> list[KnowledgeNote]:
        normalized_user = user_id or self.settings.default_user
        return list(reversed(self.store.list_notes(normalized_user)))

    def health(self) -> dict[str, object]:
        graph_status = self.graph_store.status()
        return {
            "status": "ok",
            "graphiti": graph_status,
        }

    def reset_debug_data(self) -> ResetResult:
        logger.warning("Resetting all development data stores")
        protected_eval_groups = _protected_eval_graph_group_ids(
            self.settings,
            graph_store=self.graph_store,
        )
        deleted_graph_nodes = self.graph_store.clear_all_data(
            preserve_group_ids=protected_eval_groups
        )
        self.store.ensure_schema()
        checkpointer = self._get_orch_graph().checkpointer
        counts = PostgresDebugResetStore(self.settings.postgres_url).clear_all_data()
        checkpointer.setup()
        deleted_upload_files = clear_upload_files(self.settings.data_dir)
        return ResetResult(
            deleted_notes=counts["notes"],
            deleted_reviews=counts["reviews"],
            deleted_upload_files=deleted_upload_files,
            deleted_graph_nodes=deleted_graph_nodes,
            deleted_checkpoints=counts["checkpoints"],
            deleted_checkpoint_blobs=counts["checkpoint_blobs"],
            deleted_checkpoint_writes=counts["checkpoint_writes"],
            deleted_checkpoint_migrations=counts["checkpoint_migrations"],
            truncated_postgres_tables=counts["postgres_tables"],
            deleted_postgres_rows=counts["postgres_rows"],
        )


def _protected_eval_graph_group_ids(
    settings,
    *,
    graph_store,
    project_root: Path | None = None,
) -> list[str]:
    """Return Graphiti group ids backed by eval manifests for incremental reuse."""
    root = project_root or Path(__file__).resolve().parents[3]
    evals_dir = root / "evals"
    if not evals_dir.exists():
        return []

    protected: set[str] = set()
    for manifest_path in evals_dir.rglob("*manifest*.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.debug("Skipping unreadable eval manifest %s", manifest_path)
            continue

        user_id = manifest.get("user_id")
        if not isinstance(user_id, str) or not user_id.strip():
            continue
        if manifest.get("graphiti_group_prefix") != settings.graphiti.group_prefix:
            continue
        if not manifest.get("episode_to_note_id"):
            continue

        protected.add(graph_store.group_id_for_user(user_id))

    return sorted(protected)
