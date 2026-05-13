"""Persistent cross-request state for citations, solidify drafts, and conclusions.

Survives process restarts by writing to data/cross_session.json.
Provides continuity for delete_knowledge targeting and solidify_conversation resumption.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

from ..core.models import Citation

logger = logging.getLogger(__name__)

MAX_CITATIONS = 30
MAX_DRAFTS = 10
MAX_CONCLUSIONS = 20
CITATION_TTL_HOURS = 24
DRAFT_TTL_HOURS = 48
CONCLUSION_TTL_HOURS = 72


class CrossSessionStore:
    """Persistent key-value store for artifacts that span multiple requests.

    Stores three artifact types per user:
      - recent_citations: citations from recent ask responses (for delete targeting)
      - solidify_drafts: saved knowledge drafts awaiting confirmation
      - candidate_conclusions: extracted facts/conclusions from conversations
    """

    def __init__(self, data_dir: Path) -> None:
        self._file = data_dir / "cross_session.json"
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._loaded = False

    # -- citations ------------------------------------------------------------

    def add_citations(
        self, user_id: str, citations: list[Citation], question: str = "",
    ) -> None:
        self._ensure_loaded()
        with self._lock:
            user_data = self._user_data(user_id)
            existing: list[dict] = user_data.setdefault("recent_citations", [])
            now = datetime.now(timezone.utc)
            for c in citations:
                existing.append({
                    "id": str(uuid4()),
                    "note_id": c.note_id,
                    "title": c.title,
                    "snippet": c.snippet,
                    "relation_fact": c.relation_fact,
                    "source_question": question,
                    "created_at": now.isoformat(),
                })
            # Trim to max and remove expired
            cutoff = now - timedelta(hours=CITATION_TTL_HOURS)
            existing[:] = [
                c for c in existing
                if datetime.fromisoformat(c["created_at"]) > cutoff
            ][-MAX_CITATIONS:]
            self._save()

    def recent_citations(self, user_id: str, limit: int = 10) -> list[dict]:
        self._ensure_loaded()
        with self._lock:
            items = self._user_data(user_id).get("recent_citations", [])
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=CITATION_TTL_HOURS)
            valid = [
                c for c in items
                if datetime.fromisoformat(c["created_at"]) > cutoff
            ]
            return valid[-limit:]

    # -- solidify drafts ------------------------------------------------------

    def save_draft(self, user_id: str, text: str, source_context: str = "") -> str:
        """Save a solidify draft. Returns the draft ID."""
        self._ensure_loaded()
        draft_id = str(uuid4())
        with self._lock:
            user_data = self._user_data(user_id)
            drafts: list[dict] = user_data.setdefault("solidify_drafts", [])
            drafts.append({
                "id": draft_id,
                "text": text,
                "source_context": source_context,
                "status": "draft",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            cutoff = datetime.now(timezone.utc) - timedelta(hours=DRAFT_TTL_HOURS)
            drafts[:] = [
                d for d in drafts
                if datetime.fromisoformat(d["created_at"]) > cutoff
            ][-MAX_DRAFTS:]
            self._save()
        return draft_id

    def get_draft(self, user_id: str, draft_id: str) -> dict | None:
        self._ensure_loaded()
        with self._lock:
            drafts = self._user_data(user_id).get("solidify_drafts", [])
            for d in drafts:
                if d["id"] == draft_id:
                    return d
            return None

    def list_drafts(self, user_id: str, status: str | None = None) -> list[dict]:
        self._ensure_loaded()
        with self._lock:
            drafts = self._user_data(user_id).get("solidify_drafts", [])
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=DRAFT_TTL_HOURS)
            valid = [
                d for d in drafts
                if datetime.fromisoformat(d["created_at"]) > cutoff
            ]
            if status:
                valid = [d for d in valid if d.get("status") == status]
            return valid

    def mark_draft_status(self, user_id: str, draft_id: str, status: str) -> bool:
        self._ensure_loaded()
        with self._lock:
            drafts = self._user_data(user_id).get("solidify_drafts", [])
            for d in drafts:
                if d["id"] == draft_id:
                    d["status"] = status
                    self._save()
                    return True
            return False

    # -- candidate conclusions ------------------------------------------------

    def add_conclusion(
        self, user_id: str, text: str, source_session_id: str = "",
    ) -> str:
        self._ensure_loaded()
        conclusion_id = str(uuid4())
        with self._lock:
            user_data = self._user_data(user_id)
            conclusions: list[dict] = user_data.setdefault("candidate_conclusions", [])
            conclusions.append({
                "id": conclusion_id,
                "text": text,
                "source_session_id": source_session_id,
                "solidified": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            cutoff = datetime.now(timezone.utc) - timedelta(hours=CONCLUSION_TTL_HOURS)
            conclusions[:] = [
                c for c in conclusions
                if datetime.fromisoformat(c["created_at"]) > cutoff
            ][-MAX_CONCLUSIONS:]
            self._save()
        return conclusion_id

    def list_conclusions(
        self, user_id: str, solidified: bool | None = None,
    ) -> list[dict]:
        self._ensure_loaded()
        with self._lock:
            conclusions = self._user_data(user_id).get("candidate_conclusions", [])
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=CONCLUSION_TTL_HOURS)
            valid = [
                c for c in conclusions
                if datetime.fromisoformat(c["created_at"]) > cutoff
            ]
            if solidified is not None:
                valid = [c for c in valid if c.get("solidified") == solidified]
            return valid

    def mark_conclusion_solidified(self, user_id: str, conclusion_id: str) -> bool:
        self._ensure_loaded()
        with self._lock:
            conclusions = self._user_data(user_id).get("candidate_conclusions", [])
            for c in conclusions:
                if c["id"] == conclusion_id:
                    c["solidified"] = True
                    self._save()
                    return True
            return False

    # -- cleanup --------------------------------------------------------------

    def clear_user(self, user_id: str) -> int:
        self._ensure_loaded()
        with self._lock:
            if user_id in self._data:
                count = sum(
                    len(self._data[user_id].get(k, []))
                    for k in ("recent_citations", "solidify_drafts", "candidate_conclusions")
                )
                del self._data[user_id]
                self._save()
                return count
            return 0

    # -- internal -------------------------------------------------------------

    def _user_data(self, user_id: str) -> dict:
        if user_id not in self._data:
            self._data[user_id] = {}
        return self._data[user_id]

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            try:
                if self._file.exists():
                    raw = json.loads(self._file.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        self._data = raw
            except Exception:
                logger.exception("Failed to load cross_session.json, starting fresh")
                self._data = {}
            self._loaded = True

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to save cross_session.json")
