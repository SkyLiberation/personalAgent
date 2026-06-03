from __future__ import annotations

import logging
import time
from hashlib import sha256
from uuid import uuid4

from ..core.config import Settings
from ..core.logging_utils import log_event, trace_span
from ..core.models import AgentState, KnowledgeNote, RawIngestItem, local_now
from ..extract import PreExtractService
from ..graphiti.store import GraphCaptureResult, GraphitiStore
from ..storage.postgres_memory_store import PostgresMemoryStore
from .nodes import (
    capture_node,
    chunk_reconcile_node,
    enrich_node,
    link_node,
    preextract_node,
    schedule_review_node,
    structural_chunk_node,
)
from .runtime_helpers import _merge_notes
from .runtime_results import CaptureResult

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """End-to-end ingestion of raw text into local notes and the knowledge graph.

    This is the single home for the deterministic capture pipeline. It owns:

    - source-fingerprint dedupe before running the pipeline
    - the local node sequence (capture → chunk → preextract → reconcile →
      enrich → link → schedule_review)
    - Graphiti ingestion of the resulting note (or chunk-level delegation)
    - background single-note and batch graph sync entry points
    - graph quality metrics and retry/backoff policy
    """

    def __init__(
        self,
        settings: Settings,
        store: PostgresMemoryStore,
        graph_store: GraphitiStore,
        preextract_service: PreExtractService,
    ) -> None:
        self.settings = settings
        self.store = store
        self.graph_store = graph_store
        self.preextract_service = preextract_service

    # ------------------------------------------------------------------
    # Foreground ingestion entry
    # ------------------------------------------------------------------

    def ingest(
        self,
        text: str,
        source_type: str = "text",
        user_id: str | None = None,
        source_ref: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> CaptureResult:
        normalized_user = user_id or self.settings.default_user
        normalized_metadata = dict(metadata or {})
        source_fingerprint = _source_fingerprint(
            text=text,
            source_type=source_type,
            source_ref=source_ref,
        )
        existing_note = self.store.find_note_by_source_fingerprint(
            normalized_user,
            source_fingerprint,
        )
        if existing_note is not None:
            logger.info(
                "Capture skipped duplicate user=%s note_id=%s source_type=%s fingerprint=%s",
                normalized_user, existing_note.id, source_type, source_fingerprint[:12],
            )
            return CaptureResult(
                note=existing_note,
                chunk_notes=self.store.get_chunks_for_parent(existing_note.id),
                related_notes=[],
                review_card=None,
            )

        logger.info("Starting capture user=%s source_type=%s", normalized_user, source_type)
        state = AgentState(
            mode="capture",
            user_id=normalized_user,
            raw_item=RawIngestItem(
                content=text,
                source_type=source_type,
                source_ref=source_ref,
                user_id=normalized_user,
                metadata=normalized_metadata,
                source_fingerprint=source_fingerprint,
            ),
        )
        state = self._run_local_pipeline(state)
        if state.note is None:
            raise ValueError("Capture flow did not produce a note.")

        capture_result = CaptureResult(
            note=state.note,
            chunk_notes=state.chunk_notes,
            related_notes=state.matches,
            review_card=state.review_card,
        )
        capture_result = self._ingest_to_graph(capture_result)

        logger.info(
            "Capture finished user=%s note_id=%s graph_sync_status=%s related_notes=%s chunks=%d",
            normalized_user,
            capture_result.note.id,
            capture_result.note.graph_sync.status,
            len(capture_result.related_notes),
            len(capture_result.chunk_notes),
        )
        return capture_result

    # ------------------------------------------------------------------
    # Local deterministic node pipeline
    # ------------------------------------------------------------------

    def _run_local_pipeline(self, state: AgentState) -> AgentState:
        """Run the capture branch without compiling a standalone LangGraph.

        Entry orchestration is owned by ``orchestration_graph``. Capture stays
        a deterministic branch workflow here so direct API calls and
        entry-driven capture share the same behavior without creating a second
        graph layer.
        """
        state = capture_node(state, self.store)
        state = structural_chunk_node(state, self.store)
        state = preextract_node(state, self.store, self.preextract_service)
        state = chunk_reconcile_node(state, self.store)
        state = enrich_node(state, self.store)
        state = link_node(state, self.store)
        state = schedule_review_node(state, self.store)
        return state

    # ------------------------------------------------------------------
    # Graph ingestion (post-local capture)
    # ------------------------------------------------------------------

    def _ingest_to_graph(self, result: CaptureResult) -> CaptureResult:
        note = result.note
        related_notes = result.related_notes

        if result.chunk_notes and self.graph_store.configured():
            note.graph_sync.status = "skipped"
            note.graph_sync.error = "Graph sync delegated to graph-worthy chunks."
            note.updated_at = local_now()
            self.store.update_note(note)
        else:
            graph_result = self.graph_store.ingest_note(note)
            if graph_result.enabled is True:
                note, related_notes = self._apply_graph_capture_result(
                    note,
                    graph_result,
                    related_notes,
                )
            else:
                note.graph_sync.status = "failed"
                note.graph_sync.error = (
                    graph_result.error
                    if isinstance(graph_result.error, str) and graph_result.error
                    else "Graphiti ingest returned disabled result."
                )
                note.updated_at = local_now()
                self.store.update_note(note)

        if self.graph_store.configured():
            self._mark_chunk_graph_sync(result.chunk_notes)

        return result.model_copy(
            update={
                "note": note,
                "related_notes": related_notes,
            }
        )

    def _mark_chunk_graph_sync(self, chunks: list[KnowledgeNote]) -> None:
        """Set pending/skipped graph state for child chunks after capture."""
        sync_budget = max(0, self.settings.graphiti.sync_max_notes_per_capture)
        eligible_seen = 0
        for chunk in chunks:
            if chunk.preextract.graph_worthy is False:
                chunk.graph_sync.status = "skipped"
                chunk.graph_sync.error = None
            elif sync_budget and eligible_seen >= sync_budget:
                chunk.graph_sync.status = "skipped"
                chunk.graph_sync.error = "Graph sync budget exceeded for this capture."
            else:
                eligible_seen += 1
                chunk.graph_sync.status = "pending"
                chunk.graph_sync.error = None
            self.store.update_note(chunk)

    # ------------------------------------------------------------------
    # Background sync entries
    # ------------------------------------------------------------------

    def sync_note_to_graph(self, note_id: str) -> bool:
        note = self.store.get_note(note_id)
        if note is None:
            logger.warning("Graph sync skipped because note_id=%s was not found", note_id)
            return False
        if not self.graph_store.configured():
            logger.info("Graph sync skipped because graph is not configured note_id=%s", note_id)
            note.graph_sync.status = "idle"
            note.graph_sync.error = None
            note.updated_at = local_now()
            self.store.update_note(note)
            return False

        trace_id = uuid4().hex[:12]
        max_attempts = max(1, self.settings.graphiti.sync_max_attempts)
        logger.info("Starting background graph sync note_id=%s trace_id=%s", note_id, trace_id)
        note.graph_sync.status = "pending"
        note.graph_sync.error = None
        note.updated_at = local_now()
        self.store.update_note(note)

        last_error: str | None = None
        with trace_span(
            logger,
            "agent.sync_note_to_graph",
            trace_id=trace_id,
            note_id=note_id,
            user_id=note.user_id,
            max_attempts=max_attempts,
        ):
            for attempt in range(1, max_attempts + 1):
                note = self.store.get_note(note_id) or note
                note.graph_sync.status = "pending"
                note.updated_at = local_now()
                self.store.update_note(note)

                log_event(
                    logger,
                    logging.INFO,
                    "graph_sync.attempt.started",
                    trace_id=trace_id,
                    note_id=note_id,
                    user_id=note.user_id,
                    attempt=attempt,
                    max_attempts=max_attempts,
                )

                graph_result = self.graph_store.ingest_note(
                    note,
                    trace_id=trace_id,
                    attempt=attempt,
                )
                if graph_result.enabled is True:
                    updated_note, _related_notes = self._apply_graph_capture_result(
                        note,
                        graph_result,
                        [],
                    )
                    log_event(
                        logger,
                        logging.INFO,
                        "graph_sync.completed",
                        trace_id=trace_id,
                        note_id=note_id,
                        user_id=note.user_id,
                        attempt=attempt,
                        episode_uuid=updated_note.graph.episode_uuid,
                        entity_count=len(updated_note.graph.entity_names),
                        relation_count=len(updated_note.graph.relation_facts),
                    )
                    logger.info(
                        "Background graph sync succeeded note_id=%s episode_uuid=%s entities=%s relations=%s",
                        note_id,
                        updated_note.graph.episode_uuid,
                        len(updated_note.graph.entity_names),
                        len(updated_note.graph.relation_facts),
                    )
                    return True

                last_error = graph_result.error or "Graphiti ingest returned disabled result."
                retryable = self._is_retryable_graph_error(last_error)
                log_event(
                    logger,
                    logging.WARNING,
                    "graph_sync.attempt.failed",
                    trace_id=trace_id,
                    note_id=note_id,
                    user_id=note.user_id,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    retryable=retryable,
                    error=last_error,
                )
                if retryable and attempt < max_attempts:
                    backoff_seconds = self._graph_retry_backoff_seconds(attempt)
                    log_event(
                        logger,
                        logging.INFO,
                        "graph_sync.retry.scheduled",
                        trace_id=trace_id,
                        note_id=note_id,
                        user_id=note.user_id,
                        attempt=attempt,
                        next_attempt=attempt + 1,
                        sleep_seconds=backoff_seconds,
                    )
                    time.sleep(backoff_seconds)
                    continue
                break

        note = self.store.get_note(note_id) or note
        note.graph_sync.status = "failed"
        note.graph_sync.error = last_error or "Graph sync failed."
        note.updated_at = local_now()
        self.store.update_note(note)
        logger.warning("Background graph sync failed note_id=%s error=%s", note_id, note.graph_sync.error)
        return False

    def sync_notes_to_graph(self, note_ids: list[str]) -> dict[str, bool]:
        """Sync multiple notes to Graphiti concurrently."""
        unique_note_ids = list(dict.fromkeys(note_ids))
        notes = [
            note
            for note_id in unique_note_ids
            for note in [self.store.get_note(note_id)]
            if note is not None
        ]
        if not notes:
            return {}
        if not self.graph_store.configured():
            for note in notes:
                note.graph_sync.status = "idle"
                note.graph_sync.error = None
                note.updated_at = local_now()
                self.store.update_note(note)
            return {note.id: False for note in notes}

        trace_id = uuid4().hex[:12]
        max_workers = max(1, self.settings.graphiti.sync_max_workers)
        for note in notes:
            if note.graph_sync.status == "skipped":
                continue
            note.graph_sync.status = "pending"
            note.graph_sync.error = None
            note.updated_at = local_now()
            self.store.update_note(note)

        active_notes = [note for note in notes if note.graph_sync.status != "skipped"]
        if not active_notes:
            return {note.id: False for note in notes}

        log_event(
            logger,
            logging.INFO,
            "graph_sync.batch.started",
            trace_id=trace_id,
            note_count=len(active_notes),
            max_workers=max_workers,
        )
        results = self.graph_store.ingest_notes(
            active_notes,
            trace_id=trace_id,
            max_workers=max_workers,
        )

        outcomes: dict[str, bool] = {
            note.id: False for note in notes if note.graph_sync.status == "skipped"
        }
        for note in active_notes:
            graph_result = results.get(note.id) or GraphCaptureResult(
                enabled=False,
                error="Graphiti batch ingest returned no result.",
            )
            if graph_result.enabled is True:
                updated_note, _related_notes = self._apply_graph_capture_result(
                    note,
                    graph_result,
                    [],
                )
                outcomes[updated_note.id] = True
                continue

            note.graph_sync.status = "failed"
            note.graph_sync.error = graph_result.error or "Graph sync failed."
            note.updated_at = local_now()
            self.store.update_note(note)
            outcomes[note.id] = False

        log_event(
            logger,
            logging.INFO,
            "graph_sync.batch.completed",
            trace_id=trace_id,
            note_count=len(active_notes),
            succeeded=sum(1 for ok in outcomes.values() if ok),
            failed=sum(1 for ok in outcomes.values() if not ok),
        )
        return outcomes

    # ------------------------------------------------------------------
    # Graph result merging and quality metrics
    # ------------------------------------------------------------------

    def _apply_graph_capture_result(
        self,
        note: KnowledgeNote,
        graph_result: GraphCaptureResult,
        related_notes: list[KnowledgeNote],
    ) -> tuple[KnowledgeNote, list[KnowledgeNote]]:
        updated_note = self._merge_graph_capture(note, graph_result)
        graph_related_notes = self.store.find_notes_by_graph_episode_uuids(
            note.user_id,
            graph_result.related_episode_uuids,
        )
        merged_related_notes = _merge_notes(graph_related_notes, related_notes)
        updated_note.related_note_ids = [
            item.id for item in merged_related_notes if item.id != updated_note.id
        ]
        updated_note.updated_at = local_now()
        self.store.update_note(updated_note)
        return updated_note, merged_related_notes

    def _merge_graph_capture(
        self,
        note: KnowledgeNote,
        graph_result: GraphCaptureResult,
    ) -> KnowledgeNote:
        note.graph.episode_uuid = graph_result.episode_uuid
        note.graph.entity_names = graph_result.entity_names
        note.graph.relation_facts = graph_result.relation_facts[:8]
        note.graph.node_refs = graph_result.node_refs
        note.graph.edge_refs = graph_result.edge_refs
        note.graph.fact_refs = graph_result.fact_refs
        note.graph_sync.status = "synced"
        note.graph_sync.error = None
        note.updated_at = local_now()

        from ..graphiti.quality_vocab import all_relations_weak

        entity_count = len(graph_result.entity_names)
        relation_count = len(graph_result.relation_facts)
        fact_lengths = [len(f) for f in graph_result.relation_facts if f.strip()]
        avg_fact_length = round(
            sum(fact_lengths) / len(fact_lengths) if fact_lengths else 0.0,
            1,
        )
        zero_entities = note.preextract.graph_worthy is True and entity_count == 0
        weak_only = (
            all_relations_weak(graph_result.relation_facts)
            if relation_count > 0
            else False
        )

        note.graph_quality.entity_count = entity_count
        note.graph_quality.relation_count = relation_count
        note.graph_quality.avg_fact_length = avg_fact_length
        note.graph_quality.zero_entities = zero_entities
        note.graph_quality.weak_relations_only = weak_only

        log_event(
            logger,
            logging.INFO,
            "graph_quality.metrics",
            note_id=note.id,
            user_id=note.user_id,
            entity_count=entity_count,
            relation_count=relation_count,
            avg_fact_length=avg_fact_length,
            zero_entities=zero_entities,
            weak_relations_only=weak_only,
            preextract_topic=note.preextract.topic,
        )

        if zero_entities:
            preview = note.body.content[:120].replace("\n", " ")
            logger.warning(
                "graph_quality.anomaly zero_entities note_id=%s topic=%s preview=%r",
                note.id,
                note.preextract.topic,
                preview,
            )
        if weak_only:
            logger.warning(
                "graph_quality.anomaly weak_relations_only note_id=%s topic=%s relations=%s",
                note.id,
                note.preextract.topic,
                graph_result.relation_facts[:5],
            )

        return note

    # ------------------------------------------------------------------
    # Retry policy helpers
    # ------------------------------------------------------------------

    def _is_retryable_graph_error(self, error: str | None) -> bool:
        if not error:
            return False
        normalized = error.lower()
        retryable_signals = (
            "timed out",
            "timeout",
            "503",
            "service unavailable",
            "service is too busy",
            "rate limit",
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
            "readtimeout",
            "apitimeouterror",
        )
        return any(signal in normalized for signal in retryable_signals)

    def _graph_retry_backoff_seconds(self, attempt: int) -> float:
        initial = max(0.0, self.settings.graphiti.sync_initial_backoff_seconds)
        multiplier = max(1.0, self.settings.graphiti.sync_backoff_multiplier)
        maximum = max(initial, self.settings.graphiti.sync_max_backoff_seconds)
        delay = initial * (multiplier ** max(0, attempt - 1))
        return min(delay, maximum)


def _source_fingerprint(text: str, source_type: str, source_ref: str | None) -> str:
    normalized_text = " ".join(text.split())
    normalized_ref = (source_ref or "").strip().lower()
    payload = "\0".join([source_type.strip().lower(), normalized_ref, normalized_text])
    return sha256(payload.encode("utf-8")).hexdigest()
