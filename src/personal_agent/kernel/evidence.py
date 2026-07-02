"""Unified evidence model for the personal agent.

Converges graph facts, note/chunk snippets, web citations, and tool results
into a single trackable evidence structure.  The existing ``Citation`` model
remains as a lightweight display type derived from ``EvidenceItem``.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from personal_agent.kernel.models import Citation, KnowledgeNote, MemoryEpisode, MemoryItem
from personal_agent.kernel.projections import EvidenceSource, evidence_source_from_note
from personal_agent.kernel.graph_results import GraphAskResult, GraphCitationHit


class SourceDocument(BaseModel):
    """Canonical source material before task-specific evidence selection."""

    source_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    source_type: str = "unknown"
    source_ref: str | None = None
    source_fingerprint: str | None = None
    url: str | None = None
    canonical_url: str | None = None
    domain: str = ""
    title: str = ""
    snippet: str = ""
    content: str = ""
    published_at: datetime | None = None
    provider: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def preferred_ref(self) -> str:
        return self.canonical_url or self.url or self.source_ref or self.source_id


class EvidenceItem(BaseModel):
    evidence_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    source_type: Literal["graph_fact", "note", "chunk", "web", "tool", "episode", "procedural", "reflection"]
    source_id: str = ""
    parent_note_id: str | None = None
    title: str = ""
    snippet: str = ""
    fact: str | None = None
    source_span: str | None = None
    source_ref: str | None = None
    source_fingerprint: str | None = None
    page_number: int | None = None
    element_ids: list[str] = Field(default_factory=list)
    coordinates: dict[str, Any] | None = None
    url: str | None = None
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def lineage(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "parent_note_id": self.parent_note_id,
            "source_ref": self.source_ref,
            "source_fingerprint": self.source_fingerprint,
            "source_span": self.source_span,
            "page_number": self.page_number,
            "element_ids": list(self.element_ids),
            "coordinates": self.coordinates,
            "url": self.url,
        }


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
    mmr_lambda: float = 0.7,
) -> ContextPack:
    """Select ranked evidence under MMR diversity + prompt budget constraints.

    Greedy-by-score selection lets several near-identical snippets (same opinion
    restated by different sources) fill the budget. MMR instead picks, at each
    step, the candidate maximizing ``λ·relevance − (1−λ)·max_similarity`` against
    what's already selected, so the pack covers more distinct points within the
    same budget. ``mmr_lambda`` leans toward relevance (0.7) by default; lower
    values diversify harder. Similarity is lexical Jaccard over content terms —
    cheap, deterministic, no embeddings.
    """
    ranked = [
        item.model_copy(update={"selected_for_prompt": False})
        for item in ranked
    ]

    # Hard filter: stale versions never enter the pack regardless of score.
    candidates: list[RankedEvidence] = []
    dropped: list[RankedEvidence] = []
    for item in ranked:
        version_status = str(item.evidence.metadata.get("version_status") or "current")
        superseded = bool(item.evidence.metadata.get("superseded_by_note_id"))
        if item.evidence.source_type in {"note", "chunk"} and (
            version_status in {"superseded", "deprecated"} or superseded
        ):
            dropped.append(item)
        else:
            candidates.append(item)

    # Precompute content term sets once for the similarity matrix.
    term_cache: dict[str, set[str]] = {}

    def _content_terms(item: RankedEvidence) -> set[str]:
        key = item.evidence.evidence_id
        cached = term_cache.get(key)
        if cached is None:
            ev = item.evidence
            text = " ".join(part for part in [ev.title, ev.fact or "", ev.snippet] if part)
            cached = _terms(text)
            term_cache[key] = cached
        return cached

    max_score = max((c.score for c in candidates), default=0.0) or 1.0
    selected: list[RankedEvidence] = []
    used_chars = 0
    remaining = list(candidates)

    while remaining and len(selected) < max_items:
        best: RankedEvidence | None = None
        best_mmr = float("-inf")
        for cand in remaining:
            would_fit = used_chars + cand.estimated_chars <= char_budget
            if selected and not would_fit:
                continue
            relevance = cand.score / max_score
            if selected:
                cand_terms = _content_terms(cand)
                similarity = max(
                    _jaccard(cand_terms, _content_terms(sel)) for sel in selected
                )
            else:
                similarity = 0.0
            mmr = mmr_lambda * relevance - (1.0 - mmr_lambda) * similarity
            if mmr > best_mmr:
                best_mmr = mmr
                best = cand

        if best is None:
            break
        best.selected_for_prompt = True
        selected.append(best)
        used_chars += best.estimated_chars
        remaining.remove(best)

    for item in remaining:
        item.selected_for_prompt = False
        dropped.append(item)

    return ContextPack(
        question=question,
        selected=selected,
        dropped=dropped,
        char_budget=char_budget,
        used_chars=used_chars,
    )


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    if not intersection:
        return 0.0
    return intersection / len(a | b)


def _split_sentences(text: str) -> list[str]:
    """Split into sentences on CJK + ASCII terminators and newlines."""
    normalized = text.replace("\r", "\n")
    parts: list[str] = []
    current = ""
    for char in normalized:
        current += char
        if char in {"。", "！", "？", ".", "!", "?", "\n"}:
            stripped = current.strip()
            if stripped:
                parts.append(stripped)
            current = ""
    if current.strip():
        parts.append(current.strip())
    return parts


def _tokenize_for_overlap(text: str) -> set[str]:
    """Tokenize text into lowercased meaningful words for overlap scoring."""
    if not text:
        return set()
    tokens: set[str] = set()
    for token in text.lower().split():
        cleaned = "".join(c for c in token if c.isalnum())
        if len(cleaned) >= 2:
            tokens.add(cleaned)
    return tokens


def _extract_question_keywords(question: str) -> list[str]:
    keywords: list[str] = []
    buffer = ""
    for char in question:
        if char.isascii() and (char.isalnum() or char in {"_", "-"}):
            buffer += char.lower()
            continue
        if buffer:
            if len(buffer) >= 2 and buffer not in keywords:
                keywords.append(buffer)
            buffer = ""
    if buffer and len(buffer) >= 2 and buffer not in keywords:
        keywords.append(buffer)
    compact = question.replace("？", " ").replace("。", " ").replace("，", " ").replace(",", " ")
    for chunk in compact.split():
        normalized = chunk.strip()
        if len(normalized) >= 2 and not normalized.isascii() and normalized not in keywords:
            keywords.append(normalized)
    return keywords[:8]


def _best_snippet(note: KnowledgeNote, hit: GraphCitationHit, question: str) -> str:
    """Select the sentence from note content that best anchors the graph relation_fact.

    Uses word-overlap scoring between the relation_fact and each sentence,
    weighted by entity name matches and question keyword relevance.
    Falls back to note summary when no sentence reaches the minimum score.
    """
    best_part = ""
    best_score = -1
    question_keywords = _extract_question_keywords(question)
    fact_tokens = _tokenize_for_overlap(hit.relation_fact)
    entity_names = [n for n in (hit.endpoint_names or note.graph.entity_names or []) if len(n) >= 2]

    for part in _split_sentences(note.body.content):
        if len(part) < 10:
            continue
        score = 0
        if fact_tokens:
            part_tokens = _tokenize_for_overlap(part)
            if part_tokens:
                overlap = len(fact_tokens & part_tokens)
                score += min(overlap * 5, 30)
        if hit.relation_fact and hit.relation_fact in part:
            score += 10
        for entity_name in entity_names:
            if entity_name in part:
                score += 5
        for keyword in question_keywords:
            if keyword in part:
                score += 2
        if score > best_score:
            best_part = part
            best_score = score

    if best_part and best_score >= 3:
        return best_part[:160]
    if best_part:
        return best_part[:160]
    return note.body.summary[:160]


def compress_evidence(
    question: str,
    evidence: list[EvidenceItem],
    *,
    max_sentences: int = 3,
    min_chars: int = 240,
) -> list[EvidenceItem]:
    """Extractive sentence-level compression of evidence snippets.

    For each long ``note``/``chunk`` snippet, keep only the top sentences by
    question-term overlap (in original order, so reading flow and citation
    anchors survive). Extractive — never rewrites text, so no hallucination —
    and skips short snippets and atomic facts (``graph_fact``/``web``) where
    there is nothing to trim. Run before rank/select so the freed character
    budget admits more *distinct* evidence rather than fewer long blocks.
    """
    q_terms = _terms(question)
    compressed: list[EvidenceItem] = []
    for item in evidence:
        snippet = item.snippet or ""
        if item.source_type not in {"note", "chunk"} or len(snippet) <= min_chars:
            compressed.append(item)
            continue
        sentences = _split_sentences(snippet)
        if len(sentences) <= max_sentences:
            compressed.append(item)
            continue
        scored = [
            (len(_terms(sentence) & q_terms), index, sentence)
            for index, sentence in enumerate(sentences)
        ]
        # Keep the highest-overlap sentences, then restore original order.
        top = sorted(scored, key=lambda triple: (-triple[0], triple[1]))[:max_sentences]
        if not any(score > 0 for score, _, _ in top):
            compressed.append(item)
            continue
        kept = [sentence for _, _, sentence in sorted(top, key=lambda triple: triple[1])]
        new_snippet = " ".join(kept)
        if len(new_snippet) >= len(snippet):
            compressed.append(item)
            continue
        meta = dict(item.metadata)
        meta["compressed_from_chars"] = len(snippet)
        compressed.append(item.model_copy(update={"snippet": new_snippet, "metadata": meta}))
    return compressed


def canonical_evidence_key(item: EvidenceItem) -> tuple[str, str]:
    """Identity of the *thing* an evidence item points at.

    Dedup must key on the underlying entity, not on volatile fields like
    ``source_type`` / ``snippet`` / ``score``. The same note reached via the
    graph path (``retrieved_by="graphiti"``, score floored to 0.55) and via the
    local path is one entity; keying on entity identity collapses them into a
    single consensus-bearing item instead of two near-duplicate candidates.
    """
    if item.source_type in {"note", "chunk"}:
        return ("note_entity", item.source_id)
    if item.source_type == "graph_fact":
        return ("fact", item.source_id or (item.fact or "").strip())
    if item.source_type == "web":
        return ("web", (item.url or item.source_id or "").strip())
    return (item.source_type, item.source_id or (item.snippet or "").strip()[:180])


def _merge_evidence_group(items: list[EvidenceItem]) -> EvidenceItem:
    """Collapse same-entity items into one, keeping the highest-scored as the
    representative and recording which retrieval paths reached it (consensus).

    ``source_ranks`` from every member is merged (min rank per source) so the
    downstream RRF fusion can reward an entity that ranked highly across several
    independent retrieval paths instead of treating the overlap as waste."""
    merged_ranks: dict[str, int] = {}
    for it in items:
        for source, rank in (it.metadata.get("source_ranks") or {}).items():
            if source not in merged_ranks or rank < merged_ranks[source]:
                merged_ranks[source] = rank
    if len(items) == 1 and not merged_ranks:
        return items[0]
    best = max(items, key=lambda it: it.score)
    retrieved_by_all: list[str] = []
    for it in items:
        rb = it.metadata.get("retrieved_by")
        if rb and rb not in retrieved_by_all:
            retrieved_by_all.append(rb)
    merged_metadata = dict(best.metadata)
    if retrieved_by_all:
        merged_metadata["retrieved_by_all"] = retrieved_by_all
    if merged_ranks:
        merged_metadata["source_ranks"] = merged_ranks
        merged_metadata["consensus_count"] = len(merged_ranks)
    else:
        merged_metadata["consensus_count"] = len(items)
    return best.model_copy(update={"metadata": merged_metadata})


def apply_rrf_fusion(evidence: list[EvidenceItem], *, k: int = 60) -> list[EvidenceItem]:
    """Reciprocal Rank Fusion over per-source ranks recorded during retrieval.

    Each item carries ``metadata["source_ranks"]`` = {source: rank} populated
    when the coordinator absorbed each source's ranked contribution. RRF score
    is ``Σ 1/(k + rank)`` over those sources: an item ranked highly by several
    independent paths sums several terms and rises, so multi-path overlap (e.g.
    a note hit by both graph and local recall) becomes a consensus signal rather
    than duplicate candidates. Rank-based, so incomparable per-source scores
    (graph 0.55 floor vs local cosine) never need to be normalized.

    Mutates and returns ``evidence`` in place; sets ``metadata["fusion_score"]``.
    """
    for item in evidence:
        ranks = item.metadata.get("source_ranks") or {}
        if not ranks:
            continue
        rrf = sum(1.0 / (k + int(rank)) for rank in ranks.values())
        item.metadata["fusion_score"] = round(rrf, 6)
    return evidence


def _dedupe_evidence_items(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    groups: dict[tuple[str, str], list[EvidenceItem]] = {}
    order: list[tuple[str, str]] = []
    for item in evidence:
        key = canonical_evidence_key(item)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)
    return [_merge_evidence_group(groups[key]) for key in order]


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
        "episode": 0.13,
        "procedural": 0.12,
        "reflection": 0.11,
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
    version_status = item.metadata.get("version_status")
    if version_status == "conflicted":
        score -= 0.18
        reasons.append("conflict_penalty")
    elif version_status in {"superseded", "deprecated"} or item.metadata.get("superseded_by_note_id"):
        score -= 1.0
        reasons.append("stale_version_penalty")
    confidence = item.metadata.get("version_confidence")
    if isinstance(confidence, int | float):
        score += max(0.0, min(float(confidence), 1.0)) * 0.05
        reasons.append(f"version_confidence={float(confidence):.2f}")
    if item.metadata.get("published_at"):
        score += 0.04
        reasons.append("freshness_metadata")

    # RRF consensus: an entity ranked highly by several independent retrieval
    # paths sums several 1/(k+rank) terms. Scaled into the same band as the
    # other heuristic signals and capped so consensus informs but never
    # dominates lexical/version relevance.
    fusion_score = item.metadata.get("fusion_score")
    if isinstance(fusion_score, int | float) and fusion_score > 0:
        boost = min(float(fusion_score) * 3.0, 0.15)
        score += boost
        consensus = item.metadata.get("consensus_count")
        reasons.append(
            f"rrf_consensus={consensus}" if consensus else f"rrf={float(fusion_score):.4f}"
        )

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
            source_type = "chunk" if note.chunk.parent_note_id is not None else "note"
            snippet = _best_snippet(note, hit, question)
            items.append(EvidenceItem(
                source_type=source_type,
                source_id=note.id,
                parent_note_id=note.chunk.parent_note_id,
                title=note.body.title,
                snippet=snippet,
                fact=hit.relation_fact,
                source_ref=note.source.ref,
                source_fingerprint=note.source.fingerprint,
                source_span=note.chunk.source_span,
                page_number=note.chunk.page_number,
                element_ids=list(note.chunk.element_ids),
                coordinates=note.chunk.coordinates,
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

    # 4. provider-level relation facts/answers. Some graph providers (for
    # example Microsoft GraphRAG CLI queries) return a synthesized answer
    # rather than episode-level citation hits.
    for index, fact in enumerate(graph_result.relation_facts):
        normalized = fact.strip()
        if not normalized or normalized in seen_facts:
            continue
        seen_facts.add(normalized)
        items.append(EvidenceItem(
            source_type="graph_fact",
            source_id=f"relation_fact_{index}",
            fact=normalized,
            score=0.55,
            metadata={"retrieved_by": "graph_provider_relation_fact"},
        ))

    if graph_result.answer:
        answer = graph_result.answer.strip()
        if answer and answer not in seen_facts:
            items.append(EvidenceItem(
                source_type="graph_fact",
                source_id="graph_answer",
                fact=answer,
                score=0.5,
                metadata={"retrieved_by": "graph_provider_answer"},
            ))

    return items


def source_documents_to_evidence(documents: list[SourceDocument]) -> list[EvidenceItem]:
    """Convert canonical source documents to shared web/tool evidence."""
    items: list[EvidenceItem] = []
    for document in documents:
        ref = document.preferred_ref
        snippet = document.snippet or _first_text_span(document.content)
        items.append(EvidenceItem(
            source_type="web" if document.url else "tool",
            source_id=document.source_id,
            title=document.title or ref,
            snippet=snippet,
            source_ref=ref,
            source_fingerprint=document.source_fingerprint,
            url=document.url,
            metadata={
                "source_document_id": document.source_id,
                "source_document_type": document.source_type,
                "canonical_url": document.canonical_url,
                "domain": document.domain,
                "provider": document.provider,
                "published_at": document.published_at.isoformat() if document.published_at else None,
                "content": document.content,
                **document.metadata,
            },
        ))
    return items


def research_sources_to_source_documents(sources: list[Any]) -> list[SourceDocument]:
    """Project research sources into the shared source-document boundary."""
    documents: list[SourceDocument] = []
    for source in sources:
        documents.append(SourceDocument(
            source_id=str(getattr(source, "id", "") or uuid4().hex[:12]),
            source_type=str(getattr(source, "source_type", "") or "unknown"),
            source_ref=str(getattr(source, "canonical_url", "") or getattr(source, "url", "") or ""),
            source_fingerprint=str(getattr(source, "content_fingerprint", "") or ""),
            url=str(getattr(source, "url", "") or ""),
            canonical_url=str(getattr(source, "canonical_url", "") or ""),
            domain=str(getattr(source, "domain", "") or ""),
            title=str(getattr(source, "title", "") or ""),
            snippet=str(getattr(source, "snippet", "") or ""),
            content=str(getattr(source, "content", "") or ""),
            published_at=getattr(source, "published_at", None),
            provider=str(getattr(source, "provider", "") or ""),
            metadata={
                "decision_id": getattr(source, "decision_id", None),
                "query": getattr(source, "query", ""),
                "query_phase": getattr(source, "query_phase", ""),
            },
        ))
    return documents


def research_sources_to_evidence(sources: list[Any]) -> list[EvidenceItem]:
    """Convert research sources to the same ``EvidenceItem`` shape ask uses."""
    return source_documents_to_evidence(research_sources_to_source_documents(sources))


def evidence_text_spans(evidence: EvidenceItem, *, max_spans: int = 12) -> list[str]:
    """Return compact source spans for claim grounding."""
    candidates = [
        evidence.fact or "",
        evidence.title,
        evidence.snippet,
        str(evidence.metadata.get("content") or ""),
    ]
    spans: list[str] = []
    for candidate in candidates:
        for span in _compact_text_spans(candidate):
            if span not in spans:
                spans.append(span)
            if len(spans) >= max_spans:
                return spans
    return spans


def _first_text_span(text: str, *, limit: int = 500) -> str:
    spans = _compact_text_spans(text, max_long_span_chars=limit)
    return spans[0] if spans else ""


def _compact_text_spans(
    text: str,
    *,
    max_short_chars: int = 220,
    max_long_span_chars: int = 320,
) -> list[str]:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    if len(cleaned) <= max_short_chars:
        return [cleaned]
    spans: list[str] = []
    for part in re.split(r"(?<=[。！？!?；;.\n])\s+", cleaned):
        span = part.strip()
        if len(span) < 8:
            continue
        spans.append(span[:max_long_span_chars])
        if len(spans) >= 12:
            break
    return spans


def notes_to_evidence(matches: list[KnowledgeNote | EvidenceSource]) -> list[EvidenceItem]:
    """Convert local note/chunk matches to ``EvidenceItem``."""
    items: list[EvidenceItem] = []
    for match in matches:
        source = (
            evidence_source_from_note(match)
            if isinstance(match, KnowledgeNote)
            else match
        )
        source_type = "chunk" if source.parent_note_id is not None else "note"
        snippet = source.content[:500] if source_type == "chunk" else source.summary
        items.append(EvidenceItem(
            source_type=source_type,
            source_id=source.id,
            parent_note_id=source.parent_note_id,
            title=source.title,
            snippet=snippet,
            source_span=source.source_span,
            source_ref=source.source_ref,
            source_fingerprint=source.source_fingerprint,
            page_number=match.chunk.page_number if isinstance(match, KnowledgeNote) else None,
            element_ids=list(match.chunk.element_ids) if isinstance(match, KnowledgeNote) else [],
            coordinates=match.chunk.coordinates if isinstance(match, KnowledgeNote) else None,
            metadata={
                "source_ref": source.source_ref,
                "source_fingerprint": source.source_fingerprint,
                "version_status": match.version.status if isinstance(match, KnowledgeNote) else "current",
                "version": match.version.version if isinstance(match, KnowledgeNote) else 1,
                "version_id": match.version.version_id if isinstance(match, KnowledgeNote) else "",
                "topic_key": match.version.topic_key if isinstance(match, KnowledgeNote) else None,
                "supersedes_note_ids": match.version.supersedes_note_ids if isinstance(match, KnowledgeNote) else [],
                "superseded_by_note_id": match.version.superseded_by_note_id if isinstance(match, KnowledgeNote) else None,
                "conflict_note_ids": match.version.conflict_note_ids if isinstance(match, KnowledgeNote) else [],
                "version_confidence": match.version.confidence if isinstance(match, KnowledgeNote) else 1.0,
                **source.metadata,
            },
        ))
    return items


def web_results_to_evidence(
    results: list[dict],
    *,
    sanitize: Callable[[str], str] | None = None,
) -> list[EvidenceItem]:
    """Convert raw web search result dicts to ``EvidenceItem``.

    Web text is untrusted: it can carry indirect prompt injection. Callers pass a
    ``sanitize`` function (backed by the content guard) to neutralize injection
    markers in ``title``/``snippet`` before they cross into the trusted
    evidence/context boundary. The guard lives in a higher layer, so it is
    injected here rather than imported — keeping the kernel free of an upward
    dependency. When omitted, text passes through unchanged.
    """
    clean = sanitize or (lambda text: text)
    items: list[EvidenceItem] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        url = str(r.get("url", ""))
        items.append(EvidenceItem(
            source_type="web",
            source_id=url,
            title=clean(str(r.get("title", ""))),
            snippet=clean(str(r.get("snippet", ""))),
            url=url,
            source_ref=url,
            metadata={
                "source": r.get("source", ""),
                "published_at": r.get("published_at"),
            },
        ))
    return items


def episodes_to_evidence(episodes: list[MemoryEpisode]) -> list[EvidenceItem]:
    """Convert workflow/run episodes to historical-intent evidence."""
    items: list[EvidenceItem] = []
    for episode in episodes:
        snippet_parts = [episode.summary]
        if episode.decisions:
            snippet_parts.append("决策: " + "；".join(episode.decisions[:3]))
        if episode.open_items:
            snippet_parts.append("未完成: " + "；".join(episode.open_items[:3]))
        items.append(EvidenceItem(
            source_type="episode",
            source_id=episode.id,
            title=episode.title,
            snippet="\n".join(part for part in snippet_parts if part),
            score=0.6,
            metadata={
                "run_id": episode.run_id,
                "thread_id": episode.thread_id,
                "session_id": episode.session_id,
                "workflow": episode.workflow,
                "outcome": episode.outcome,
                "entry_text": episode.entry_text,
                "event_refs": episode.event_refs,
                "tool_refs": episode.tool_refs,
                "note_refs": episode.note_refs,
                **episode.metadata,
            },
        ))
    return items


def memory_items_to_evidence(items: list[MemoryItem]) -> list[EvidenceItem]:
    """Convert procedural/reflection long-term memory to evidence."""
    evidence: list[EvidenceItem] = []
    for item in items:
        evidence.append(EvidenceItem(
            source_type=item.memory_type,
            source_id=item.id,
            title=item.title,
            snippet=item.content[:700],
            score=item.confidence,
            metadata={
                "memory_type": item.memory_type,
                "status": item.status,
                "session_id": item.session_id,
                "thread_id": item.thread_id,
                "source_episode_ids": item.source_episode_ids,
                "source_run_ids": item.source_run_ids,
                "evidence_refs": item.evidence_refs,
                "applies_to": item.applies_to,
                **item.metadata,
            },
        ))
    return evidence


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
                evidence_id=item.evidence_id,
                source_ref=item.source_ref,
            ))
        else:
            citations.append(Citation(
                note_id=item.source_id,
                title=item.title,
                snippet=item.snippet,
                relation_fact=item.fact,
                source_type="note",
                evidence_id=item.evidence_id,
                parent_note_id=item.parent_note_id,
                source_ref=item.source_ref,
                source_fingerprint=item.source_fingerprint,
                source_span=item.source_span,
                page_number=item.page_number,
                element_ids=list(item.element_ids),
                coordinates=item.coordinates,
            ))
    return citations
