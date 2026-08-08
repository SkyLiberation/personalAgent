from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from personal_agent.kernel.evidence import (
    Candidate,
    EvidenceItem,
    _dedupe_evidence_items,
    candidate_from_evidence,
)


@dataclass(slots=True)
class CandidateFusionTrace:
    input_candidate_count: int = 0
    deduped_candidate_count: int = 0
    fused_candidate_count: int = 0
    multi_source_candidate_count: int = 0
    events: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CandidateFusionResult:
    candidates: list[Candidate]
    evidence: list[EvidenceItem]
    trace: CandidateFusionTrace = field(default_factory=CandidateFusionTrace)


class CandidateFusion:
    """Fuse retriever-neutral candidates before evidence reranking.

    RRF is intentionally rank-based: dense cosine, BM25, graph scores and
    knowledge confidence have different scales, while ranks are comparable
    enough to reward candidates reached by multiple independent paths.
    """

    name = "rrf"

    def __init__(self, *, k: int = 60) -> None:
        self.k = k

    def fuse_evidence(self, evidence: list[EvidenceItem]) -> CandidateFusionResult:
        trace = CandidateFusionTrace(input_candidate_count=len(evidence))
        deduped = _dedupe_evidence_items(evidence)
        trace.deduped_candidate_count = len(deduped)
        candidates = [candidate_from_evidence(item) for item in deduped]
        fused_candidates = self.fuse_candidates(candidates, trace=trace)
        by_id = {item.evidence_id: item for item in deduped}
        fused_evidence: list[EvidenceItem] = []
        for candidate in fused_candidates:
            item = by_id.get(candidate.candidate_id)
            if item is None:
                continue
            metadata = dict(item.metadata)
            metadata.update({
                "candidate": candidate.model_dump(mode="json"),
                "candidate_source_type": candidate.source_type,
                "fusion_rank": candidate.fusion_rank,
                "fusion_score": candidate.metadata.get("fusion_score", 0.0),
                "fusion_components": candidate.metadata.get("fusion_components", []),
                "consensus_count": candidate.support_features.get("consensus_count", 1),
            })
            if candidate.dense_rank is not None:
                metadata["dense_rank"] = candidate.dense_rank
            if candidate.sparse_rank is not None:
                metadata["sparse_rank"] = candidate.sparse_rank
            fused_evidence.append(item.model_copy(update={"metadata": metadata}))

        trace.fused_candidate_count = len(fused_candidates)
        if trace.multi_source_candidate_count:
            trace.events.append(
                f"CandidateFusion(rrf): multi_source={trace.multi_source_candidate_count} "
                f"candidates={len(fused_candidates)}"
            )
        return CandidateFusionResult(
            candidates=fused_candidates,
            evidence=fused_evidence,
            trace=trace,
        )

    def fuse_candidates(
        self,
        candidates: list[Candidate],
        *,
        trace: CandidateFusionTrace | None = None,
    ) -> list[Candidate]:
        local_trace = trace or CandidateFusionTrace(input_candidate_count=len(candidates))
        groups: dict[tuple[str, str, str], list[Candidate]] = {}
        order: list[tuple[str, str, str]] = []
        for candidate in candidates:
            key = _candidate_key(candidate)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(candidate)

        merged = [self._merge_group(groups[key]) for key in order]
        local_trace.deduped_candidate_count = len(merged)
        scored: list[tuple[float, int, Candidate]] = []
        for index, candidate in enumerate(merged):
            components = _fusion_components(candidate, self.k)
            fusion_score = round(sum(float(item["rrf"]) for item in components), 6)
            metadata = dict(candidate.metadata)
            metadata["fusion_score"] = fusion_score
            metadata["fusion_components"] = components
            support_features = dict(candidate.support_features)
            support_features["consensus_count"] = len(components) if components else 1
            if len(components) > 1:
                local_trace.multi_source_candidate_count += 1
            scored.append((
                fusion_score,
                index,
                candidate.model_copy(update={
                    "metadata": metadata,
                    "support_features": support_features,
                }),
            ))

        scored.sort(key=lambda item: (-item[0], item[1]))
        fused: list[Candidate] = []
        for rank, (_, _, candidate) in enumerate(scored, 1):
            fused.append(candidate.model_copy(update={"fusion_rank": rank}))
        local_trace.fused_candidate_count = len(fused)
        return fused

    def _merge_group(self, candidates: list[Candidate]) -> Candidate:
        if len(candidates) == 1:
            return candidates[0]
        best = max(candidates, key=lambda item: item.raw_score)
        source_ranks: dict[str, int] = {}
        for candidate in candidates:
            for source, rank in _source_ranks(candidate).items():
                if source not in source_ranks or rank < source_ranks[source]:
                    source_ranks[source] = rank
        metadata = dict(best.metadata)
        metadata["source_ranks"] = source_ranks
        support_features = dict(best.support_features)
        support_features["source_ranks"] = source_ranks
        support_features["consensus_count"] = len(source_ranks) if source_ranks else len(candidates)
        return best.model_copy(update={
            "dense_score": _max_optional(c.dense_score for c in candidates),
            "sparse_score": _max_optional(c.sparse_score for c in candidates),
            "dense_rank": _min_optional(c.dense_rank for c in candidates),
            "sparse_rank": _min_optional(c.sparse_rank for c in candidates),
            "source_rank": _min_optional(c.source_rank for c in candidates),
            "metadata": metadata,
            "support_features": support_features,
        })


def _candidate_key(candidate: Candidate) -> tuple[str, str, str]:
    return (
        candidate.document_id or candidate.metadata.get("evidence_source_ref") or "",
        candidate.chunk_id or candidate.metadata.get("evidence_source_id") or "",
        candidate.passage_id or candidate.locator or candidate.text[:180],
    )


def _source_ranks(candidate: Candidate) -> dict[str, int]:
    raw = (
        candidate.support_features.get("source_ranks")
        or candidate.metadata.get("source_ranks")
        or {}
    )
    ranks: dict[str, int] = {}
    if isinstance(raw, dict):
        for source, rank in raw.items():
            try:
                ranks[str(source)] = int(rank)
            except (TypeError, ValueError):
                continue
    if not ranks and candidate.source_rank is not None:
        ranks[candidate.source_type] = int(candidate.source_rank)
    return ranks


def _fusion_components(candidate: Candidate, k: int) -> list[dict[str, Any]]:
    ranks = _source_ranks(candidate)
    if not ranks:
        return []
    components: list[dict[str, Any]] = []
    for source, rank in sorted(ranks.items(), key=lambda item: (item[1], item[0])):
        components.append({
            "source": source,
            "rank": rank,
            "rrf": round(1.0 / (k + rank), 6),
        })
    return components


def _min_optional(values: Any) -> int | None:
    usable = [int(value) for value in values if value is not None]
    return min(usable) if usable else None


def _max_optional(values: Any) -> float | None:
    usable = [float(value) for value in values if value is not None]
    return max(usable) if usable else None
