"""Per-question-type grouped metrics for MultiHopRAG.

Reuses the dataset-agnostic IR metrics from ``evals.open_ragbench.metrics``
(MRR / Recall@k / NDCG@k) and adds grouping by ``question_type`` so we can see
how retrieval quality differs across inference / comparison / temporal / null
queries — the axis the MultiHopRAG paper emphasises.
"""
from __future__ import annotations

from evals.open_ragbench.metrics import RetrievalReport, compute_report

__all__ = ["RetrievalReport", "compute_report", "compute_grouped_report", "format_grouped_report"]


def compute_grouped_report(
    rankings: list[tuple[str, list[str]]],
    relevance: dict[str, set[str]],
    query_types: dict[str, str],
) -> dict[str, RetrievalReport]:
    """Compute one RetrievalReport per question type plus an ``overall`` bucket.

    *rankings* is ``[(query_id, [ranked_ids]), ...]``.
    *relevance* is ``{query_id: {relevant_ids}}``.
    *query_types* is ``{query_id: question_type}``.

    Returns ``{question_type: report, ..., "overall": report}``. Buckets with no
    queries are omitted (other than ``overall``, which always reflects all
    queries).
    """
    buckets: dict[str, list[tuple[str, list[str]]]] = {}
    for qid, ranked in rankings:
        qtype = query_types.get(qid, "unknown")
        buckets.setdefault(qtype, []).append((qid, ranked))

    reports: dict[str, RetrievalReport] = {}
    for qtype, group in sorted(buckets.items()):
        reports[qtype] = compute_report(group, relevance)
    reports["overall"] = compute_report(rankings, relevance)
    return reports


def format_grouped_report(reports: dict[str, RetrievalReport]) -> str:
    """Render a grouped report as a readable multi-section summary."""
    lines: list[str] = []
    # Show overall first, then each type alphabetically.
    ordered = ["overall"] + [k for k in sorted(reports) if k != "overall"]
    for key in ordered:
        report = reports.get(key)
        if report is None:
            continue
        lines.append(f"[{key}]")
        lines.append(report.summary())
        lines.append("")
    return "\n".join(lines).rstrip()
