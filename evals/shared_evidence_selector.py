"""Dataset-agnostic evidence selection utilities for retrieval evals.

The selector operates on evidence units instead of benchmark-specific objects:
Open RAGBench sections, Galileo sentences, or future passages can all be
ranked through the same path. Dataset-specific priors such as doc-first ranking
should remain outside this module as explicit ablations.
"""
from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Iterable, Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class EvidenceUnit:
    id: str
    text: str
    parent_id: str | None = None
    kind: str = "evidence"
    title: str = ""


@dataclass(frozen=True)
class SharedEvidenceSelectorConfig:
    embedding_weight: float = 1.0
    lexical_rrf_weight: float = 0.5
    lexical_weight: float = 0.30
    support_weight: float = 0.08
    rrf_k: int = 60
    min_lexical_score: float = 0.0
    include_parent_companions: bool = True
    exclude_low_information_units: bool = True


@dataclass(frozen=True)
class SharedEvidenceSelection:
    ranked_ids: list[str]
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedEvidenceCorpus:
    units: list[EvidenceUnit]
    tokenized_units: list[tuple[EvidenceUnit, list[str]]]
    unit_by_id: dict[str, EvidenceUnit]
    avg_len: float
    original_count: int


class SharedEvidencePolicy(BaseModel):
    should_intervene: bool = False
    action: Literal[
        "no_op",
        "promote_primary_evidence",
        "reorder_within_top5",
        "request_more_retrieval",
    ] = "no_op"
    primary_candidate_id: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_status: Literal[
        "direct_support",
        "partial_support",
        "background_only",
        "insufficient_evidence",
        "no_ambiguity",
    ] = "no_ambiguity"
    rationale: str = ""


@dataclass(frozen=True)
class SharedEvidencePolicyDecision:
    policy: SharedEvidencePolicy = field(default_factory=SharedEvidencePolicy)
    retry_attempts: int = 0
    retry_errors: list[str] = field(default_factory=list)
    response_model: str | None = None
    error: str | None = None


def select_shared_evidence(
    question: str,
    units: Iterable[EvidenceUnit] | PreparedEvidenceCorpus,
    *,
    limit: int,
    embedding_ranked_ids: list[str] | None = None,
    config: SharedEvidenceSelectorConfig | None = None,
) -> SharedEvidenceSelection:
    """Rank evidence units with a benchmark-agnostic scoring recipe.

    The method intentionally uses only evidence-unit text and optional external
    retrieval order. It does not know about papers, sections, or Galileo
    documents, so both benchmarks can call it without inheriting each other's
    structural assumptions.
    """
    config = config or SharedEvidenceSelectorConfig()
    corpus = (
        units if isinstance(units, PreparedEvidenceCorpus)
        else prepare_shared_evidence_corpus(units, config=config)
    )
    unit_by_id = corpus.unit_by_id
    question_tokens = _tokens(question)
    if not unit_by_id:
        return SharedEvidenceSelection(ranked_ids=[], diagnostics={"candidate_count": 0})

    first_seen: dict[str, int] = {}
    scores: dict[str, float] = {}
    components: dict[str, dict[str, float]] = {}

    lexical_ranked = _rank_by_text_support(question_tokens, corpus)
    for rank, (unit_id, lexical_score, support_score) in enumerate(lexical_ranked, 1):
        if lexical_score < config.min_lexical_score and not embedding_ranked_ids:
            continue
        first_seen.setdefault(unit_id, len(first_seen))
        lexical_rrf_component = config.lexical_rrf_weight / (config.rrf_k + rank)
        lexical_component = config.lexical_weight * lexical_score
        support_component = config.support_weight * support_score
        scores[unit_id] = (
            scores.get(unit_id, 0.0)
            + lexical_rrf_component
            + lexical_component
            + support_component
        )
        components.setdefault(unit_id, {})["lexical_rrf"] = lexical_rrf_component
        components.setdefault(unit_id, {})["lexical"] = lexical_component
        components.setdefault(unit_id, {})["support"] = support_component

    if embedding_ranked_ids:
        for rank, unit_id in enumerate(embedding_ranked_ids, 1):
            if unit_id not in unit_by_id:
                continue
            first_seen.setdefault(unit_id, len(first_seen))
            component = config.embedding_weight / (config.rrf_k + rank)
            scores[unit_id] = scores.get(unit_id, 0.0) + component
            components.setdefault(unit_id, {})["embedding_rrf"] = component

    if not scores:
        for rank, (unit_id, lexical_score, support_score) in enumerate(lexical_ranked, 1):
            first_seen.setdefault(unit_id, len(first_seen))
            scores[unit_id] = lexical_score + support_score
            components[unit_id] = {"lexical": lexical_score, "support": support_score}

    ranked_before_companions = sorted(
        scores,
        key=lambda unit_id: (-scores[unit_id], first_seen.get(unit_id, math.inf), unit_id),
    )
    ranked = (
        _add_parent_companions(ranked_before_companions, unit_by_id, limit=limit)
        if config.include_parent_companions else ranked_before_companions[:limit]
    )
    return SharedEvidenceSelection(
        ranked_ids=ranked,
        diagnostics={
            "candidate_count": len(unit_by_id),
            "embedding_candidate_count": len(embedding_ranked_ids or []),
            "lexical_candidate_count": len(lexical_ranked),
            "shared_selector_config": {
                "embedding_weight": config.embedding_weight,
                "lexical_rrf_weight": config.lexical_rrf_weight,
                "lexical_weight": config.lexical_weight,
                "support_weight": config.support_weight,
                "rrf_k": config.rrf_k,
                "min_lexical_score": config.min_lexical_score,
                "include_parent_companions": config.include_parent_companions,
                "exclude_low_information_units": config.exclude_low_information_units,
            },
            "low_information_unit_count": corpus.original_count - len(corpus.units),
            "shared_selector_before_parent_companions_top20": ranked_before_companions[:20],
            "shared_selector_scores_top20": [
                {
                    "id": unit_id,
                    "score": round(scores[unit_id], 6),
                    "components": {
                        name: round(value, 6)
                        for name, value in components.get(unit_id, {}).items()
                    },
                }
                for unit_id in ranked[:20]
            ],
        },
    )


