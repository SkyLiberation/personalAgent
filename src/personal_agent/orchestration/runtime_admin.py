from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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
