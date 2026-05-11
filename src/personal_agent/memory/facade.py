from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .working_memory import WorkingMemory

if TYPE_CHECKING:
    from ..storage.ask_history_store import AskHistoryStore
    from ..storage.memory_store import LocalMemoryStore

logger = logging.getLogger(__name__)


class MemoryFacade:
    """Unified read/write facade over working memory, local store, and ask history.

    AgentService uses this single entry-point instead of juggling three
    separate store objects.
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
        """Return the latest few Q&A turns as a plain-text summary block."""
        records = self._load_conversation_turns(user_id, session_id, limit=6)
        if not records:
            self.working.set_conversation_summary("暂无对话历史。")
            return ""
        lines = [f"Q: {item.get('question', '')}\nA: {item.get('answer', '')}" for item in records]
        summary = "\n\n".join(lines)
        self.working.set_conversation_summary(summary)
        return summary

    def record_turn(self, user_id: str, session_id: str, question: str, answer: str) -> None:
        from datetime import datetime
        from uuid import uuid4

        record = {
            "id": str(uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "question": question,
            "answer": answer,
            "created_at": datetime.utcnow().isoformat(),
        }
        self.local.append_conversation_turn(record)
        # Update the summary after each turn so it stays current
        self.refresh_conversation_summary(user_id, session_id)
        self.working.add_step(f"Q: {question[:120]} -> A: {answer[:120]}")

    # -- helpers ------------------------------------------------------------

    def _load_conversation_turns(
        self, user_id: str, session_id: str, limit: int = 6
    ) -> list[dict]:
        return self.local.list_conversation_turns(user_id, session_id, limit)
