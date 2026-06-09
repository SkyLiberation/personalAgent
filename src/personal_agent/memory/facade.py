from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.models import KnowledgeNote, MemoryEpisode, ReviewCard, local_now
from ..core.query_understanding import RetrievalFilters

if TYPE_CHECKING:
    from ..graphiti.store import GraphitiStore
    from ..storage.postgres_memory_store import PostgresMemoryStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeleteMemoryResult:
    """Result of a long-term memory delete use case."""

    ok: bool
    note_id: str
    title: str = ""
    summary: str = ""
    message: str = ""
    description: str = ""
    deleted_note: KnowledgeNote | None = None
    chunks: list[KnowledgeNote] = field(default_factory=list)
    graph_cleaned: int = 0
    graph_failed: int = 0
    error: str | None = None


class MemoryFacade:
    """Unified read facade over Postgres long-term memory stores.

    AgentService uses this single entry-point instead of juggling separate
    store objects. Conversation history (short-term memory) lives entirely in
    LangGraph checkpoints; this facade only owns long-term knowledge.
    """

    def __init__(
        self,
        local_store: "PostgresMemoryStore",
        graph_store: "GraphitiStore | None" = None,
    ) -> None:
        self.local = local_store
        self.graph = graph_store
        self._session_key: str | None = None

    # -- session lifecycle --------------------------------------------------

    def bind_session(self, user_id: str, session_id: str) -> None:
        key = f"{user_id}:{session_id}"
        if self._session_key != key:
            self._session_key = key

    def ensure_schema(self) -> None:
        self.local.ensure_schema()

    # -- long-term reads ----------------------------------------------------

    def find_note_by_source_fingerprint(
        self,
        user_id: str,
        source_fingerprint: str | None,
    ) -> KnowledgeNote | None:
        return self.local.find_note_by_source_fingerprint(user_id, source_fingerprint)

    def list_notes(self, user_id: str, *, include_chunks: bool = True) -> list[KnowledgeNote]:
        return self.local.list_notes(user_id, include_chunks=include_chunks)

    def list_recent_notes(
        self,
        user_id: str,
        *,
        limit: int = 5,
        include_chunks: bool = True,
    ) -> list[KnowledgeNote]:
        if limit <= 0:
            return []
        return self.list_notes(user_id, include_chunks=include_chunks)[-limit:]

    def get_note(self, note_id: str, *, user_id: str | None = None) -> KnowledgeNote | None:
        note = self.local.get_note(note_id)
        if note is None:
            return None
        if user_id is not None and note.user_id != user_id:
            return None
        return note

    def list_chunks(self, parent_note_id: str, *, user_id: str | None = None) -> list[KnowledgeNote]:
        chunks = self.local.get_chunks_for_parent(parent_note_id)
        if user_id is None:
            return chunks
        return [chunk for chunk in chunks if chunk.user_id == user_id]

    def get_chunks_for_parent(self, parent_note_id: str) -> list[KnowledgeNote]:
        """Compatibility alias for parent/child candidate enrichment."""
        return self.list_chunks(parent_note_id)

    def get_parent_note(self, note_id: str) -> KnowledgeNote | None:
        note = self.get_note(note_id)
        if note is None or note.chunk.parent_note_id is None:
            return None
        return self.get_note(note.chunk.parent_note_id)

    def search_memory(
        self,
        user_id: str,
        query: str,
        *,
        limit: int = 8,
        filters: RetrievalFilters | None = None,
    ) -> list[KnowledgeNote]:
        return self.local.find_similar_notes(user_id, query, limit=limit, filters=filters)

    def find_similar_notes(
        self,
        user_id: str,
        query: str,
        limit: int = 8,
        filters: RetrievalFilters | None = None,
    ) -> list[KnowledgeNote]:
        """Compatibility alias for deterministic capture / legacy nodes."""
        return self.search_memory(user_id, query, limit=limit, filters=filters)

    def find_by_graph_episodes(
        self,
        user_id: str,
        episode_uuids: list[str],
        *,
        filters: RetrievalFilters | None = None,
    ) -> list[KnowledgeNote]:
        return self.local.find_notes_by_graph_episode_uuids(user_id, episode_uuids, filters=filters)

    def list_episodes(
        self,
        user_id: str,
        *,
        limit: int = 50,
        session_id: str | None = None,
        workflow: str | None = None,
        outcome: str | None = None,
    ) -> list[MemoryEpisode]:
        return self.local.list_episodes(
            user_id,
            limit=limit,
            session_id=session_id,
            workflow=workflow,
            outcome=outcome,
        )

    def search_episodes(
        self,
        user_id: str,
        query: str,
        *,
        limit: int = 5,
        session_id: str | None = None,
    ) -> list[MemoryEpisode]:
        return self.local.search_episodes(user_id, query, limit=limit, session_id=session_id)

    # -- reviews ------------------------------------------------------------

    def list_reviews(self, user_id: str) -> list[ReviewCard]:
        return self.local.list_reviews(user_id)

    def due_reviews(self, user_id: str) -> list[ReviewCard]:
        return self.local.due_reviews(user_id)

    def add_review(self, review: ReviewCard) -> None:
        self.local.add_review(review)

    # -- writes -------------------------------------------------------------

    def add_note(self, note: KnowledgeNote, *, user_id: str | None = None) -> KnowledgeNote:
        if user_id is not None and note.user_id != user_id:
            raise PermissionError(f"Note {note.id} does not belong to user {user_id}.")
        self.local.add_note(note)
        return note

    def add_episode(self, episode: MemoryEpisode, *, user_id: str | None = None) -> MemoryEpisode:
        if user_id is not None and episode.user_id != user_id:
            raise PermissionError(f"Episode {episode.id} does not belong to user {user_id}.")
        self.local.add_episode(episode)
        return episode

    # -- updates ------------------------------------------------------------

    def update_note(self, note: KnowledgeNote, *, user_id: str | None = None) -> KnowledgeNote:
        if user_id is not None and note.user_id != user_id:
            raise PermissionError(f"Note {note.id} does not belong to user {user_id}.")
        self.local.update_note(note)
        return note

    def mark_graph_sync_pending(self, note_id: str, *, user_id: str | None = None) -> KnowledgeNote | None:
        note = self.get_note(note_id, user_id=user_id)
        if note is None:
            return None
        note.graph_sync.status = "pending"
        note.graph_sync.error = None
        note.updated_at = local_now()
        self.local.update_note(note)
        return note

    # -- deletion -----------------------------------------------------------

    def build_delete_confirmation(self, note_id: str, user_id: str) -> DeleteMemoryResult:
        note = self.get_note(note_id, user_id=user_id)
        if note is None:
            return DeleteMemoryResult(
                ok=False,
                note_id=note_id,
                error=f"笔记 {note_id} 不存在或不属于用户 {user_id}。",
            )
        chunks = self.list_chunks(note_id, user_id=user_id)
        cascade_note = "及其所有子章节笔记" if chunks else ""
        description = (
            f"将删除笔记「{note.body.title}」{cascade_note}"
            + (f"（共 {len(chunks) + 1} 条笔记）" if chunks else "")
            + "及其关联的复习卡片"
            + ("和图谱映射。" if note.graph.episode_uuid else "。")
        )
        return DeleteMemoryResult(
            ok=True,
            note_id=note_id,
            title=note.body.title,
            summary=note.body.summary,
            description=description,
            message=f"确认删除笔记「{note.body.title}」？",
            chunks=chunks,
        )

    def delete_note_confirmed(self, note_id: str, user_id: str) -> DeleteMemoryResult:
        note = self.get_note(note_id, user_id=user_id)
        if note is None:
            return DeleteMemoryResult(
                ok=False,
                note_id=note_id,
                error=f"笔记 {note_id} 不存在或不属于用户 {user_id}。",
            )
        chunks_before = self.list_chunks(note_id, user_id=user_id)
        deleted_note = self.local.delete_note(note_id, user_id, cascade_chunks=bool(chunks_before))
        if deleted_note is None:
            return DeleteMemoryResult(ok=False, note_id=note_id, error=f"删除失败：笔记 {note_id} 不存在。")

        graph_cleaned = 0
        graph_failed = 0
        if self.graph is not None and self.graph.configured():
            for candidate in [deleted_note, *chunks_before]:
                if not candidate.graph.episode_uuid:
                    continue
                try:
                    if self.graph.delete_episode(candidate.graph.episode_uuid):
                        graph_cleaned += 1
                except Exception:
                    logger.exception("Failed to delete graph episode for note %s", candidate.id)
                    graph_failed += 1

        graph_result = f"，已清理 {graph_cleaned} 个图谱 episode" if graph_cleaned else ""
        if graph_failed:
            graph_result += f"，{graph_failed} 个图谱 episode 清理失败(已记录日志)"
        return DeleteMemoryResult(
            ok=True,
            note_id=note_id,
            title=deleted_note.body.title,
            summary=deleted_note.body.summary,
            message=f"已删除笔记「{deleted_note.body.title}」{graph_result}。",
            deleted_note=deleted_note,
            chunks=chunks_before,
            graph_cleaned=graph_cleaned,
            graph_failed=graph_failed,
        )
