from __future__ import annotations

import math
import re
from dataclasses import dataclass
from threading import Lock

from ..core.models import Citation, KnowledgeNote
from ..core.projections import RetrievalDocument, retrieval_document_from_note
from ..core.query_understanding import RetrievalFilters
from ..storage.postgres_memory_store import PostgresMemoryStore


@dataclass(frozen=True)
class _StructuralSection:
    note_id: str
    parent_id: str | None
    doc_id: str
    index: int
    tokens: set[str]


@dataclass(frozen=True)
class _StructuralDoc:
    note_id: str
    doc_id: str
    tokens: set[str]
    sections: list[_StructuralSection]


@dataclass(frozen=True)
class _StructuralIndex:
    docs: list[_StructuralDoc]
    sections: list[_StructuralSection]
    document_frequency: dict[str, int]
    num_sections: int
    notes_by_id: dict[str, KnowledgeNote]


@dataclass(frozen=True)
class _StructuralCacheEntry:
    signature: str
    index: _StructuralIndex


class StructuralRetrieverStore:
    """Structural retriever over persisted parent/chunk notes.

    This builds a deterministic parent-section graph over local notes. It does
    not perform LLM/entity ingestion, community detection, or global summary
    generation; cache invalidation is based on the current note set.
    """

    def __init__(self, store: PostgresMemoryStore) -> None:
        self.store = store
        self._cache: dict[tuple[str, str], _StructuralCacheEntry] = {}
        self._lock = Lock()

    def configured(self) -> bool:
        return True

    def search_notes(
        self,
        question: str,
        user_id: str,
        *,
        limit: int = 10,
        filters: RetrievalFilters | None = None,
    ) -> list[KnowledgeNote]:
        index = self._index_for_user(user_id, filters)
        ranked_ids = self.rank_note_ids(question, index, limit=limit)
        return [index.notes_by_id[note_id] for note_id in ranked_ids if note_id in index.notes_by_id]

    def ask(
        self,
        question: str,
        user_id: str,
        *,
        limit: int = 10,
        filters: RetrievalFilters | None = None,
    ) -> tuple[list[KnowledgeNote], list[Citation]]:
        matches = self.search_notes(question, user_id, limit=limit, filters=filters)
        citations = [
            Citation(
                note_id=note.id,
                title=note.body.title,
                snippet=(note.body.summary or note.body.content)[:160],
                relation_fact="Structural retriever match",
            )
            for note in matches[:5]
        ]
        return matches, citations

    def rank_note_ids(
        self,
        query: str,
        index: _StructuralIndex,
        *,
        limit: int,
    ) -> list[str]:
        query_tokens = _structural_tokens(query)
        if not query_tokens:
            return []

        section_scores: dict[str, float] = {}
        parent_scores: dict[str, float] = {}
        sections_by_id = {section.note_id: section for section in index.sections}

        for doc in index.docs:
            doc_score = _token_score(query_tokens, doc.tokens, index)
            if doc_score > 0:
                parent_scores[doc.note_id] = doc_score * 0.8

            best_section_score = 0.0
            for section in doc.sections:
                local_score = _token_score(query_tokens, section.tokens, index)
                propagated_score = local_score + doc_score * 0.25
                if propagated_score <= 0:
                    continue
                section_scores[section.note_id] = propagated_score
                best_section_score = max(best_section_score, local_score)

            if best_section_score > 0:
                parent_scores[doc.note_id] = max(
                    parent_scores.get(doc.note_id, 0.0),
                    best_section_score * 0.7,
                )
                for section in doc.sections:
                    if section.note_id in section_scores:
                        section_scores[section.note_id] += best_section_score * 0.1

        scored_items: list[tuple[float, str]] = []
        scored_items.extend((score, note_id) for note_id, score in section_scores.items())
        scored_items.extend((score, note_id) for note_id, score in parent_scores.items())
        scored_items.sort(
            key=lambda item: (item[0], _structural_tiebreak(item[1], sections_by_id)),
            reverse=True,
        )

        ranked: list[str] = []
        seen: set[str] = set()
        for _, note_id in scored_items:
            if note_id in seen:
                continue
            ranked.append(note_id)
            seen.add(note_id)
            if len(ranked) >= limit:
                break
        return ranked

    def _index_for_user(
        self,
        user_id: str,
        filters: RetrievalFilters | None,
    ) -> _StructuralIndex:
        notes = [
            note
            for note in self.store.list_notes(user_id, include_chunks=True)
            if _note_matches_filters(note, filters)
        ]
        signature = _signature(notes)
        cache_key = (user_id, _filters_signature(filters))
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None and cached.signature == signature:
                return cached.index
            index = build_structural_index(notes)
            self._cache[cache_key] = _StructuralCacheEntry(signature=signature, index=index)
            return index


