from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field, model_validator

from personal_agent.kernel.config import Settings
from personal_agent.kernel.evidence import (
    ContextPack,
    EvidenceItem,
    RankedEvidence,
    rank_evidence_items,
    select_ranked_evidence,
)
from personal_agent.kernel.prompts import get_prompt, render_prompt

logger = logging.getLogger(__name__)

_QUESTION_STOPWORDS = {
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "when",
    "where",
    "why",
    "how",
    "does",
    "do",
    "did",
    "is",
    "are",
    "was",
    "were",
    "can",
    "could",
    "should",
    "would",
    "the",
    "a",
    "an",
    "of",
    "to",
    "for",
    "in",
    "on",
    "with",
    "about",
    "explain",
    "describe",
}

_CJK_QUESTION_STOPS = (
    "是什么",
    "什么是",
    "为什么",
    "怎么",
    "如何",
    "是否",
    "吗",
    "呢",
    "请问",
    "介绍",
    "说明",
    "解释",
)


class _RerankResult(BaseModel):
    """LLM rerank output: an ordered list of evidence ids.

    Accepts both ``{"ranked_ids": [...]}`` and a bare ``[...]`` top-level list.
    """

    ranked_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_list(cls, data: object) -> object:
        if isinstance(data, list):
            return {"ranked_ids": data}
        return data


class EvidenceReranker(Protocol):
    name: str

    def rerank(
        self,
        question: str,
        evidence: list[EvidenceItem],
        *,
        max_items: int,
        char_budget: int,
        mmr_lambda: float = 0.7,
    ) -> ContextPack:
        ...


class HeuristicEvidenceReranker:
    name = "heuristic"

    def rerank(
        self,
        question: str,
        evidence: list[EvidenceItem],
        *,
        max_items: int,
        char_budget: int,
        mmr_lambda: float = 0.7,
    ) -> ContextPack:
        return select_ranked_evidence(
            question,
            rank_evidence_items(question, evidence),
            max_items=max_items,
            char_budget=char_budget,
            mmr_lambda=mmr_lambda,
        )


@dataclass(frozen=True, slots=True)
class SupportSignal:
    status: str
    coverage: float
    overlap: int
    exact_query_match: bool
    consensus_count: int
    dense_sparse_agree: bool
    low_information: bool


class SupportEvidenceReranker:
    """Fast query-evidence relevance reranker.

    This is the productionized, dataset-agnostic version of the sparse/support
    idea: it uses only the question text, candidate text, and generic
    fusion/lineage metadata. It deliberately avoids Open/Galileo-specific
    document, paper, section, or yes/no priors.
    """

    name = "support"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.last_telemetry: dict[str, object] = {}

    def rerank(
        self,
        question: str,
        evidence: list[EvidenceItem],
        *,
        max_items: int,
        char_budget: int,
        mmr_lambda: float = 0.7,
    ) -> ContextPack:
        ranked = _support_rank_evidence(question, evidence, self.settings)
        self.last_telemetry = _support_telemetry(ranked)
        return select_ranked_evidence(
            question,
            ranked,
            max_items=max_items,
            char_budget=char_budget,
            mmr_lambda=mmr_lambda,
        )


