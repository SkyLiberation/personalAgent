from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from .working_memory import WorkingMemory

if TYPE_CHECKING:
    from ..core.models import Citation
    from ..storage.ask_history_store import AskHistoryStore
    from ..storage.cross_session_store import CrossSessionStore
    from ..storage.memory_store import LocalMemoryStore

logger = logging.getLogger(__name__)


class MemoryFacade:
    """Unified read/write facade over working memory, local store, and ask history.

    AgentService uses this single entry-point instead of juggling three
    separate store objects.

    Reads prefer Postgres (if configured), falling back to local store.
    Writes go to Postgres as primary (if configured), with local store
    as fallback.
    """

    def __init__(
        self,
        local_store: "LocalMemoryStore",
        ask_history_store: "AskHistoryStore",
        cross_session_store: "CrossSessionStore | None" = None,
    ) -> None:
        self.local = local_store
        self.ask_history = ask_history_store
        self.cross_session = cross_session_store
        self.working: WorkingMemory = WorkingMemory()
        self._session_key: str | None = None

    # -- session lifecycle --------------------------------------------------

    def bind_session(self, user_id: str, session_id: str) -> None:
        key = f"{user_id}:{session_id}"
        if self._session_key != key:
            self.working.reset()
            self._session_key = key

    # -- conversation summary -----------------------------------------------

    def refresh_conversation_summary(self, user_id: str, session_id: str) -> str:
        """Return the latest few Q&A turns as a plain-text summary block.

        Reads from Postgres first (if configured), falls back to local store.
        """
        records = self._load_conversation_turns(user_id, session_id, limit=6)
        if not records:
            self.working.set_conversation_summary("暂无对话历史。")
            return ""
        lines = [
            f"Q: {item.get('question', '')}\nA: {item.get('answer', '')}"
            for item in records
        ]
        summary = "\n\n".join(lines)
        self.working.set_conversation_summary(summary)
        return summary

    def record_turn(
        self,
        user_id: str,
        session_id: str,
        question: str,
        answer: str,
        citations: "list[Citation] | None" = None,
    ) -> None:
        """Record a Q&A turn to Postgres (primary) and local store (fallback)."""
        record = {
            "id": str(uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "question": question,
            "answer": answer,
            "citations": [c.model_dump(mode="json") for c in citations] if citations else [],
            "created_at": datetime.utcnow().isoformat(),
        }

        # Primary: Postgres (if configured)
        pg_written = False
        if self.ask_history.configured():
            try:
                from ..core.models import AskHistoryRecord

                pg_record = AskHistoryRecord(
                    id=record["id"],
                    user_id=user_id,
                    session_id=session_id,
                    question=question,
                    answer=answer,
                    citations=citations or [],
                )
                self.ask_history.append(pg_record)
                pg_written = True
            except Exception:
                logger.exception("Failed to persist turn to Postgres, falling back to local store")

        # Fallback: local store (always written, or as fallback when Postgres fails)
        if not pg_written:
            self.local.append_conversation_turn(record)

        # Update the summary after each turn so it stays current
        self.refresh_conversation_summary(user_id, session_id)
        self.working.add_step(f"Q: {question[:120]} -> A: {answer[:120]}")

        # Persist citations to cross-session store for delete targeting
        if citations and self.cross_session is not None:
            try:
                self.cross_session.add_citations(user_id, citations, question=question)
            except Exception:
                logger.exception("Failed to record citations to cross_session store")

    # -- cross-session state ------------------------------------------------

    def record_citations(
        self, user_id: str, citations: "list[Citation]", question: str = "",
    ) -> None:
        """Record citations from an ask response for future delete targeting."""
        if self.cross_session is not None:
            try:
                self.cross_session.add_citations(user_id, citations, question=question)
            except Exception:
                logger.exception("Failed to record citations to cross_session store")

    def recent_citations(self, user_id: str, limit: int = 10) -> list[dict]:
        """Return recently cited notes for delete targeting resolution."""
        if self.cross_session is not None:
            return self.cross_session.recent_citations(user_id, limit)
        return []

    def save_draft(self, user_id: str, text: str, source_context: str = "") -> str:
        """Save a solidify draft. Returns the draft ID."""
        if self.cross_session is not None:
            return self.cross_session.save_draft(user_id, text, source_context)
        return ""

    def get_draft(self, user_id: str, draft_id: str) -> dict | None:
        """Get a specific draft by ID."""
        if self.cross_session is not None:
            return self.cross_session.get_draft(user_id, draft_id)
        return None

    def list_drafts(self, user_id: str, status: str | None = None) -> list[dict]:
        """List drafts for a user, optionally filtered by status."""
        if self.cross_session is not None:
            return self.cross_session.list_drafts(user_id, status)
        return []

    def add_conclusion(self, user_id: str, text: str, session_id: str = "") -> str:
        """Record a candidate conclusion from a conversation. Returns conclusion ID."""
        if self.cross_session is not None:
            return self.cross_session.add_conclusion(user_id, text, session_id)
        return ""

    def list_conclusions(
        self, user_id: str, solidified: bool | None = None,
    ) -> list[dict]:
        """List candidate conclusions, optionally filtered by solidified status."""
        if self.cross_session is not None:
            return self.cross_session.list_conclusions(user_id, solidified)
        return []

    def mark_draft_solidified(self, user_id: str, draft_id: str) -> bool:
        """Mark a solidify draft as solidified after capture_text stores the note."""
        if self.cross_session is not None:
            return self.cross_session.mark_draft_status(user_id, draft_id, "solidified")
        return False

    def mark_conclusion_solidified(self, user_id: str, conclusion_id: str) -> bool:
        """Mark a candidate conclusion as solidified."""
        if self.cross_session is not None:
            return self.cross_session.mark_conclusion_solidified(user_id, conclusion_id)
        return False

    # -- helpers ------------------------------------------------------------

    def _load_conversation_turns(
        self, user_id: str, session_id: str, limit: int = 6
    ) -> list[dict]:
        """Load conversation turns, preferring Postgres over local store."""
        if self.ask_history.configured():
            try:
                records = self.ask_history.list_history(user_id, limit, session_id)
                if records:
                    return [
                        {
                            "question": r.question,
                            "answer": r.answer,
                            "created_at": r.created_at.isoformat()
                            if hasattr(r.created_at, "isoformat")
                            else str(r.created_at),
                        }
                        for r in records
                    ]
            except Exception:
                logger.exception("Failed to read conversation turns from Postgres")
        return self.local.list_conversation_turns(user_id, session_id, limit)
