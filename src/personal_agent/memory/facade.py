from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from ..core.models import (
    GraphReconcileIssue,
    GraphReconcileReport,
    GraphSyncTask,
    KnowledgeNote,
    MemoryEpisode,
    MemoryItem,
    ReviewCard,
    local_now,
)
from ..core.observability import record_policy_decision
from ..core.logging_utils import log_event
from ..core.query_understanding import RetrievalFilters
from ..policy import PolicyAction, PolicyDecision, PolicyEngine, PolicyInput

if TYPE_CHECKING:
    from ..graphiti.store import GraphitiStore
    from ..storage.postgres_memory_store import PostgresMemoryStore

logger = logging.getLogger(__name__)

_MEMORY_SCOPES: dict[str, str] = {
    "memory_read": "memory:read",
    "memory_write": "memory:write",
    "memory_delete": "memory:delete",
    "memory_graph_sync": "memory:write",
}


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
    snapshot_id: str = ""
    graph_cleaned: int = 0
    graph_failed: int = 0
    error: str | None = None


@dataclass(frozen=True)
class RestoreMemoryResult:
    """Result of a long-term memory restore use case."""

    ok: bool
    note_id: str
    title: str = ""
    summary: str = ""
    message: str = ""
    restored_note: KnowledgeNote | None = None
    restored_notes: list[KnowledgeNote] = field(default_factory=list)
    restored_reviews: list[ReviewCard] = field(default_factory=list)
    snapshot_id: str = ""
    error: str | None = None


