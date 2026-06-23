"""Metric primitives for the RAG-quality harness.

Three families:
  - retrieval:  recall@k / nDCG@k (reused from open_ragbench) + precision@k
  - generation: answer_relevance / faithfulness (lexical, deterministic)
  - grounding:  claim-level entailment accuracy + contrastive coverage

All functions are pure and LLM-free. The lexical helpers reuse the project's
canonical tokenizer (``core.evidence._terms``) so scoring matches the same
term space the retriever/verifier use.
"""

from __future__ import annotations

from personal_agent.core.evidence import _jaccard, _terms

# Re-export the IR primitives so callers import everything from one place.
from ..open_ragbench.metrics import (  # noqa: F401
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)


def precision_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Fraction of the top-K that is relevant. Returns 0.0 for empty top-K.

    Complements ``recall_at_k``: recall asks "did we find the gold set", this
    asks "is what we surfaced mostly gold" — the context-precision signal for
    the *selected* evidence pack.
    """
    if k <= 0:
        return 0.0
    top_k = ranked_ids[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for rid in top_k if rid in relevant_ids)
    return hits / len(top_k)


def context_precision(selected_ids: list[str], relevant_ids: set[str]) -> float:
    """Precision over the *whole* selected context pack (k = pack size)."""
    return precision_at_k(selected_ids, relevant_ids, len(selected_ids))


def answer_relevance(answer: str, question: str, reference: str = "") -> float:
    """Lexical relevance of the answer to the question (+ optional reference).

    Jaccard term overlap; when a reference answer is annotated, the score is the
    max of (answer↔question, answer↔reference) so a well-phrased answer that
    matches the gold wording is not penalized for using few question terms.
    Deterministic stand-in for an LLM relevance judge (the Protocol seam is the
    function boundary — swap this for a model scorer later).
    """
    if not answer.strip():
        return 0.0
    a_terms = _terms(answer)
    score = _jaccard(a_terms, _terms(question))
    if reference.strip():
        score = max(score, _jaccard(a_terms, _terms(reference)))
    return round(score, 4)


def faithfulness(answer: str, evidence_texts: list[str]) -> float:
    """Fraction of answer terms grounded in the supplied evidence.

    Measures how much of what the answer *says* is traceable to the evidence
    pack — the lexical floor under "faithfulness". Low score = the answer
    asserts terms absent from any evidence (possible hallucination). Returns
    1.0 for an empty answer (nothing unfaithful asserted) and 0.0 when there is
    no evidence but the answer makes claims.
    """
    a_terms = _terms(answer)
    if not a_terms:
        return 1.0
    evidence_terms: set[str] = set()
    for text in evidence_texts:
        evidence_terms |= _terms(text)
    if not evidence_terms:
        return 0.0
    grounded = len(a_terms & evidence_terms)
    return round(grounded / len(a_terms), 4)


def claim_entailment_accuracy(
    predicted: list[str],
    gold: list[str],
) -> float:
    """Agreement between the verifier's per-claim verdicts and gold labels.

    ``predicted`` / ``gold`` are aligned lists of status strings
    (``supported`` / ``contradicted`` / ``not_found``). Returns the fraction
    that match. Returns 1.0 when there are no gold labels (nothing to disagree
    with).

    Claim segmentation is not deterministic across answer phrasings — a
    verifier may merge or split sentences differently than the annotator. So a
    length mismatch degrades gracefully (matches over ``max(len)``) rather than
    scoring zero: wrong labels and wrong counts both cost, but a verifier that
    merges two correct claims into one correct claim is not treated as a total
    grounding failure.
    """
    if not gold and not predicted:
        return 1.0
    if not gold:
        return 1.0
    hits = sum(1 for p, g in zip(predicted, gold) if p == g)
    denom = max(len(predicted), len(gold))
    return round(hits / denom, 4) if denom else 1.0



def contrastive_coverage(
    contradicted_or_missing_claims: int,
    counter_evidence_found: int,
) -> float:
    """How well counter-evidence was surfaced for claims that needed it.

    For cases where the answer had contradicted / unsupported claims, this is
    the ratio of those that ended up with at least one piece of opposing
    evidence in the pool. Returns 1.0 when no claim needed contrastive recall.
    """
    if contradicted_or_missing_claims <= 0:
        return 1.0
    return round(min(counter_evidence_found, contradicted_or_missing_claims)
                 / contradicted_or_missing_claims, 4)


def graph_contribution_rate(retrieval_sources: list[str]) -> float:
    """Fraction of retrieved evidence contributed by a graph retriever."""
    if not retrieval_sources:
        return 0.0
    graph_labels = {"graph", "graphiti", "graphrag", "ms_graphrag", "structural"}
    graph_items = sum(source.lower() in graph_labels for source in retrieval_sources)
    return round(graph_items / len(retrieval_sources), 4)


def graph_hit_rate(retrieval_sources: list[str]) -> float:
    """1.0 when at least one graph-derived evidence item was retrieved."""
    return 1.0 if graph_contribution_rate(retrieval_sources) > 0 else 0.0


def graph_requirement_met(retrieval_sources: list[str], required: bool) -> float:
    """Strict case-level graph coverage contract."""
    if not required:
        return 1.0
    return graph_hit_rate(retrieval_sources)
