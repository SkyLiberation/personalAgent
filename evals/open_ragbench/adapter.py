"""Convert Open RAG Benchmark data into project-internal types."""
from __future__ import annotations

from dataclasses import dataclass

from personal_agent.core.models import KnowledgeNote, NoteBody, NoteChunk, NoteSource

from .loader import RAGBenchDoc, RAGBenchQuery

_EVAL_USER = "ragbench_eval"
CorpusNoteMode = str


@dataclass(frozen=True)
class EdgeLike:
    """Minimal edge-like object compatible with ``rank_graph_citation_hits``."""
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    episodes: list[str]


def corpus_to_notes(docs: dict[str, RAGBenchDoc], mode: CorpusNoteMode = "parent_sections") -> list[KnowledgeNote]:
    """Convert RAGBenchDocs to parent + child KnowledgeNote objects.

    Each paper becomes a parent note; each section becomes a child note
    with ``parent_note_id`` linking back to the parent.
    """
    if mode not in {"parent_sections", "parent_only", "section_only"}:
        raise ValueError(f"Unknown corpus note mode: {mode}")

    notes: list[KnowledgeNote] = []
    for doc_id, doc in docs.items():
        parent_id = f"ragbench_{doc_id}"
        parent = KnowledgeNote(
            id=parent_id,
            user_id=_EVAL_USER,
            source=NoteSource(type="text"),
            body=NoteBody(title=doc.title, content=doc.abstract, summary=doc.abstract[:200]),
        )
        if mode in {"parent_sections", "parent_only"}:
            notes.append(parent)
        if mode == "parent_only":
            continue
        for idx, section_text in enumerate(doc.sections):
            child = KnowledgeNote(
                id=f"{parent_id}_sec_{idx}",
                user_id=_EVAL_USER,
                source=NoteSource(type="text"),
                body=NoteBody(
                    title=section_text[:80],
                    content=section_text,
                    summary=section_text[:200],
                ),
                chunk=NoteChunk(parent_note_id=parent_id, index=idx),
            )
            notes.append(child)
    return notes


def corpus_to_edges(
    docs: dict[str, RAGBenchDoc],
) -> tuple[list[EdgeLike], dict[str, str]]:
    """Convert corpus sections into EdgeLike objects for graph reranker eval.

    Returns ``(edges, node_names_by_uuid)``.
    """
    edges: list[EdgeLike] = []
    node_names: dict[str, str] = {}
    for doc_id, doc in docs.items():
        doc_node = f"node_doc_{doc_id}"
        node_names[doc_node] = doc.title
        for idx, section_text in enumerate(doc.sections):
            sec_node = f"node_sec_{doc_id}_{idx}"
            node_names[sec_node] = section_text[:60]
            edges.append(EdgeLike(
                fact=section_text[:500],
                source_node_uuid=doc_node,
                target_node_uuid=sec_node,
                episodes=[f"ep_{doc_id}_{idx}"],
            ))
    return edges, node_names


def expected_note_ids(query: RAGBenchQuery) -> tuple[str, str]:
    """Return ``(section_note_id, parent_note_id)`` for relevance matching."""
    parent_id = f"ragbench_{query.relevant_doc_id}"
    section_id = f"{parent_id}_sec_{query.relevant_section_idx}"
    return section_id, parent_id


def expected_episode(query: RAGBenchQuery) -> str:
    """Return the expected episode UUID for reranker eval."""
    return f"ep_{query.relevant_doc_id}_{query.relevant_section_idx}"