def _graph_sync_task_from_note(note: KnowledgeNote) -> GraphSyncTask:
    return GraphSyncTask(
        note_id=note.id,
        user_id=note.user_id,
        title=note.body.title,
        status=note.graph_sync.status,
        error=note.graph_sync.error,
        episode_uuid=note.graph.episode_uuid,
        attempt_count=note.graph_sync.attempt_count,
        last_attempt_at=note.graph_sync.last_attempt_at,
        last_synced_at=note.graph_sync.last_synced_at,
        updated_at=note.updated_at,
        quality=note.graph_quality,
    )


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
        *,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self.local = local_store
        self.graph = graph_store
        self._policy = policy_engine or PolicyEngine()
        self._session_key: str | None = None

    # -- policy enforcement -------------------------------------------------

    def _enforce(
        self,
        action: PolicyAction,
        *,
        subject: str | None,
        owner: str | None = None,
        resource: str | None = None,
        confirmed: bool = False,
    ) -> PolicyDecision:
        """Evaluate a memory access decision and audit non-allow outcomes."""
        decision = self._policy.evaluate(
            PolicyInput(
                action=action,
                user_id=subject,
                execution_mode="memory",
                resource=resource,
                resource_owner=owner,
                permission_scope=_MEMORY_SCOPES.get(action, "memory:access"),
                confirmed=confirmed,
            )
        )
        if not decision.allowed:
            record_policy_decision(
                action=action,
                effect=decision.effect,
                rule=decision.rule,
                reason=decision.reason,
                permission_scope=_MEMORY_SCOPES.get(action, "memory:access"),
                resource=resource,
                user_id=subject,
                execution_mode="memory",
            )
        return decision

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

    def list_notes(self, user_id: str = "default", *, include_chunks: bool = True) -> list[KnowledgeNote]:
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
        if user_id is not None:
            decision = self._enforce(
                "memory_write", subject=user_id, owner=note.user_id, resource=note.id,
            )
            if not decision.allowed:
                raise PermissionError(decision.reason)
        self.local.add_note(note)
        return note

    def add_episode(self, episode: MemoryEpisode, *, user_id: str | None = None) -> MemoryEpisode:
        if user_id is not None:
            decision = self._enforce(
                "memory_write", subject=user_id, owner=episode.user_id, resource=episode.id,
            )
            if not decision.allowed:
                raise PermissionError(decision.reason)
        self.local.add_episode(episode)
        return episode

    def add_memory_item(self, item: MemoryItem, *, user_id: str | None = None) -> MemoryItem:
        if user_id is not None:
            decision = self._enforce(
                "memory_write", subject=user_id, owner=item.user_id, resource=item.id,
            )
            if not decision.allowed:
                raise PermissionError(decision.reason)
        self.local.add_memory_item(item)
        return item

    def list_memory_items(
        self,
        user_id: str,
        *,
        memory_type: str | None = None,
        status: str | list[str] | None = None,
        limit: int = 50,
    ) -> list[MemoryItem]:
        return self.local.list_memory_items(
            user_id,
            memory_type=memory_type,
            status=status,
            limit=limit,
        )

    def search_memory_items(
        self,
        user_id: str,
        query: str,
        *,
        memory_type: str | None = None,
        status: str | list[str] | None = "confirmed",
        limit: int = 5,
    ) -> list[MemoryItem]:
        return self.local.search_memory_items(
            user_id,
            query,
            memory_type=memory_type,
            status=status,
            limit=limit,
        )

    def get_memory_item(self, item_id: str, *, user_id: str | None = None) -> MemoryItem | None:
        return self.local.get_memory_item(item_id, user_id=user_id)

    def promote_reflection(
        self,
        item_id: str,
        *,
        user_id: str,
        outcome: str,
        promote_step: float = 0.2,
        demote_step: float = 0.25,
        promote_threshold: float = 0.8,
        reject_floor: float = 0.2,
    ) -> MemoryItem | None:
        """Adjust a reflection's confidence/status after a run that used it.

        ``outcome == "completed"`` raises confidence (and promotes to
        ``confirmed`` past ``promote_threshold``); any other outcome lowers it
        (and marks ``rejected`` at/below ``reject_floor``). Returns the updated
        item, or None when the item is missing / not a reflection / terminal.
        """
        item = self.local.get_memory_item(item_id, user_id=user_id)
        if item is None or item.memory_type != "reflection":
            return None
        if item.status in {"rejected", "superseded"}:
            return item

        decision = self._enforce(
            "memory_write", subject=user_id, owner=item.user_id, resource=item.id,
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)

        if outcome == "completed":
            item.confidence = min(1.0, item.confidence + promote_step)
            if item.confidence >= promote_threshold:
                item.status = "confirmed"
        else:
            item.confidence = max(0.0, item.confidence - demote_step)
            if item.confidence <= reject_floor:
                item.status = "rejected"
        item.updated_at = local_now()
        self.local.add_memory_item(item)
        return item

    # -- updates ------------------------------------------------------------

    def update_note(self, note: KnowledgeNote, *, user_id: str | None = None) -> KnowledgeNote:
        if user_id is not None:
            decision = self._enforce(
                "memory_write", subject=user_id, owner=note.user_id, resource=note.id,
            )
            if not decision.allowed:
                raise PermissionError(decision.reason)
        self.local.update_note(note)
        return note

    def mark_graph_sync_pending(self, note_id: str, *, user_id: str | None = None) -> KnowledgeNote | None:
        note = self.get_note(note_id, user_id=user_id)
        if note is None:
            return None
        if user_id is not None:
            decision = self._enforce(
                "memory_graph_sync", subject=user_id, owner=note.user_id, resource=note.id,
            )
            if not decision.allowed:
                raise PermissionError(decision.reason)
        note.graph_sync.status = "pending"
        note.graph_sync.error = None
        note.updated_at = local_now()
        self.local.update_note(note)
        return note

    def supersede_note(
        self,
        old_note_id: str,
        new_note_id: str,
        *,
        user_id: str,
        reason: str = "",
    ) -> tuple[KnowledgeNote, KnowledgeNote]:
        old_note = self.get_note(old_note_id, user_id=user_id)
        new_note = self.get_note(new_note_id, user_id=user_id)
        if old_note is None or new_note is None:
            raise ValueError("old_note_id or new_note_id does not exist for user.")
        decision = self._enforce(
            "memory_write", subject=user_id, owner=user_id, resource=f"{old_note_id}->{new_note_id}",
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)

        old_note.version.status = "superseded"
        old_note.version.superseded_by_note_id = new_note.id
        old_note.version.valid_until = local_now()
        old_note.version.reason = reason
        new_note.version.status = "current"
        new_note.version.version = max(new_note.version.version, old_note.version.version + 1)
        if old_note.id not in new_note.version.supersedes_note_ids:
            new_note.version.supersedes_note_ids.append(old_note.id)
        new_note.version.topic_key = new_note.version.topic_key or old_note.version.topic_key
        new_note.version.source_fingerprint = (
            new_note.version.source_fingerprint or new_note.source.fingerprint
        )
        new_note.version.reason = reason
        old_note.updated_at = local_now()
        new_note.updated_at = local_now()
        self.local.update_note(old_note)
        self.local.update_note(new_note)
        log_event(
            logger,
            logging.INFO,
            "memory.version.superseded",
            user_id=user_id,
            old_note_id=old_note.id,
            new_note_id=new_note.id,
            reason=reason,
        )
        return old_note, new_note

    def mark_note_deprecated(
        self,
        note_id: str,
        *,
        user_id: str,
        reason: str = "",
    ) -> KnowledgeNote:
        note = self.get_note(note_id, user_id=user_id)
        if note is None:
            raise ValueError(f"note {note_id} does not exist for user.")
        decision = self._enforce(
            "memory_write", subject=user_id, owner=note.user_id, resource=note.id,
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)
        note.version.status = "deprecated"
        note.version.valid_until = local_now()
        note.version.reason = reason
        note.updated_at = local_now()
        self.local.update_note(note)
        log_event(
            logger,
            logging.INFO,
            "memory.version.deprecated",
            user_id=user_id,
            note_id=note.id,
            reason=reason,
        )
        return note

    def mark_notes_conflicted(
        self,
        note_ids: list[str],
        *,
        user_id: str,
        reason: str = "",
    ) -> list[KnowledgeNote]:
        notes = [note for note_id in dict.fromkeys(note_ids) for note in [self.get_note(note_id, user_id=user_id)] if note]
        if len(notes) < 2:
            raise ValueError("At least two existing notes are required to mark a conflict.")
        decision = self._enforce(
            "memory_write", subject=user_id, owner=user_id, resource="memory_conflict",
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)
        ids = [note.id for note in notes]
        for note in notes:
            note.version.status = "conflicted"
            note.version.conflict_note_ids = [item for item in ids if item != note.id]
            note.version.reason = reason
            note.updated_at = local_now()
            self.local.update_note(note)
        log_event(
            logger,
            logging.WARNING,
            "memory.version.conflicted",
            user_id=user_id,
            note_ids=ids,
            reason=reason,
        )
        return notes

    def list_graph_sync_tasks(
        self,
        *,
        user_id: str | None = None,
        statuses: list[str] | None = None,
        include_chunks: bool = True,
        limit: int | None = None,
    ) -> list[GraphSyncTask]:
        notes = self.local.list_notes_by_graph_sync_status(
            user_id=user_id,
            statuses=statuses,
            include_chunks=include_chunks,
            limit=limit,
        )
        return [_graph_sync_task_from_note(note) for note in notes]

    def reconcile_graph_sync(
        self,
        user_id: str,
        *,
        graph_episode_uuids: list[str] | None = None,
        retry_statuses: list[str] | None = None,
        clean_orphans: bool = False,
        sync_note: Callable[[str], bool] | None = None,
    ) -> GraphReconcileReport:
        decision = self._enforce(
            "memory_graph_sync", subject=user_id, owner=user_id, resource="graph_sync_reconcile",
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)

        notes = self.local.list_notes_by_graph_sync_status(user_id=user_id, include_chunks=True)
        report = GraphReconcileReport(user_id=user_id, checked_notes=len(notes))
        log_event(
            logger,
            logging.INFO,
            "graph_sync.reconcile.started",
            user_id=user_id,
            checked_notes=len(notes),
            retry_statuses=retry_statuses or [],
            clean_orphans=clean_orphans,
            graph_episode_inventory_count=len(graph_episode_uuids or []),
        )
        retry_set = set(retry_statuses or [])
        known_episodes = {note.graph.episode_uuid for note in notes if note.graph.episode_uuid}

        for note in notes:
            status = note.graph_sync.status
            if status == "pending":
                report.pending_count += 1
                report.issues.append(GraphReconcileIssue(
                    issue_type="pending_sync",
                    severity="info",
                    note_id=note.id,
                    episode_uuid=note.graph.episode_uuid,
                    message=f"Graph sync is pending for note {note.id}.",
                    action="retry_sync" if "pending" in retry_set else "none",
                ))
            elif status == "failed":
                report.failed_count += 1
                report.issues.append(GraphReconcileIssue(
                    issue_type="failed_sync",
                    severity="warning",
                    note_id=note.id,
                    episode_uuid=note.graph.episode_uuid,
                    message=note.graph_sync.error or f"Graph sync failed for note {note.id}.",
                    action="retry_sync" if "failed" in retry_set else "none",
                ))
            elif status == "synced":
                report.synced_count += 1
                if not note.graph.episode_uuid:
                    report.issues.append(GraphReconcileIssue(
                        issue_type="missing_episode",
                        severity="error",
                        note_id=note.id,
                        message=f"Note {note.id} is marked synced but has no graph episode uuid.",
                        action="retry_sync" if "synced" in retry_set else "none",
                    ))
            elif status == "skipped":
                report.skipped_count += 1

            if note.graph_quality.zero_entities or note.graph_quality.weak_relations_only:
                report.weak_quality_count += 1
                report.issues.append(GraphReconcileIssue(
                    issue_type="weak_quality",
                    severity="warning",
                    note_id=note.id,
                    episode_uuid=note.graph.episode_uuid,
                    message=f"Graph quality is weak for note {note.id}.",
                    action="rebuild",
                ))

            if sync_note is not None and status in retry_set:
                try:
                    if bool(sync_note(note.id)):
                        report.retried_count += 1
                        note = self.get_note(note.id, user_id=user_id) or note
                        log_event(
                            logger,
                            logging.INFO,
                            "graph_sync.reconcile.retry.completed",
                            user_id=user_id,
                            note_id=note.id,
                            status=note.graph_sync.status,
                            episode_uuid=note.graph.episode_uuid,
                        )
                    else:
                        log_event(
                            logger,
                            logging.WARNING,
                            "graph_sync.reconcile.retry.failed",
                            user_id=user_id,
                            note_id=note.id,
                            error="sync_note returned False",
                        )
                        report.issues.append(GraphReconcileIssue(
                            issue_type="retry_failed",
                            severity="warning",
                            note_id=note.id,
                            episode_uuid=note.graph.episode_uuid,
                            message=f"Retry did not sync note {note.id}.",
                            action="retry_sync",
                            error="sync_note returned False",
                        ))
                except Exception as exc:
                    logger.exception("Graph sync retry failed note_id=%s", note.id)
                    log_event(
                        logger,
                        logging.ERROR,
                        "graph_sync.reconcile.retry.failed",
                        user_id=user_id,
                        note_id=note.id,
                        error=str(exc),
                    )
                    report.issues.append(GraphReconcileIssue(
                        issue_type="retry_failed",
                        severity="error",
                        note_id=note.id,
                        episode_uuid=note.graph.episode_uuid,
                        message=f"Retry raised for note {note.id}.",
                        action="retry_sync",
                        error=str(exc),
                    ))

            note.graph_sync.last_reconciled_at = report.generated_at
            note.updated_at = local_now()
            self.local.update_note(note)

        for episode_uuid in sorted(set(graph_episode_uuids or []) - known_episodes):
            issue = GraphReconcileIssue(
                issue_type="orphan_episode",
                severity="warning",
                episode_uuid=episode_uuid,
                message=f"Graph episode {episode_uuid} has no backing Postgres note.",
                action="delete_episode" if clean_orphans else "none",
            )
            report.orphan_episode_count += 1
            if clean_orphans and self.graph is not None and self.graph.configured():
                try:
                    issue.fixed = bool(self.graph.delete_episode(episode_uuid))
                    if issue.fixed:
                        report.cleaned_orphan_count += 1
                        log_event(
                            logger,
                            logging.INFO,
                            "graph_sync.reconcile.orphan_deleted",
                            user_id=user_id,
                            episode_uuid=episode_uuid,
                        )
                    else:
                        issue.error = "delete_episode returned False"
                        log_event(
                            logger,
                            logging.WARNING,
                            "graph_sync.reconcile.orphan_delete_failed",
                            user_id=user_id,
                            episode_uuid=episode_uuid,
                            error=issue.error,
                        )
                except Exception as exc:
                    logger.exception("Failed to delete orphan graph episode %s", episode_uuid)
                    log_event(
                        logger,
                        logging.ERROR,
                        "graph_sync.reconcile.orphan_delete_failed",
                        user_id=user_id,
                        episode_uuid=episode_uuid,
                        error=str(exc),
                    )
                    issue.issue_type = "delete_failed"
                    issue.severity = "error"
                    issue.error = str(exc)
            report.issues.append(issue)

        log_event(
            logger,
            logging.INFO,
            "graph_sync.reconcile.completed",
            user_id=user_id,
            checked_notes=report.checked_notes,
            pending_count=report.pending_count,
            failed_count=report.failed_count,
            synced_count=report.synced_count,
            skipped_count=report.skipped_count,
            orphan_episode_count=report.orphan_episode_count,
            weak_quality_count=report.weak_quality_count,
            retried_count=report.retried_count,
            cleaned_orphan_count=report.cleaned_orphan_count,
            issue_count=len(report.issues),
        )
        return report

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

    def delete_note_confirmed(
        self,
        note_id: str,
        user_id: str,
        *,
        delete_reason: str = "",
        run_id: str | None = None,
        checkpoint_id: str | None = None,
    ) -> DeleteMemoryResult:
        decision = self._enforce(
            "memory_delete", subject=user_id, owner=user_id, resource=note_id, confirmed=True,
        )
        if not decision.allowed:
            return DeleteMemoryResult(ok=False, note_id=note_id, error=decision.reason)
        note = self.get_note(note_id, user_id=user_id)
        if note is None:
            return DeleteMemoryResult(
                ok=False,
                note_id=note_id,
                error=f"笔记 {note_id} 不存在或不属于用户 {user_id}。",
            )
        chunks_before = self.list_chunks(note_id, user_id=user_id)
        deleted = self.local.delete_note(
            note_id,
            user_id,
            cascade_chunks=bool(chunks_before),
            deleted_by=user_id,
            delete_reason=delete_reason,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
        )
        if deleted is None:
            return DeleteMemoryResult(ok=False, note_id=note_id, error=f"删除失败：笔记 {note_id} 不存在。")
        deleted_note = deleted.target

        graph_cleaned = 0
        graph_failed = 0
        return DeleteMemoryResult(
            ok=True,
            note_id=note_id,
            title=deleted_note.body.title,
            summary=deleted_note.body.summary,
            message=f"已删除笔记「{deleted_note.body.title}」，可通过删除快照恢复。",
            deleted_note=deleted_note,
            chunks=[note for note in deleted.notes if note.id != deleted_note.id],
            snapshot_id=deleted.snapshot_id,
            graph_cleaned=graph_cleaned,
            graph_failed=graph_failed,
        )

    def restore_note_confirmed(
        self,
        *,
        note_id: str | None = None,
        snapshot_id: str | None = None,
        user_id: str,
    ) -> RestoreMemoryResult:
        resource = snapshot_id or note_id or "memory_restore"
        decision = self._enforce(
            "memory_write", subject=user_id, owner=user_id, resource=resource, confirmed=True,
        )
        if not decision.allowed:
            return RestoreMemoryResult(ok=False, note_id=note_id or "", error=decision.reason)
        try:
            restored = self.local.restore_note(user_id=user_id, note_id=note_id, snapshot_id=snapshot_id)
        except ValueError as exc:
            return RestoreMemoryResult(ok=False, note_id=note_id or "", error=str(exc))
        if restored is None:
            return RestoreMemoryResult(
                ok=False,
                note_id=note_id or "",
                snapshot_id=snapshot_id or "",
                error="未找到可恢复的删除快照。",
            )
        return RestoreMemoryResult(
            ok=True,
            note_id=restored.target.id,
            title=restored.target.body.title,
            summary=restored.target.body.summary,
            message=f"已恢复笔记「{restored.target.body.title}」。",
            restored_note=restored.target,
            restored_notes=restored.notes,
            restored_reviews=restored.review_cards,
            snapshot_id=restored.snapshot_id,
        )