class LlmEvidenceReranker:
    name = "llm"

    def __init__(self, settings: Settings, model_client: "object | None" = None) -> None:
        self.settings = settings
        self._model_client = model_client
        self.last_telemetry: dict[str, object] = {}

    def rerank(
        self,
        question: str,
        evidence: list[EvidenceItem],
        *,
        max_items: int,
        char_budget: int,
        mmr_lambda: float = 0.7,
    ) -> ContextPack:
        heuristic_ranked = rank_evidence_items(question, evidence)
        top_n = max(max_items, self.settings.ask.llm_rerank_top_n)
        candidates = heuristic_ranked[:top_n]
        if len(candidates) <= 1:
            return select_ranked_evidence(
                question,
                heuristic_ranked,
                max_items=max_items,
                char_budget=char_budget,
                mmr_lambda=mmr_lambda,
            )

        try:
            ranked_ids = self._rank_ids(question, candidates)
        except Exception as exc:  # pragma: no cover - defensive fallback path
            logger.warning("llm rerank failed; falling back to heuristic: %s", exc)
            return select_ranked_evidence(
                question,
                heuristic_ranked,
                max_items=max_items,
                char_budget=char_budget,
                mmr_lambda=mmr_lambda,
            )

        reordered = _apply_llm_order(heuristic_ranked, ranked_ids)
        return select_ranked_evidence(
            question,
            reordered,
            max_items=max_items,
            char_budget=char_budget,
            mmr_lambda=mmr_lambda,
        )

    def _rank_ids(self, question: str, candidates: list[RankedEvidence]) -> list[str]:
        if self._model_client is None:
            raise RuntimeError("LLM reranker requires a configured model client")

        from personal_agent.capabilities.contracts.model import (
            StructuredModelRequest,
            sealed_context_projection_ref,
        )

        system_prompt = get_prompt("evidence_rerank.system")
        messages = [
            {"role": "system", "content": system_prompt.template},
            {
                "role": "user",
                "content": render_prompt(
                    "evidence_rerank.user",
                    rerank_prompt=_rerank_prompt(question, candidates),
                ),
            },
        ]
        response = self._model_client.generate(StructuredModelRequest(
            operation="evidence_rerank",
            version=system_prompt.version,
            temperature=0,
            max_tokens=700,
            kind="structured",
            messages=messages,
            output_type=_RerankResult,
            context_projection_ref=sealed_context_projection_ref(
                purpose="evidence_rerank", messages=messages,
            ),
            metadata={"component": "evidence_reranker", "candidate_count": len(candidates)},
        ))
        valid_ids = {item.evidence.evidence_id for item in candidates}
        return [item_id for item_id in response.value.ranked_ids if item_id in valid_ids]


class GatedLlmEvidenceReranker(LlmEvidenceReranker):
    name = "llm_gated"

    def rerank(
        self,
        question: str,
        evidence: list[EvidenceItem],
        *,
        max_items: int,
        char_budget: int,
        mmr_lambda: float = 0.7,
    ) -> ContextPack:
        heuristic_ranked = _support_rank_evidence(question, evidence, self.settings)
        support_telemetry = _support_telemetry(heuristic_ranked)
        candidate_count = len(heuristic_ranked)
        trigger_reason = _gated_llm_trigger_reason(
            heuristic_ranked,
            min_candidates=max(2, self.settings.ask.llm_rerank_gated_min_candidates),
            score_margin=max(0.0, self.settings.ask.llm_rerank_gated_score_margin),
            low_score=max(0.0, self.settings.ask.llm_rerank_gated_low_score),
            dense_sparse_gap=max(1, self.settings.ask.llm_rerank_gated_dense_sparse_gap),
            min_support_coverage=max(
                0.0,
                self.settings.ask.llm_rerank_gated_min_support_coverage,
            ),
        )
        self.last_telemetry = {
            "reranker": self.name,
            "triggered": trigger_reason is not None,
            "trigger_reason": trigger_reason or "not_triggered",
            "llm_call_count": 0,
            "fallback_reason": "",
            "candidate_count": candidate_count,
            "model_configured": self._model_client is not None,
            **support_telemetry,
        }
        if trigger_reason is None or self._model_client is None:
            if trigger_reason is not None and self._model_client is None:
                self.last_telemetry["fallback_reason"] = "model_not_configured"
            return select_ranked_evidence(
                question,
                heuristic_ranked,
                max_items=max_items,
                char_budget=char_budget,
                mmr_lambda=mmr_lambda,
            )

        top_n = max(max_items, self.settings.ask.llm_rerank_top_n)
        candidates = heuristic_ranked[:top_n]
        try:
            self.last_telemetry["llm_call_count"] = 1
            self.last_telemetry["llm_candidate_count"] = len(candidates)
            ranked_ids = self._rank_ids(question, candidates)
        except Exception as exc:  # pragma: no cover - defensive fallback path
            logger.warning("gated llm rerank failed; falling back to heuristic: %s", exc)
            self.last_telemetry["fallback_reason"] = "llm_error"
            self.last_telemetry["error"] = str(exc)
            return select_ranked_evidence(
                question,
                heuristic_ranked,
                max_items=max_items,
                char_budget=char_budget,
                mmr_lambda=mmr_lambda,
            )

        preserve_top_k = max(0, self.settings.ask.llm_rerank_gated_preserve_top_k)
        reordered = _apply_llm_order(
            heuristic_ranked,
            ranked_ids,
            reason_prefix=f"llm_gated({trigger_reason})",
            preserve_top_k=preserve_top_k,
        )
        self.last_telemetry["ranked_id_count"] = len(ranked_ids)
        self.last_telemetry["preserve_top_k"] = preserve_top_k
        return select_ranked_evidence(
            question,
            reordered,
            max_items=max_items,
            char_budget=char_budget,
            mmr_lambda=mmr_lambda,
        )


