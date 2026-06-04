"""Convert MultiHopRAG data into project-internal types.

Key differences from the Open RAGBench adapter:

- Documents have no section split, so chunk notes are produced by running the
  *production* chunker (``personal_agent.core.chunking.chunk_content``) over the
  article body.
- A query's relevance is a *set* of parent note ids (one per evidence URL),
  because MultiHopRAG evidence is distributed across 2-4 documents.
- The article URL is the doc key; note ids are derived via a stable hash slug
  because URLs cannot be used as note ids directly.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from personal_agent.core.chunking import chunk_content
from personal_agent.core.models import KnowledgeNote, NoteBody, NoteChunk, NoteSource

from .loader import MHRDoc, MHRQuery

_EVAL_USER = "multihoprag_eval"
CorpusNoteMode = str  # parent_only | parent_chunks | section_only


def parent_note_id(url: str) -> str:
    """Deterministic, filesystem/id-safe note id derived from an article URL."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"mhr_{digest}"


@dataclass(frozen=True)
class EdgeLike:
    """Minimal edge-like object compatible with ``rank_graph_citation_hits``."""
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    episodes: list[str]


def corpus_to_notes(
    docs: dict[str, MHRDoc],
    mode: CorpusNoteMode = "parent_chunks",
) -> list[KnowledgeNote]:
    """Convert MHRDocs into parent + chunk KnowledgeNote objects.

    Each article becomes a parent note; the body is split into chunk child
    notes via the production chunker. ``parent_only`` keeps just the parent,
    ``section_only`` keeps just the chunks, ``parent_chunks`` keeps both.
    """
    if mode not in {"parent_only", "parent_chunks", "section_only"}:
        raise ValueError(f"Unknown corpus note mode: {mode}")

    notes: list[KnowledgeNote] = []
    for url, doc in docs.items():
        pid = parent_note_id(url)
        parent = KnowledgeNote(
            id=pid,
            user_id=_EVAL_USER,
            source=NoteSource(type="text", ref=url),
            body=NoteBody(title=doc.title, content=doc.body, summary=doc.body[:200]),
        )
        if mode in {"parent_only", "parent_chunks"}:
            notes.append(parent)
        if mode == "parent_only":
            continue
        chunks = chunk_content(doc.body, "text")
        for idx, chunk in enumerate(chunks):
            content = chunk.get("content", "").strip()
            if not content:
                continue
            child = KnowledgeNote(
                id=f"{pid}_sec_{idx}",
                user_id=_EVAL_USER,
                source=NoteSource(type="text", ref=url),
                body=NoteBody(
                    title=(chunk.get("title") or content[:80]),
                    content=content,
                    summary=content[:200],
                ),
                chunk=NoteChunk(
                    parent_note_id=pid,
                    index=idx,
                    source_span=chunk.get("source_span"),
                ),
            )
            notes.append(child)
    return notes


def corpus_to_edges(
    docs: dict[str, MHRDoc],
) -> tuple[list[EdgeLike], dict[str, str]]:
    """Convert corpus chunks into EdgeLike objects for graph reranker eval.

    Returns ``(edges, node_names_by_uuid)``. Episode ids are
    ``ep_{parent_note_id}_{chunk_idx}`` to mirror ``expected_episodes``.
    """
    edges: list[EdgeLike] = []
    node_names: dict[str, str] = {}
    for url, doc in docs.items():
        pid = parent_note_id(url)
        doc_node = f"node_doc_{pid}"
        node_names[doc_node] = doc.title
        for idx, chunk in enumerate(chunk_content(doc.body, "text")):
            content = chunk.get("content", "").strip()
            if not content:
                continue
            sec_node = f"node_sec_{pid}_{idx}"
            node_names[sec_node] = content[:60]
            edges.append(EdgeLike(
                fact=content[:500],
                source_node_uuid=doc_node,
                target_node_uuid=sec_node,
                episodes=[f"ep_{pid}_{idx}"],
            ))
    return edges, node_names


def expected_note_ids(query: MHRQuery) -> set[str]:
    """Return the set of parent note ids backing a query's evidence.

    This is the multi-hop relevance set: a query is fully answered only when
    all evidence documents are retrieved, so we score against the whole set.
    """
    return {parent_note_id(url) for url in query.evidence_urls}


def expected_episodes(query: MHRQuery) -> set[str]:
    """Return parent-level episode prefixes for citation-style eval.

    Chunk indices are unknown at query time, so this returns the parent doc
    nodes; citation strategies should map episode -> note id before scoring.
    """
    return {f"node_doc_{parent_note_id(url)}" for url in query.evidence_urls}
