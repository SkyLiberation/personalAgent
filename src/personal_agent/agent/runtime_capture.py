from __future__ import annotations

from datetime import datetime
import logging
import time
from uuid import uuid4

from ..core.logging_utils import log_event, trace_span
from ..core.models import AgentState, KnowledgeNote, RawIngestItem
from ..graphiti.store import GraphCaptureResult
from .graph import build_capture_graph
from .runtime_helpers import _merge_notes
from .runtime_results import CaptureResult

logger = logging.getLogger(__name__)


class RuntimeCaptureMixin:
    def execute_capture(
        self,
        text: str,
        source_type: str = "text",
        user_id: str | None = None,
        source_ref: str | None = None,
    ) -> CaptureResult:
        normalized_user = user_id or self.settings.default_user
        logger.info("Starting capture user=%s source_type=%s", normalized_user, source_type)
        self.memory.working.set_goal(f"采集知识: {text[:80]}")
        graph = build_capture_graph(self.store)
        state = AgentState(
            mode="capture",
            user_id=normalized_user,
            raw_item=RawIngestItem(
                content=text,
                source_type=source_type,
                source_ref=source_ref,
                user_id=normalized_user,
            ),
        )
        result = AgentState.model_validate(graph.invoke(state))
        if result.note is None:
            raise ValueError("Capture flow did not produce a note.")

        graph_result = self.graph_store.ingest_note(result.note)
        related_notes = result.matches
        if graph_result.enabled is True:
            updated_note = self._merge_graph_capture(result.note, graph_result)
            self.store.update_note(updated_note)
            result.note = updated_note
            graph_related_notes = self.store.find_notes_by_graph_episode_uuids(
                normalized_user, graph_result.related_episode_uuids
            )
            related_notes = _merge_notes(graph_related_notes, related_notes)
            updated_note.related_note_ids = [n.id for n in related_notes if n.id != updated_note.id]
            updated_note.updated_at = datetime.utcnow()
            self.store.update_note(updated_note)
            result.note = updated_note
        else:
            result.note.graph_sync_status = "failed"
            result.note.graph_sync_error = (
                graph_result.error
                if isinstance(graph_result.error, str) and graph_result.error
                else "Graphiti ingest returned disabled result."
            )
            result.note.updated_at = datetime.utcnow()
            self.store.update_note(result.note)

        # Set pending status on chunk notes for background graph sync
        if self.graph_store.configured():
            for chunk in result.chunk_notes:
                chunk.graph_sync_status = "pending"
                chunk.graph_sync_error = None
                self.store.update_note(chunk)

        logger.info(
            "Capture finished user=%s note_id=%s graph_sync_status=%s related_notes=%s chunks=%d",
            normalized_user, result.note.id, result.note.graph_sync_status, len(related_notes), len(result.chunk_notes),
        )
        return CaptureResult(
            note=result.note,
            chunk_notes=result.chunk_notes,
            related_notes=related_notes,
            review_card=result.review_card,
        )
    def sync_note_to_graph(self, note_id: str) -> bool:
        note = self.store.get_note(note_id)
        if note is None:
            logger.warning("Graph sync skipped because note_id=%s was not found", note_id)
            return False
        if not self.graph_store.configured():
            logger.info("Graph sync skipped because graph is not configured note_id=%s", note_id)
            note.graph_sync_status = "idle"
            note.graph_sync_error = None
            note.updated_at = datetime.utcnow()
            self.store.update_note(note)
            return False

        trace_id = uuid4().hex[:12]
        max_attempts = max(1, self.settings.graph_sync_max_attempts)
        logger.info("Starting background graph sync note_id=%s trace_id=%s", note_id, trace_id)
        note.graph_sync_status = "pending"
        note.graph_sync_error = None
        note.updated_at = datetime.utcnow()
        self.store.update_note(note)

        last_error: str | None = None
        with trace_span(
            logger, "agent.sync_note_to_graph",
            trace_id=trace_id, note_id=note_id, user_id=note.user_id, max_attempts=max_attempts,
        ):
            for attempt in range(1, max_attempts + 1):
                note = self.store.get_note(note_id) or note
                note.graph_sync_status = "pending"
                note.updated_at = datetime.utcnow()
                self.store.update_note(note)

                log_event(logger, logging.INFO, "graph_sync.attempt.started",
                    trace_id=trace_id, note_id=note_id, user_id=note.user_id,
                    attempt=attempt, max_attempts=max_attempts)

                graph_result = self.graph_store.ingest_note(note, trace_id=trace_id, attempt=attempt)
                if graph_result.enabled is True:
                    updated_note = self._merge_graph_capture(note, graph_result)
                    related_notes = self.store.find_notes_by_graph_episode_uuids(
                        note.user_id, graph_result.related_episode_uuids
                    )
                    updated_note.related_note_ids = [item.id for item in related_notes if item.id != updated_note.id]
                    updated_note.updated_at = datetime.utcnow()
                    self.store.update_note(updated_note)
                    log_event(logger, logging.INFO, "graph_sync.completed",
                        trace_id=trace_id, note_id=note_id, user_id=note.user_id, attempt=attempt,
                        episode_uuid=updated_note.graph_episode_uuid,
                        entity_count=len(updated_note.entity_names),
                        relation_count=len(updated_note.relation_facts))
                    logger.info(
                        "Background graph sync succeeded note_id=%s episode_uuid=%s entities=%s relations=%s",
                        note_id, updated_note.graph_episode_uuid,
                        len(updated_note.entity_names), len(updated_note.relation_facts),
                    )
                    return True

                last_error = graph_result.error or "Graphiti ingest returned disabled result."
                retryable = self._is_retryable_graph_error(last_error)
                log_event(logger, logging.WARNING, "graph_sync.attempt.failed",
                    trace_id=trace_id, note_id=note_id, user_id=note.user_id,
                    attempt=attempt, max_attempts=max_attempts, retryable=retryable, error=last_error)
                if retryable and attempt < max_attempts:
                    backoff_seconds = self._graph_retry_backoff_seconds(attempt)
                    log_event(logger, logging.INFO, "graph_sync.retry.scheduled",
                        trace_id=trace_id, note_id=note_id, user_id=note.user_id,
                        attempt=attempt, next_attempt=attempt + 1, sleep_seconds=backoff_seconds)
                    time.sleep(backoff_seconds)
                    continue
                break

        note = self.store.get_note(note_id) or note
        note.graph_sync_status = "failed"
        note.graph_sync_error = last_error or "Graph sync failed."
        note.updated_at = datetime.utcnow()
        self.store.update_note(note)
        logger.warning("Background graph sync failed note_id=%s error=%s", note_id, note.graph_sync_error)
        return False
    def _merge_graph_capture(self, note: KnowledgeNote, graph_result: GraphCaptureResult) -> KnowledgeNote:
        note.graph_episode_uuid = graph_result.episode_uuid
        note.entity_names = graph_result.entity_names
        note.relation_facts = graph_result.relation_facts[:8]
        note.graph_node_refs = graph_result.node_refs
        note.graph_edge_refs = graph_result.edge_refs
        note.graph_fact_refs = graph_result.fact_refs
        note.graph_sync_status = "synced"
        note.graph_sync_error = None
        note.updated_at = datetime.utcnow()
        return note

    def _is_retryable_graph_error(self, error: str | None) -> bool:
        if not error:
            return False
        normalized = error.lower()
        retryable_signals = (
            "timed out", "timeout", "503", "service unavailable",
            "service is too busy", "rate limit", "temporarily unavailable",
            "connection reset", "connection aborted", "readtimeout", "apitimeouterror",
        )
        return any(signal in normalized for signal in retryable_signals)

    def _graph_retry_backoff_seconds(self, attempt: int) -> float:
        initial = max(0.0, self.settings.graph_sync_initial_backoff_seconds)
        multiplier = max(1.0, self.settings.graph_sync_backoff_multiplier)
        maximum = max(initial, self.settings.graph_sync_max_backoff_seconds)
        delay = initial * (multiplier ** max(0, attempt - 1))
        return min(delay, maximum)


