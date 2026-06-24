from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Protocol

from personal_agent.kernel.config import Settings
from personal_agent.kernel.evidence import EvidenceItem, notes_to_evidence, rank_evidence_items
from personal_agent.kernel.models import Citation, KnowledgeNote
from personal_agent.kernel.projections import EvidenceSource, evidence_source_from_note
from personal_agent.kernel.query_understanding import RetrievalFilters


class NoteStoreForEnrichment(Protocol):
    def get_chunks_for_parent(self, parent_note_id: str) -> list[KnowledgeNote]:
        ...

    def get_parent_note(self, note_id: str) -> KnowledgeNote | None:
        ...


@dataclass
class CandidateSet:
    evidence: list[EvidenceItem]
    matches: list[KnowledgeNote]
    citations: list[Citation]
    added_note_ids: list[str] = field(default_factory=list)


class CandidateEnricher(Protocol):
    name: str

    def enrich(
        self,
        question: str,
        *,
        evidence: list[EvidenceItem],
        matches: list[KnowledgeNote],
        citations: list[Citation],
        store: object,
        filters: RetrievalFilters | None = None,
    ) -> CandidateSet:
        ...


class NoopCandidateEnricher:
    name = "none"

    def enrich(
        self,
        question: str,
        *,
        evidence: list[EvidenceItem],
        matches: list[KnowledgeNote],
        citations: list[Citation],
        store: object,
        filters: RetrievalFilters | None = None,
    ) -> CandidateSet:
        return CandidateSet(evidence=evidence, matches=matches, citations=citations)


class ParentChildCandidateEnricher:
    name = "parent_child"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def enrich(
        self,
        question: str,
        *,
        evidence: list[EvidenceItem],
        matches: list[KnowledgeNote],
        citations: list[Citation],
        store: object,
        filters: RetrievalFilters | None = None,
    ) -> CandidateSet:
        if not hasattr(store, "get_chunks_for_parent") or not hasattr(store, "get_parent_note"):
            return CandidateSet(evidence=evidence, matches=matches, citations=citations)

        expanded_matches = list(matches)
        seen_note_ids = {note.id for note in expanded_matches}
        added: list[KnowledgeNote] = []

        def add_note(note: KnowledgeNote | None) -> None:
            if note is None or note.id in seen_note_ids:
                return
            if not _note_matches_filters(note, filters):
                return
            seen_note_ids.add(note.id)
            expanded_matches.append(note)
            added.append(note)

        for note in matches:
            if note.chunk.parent_note_id:
                add_note(store.get_parent_note(note.id))  # type: ignore[attr-defined]
                if self.settings.ask.neighbor_chunk_window > 0:
                    for neighbor in _neighbor_chunks(
                        note,
                        store.get_chunks_for_parent(note.chunk.parent_note_id),  # type: ignore[attr-defined]
                        self.settings.ask.neighbor_chunk_window,
                    ):
                        add_note(neighbor)
                continue

            children = store.get_chunks_for_parent(note.id)  # type: ignore[attr-defined]
            ranked_children = rank_evidence_items(question, notes_to_evidence(children))
            selected = 0
            for ranked in ranked_children:
                child = _note_by_id(children, ranked.evidence.source_id)
                if child is None:
                    continue
                if _term_overlap(question, child) < self.settings.ask.parent_child_min_overlap:
                    continue
                add_note(child)
                selected += 1
                if selected >= self.settings.ask.parent_child_top_n:
                    break

        if not added:
            return CandidateSet(evidence=evidence, matches=matches, citations=citations)

        return CandidateSet(
            evidence=[*evidence, *notes_to_evidence(added)],
            matches=expanded_matches,
            citations=[*citations, *_notes_to_citations(added)],
            added_note_ids=[note.id for note in added],
        )


def create_candidate_enricher(settings: Settings) -> CandidateEnricher:
    name = settings.ask.candidate_enricher.strip().lower()
    if name in {"none", "noop", "disabled"}:
        return NoopCandidateEnricher()
    if name in {"parent_child", "default"}:
        return ParentChildCandidateEnricher(settings)
    raise ValueError(
        "Unknown ask candidate enricher '%s'. Available: parent_child, none"
        % settings.ask.candidate_enricher
    )


def _neighbor_chunks(
    note: KnowledgeNote,
    chunks: list[KnowledgeNote],
    window: int,
) -> list[KnowledgeNote]:
    if note.chunk.index is None or window <= 0:
        return []
    return [
        chunk for chunk in chunks
        if chunk.id != note.id
        and chunk.chunk.index is not None
        and abs(chunk.chunk.index - note.chunk.index) <= window
    ]


def _note_by_id(notes: list[KnowledgeNote], note_id: str) -> KnowledgeNote | None:
    for note in notes:
        if note.id == note_id:
            return note
    return None


def _term_overlap(question: str, note: KnowledgeNote | EvidenceSource) -> int:
    source = evidence_source_from_note(note) if isinstance(note, KnowledgeNote) else note
    question_terms = _terms(question)
    content_terms = _terms(" ".join([source.title, source.summary, source.content]))
    return len(question_terms & content_terms)


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    lowered = text.lower()
    for token in re.findall(r"[a-z0-9_+-]{2,}", lowered):
        terms.add(token)
    for run in re.findall(r"[\u3400-\u9fff]{2,}", text):
        terms.add(run)
        for size in (2, 3):
            for index in range(0, max(0, len(run) - size + 1)):
                terms.add(run[index:index + size])
    return terms


def _notes_to_citations(notes: list[KnowledgeNote]) -> list[Citation]:
    sources = [evidence_source_from_note(note) for note in notes]
    return [
        Citation(note_id=source.id, title=source.title, snippet=source.summary[:120])
        for source in sources
    ]


def _note_matches_filters(note: KnowledgeNote, filters: RetrievalFilters | None) -> bool:
    if filters is None or not filters.active():
        return True
    if filters.source_types and note.source.type not in filters.source_types:
        return False
    if filters.parent_note_id.strip():
        parent_id = filters.parent_note_id.strip()
        if note.id != parent_id and note.chunk.parent_note_id != parent_id:
            return False
    if filters.source_ref_contains.strip():
        if filters.source_ref_contains.strip().lower() not in (note.source.ref or "").lower():
            return False
    if filters.metadata_contains.strip():
        metadata_text = " ".join(str(value) for value in note.source.metadata.values()).lower()
        if filters.metadata_contains.strip().lower() not in metadata_text:
            return False
    if filters.tags:
        note_tags = {tag.lower() for tag in note.tags}
        if not all(tag.lower() in note_tags for tag in filters.tags):
            return False
    return True
