from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage.postgres_memory_store import PostgresMemoryStore

logger = logging.getLogger(__name__)


class MemoryFacade:
    """Unified read facade over Postgres long-term memory stores.

    AgentService uses this single entry-point instead of juggling separate
    store objects. Conversation history (short-term memory) lives entirely in
    LangGraph checkpoints; this facade only owns long-term knowledge.
    """

    def __init__(self, local_store: "PostgresMemoryStore") -> None:
        self.local = local_store
        self._session_key: str | None = None

    # -- session lifecycle --------------------------------------------------

    def bind_session(self, user_id: str, session_id: str) -> None:
        key = f"{user_id}:{session_id}"
        if self._session_key != key:
            self._session_key = key