def prepare_shared_evidence_corpus(
    units: Iterable[EvidenceUnit],
    *,
    config: SharedEvidenceSelectorConfig | None = None,
) -> PreparedEvidenceCorpus:
    config = config or SharedEvidenceSelectorConfig()
    original_units = list(units)
    unit_list = _filter_low_information_units(original_units) if config.exclude_low_information_units else original_units
    if not unit_list:
        unit_list = original_units
    tokenized_units = [
        (unit, _tokens(f"{unit.title} {unit.text}"))
        for unit in unit_list
    ]
    avg_len = (
        sum(len(tokens) for _, tokens in tokenized_units) / len(tokenized_units)
        if tokenized_units else 0.0
    )
    return PreparedEvidenceCorpus(
        units=unit_list,
        tokenized_units=tokenized_units,
        unit_by_id={unit.id: unit for unit in unit_list},
        avg_len=avg_len,
        original_count=len(original_units),
    )


def _filter_low_information_units(units: list[EvidenceUnit]) -> list[EvidenceUnit]:
    return [unit for unit in units if not _is_low_information_unit(unit)]


def _is_low_information_unit(unit: EvidenceUnit) -> bool:
    raw_text = re.sub(r"\s+", " ", unit.text).strip()
    if raw_text.lower().startswith("title:"):
        return True
    text = re.sub(r"\s+", " ", f"{unit.title} {unit.text}").strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered.startswith("title:"):
        return True
    tokens = _tokens(text)
    if len(tokens) <= 4 and not re.search(r"[.;:?!]", text):
        return True
    return False


def _add_parent_companions(
    ranked_ids: list[str],
    unit_by_id: dict[str, EvidenceUnit],
    *,
    limit: int,
) -> list[str]:
    expanded: list[str] = []
    for unit_id in ranked_ids:
        if unit_id not in expanded:
            expanded.append(unit_id)
        unit = unit_by_id.get(unit_id)
        parent_id = unit.parent_id if unit is not None else None
        if parent_id and parent_id in unit_by_id and parent_id not in expanded:
            expanded.append(parent_id)
        if len(expanded) >= limit:
            break
    return expanded[:limit]


def apply_shared_evidence_policy(
    ranked_ids: list[str],
    policy: SharedEvidencePolicy,
    *,
    limit: int,
    confidence_threshold: float = 0.7,
    preserve_top_k: int = 5,
) -> tuple[list[str], str]:
    if not ranked_ids:
        return [], "empty_ranking"
    if not policy.should_intervene or policy.action == "no_op":
        return ranked_ids[:limit], "no_op"
    if policy.action == "request_more_retrieval":
        return ranked_ids[:limit], "request_more_retrieval_recorded"
    if policy.confidence < confidence_threshold:
        return ranked_ids[:limit], "low_confidence_ignored"
    primary = policy.primary_candidate_id
    if not primary or primary not in ranked_ids:
        return ranked_ids[:limit], "invalid_primary_candidate"
    if policy.action == "reorder_within_top5":
        top_k = ranked_ids[:preserve_top_k]
        if primary not in top_k:
            return ranked_ids[:limit], "primary_outside_preserve_top_k"
        reranked = [primary, *[note_id for note_id in top_k if note_id != primary], *ranked_ids[preserve_top_k:]]
        return _dedupe(reranked)[:limit], "reordered_within_top5"
    if policy.action == "promote_primary_evidence":
        reranked = [primary, *[note_id for note_id in ranked_ids if note_id != primary]]
        return reranked[:limit], "promoted_primary_evidence"
    return ranked_ids[:limit], "unsupported_action"


