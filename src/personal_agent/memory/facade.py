from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from ..core.models import local_now

if TYPE_CHECKING:
    from ..core.models import Citation
    from ..storage.ask_history_store import AskHistoryStore
    from ..storage.postgres_memory_store import PostgresMemoryStore

logger = logging.getLogger(__name__)

_MAX_HISTORY_QUESTION_CHARS = 300
_MAX_HISTORY_ANSWER_CHARS = 500
_MAX_HISTORY_CONTEXT_CHARS = 3600
_HISTORY_CONTEXT_PREAMBLE = (
    "以下为历史对话线索，仅用于解析指代、用户目标和明确更正；"
    "历史助手回复不是事实证据，必须依据本轮检索结果重新核验。"
)


def _compact_context_text(text: str, limit: int) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _bounded_history_context(blocks: list[str]) -> str:
    selected: list[str] = []
    current_length = len(_HISTORY_CONTEXT_PREAMBLE)
    for block in reversed(blocks):
        added_length = len(block) + 2
        if selected and current_length + added_length > _MAX_HISTORY_CONTEXT_CHARS:
            break
        selected.append(block)
        current_length += added_length
    selected.reverse()
    return "\n\n".join([_HISTORY_CONTEXT_PREAMBLE, *selected])


class MemoryFacade:
    """Unified read/write facade over Postgres memory stores.

    AgentService uses this single entry-point instead of juggling three
    separate store objects.

    Business persistence is database-only; no operation falls back to files.
    """

    def __init__(
        self,
        local_store: "PostgresMemoryStore",
        ask_history_store: "AskHistoryStore",
    ) -> None:
        self.local = local_store
        self.ask_history = ask_history_store
        self._session_key: str | None = None

    # -- session lifecycle --------------------------------------------------

    def bind_session(self, user_id: str, session_id: str) -> None:
        key = f"{user_id}:{session_id}"
        if self._session_key != key:
            self._session_key = key

    # -- conversation hints --------------------------------------------------

    def load_conversation_hints(self, user_id: str, session_id: str) -> str:
        """Return bounded recent dialogue hints for reference resolution.

        Reads from Postgres ask history.
        """
        records = self._load_conversation_turns(user_id, session_id, limit=6)
        if not records:
            return ""
        lines = [
            (
                f"用户: {_compact_context_text(item.get('question', ''), _MAX_HISTORY_QUESTION_CHARS)}\n"
                f"历史助手回复（待核验）: "
                f"{_compact_context_text(item.get('answer', ''), _MAX_HISTORY_ANSWER_CHARS)}"
            )
            for item in records
        ]
        return _bounded_history_context(lines)

    def record_turn(
        self,
        user_id: str,
        session_id: str,
        question: str,
        answer: str,
        citations: "list[Citation] | None" = None,
        record_id: str | None = None,
    ) -> None:
        """Record a Q&A turn to Postgres."""
        record = {
            "id": record_id or str(uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "question": question,
            "answer": answer,
            "citations": [c.model_dump(mode="json") for c in citations] if citations else [],
            "created_at": local_now().isoformat(),
        }

        from ..core.models import AskHistoryRecord

        self.ask_history.append(
            AskHistoryRecord(
                id=record["id"],
                user_id=user_id,
                session_id=session_id,
                question=question,
                answer=answer,
                citations=citations or [],
            )
        )

    # -- helpers ------------------------------------------------------------

    def _load_conversation_turns(
        self, user_id: str, session_id: str, limit: int = 6
    ) -> list[dict]:
        """Load recent turns in chronological order for prompt rendering."""
        records = self.ask_history.list_history(user_id, limit, session_id)
        return [
            {
                "question": r.question,
                "answer": r.answer,
                "created_at": r.created_at.isoformat()
                if hasattr(r.created_at, "isoformat")
                else str(r.created_at),
            }
            for r in reversed(records)
        ]
