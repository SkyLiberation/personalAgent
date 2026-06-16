"""Pure evidence/candidate operations shared across the ask stages.

These were module-level helpers inside ``runtime_ask``. They are moved here so
the retriever and stage objects can reuse them without importing the large
``runtime_ask`` module (which would create an import cycle). ``runtime_ask``
re-exports the ones that tests import by name, preserving those seams.
"""

from __future__ import annotations

import re

from ...core.evidence import EvidenceItem, notes_to_evidence
from ...core.models import Citation, KnowledgeNote
from ...core.projections import MatchRef, match_ref_from_note


def dedupe_evidence(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    deduped: list[EvidenceItem] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in evidence:
        key = (
            item.source_type,
            item.source_id or item.url or "",
            item.fact or "",
            item.snippet[:160],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def order_matches_by_evidence(
    matches: list[KnowledgeNote],
    evidence: list[EvidenceItem],
) -> list[KnowledgeNote]:
    by_id = {note.id: note for note in matches}
    ordered: list[KnowledgeNote] = []
    seen: set[str] = set()
    for item in evidence:
        note = by_id.get(item.source_id)
        if note is None or note.id in seen:
            continue
        ordered.append(note)
        seen.add(note.id)
    ordered.extend(note for note in matches if note.id not in seen)
    return ordered


def selected_matches(
    matches: list[KnowledgeNote],
    evidence: list[EvidenceItem],
) -> list[KnowledgeNote]:
    selected_ids = {
        item.source_id
        for item in evidence
        if item.source_id and item.source_type in {"note", "chunk"}
    }
    return [note for note in order_matches_by_evidence(matches, evidence) if note.id in selected_ids]


def selected_citations(
    citations: list[Citation],
    evidence: list[EvidenceItem],
) -> list[Citation]:
    selected_note_ids = {
        item.source_id
        for item in evidence
        if item.source_id and item.source_type in {"note", "chunk"}
    }
    selected_web_urls = {
        item.url or item.source_id
        for item in evidence
        if item.source_type == "web" and (item.url or item.source_id)
    }
    selected: list[Citation] = []
    seen: set[tuple[str, str, str | None]] = set()
    for citation in citations:
        keep = (
            citation.source_type == "web"
            and citation.url is not None
            and citation.url in selected_web_urls
        ) or (
            citation.source_type != "web"
            and citation.note_id in selected_note_ids
        )
        if not keep:
            continue
        key = (citation.note_id, citation.url or "", citation.relation_fact)
        if key in seen:
            continue
        seen.add(key)
        selected.append(citation)
    return selected


def match_refs(matches: list[KnowledgeNote]) -> list[MatchRef]:
    return [match_ref_from_note(note) for note in matches]


def graph_matches_to_evidence(
    question: str,
    matches: list[KnowledgeNote],
    citations: list[Citation],
    *,
    mode: str = "all",
    min_overlap: int = 2,
) -> list[EvidenceItem]:
    normalized_mode = mode.strip().lower()
    if normalized_mode in {"none", "off", "disabled"}:
        return []
    cited_note_ids = {citation.note_id for citation in citations if citation.note_id}
    if normalized_mode == "all":
        selected_notes = list(matches)
    else:
        selected_notes = [
            note for note in matches
            if note.id in cited_note_ids or note_term_overlap(question, note) >= min_overlap
        ]
    items = notes_to_evidence(selected_notes)
    return [
        item.model_copy(
            update={
                "score": max(item.score, 0.55),
                "metadata": {
                    **item.metadata,
                    "retrieved_by": "graphiti",
                },
            }
        )
        for item in items
    ]


def note_term_overlap(question: str, note: KnowledgeNote) -> int:
    question_terms = _terms(question)
    note_terms = _terms(" ".join([
        note.body.title,
        note.body.summary,
        note.preextract.topic or "",
        note.body.content,
    ]))
    return len(question_terms & note_terms)


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    lowered = text.lower()
    for token in re.findall(r"[a-z0-9_+-]{2,}", lowered):
        terms.add(token)
    for run in re.findall(r"[㐀-鿿]{2,}", text):
        terms.add(run)
        for size in (2, 3):
            for index in range(0, max(0, len(run) - size + 1)):
                terms.add(run[index:index + size])
    return terms
