"""Unified evidence model for the personal agent.

Converges graph facts, note/chunk snippets, web citations, and tool results
into a single trackable evidence structure.  The existing ``Citation`` model
remains as a lightweight display type derived from ``EvidenceItem``.
"""
from __future__ import annotations

import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .models import Citation, KnowledgeNote
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


class RankedEvidence(BaseModel):
    evidence: EvidenceItem
    score: float = 0.0
    reason: str = ""
    selected_for_prompt: bool = False
    estimated_chars: int = 0


class ContextPack(BaseModel):
    question: str
    selected: list[RankedEvidence] = Field(default_factory=list)
    dropped: list[RankedEvidence] = Field(default_factory=list)
    char_budget: int = 5000
    used_chars: int = 0

    @property
    def evidence(self) -> list[EvidenceItem]:
        return [item.evidence for item in self.selected]


def build_context_pack(
    question: str,
    evidence: list[EvidenceItem],
    *,
    max_items: int = 12,
    char_budget: int = 5000,
) -> ContextPack:
    """Rank, dedupe, and select evidence for prompt assembly.

    This is intentionally lightweight and deterministic: it gives us a clear
    boundary before introducing heavier cross-encoder or LLM rerankers.
    """
    return select_ranked_evidence(
        question,
        rank_evidence_items(question, evidence),
        max_items=max_items,
        char_budget=char_budget,
    )


def rank_evidence_items(question: str, evidence: list[EvidenceItem]) -> list[RankedEvidence]:
    """Return deterministic heuristic ranking before prompt budget selection."""
    ranked = [_rank_evidence_item(question, item) for item in _dedupe_evidence_items(evidence)]
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def select_ranked_evidence(
    question: str,
    ranked: list[RankedEvidence],
    *,
    max_items: int = 12,
    char_budget: int = 5000,
) -> ContextPack:
    """Select ranked evidence with diversity and prompt budget constraints."""
    ranked = [
        item.model_copy(update={"selected_for_prompt": False})
        for item in ranked
    ]

    selected: list[RankedEvidence] = []
    dropped: list[RankedEvidence] = []
    used_chars = 0
    seen_sources: set[tuple[str, str]] = set()

    for item in ranked:
        diversity_key = (item.evidence.source_type, item.evidence.source_id or item.evidence.url or item.evidence.title)
        duplicate_source = diversity_key in seen_sources and item.evidence.source_type in {"note", "chunk", "web"}
        would_fit = used_chars + item.estimated_chars <= char_budget
        must_select_first = not selected
        if len(selected) < max_items and (would_fit or must_select_first) and not duplicate_source:
            item.selected_for_prompt = True
            selected.append(item)
            used_chars += item.estimated_chars
            if diversity_key[1]:
                seen_sources.add(diversity_key)
        else:
            item.selected_for_prompt = False
            dropped.append(item)

    return ContextPack(
        question=question,
        selected=selected,
        dropped=dropped,
        char_budget=char_budget,
        used_chars=used_chars,
    )


def _dedupe_evidence_items(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    deduped: list[EvidenceItem] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in evidence:
        key = (
            item.source_type,
            item.source_id or item.url or "",
            (item.fact or "").strip(),
            (item.snippet or "").strip()[:180],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _rank_evidence_item(question: str, item: EvidenceItem) -> RankedEvidence:
    score = 0.0
    reasons: list[str] = []
    content = " ".join(part for part in [item.title, item.fact or "", item.snippet] if part)

    overlap = _term_overlap(question, content)
    if overlap:
        score += min(overlap * 0.12, 0.48)
        reasons.append(f"term_overlap={overlap}")

    if item.score:
        normalized_source_score = min(max(float(item.score), 0.0), 1.0)
        score += normalized_source_score * 0.25
        reasons.append(f"source_score={normalized_source_score:.2f}")

    source_weight = {
        "chunk": 0.22,
        "note": 0.18,
        "graph_fact": 0.16,
        "web": 0.14,
        "tool": 0.10,
    }.get(item.source_type, 0.0)
    score += source_weight
    reasons.append(f"source={item.source_type}")

    if item.snippet:
        score += 0.10
        reasons.append("snippet")
    if item.fact:
        score += 0.08
        reasons.append("fact")
    if item.source_span:
        score += 0.05
        reasons.append("source_span")
    if item.url:
        score += 0.04
        reasons.append("url")

    if item.metadata.get("orphan") is True:
        score -= 0.12
        reasons.append("orphan_penalty")
    if item.metadata.get("published_at"):
        score += 0.04
        reasons.append("freshness_metadata")

    estimated_chars = min(max(len(content), 80), 900)
    return RankedEvidence(
        evidence=item,
        score=round(max(score, 0.0), 4),
        reason=", ".join(reasons) or "baseline",
        estimated_chars=estimated_chars,
    )


def _term_overlap(question: str, content: str) -> int:
    question_terms = _terms(question)
    content_terms = _terms(content)
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
    # Lazy import avoids a circular dependency with the ask runtime helpers.
    from ..agent.runtime_helpers import _best_snippet

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
            metadata={
                "graph_episode_uuid": note.graph_episode_uuid,
                "source_ref": note.source_ref,
                "source_fingerprint": note.source_fingerprint,
                **note.metadata,
            },
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
