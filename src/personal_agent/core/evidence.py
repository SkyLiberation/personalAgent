"""Unified evidence model for the personal agent.

Converges graph facts, note/chunk snippets, web citations, and tool results
into a single trackable evidence structure.  The existing ``Citation`` model
remains as a lightweight display type derived from ``EvidenceItem``.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .models import Citation, KnowledgeNote
from ..graphiti.reranker import GraphCitationHit
from ..graphiti.store import GraphAskResult


class EvidenceItem(BaseModel):
    evidence_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    source_type: Literal["graph_fact", "note", "chunk", "web", "tool"]
    source_id: str = ""
    title: str = ""
    snippet: str = ""
    fact: str | None = None
    source_span: str | None = None
    url: str | None = None
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def graph_result_to_evidence(
    graph_result: GraphAskResult,
    notes_by_episode: dict[str, KnowledgeNote],
    question: str,
) -> list[EvidenceItem]:
    """Convert a ``GraphAskResult`` into a list of ``EvidenceItem``.

    Mapping rules:
    - ``fact_refs / edge_refs`` -> ``source_type="graph_fact"``
    - ``citation_hits`` with episode -> note lookup -> ``source_type="note"`` / ``"chunk"``
    - ``citation_hits`` without episode match -> ``source_type="graph_fact"``, ``orphan=True``
    """
    from ..agent.runtime_helpers import _best_snippet  # noqa: lazy to avoid circular

    items: list[EvidenceItem] = []
    seen_facts: set[str] = set()

    # 1. fact_refs -> graph_fact evidence
    for fact_ref in graph_result.fact_refs:
        fact = fact_ref.fact.strip()
        if not fact or fact in seen_facts:
            continue
        seen_facts.add(fact)
        items.append(EvidenceItem(
            source_type="graph_fact",
            source_id=fact_ref.edge_uuid,
            fact=fact,
            metadata={
                "source_node_name": fact_ref.source_node_name,
                "target_node_name": fact_ref.target_node_name,
                "episode_uuids": fact_ref.episode_uuids,
            },
        ))

    # 2. edge_refs -> graph_fact evidence (dedup against fact_refs)
    for edge_ref in graph_result.edge_refs:
        fact = edge_ref.fact.strip()
        if not fact or fact in seen_facts:
            continue
        seen_facts.add(fact)
        items.append(EvidenceItem(
            source_type="graph_fact",
            source_id=edge_ref.uuid,
            fact=fact,
            metadata={
                "source_node_name": edge_ref.source_node_name,
                "target_node_name": edge_ref.target_node_name,
                "episodes": edge_ref.episodes,
            },
        ))

    # 3. citation_hits -> note/chunk or orphan graph_fact
    for hit in graph_result.citation_hits:
        note = notes_by_episode.get(hit.episode_uuid)
        if note is not None:
            source_type = "chunk" if note.parent_note_id is not None else "note"
            snippet = _best_snippet(note, hit, question)
            items.append(EvidenceItem(
                source_type=source_type,
                source_id=note.id,
                title=note.title,
                snippet=snippet,
                fact=hit.relation_fact,
                score=float(hit.score),
                metadata={
                    "episode_uuid": hit.episode_uuid,
                    "endpoint_names": hit.endpoint_names,
                    "matched_terms": hit.matched_terms,
                    "entity_overlap_count": hit.entity_overlap_count,
                    "orphan": False,
                },
            ))
        else:
            fact = hit.relation_fact.strip()
            if not fact or fact in seen_facts:
                continue
            seen_facts.add(fact)
            items.append(EvidenceItem(
                source_type="graph_fact",
                source_id=hit.episode_uuid,
                fact=fact,
                score=float(hit.score),
                metadata={
                    "episode_uuid": hit.episode_uuid,
                    "endpoint_names": hit.endpoint_names,
                    "orphan": True,
                },
            ))

    return items


def notes_to_evidence(matches: list[KnowledgeNote]) -> list[EvidenceItem]:
    """Convert local note/chunk matches to ``EvidenceItem``."""
    items: list[EvidenceItem] = []
    for note in matches:
        source_type = "chunk" if note.parent_note_id is not None else "note"
        snippet = note.content[:500] if source_type == "chunk" else note.summary
        items.append(EvidenceItem(
            source_type=source_type,
            source_id=note.id,
            title=note.title,
            snippet=snippet,
            source_span=note.source_span,
            metadata={"graph_episode_uuid": note.graph_episode_uuid},
        ))
    return items


def web_results_to_evidence(results: list[dict]) -> list[EvidenceItem]:
    """Convert raw web search result dicts to ``EvidenceItem``."""
    items: list[EvidenceItem] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        url = str(r.get("url", ""))
        items.append(EvidenceItem(
            source_type="web",
            source_id=url,
            title=str(r.get("title", "")),
            snippet=str(r.get("snippet", "")),
            url=url,
            metadata={
                "source": r.get("source", ""),
                "published_at": r.get("published_at"),
            },
        ))
    return items


def evidence_to_citations(evidence: list[EvidenceItem]) -> list[Citation]:
    """Derive ``Citation`` display models from ``EvidenceItem``."""
    citations: list[Citation] = []
    for item in evidence:
        if item.source_type == "web":
            citations.append(Citation(
                note_id="",
                title=item.title,
                snippet=item.snippet,
                url=item.url,
                source_type="web",
            ))
        else:
            citations.append(Citation(
                note_id=item.source_id,
                title=item.title,
                snippet=item.snippet,
                relation_fact=item.fact,
                source_type="note",
            ))
    return citations
