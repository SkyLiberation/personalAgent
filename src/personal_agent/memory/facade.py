from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from .working_memory import WorkingMemory

if TYPE_CHECKING:
    from ..core.models import Citation
    from ..storage.ask_history_store import AskHistoryStore
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
    ) -> None:
        self.local = local_store
        self.ask_history = ask_history_store
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
        graph_enabled: bool = False,
    ) -> None:
        """Record a Q&A turn to Postgres (primary) and local store (fallback)."""
        record = {
            "id": str(uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "question": question,
            "answer": answer,
            "citations": [c.model_dump(mode="json") for c in citations] if citations else [],
            "graph_enabled": graph_enabled,
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
                    graph_enabled=graph_enabled,
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