def build_context_pack_with_settings(
    question: str,
    evidence: list[EvidenceItem],
    settings: Settings,
) -> ContextPack:
    reranker = create_evidence_reranker(settings)
    return reranker.rerank(
        question,
        evidence,
        max_items=settings.ask.context_max_items,
        char_budget=settings.ask.context_char_budget,
        mmr_lambda=settings.ask.context_mmr_lambda,
    )


def create_evidence_reranker(
    settings: Settings,
    model_client: "object | None" = None,
) -> EvidenceReranker:
    name = settings.ask.reranker.strip().lower()
    if name in {"heuristic", "default"}:
        return HeuristicEvidenceReranker()
    if name in {"support", "semantic", "semantic_support"}:
        return SupportEvidenceReranker(settings)
    if name == "llm":
        return LlmEvidenceReranker(settings, model_client=model_client)
    if name in {"llm_gated", "gated_llm"}:
        return GatedLlmEvidenceReranker(settings, model_client=model_client)
    raise ValueError(
        "Unknown ask reranker '%s'. Available: heuristic, support, llm, llm_gated"
        % settings.ask.reranker
    )


def _apply_llm_order(
    heuristic_ranked: list[RankedEvidence],
    ranked_ids: list[str],
    *,
    reason_prefix: str = "llm_rerank",
    preserve_top_k: int = 0,
) -> list[RankedEvidence]:
    by_id = {item.evidence.evidence_id: item for item in heuristic_ranked}
    preserved = heuristic_ranked[:preserve_top_k]
    ordered: list[RankedEvidence] = list(preserved)
    seen: set[str] = {item.evidence.evidence_id for item in preserved}
    max_score = max((item.score for item in heuristic_ranked), default=0.0)
    for index, evidence_id in enumerate(ranked_ids):
        item = by_id.get(evidence_id)
        if item is None or evidence_id in seen:
            continue
        seen.add(evidence_id)
        ordered.append(item.model_copy(update={
            "score": round(max_score + 1.0 - index * 0.01, 4),
            "reason": f"{reason_prefix} rank={index + 1}, {item.reason}",
        }))
    ordered.extend(item for item in heuristic_ranked if item.evidence.evidence_id not in seen)
    return ordered


def _gated_llm_trigger_reason(
    ranked: list[RankedEvidence],
    *,
    min_candidates: int,
    score_margin: float,
    low_score: float,
    dense_sparse_gap: int,
    min_support_coverage: float,
) -> str | None:
    if len(ranked) < min_candidates:
        return None
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    top_lacks_consensus = _top_candidate_lacks_consensus(top)
    support_status = str(top.evidence.metadata.get("support_status") or "")
    support_coverage = _metadata_float(top.evidence.metadata, "support_coverage") or 0.0
    if (
        support_status not in {"direct_support", "strong_support"}
        and support_coverage < min_support_coverage
        and _any_direct_support_candidate(ranked[1:min_candidates])
    ):
        return "weak_top_support"
    if (
        score_margin > 0
        and second is not None
        and top.score - second.score <= score_margin
        and top_lacks_consensus
    ):
        return "score_margin"
    if top.score <= low_score:
        return "low_top_score"
    if top_lacks_consensus and _top_window_has_mixed_sources(ranked[:min_candidates]):
        return "source_disagreement"
    if _dense_sparse_rank_gap(top) >= dense_sparse_gap:
        return "dense_sparse_rank_gap"
    return None