def shared_policy_prompt(question: str, candidate_ids: list[str], unit_by_id: dict[str, EvidenceUnit]) -> str:
    lines = [
        "Question:",
        question,
        "",
        "Candidate evidence units:",
    ]
    for index, candidate_id in enumerate(candidate_ids, 1):
        unit = unit_by_id[candidate_id]
        text = re.sub(r"\s+", " ", unit.text).strip()[:900]
        lines.append(f"{index}. id={candidate_id} kind={unit.kind} parent={unit.parent_id or ''}")
        lines.append(f"   title={unit.title[:160]}")
        lines.append(f"   text={text}")
    lines.extend([
        "",
        "Decide whether the current ranking needs a small bounded intervention.",
        "Prefer direct supporting evidence over background-only or merely topical matches.",
        "For Galileo-style data, direct_support means the sentence supports or is usable in the answer.",
        "For Open-style data, direct_support means the section or document directly answers the question.",
        "Return one JSON object matching the schema.",
    ])
    return "\n".join(lines)


def select_shared_evidence_policy(
    question: str,
    candidate_ids: list[str],
    unit_by_id: dict[str, EvidenceUnit],
    model_client: object,
) -> tuple[SharedEvidencePolicy, int, list[str], str | None]:
    from personal_agent.infra.structured_model import StructuredModelRequest

    valid_ids = [candidate_id for candidate_id in candidate_ids if candidate_id in unit_by_id]
    if len(valid_ids) <= 1:
        return SharedEvidencePolicy(), 0, [], None
    response = model_client.generate(StructuredModelRequest(
        operation="shared_evidence_policy_selector",
        version="v1",
        temperature=0,
        max_tokens=1000,
        kind="structured",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a dataset-agnostic evidence selection policy. "
                    "Judge whether candidate evidence directly supports answering "
                    "the question. Prefer no_op when the current ranking is already "
                    "reasonable. Return JSON only."
                ),
            },
            {
                "role": "user",
                "content": shared_policy_prompt(question, valid_ids, unit_by_id),
            },
        ],
        output_type=SharedEvidencePolicy,
        metadata={"component": "shared_evidence_policy_selector", "candidate_count": len(valid_ids)},
    ))
    policy = response.value
    if policy.primary_candidate_id not in set(valid_ids):
        policy = policy.model_copy(update={"primary_candidate_id": None})
    return (
        policy,
        int(getattr(response, "retry_attempts", 0) or 0),
        list(getattr(response, "retry_errors", []) or []),
        getattr(response, "model", None),
    )


def select_shared_evidence_policies(
    policy_inputs: Iterable[tuple[str, str, list[str]]],
    unit_by_id: dict[str, EvidenceUnit],
    model_client: object,
    *,
    max_workers: int = 3,
) -> dict[str, SharedEvidencePolicyDecision]:
    """Run shared policy selection with bounded concurrency.

    Each input tuple is ``(request_id, question, candidate_ids)``. Failures are
    captured per request so callers can fall back to the pre-policy ranking
    without aborting the whole eval run.
    """
    inputs = list(policy_inputs)
    if not inputs:
        return {}
    worker_count = max(1, int(max_workers))

    def _run(item: tuple[str, str, list[str]]) -> tuple[str, SharedEvidencePolicyDecision]:
        request_id, question, candidate_ids = item
        try:
            policy, retry_attempts, retry_errors, response_model = select_shared_evidence_policy(
                question,
                candidate_ids,
                unit_by_id,
                model_client,
            )
            return request_id, SharedEvidencePolicyDecision(
                policy=policy,
                retry_attempts=retry_attempts,
                retry_errors=retry_errors,
                response_model=response_model,
            )
        except Exception as exc:  # pragma: no cover - live defensive path
            return request_id, SharedEvidencePolicyDecision(error=str(exc))

    if worker_count == 1 or len(inputs) == 1:
        return dict(_run(item) for item in inputs)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        return dict(executor.map(_run, inputs))


