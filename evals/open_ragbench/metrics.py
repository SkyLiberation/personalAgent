"""Information retrieval metrics: MRR, Recall@K, NDCG@K."""
from __future__ import annotations

import math
from dataclasses import dataclass


def reciprocal_rank(ranked_ids: list[str], relevant_ids: set[str]) -> float:
    """1 / rank of the first relevant item.  Returns 0.0 if none found."""
    for i, rid in enumerate(ranked_ids, start=1):
        if rid in relevant_ids:
            return 1.0 / i
    return 0.0


def recall_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Fraction of relevant items found in top-K.  Returns 1.0 when *relevant_ids* is empty."""
    if not relevant_ids:
        return 1.0
    top_k = set(ranked_ids[:k])
    return len(top_k & relevant_ids) / len(relevant_ids)


def _dcg_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Discounted Cumulative Gain at K with binary relevance."""
    value = 0.0
    for i, rid in enumerate(ranked_ids[:k], start=1):
        if rid in relevant_ids:
            value += 1.0 / math.log2(i + 1)
    return value


def ndcg_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Normalised DCG@K.  Returns 0.0 when *relevant_ids* is empty."""
    if not relevant_ids:
        return 0.0
    dcg = _dcg_at_k(ranked_ids, relevant_ids, k)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant_ids), k) + 1))
    return dcg / ideal if ideal > 0 else 0.0


@dataclass(frozen=True)
class RetrievalReport:
    """Aggregate retrieval quality metrics across all evaluated queries."""
    num_queries: int
    mrr: float
    recall_1: float
    recall_3: float
    recall_5: float
    recall_10: float
    ndcg_5: float
    ndcg_10: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "num_queries": self.num_queries,
            "mrr": self.mrr,
            "recall_1": self.recall_1,
            "recall_3": self.recall_3,
            "recall_5": self.recall_5,
            "recall_10": self.recall_10,
            "ndcg_5": self.ndcg_5,
            "ndcg_10": self.ndcg_10,
        }

    def summary(self) -> str:
        lines = [
            f"Retrieval Report ({self.num_queries} queries)",
            f"  MRR:       {self.mrr:.4f}",
            f"  Recall@1:  {self.recall_1:.4f}",
            f"  Recall@3:  {self.recall_3:.4f}",
            f"  Recall@5:  {self.recall_5:.4f}",
            f"  Recall@10: {self.recall_10:.4f}",
            f"  NDCG@5:    {self.ndcg_5:.4f}",
            f"  NDCG@10:   {self.ndcg_10:.4f}",
        ]
        return "\n".join(lines)


def compute_report(
    rankings: list[tuple[str, list[str]]],
    relevance: dict[str, set[str]],
) -> RetrievalReport:
    """Compute aggregate metrics over all queries.

    *rankings* is ``[(query_id, [ranked_result_ids]), ...]``.
    *relevance* is ``{query_id: {relevant_ids}}``.
    """
    n = len(rankings)
    if n == 0:
        return RetrievalReport(0, 0, 0, 0, 0, 0, 0, 0)

    sum_mrr = 0.0
    sum_r1 = 0.0
    sum_r3 = 0.0
    sum_r5 = 0.0
    sum_r10 = 0.0
    sum_ndcg5 = 0.0
    sum_ndcg10 = 0.0

    for qid, ranked in rankings:
        rel = relevance.get(qid, set())
        sum_mrr += reciprocal_rank(ranked, rel)
        sum_r1 += recall_at_k(ranked, rel, 1)
        sum_r3 += recall_at_k(ranked, rel, 3)
        sum_r5 += recall_at_k(ranked, rel, 5)
        sum_r10 += recall_at_k(ranked, rel, 10)
        sum_ndcg5 += ndcg_at_k(ranked, rel, 5)
        sum_ndcg10 += ndcg_at_k(ranked, rel, 10)

    return RetrievalReport(
        num_queries=n,
        mrr=sum_mrr / n,
        recall_1=sum_r1 / n,
        recall_3=sum_r3 / n,
        recall_5=sum_r5 / n,
        recall_10=sum_r10 / n,
        ndcg_5=sum_ndcg5 / n,
        ndcg_10=sum_ndcg10 / n,
    )