def _support_rank_evidence(
    question: str,
    evidence: list[EvidenceItem],
    settings: Settings,
) -> list[RankedEvidence]:
    ranked = rank_evidence_items(question, evidence)
    if not ranked:
        return ranked
    scored: list[RankedEvidence] = []
    for item in ranked:
        signal = _support_signal(question, item.evidence, settings)
        support_boost = signal.coverage * max(0.0, settings.ask.support_rerank_weight)
        if signal.exact_query_match:
            support_boost += 0.08
        if signal.status in {"direct_support", "strong_support"}:
            support_boost += 0.06
        elif signal.status == "background_only":
            support_boost -= 0.04
        if signal.low_information:
            support_boost -= 0.08
        if signal.dense_sparse_agree:
            support_boost += 0.03
        if signal.consensus_count > 1:
            support_boost += min(
                (signal.consensus_count - 1) * settings.ask.support_rerank_consensus_weight,
                0.08,
            )
        metadata = dict(item.evidence.metadata)
        metadata.update({
            "support_status": signal.status,
            "support_coverage": round(signal.coverage, 4),
            "support_overlap": signal.overlap,
            "support_exact_query_match": signal.exact_query_match,
            "support_low_information": signal.low_information,
            "support_dense_sparse_agree": signal.dense_sparse_agree,
        })
        reason = (
            f"support={signal.status} coverage={signal.coverage:.2f} "
            f"overlap={signal.overlap}, {item.reason}"
        )
        scored.append(item.model_copy(update={
            "evidence": item.evidence.model_copy(update={"metadata": metadata}),
            "score": round(max(item.score + support_boost, 0.0), 4),
            "reason": reason,
        }))
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def _support_signal(
    question: str,
    evidence: EvidenceItem,
    settings: Settings,
) -> SupportSignal:
    explicit_status = str(evidence.metadata.get("support_status") or "")
    explicit_coverage = _metadata_float(evidence.metadata, "support_coverage")
    explicit_overlap = evidence.metadata.get("support_overlap")
    if explicit_status in {
        "strong_support",
        "direct_support",
        "partial_support",
        "background_only",
        "insufficient_evidence",
    } and explicit_coverage is not None:
        consensus = evidence.metadata.get("consensus_count")
        consensus_count = int(consensus) if isinstance(consensus, int | float) else 1
        return SupportSignal(
            status=explicit_status,
            coverage=max(0.0, min(float(explicit_coverage), 1.0)),
            overlap=int(explicit_overlap) if isinstance(explicit_overlap, int | float) else 0,
            exact_query_match=bool(evidence.metadata.get("support_exact_query_match")),
            consensus_count=max(consensus_count, 1),
            dense_sparse_agree=_dense_sparse_agree(evidence),
            low_information=bool(evidence.metadata.get("support_low_information", False)),
        )
    q_terms = _support_terms(question, is_question=True)
    text = " ".join(part for part in [evidence.title, evidence.fact or "", evidence.snippet] if part)
    e_terms = _support_terms(text, is_question=False)
    overlap = len(q_terms & e_terms)
    coverage = overlap / max(len(q_terms), 1)
    normalized_query = _normalize_query_text(question)
    normalized_text = _normalize_query_text(text)
    exact = bool(normalized_query and normalized_query in normalized_text)
    direct_coverage = max(0.0, settings.ask.support_rerank_direct_coverage)
    min_overlap = max(1, settings.ask.support_rerank_min_overlap_terms)
    if exact or coverage >= max(direct_coverage, 0.8):
        status = "strong_support"
    elif coverage >= direct_coverage or (overlap >= min_overlap and coverage >= 0.3):
        status = "direct_support"
    elif overlap > 0:
        status = "partial_support"
    else:
        status = "background_only"
    consensus = evidence.metadata.get("consensus_count")
    consensus_count = int(consensus) if isinstance(consensus, int | float) else 1
    return SupportSignal(
        status=status,
        coverage=coverage,
        overlap=overlap,
        exact_query_match=exact,
        consensus_count=max(consensus_count, 1),
        dense_sparse_agree=_dense_sparse_agree(evidence),
        low_information=_low_information_text(text),
    )


def _support_telemetry(ranked: list[RankedEvidence]) -> dict[str, object]:
    if not ranked:
        return {
            "support_top_status": "none",
            "support_top_coverage": 0.0,
            "support_direct_candidate_count": 0,
        }
    top = ranked[0].evidence.metadata
    direct_count = sum(
        1
        for item in ranked
        if str(item.evidence.metadata.get("support_status") or "") in {
            "direct_support",
            "strong_support",
        }
    )
    return {
        "support_top_status": str(top.get("support_status") or ""),
        "support_top_coverage": float(top.get("support_coverage") or 0.0),
        "support_top_overlap": int(top.get("support_overlap") or 0),
        "support_direct_candidate_count": direct_count,
    }


def _any_direct_support_candidate(ranked: list[RankedEvidence]) -> bool:
    return any(
        str(item.evidence.metadata.get("support_status") or "") in {
            "direct_support",
            "strong_support",
        }
        for item in ranked
    )