def _dedupe(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in ids:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _rank_by_text_support(
    question_tokens: list[str],
    corpus: PreparedEvidenceCorpus,
) -> list[tuple[str, float, float]]:
    idf = _idf(question_tokens, [tokens for _, tokens in corpus.tokenized_units])
    scored: list[tuple[str, float, float]] = []
    for unit, unit_tokens in corpus.tokenized_units:
        text = f"{unit.title} {unit.text}"
        lexical_score = _lexical_score(question_tokens, unit_tokens, idf=idf, avg_len=corpus.avg_len)
        support_score = _support_score(question_tokens, text, unit_tokens)
        scored.append((unit.id, lexical_score, support_score))
    scored.sort(key=lambda item: (-(item[1] + item[2]), item[0]))
    return scored


def _lexical_score(
    question_tokens: list[str],
    unit_tokens: list[str],
    *,
    idf: dict[str, float],
    avg_len: float,
) -> float:
    if not question_tokens or not unit_tokens:
        return 0.0
    question_unique = list(dict.fromkeys(question_tokens))
    unit_set = set(unit_tokens)
    overlap = sum(1 for token in question_unique if token in unit_set)
    coverage = overlap / max(len(question_unique), 1)
    weighted_overlap = sum(idf.get(token, 0.0) for token in question_unique if token in unit_set)
    weighted_total = sum(idf.get(token, 0.0) for token in question_unique)
    weighted_coverage = weighted_overlap / max(weighted_total, 1e-9)
    bm25 = _bm25_score(question_unique, unit_tokens, idf=idf, avg_len=avg_len)
    bm25_norm = bm25 / (bm25 + 3.0) if bm25 > 0 else 0.0
    rareish_overlap = sum(
        1 for token in question_unique
        if len(token) >= 6 and token in unit_set
    )
    rareish_coverage = rareish_overlap / max(sum(1 for token in question_unique if len(token) >= 6), 1)
    return min(1.0, coverage * 0.35 + weighted_coverage * 0.30 + bm25_norm * 0.25 + rareish_coverage * 0.10)


def _idf(question_tokens: list[str], tokenized_units: list[list[str]]) -> dict[str, float]:
    query_unique = set(question_tokens)
    if not query_unique or not tokenized_units:
        return {}
    doc_count = len(tokenized_units)
    dfs = {token: 0 for token in query_unique}
    for tokens in tokenized_units:
        token_set = set(tokens)
        for token in query_unique:
            if token in token_set:
                dfs[token] += 1
    return {
        token: math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))
        for token, df in dfs.items()
    }


def _bm25_score(
    question_tokens: list[str],
    unit_tokens: list[str],
    *,
    idf: dict[str, float],
    avg_len: float,
) -> float:
    if not unit_tokens:
        return 0.0
    k1 = 1.2
    b = 0.75
    length = len(unit_tokens)
    avg = avg_len if avg_len > 0 else length
    freqs: dict[str, int] = {}
    for token in unit_tokens:
        freqs[token] = freqs.get(token, 0) + 1
    score = 0.0
    for token in question_tokens:
        tf = freqs.get(token, 0)
        if tf <= 0:
            continue
        denom = tf + k1 * (1.0 - b + b * length / max(avg, 1e-9))
        score += idf.get(token, 0.0) * (tf * (k1 + 1.0)) / denom
    return score


def _support_score(question_tokens: list[str], text: str, unit_tokens: list[str]) -> float:
    if not question_tokens or not unit_tokens:
        return 0.0
    unit_bigrams = set(zip(unit_tokens, unit_tokens[1:]))
    question_bigrams = list(zip(question_tokens, question_tokens[1:]))
    phrase_coverage = (
        sum(1 for bigram in question_bigrams if bigram in unit_bigrams) / len(question_bigrams)
        if question_bigrams else 0.0
    )
    lower = text.lower()
    answer_cue_score = min(1.0, sum(1 for cue in _ANSWER_CUES if cue in lower) / 3.0)
    background_penalty = 0.08 if any(cue in lower[:180] for cue in _BACKGROUND_CUES) else 0.0
    return max(0.0, min(1.0, phrase_coverage * 0.7 + answer_cue_score * 0.3 - background_penalty))


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-z0-9_+-]+", text.lower())
        if len(token) >= 3 and token not in _STOPWORDS
    ]


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was",
    "were", "which", "what", "how", "why", "when", "where", "who", "may",
    "can", "could", "should", "would", "does", "did", "has", "have", "had",
    "into", "than", "then", "such", "also", "their", "there", "these", "those",
}

_ANSWER_CUES = (
    "is defined",
    "defined as",
    "we define",
    "we show",
    "we prove",
    "we find",
    "we conclude",
    "because",
    "therefore",
    "the result",
    "our results",
    "is caused by",
    "is associated with",
)

_BACKGROUND_CUES = (
    "abstract",
    "introduction",
    "background",
    "related work",
    "overview",
)