def build_structural_index(notes: list[KnowledgeNote]) -> _StructuralIndex:
    notes_by_id = {note.id: note for note in notes}
    documents = [retrieval_document_from_note(note) for note in notes]
    children_by_parent: dict[str, list[RetrievalDocument]] = {}
    parent_documents: list[RetrievalDocument] = []
    standalone_children: list[RetrievalDocument] = []

    for document in documents:
        if document.parent_note_id:
            children_by_parent.setdefault(document.parent_note_id, []).append(document)
        else:
            parent_documents.append(document)

    parent_ids = {document.id for document in parent_documents}
    for document in documents:
        if document.parent_note_id and document.parent_note_id not in parent_ids:
            standalone_children.append(document)

    graph_docs: list[_StructuralDoc] = []
    sections: list[_StructuralSection] = []
    document_frequency: dict[str, int] = {}

    for parent in [*parent_documents, *standalone_children]:
        children = sorted(
            children_by_parent.get(parent.id, []),
            key=lambda item: item.chunk_index if item.chunk_index is not None else 10_000,
        )
        parent_tokens = set(_structural_tokens(_note_text(parent, include_content=not children)))
        doc_sections: list[_StructuralSection] = []
        for index, child in enumerate(children):
            child_tokens = set(_structural_tokens(_note_text(child, include_content=True)))
            section = _StructuralSection(
                note_id=child.id,
                parent_id=parent.id,
                doc_id=parent.id,
                index=index,
                tokens=child_tokens,
            )
            doc_sections.append(section)
            sections.append(section)
            for token in child_tokens:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        if not children:
            section = _StructuralSection(
                note_id=parent.id,
                parent_id=None,
                doc_id=parent.id,
                index=0,
                tokens=parent_tokens,
            )
            doc_sections.append(section)
            sections.append(section)
            for token in parent_tokens:
                document_frequency[token] = document_frequency.get(token, 0) + 1

        graph_docs.append(
            _StructuralDoc(
                note_id=parent.id,
                doc_id=parent.id,
                tokens=parent_tokens,
                sections=doc_sections,
            )
        )

    return _StructuralIndex(
        docs=graph_docs,
        sections=sections,
        document_frequency=document_frequency,
        num_sections=max(1, len(sections)),
        notes_by_id=notes_by_id,
    )


def _note_text(document: RetrievalDocument, *, include_content: bool) -> str:
    parts = [
        document.title,
        document.summary,
        document.preextract_topic or "",
        " ".join(document.tags),
        " ".join(document.entity_names),
        " ".join(document.relation_facts),
        " ".join(str(value) for value in document.metadata.values() if value),
    ]
    if include_content:
        parts.append(document.content)
    return " ".join(part for part in parts if part)


def _token_score(query_tokens: list[str], candidate_tokens: set[str], graph: _StructuralIndex) -> float:
    score = 0.0
    for token in query_tokens:
        if token not in candidate_tokens:
            continue
        document_frequency = graph.document_frequency.get(token, 0)
        inverse_document_frequency = math.log((graph.num_sections + 1) / (document_frequency + 1)) + 1.0
        score += inverse_document_frequency * (1.5 if len(token) >= 6 else 1.0)
    return score


def _structural_tiebreak(note_id: str, sections_by_id: dict[str, _StructuralSection]) -> float:
    section = sections_by_id.get(note_id)
    if section is None:
        return 0.0
    return -float(section.index)


def _structural_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+", text.lower()):
        if len(raw) < 2 or raw in _STRUCTURAL_STOPWORDS:
            continue
        tokens.append(raw)
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", raw):
            for size in (2, 3):
                for index in range(0, len(raw) - size + 1):
                    tokens.append(raw[index:index + size])
    return tokens


def _signature(notes: list[KnowledgeNote]) -> str:
    documents = [retrieval_document_from_note(note) for note in notes]
    parts = [
        f"{document.id}:{document.updated_at.isoformat()}:{document.parent_note_id or ''}:{document.chunk_index or ''}"
        for document in sorted(documents, key=lambda item: item.id)
    ]
    return f"{len(documents)}|" + "|".join(parts)


def _filters_signature(filters: RetrievalFilters | None) -> str:
    if filters is None or not filters.active():
        return ""
    return filters.model_dump_json(exclude_defaults=True)


def _note_matches_filters(note: KnowledgeNote, filters: RetrievalFilters | None) -> bool:
    if filters is None or not filters.active():
        return True
    if filters.source_types and note.source.type not in filters.source_types:
        return False
    if filters.source_ref_contains.strip():
        needle = filters.source_ref_contains.strip().lower()
        if needle not in (note.source.ref or "").lower():
            return False
    if filters.tags:
        note_tags = {tag.lower() for tag in note.tags}
        if not all(tag.lower() in note_tags for tag in filters.tags):
            return False
    if filters.metadata_contains.strip():
        metadata_text = " ".join(str(value) for value in note.source.metadata.values()).lower()
        if filters.metadata_contains.strip().lower() not in metadata_text:
            return False
    if filters.parent_note_id.strip():
        parent_id = filters.parent_note_id.strip()
        if note.id != parent_id and note.chunk.parent_note_id != parent_id:
            return False
    return True


_STRUCTURAL_STOPWORDS = {
    "the",
    "and",
    "for",
    "from",
    "with",
    "that",
    "this",
    "are",
    "was",
    "were",
    "into",
    "about",
    "what",
    "which",
    "where",
    "when",
    "how",
    "why",
    "who",
}
