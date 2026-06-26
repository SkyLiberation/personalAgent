from __future__ import annotations

import logging
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
from personal_agent.infra.structured_parse import parse_structured

logger = logging.getLogger(__name__)


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


class LlmEvidenceReranker:
    name = "llm"

    def __init__(self, settings: Settings, model_client: "object | None" = None) -> None:
        self.settings = settings
        self._model_client = model_client

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

        from personal_agent.infra.structured_model import StructuredModelRequest
        from pydantic import BaseModel

        system_prompt = get_prompt("evidence_rerank.system")
        response = self._model_client.generate(StructuredModelRequest(
            operation="evidence_rerank",
            version=system_prompt.version,
            temperature=0,
            max_tokens=700,
            kind="text",
            response_format=_rerank_response_format(),
            messages=[
                {"role": "system", "content": system_prompt.template},
                {
                    "role": "user",
                    "content": render_prompt(
                        "evidence_rerank.user",
                        rerank_prompt=_rerank_prompt(question, candidates),
                    ),
                },
            ],
            output_type=BaseModel,
            metadata={"component": "evidence_reranker", "candidate_count": len(candidates)},
        ))
        parsed = parse_structured(
            response.content or "{}",
            _RerankResult,
            operation="evidence_rerank",
            version=system_prompt.version,
            model_name=response.model,
            latency_ms=response.latency_ms,
        )
        if not parsed.ok:
            raise ValueError(f"evidence_rerank structured parse failed: {parsed.error}")
        valid_ids = {item.evidence.evidence_id for item in candidates}
        return [item_id for item_id in parsed.value.ranked_ids if item_id in valid_ids]


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
    if name == "llm":
        return LlmEvidenceReranker(settings, model_client=model_client)
    raise ValueError("Unknown ask reranker '%s'. Available: heuristic, llm" % settings.ask.reranker)


def _apply_llm_order(
    heuristic_ranked: list[RankedEvidence],
    ranked_ids: list[str],
) -> list[RankedEvidence]:
    by_id = {item.evidence.evidence_id: item for item in heuristic_ranked}
    ordered: list[RankedEvidence] = []
    seen: set[str] = set()
    boost = len(ranked_ids)
    for index, evidence_id in enumerate(ranked_ids):
        item = by_id.get(evidence_id)
        if item is None or evidence_id in seen:
            continue
        seen.add(evidence_id)
        ordered.append(item.model_copy(update={
            "score": round(item.score + (boost - index) * 0.001, 4),
            "reason": f"llm_rerank, {item.reason}",
        }))
    ordered.extend(item for item in heuristic_ranked if item.evidence.evidence_id not in seen)
    return ordered


def _rerank_response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "evidence_rerank",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "ranked_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["ranked_ids"],
                "additionalProperties": False,
            },
        },
    }


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
    lines.append("Return ranked_ids containing the candidate ids in best-to-worst order.")
    return "\n".join(lines)