def _dense_sparse_agree(evidence: EvidenceItem) -> bool:
    dense = evidence.metadata.get("dense_rank")
    sparse = evidence.metadata.get("sparse_rank")
    if isinstance(dense, int | float) and isinstance(sparse, int | float):
        return abs(int(dense) - int(sparse)) <= 3
    components = evidence.metadata.get("fusion_components") or []
    if isinstance(components, list):
        sources = {
            str(item.get("source", "")).lower()
            for item in components
            if isinstance(item, dict)
        }
        return bool(sources & {"dense", "vector", "embedding", "semantic"}) and bool(
            sources & {"sparse", "local", "lexical", "keyword", "bm25", "support"}
        )
    return False


def _low_information_text(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if len(normalized) < 16:
        return True
    if normalized.lower().startswith("title:"):
        return True
    tokens = _support_terms(normalized, is_question=False)
    return len(tokens) <= 3 and not re.search(r"[.;:?!。！？；]", normalized)


def _support_terms(text: str, *, is_question: bool) -> set[str]:
    normalized = _normalize_query_text(text) if is_question else str(text or "").lower()
    terms: set[str] = set()
    for token in re.findall(r"[a-z0-9_+-]{2,}", normalized):
        if token not in _QUESTION_STOPWORDS:
            terms.add(token)
    for run in re.findall(r"[\u3400-\u9fff]{2,}", normalized):
        for stop in _CJK_QUESTION_STOPS:
            run = run.replace(stop, "")
        if len(run) >= 2:
            terms.add(run)
        for size in (2, 3):
            for index in range(0, max(0, len(run) - size + 1)):
                terms.add(run[index:index + size])
    return terms


def _normalize_query_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    for token in _CJK_QUESTION_STOPS:
        normalized = normalized.replace(token, "")
    for token in _QUESTION_STOPWORDS:
        normalized = re.sub(rf"\b{re.escape(token)}\b", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _metadata_float(metadata: dict[str, object], key: str) -> float | None:
    value = metadata.get(key)
    if isinstance(value, int | float):
        return float(value)
    return None


def _top_candidate_lacks_consensus(item: RankedEvidence) -> bool:
    consensus = item.evidence.metadata.get("consensus_count")
    if isinstance(consensus, int | float) and consensus >= 2:
        return False
    components = item.evidence.metadata.get("fusion_components") or []
    return not (isinstance(components, list) and len(components) >= 2)


def _top_window_has_mixed_sources(ranked: list[RankedEvidence]) -> bool:
    families: set[str] = set()
    for item in ranked:
        candidate = item.evidence.metadata.get("candidate") or {}
        if isinstance(candidate, dict):
            source_type = candidate.get("source_type")
            if source_type:
                families.add(str(source_type))
        source_ranks = item.evidence.metadata.get("source_ranks") or {}
        if isinstance(source_ranks, dict):
            for source in source_ranks:
                normalized = str(source).lower()
                if normalized in {"dense", "vector", "embedding", "semantic"}:
                    families.add("dense")
                elif normalized in {"sparse", "local", "lexical", "keyword", "bm25"}:
                    families.add("sparse")
                elif normalized:
                    families.add(normalized)
    return len(families) >= 2


def _dense_sparse_rank_gap(item: RankedEvidence) -> int:
    metadata = item.evidence.metadata
    dense = metadata.get("dense_rank")
    sparse = metadata.get("sparse_rank")
    if not isinstance(dense, int | float) or not isinstance(sparse, int | float):
        return 0
    return abs(int(dense) - int(sparse))


def _rerank_prompt(question: str, candidates: list[RankedEvidence]) -> str:
    lines = [f"Question: {question}", "", "Candidates:"]
    for item in candidates:
        evidence = item.evidence
        text = " ".join(part for part in [evidence.fact, evidence.snippet] if part)
        retrieved_by = evidence.metadata.get("retrieved_by") or evidence.metadata.get("source") or ""
        lines.append(
            "\n".join([
                f"- id: {evidence.evidence_id}",
                f"  source_type: {evidence.source_type}",
                f"  retrieved_by: {retrieved_by}",
                f"  source_id: {evidence.source_id}",
                f"  title: {evidence.title[:160]}",
                f"  text: {text[:700]}",
                f"  heuristic_reason: {item.reason}",
            ])
        )
    lines.append("")
    lines.append(
        "Return ranked_ids in best-to-worst order. Put candidates that can directly answer "
        "the question before candidates that only share topic words or provide background."
    )
    return "\n".join(lines)
