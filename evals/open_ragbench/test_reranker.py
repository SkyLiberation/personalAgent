"""Benchmark rank_graph_citation_hits against Open RAG Benchmark."""
from __future__ import annotations

import pytest

from personal_agent.graphiti.reranker import rank_graph_citation_hits

from .adapter import corpus_to_edges, expected_episode
from .metrics import RetrievalReport, compute_report


@pytest.fixture(scope="session")
def reranker_data(benchmark_data):
    """Convert corpus to EdgeLike + node_names_by_uuid."""
    queries, docs = benchmark_data
    edges, node_names = corpus_to_edges(docs)
    return edges, node_names, queries


@pytest.fixture(scope="session")
def reranker_rankings(reranker_data):
    """Run all queries through rank_graph_citation_hits."""
    edges, node_names, queries = reranker_data
    rankings: list[tuple[str, list[str]]] = []
    for query in queries:
        hits = rank_graph_citation_hits(
            question=query.query_text,
            edges=edges,
            node_names_by_uuid=node_names,
            limit=10,
        )
        ranked_episodes = [hit.episode_uuid for hit in hits]
        rankings.append((query.query_id, ranked_episodes))
    return rankings


@pytest.fixture(scope="session")
def reranker_relevance(benchmark_data):
    """Build relevance map: query_id -> set of relevant episode UUIDs."""
    queries, _ = benchmark_data
    relevance: dict[str, set[str]] = {}
    for query in queries:
        relevance[query.query_id] = {expected_episode(query)}
    return relevance


def test_reranker_metrics(reranker_rankings, reranker_relevance):
    """Compute and report reranker retrieval quality."""
    report: RetrievalReport = compute_report(reranker_rankings, reranker_relevance)
    print(f"\n{report.summary()}")
    assert report.num_queries > 0, "No queries evaluated"


def test_reranker_produces_hits(reranker_data):
    """Sanity: the reranker produces non-empty results for at least some queries."""
    edges, node_names, queries = reranker_data
    hits_found = 0
    for query in queries[:50]:
        hits = rank_graph_citation_hits(
            question=query.query_text,
            edges=edges,
            node_names_by_uuid=node_names,
            limit=10,
        )
        if hits:
            hits_found += 1
    assert hits_found > 0, "rank_graph_citation_hits produced no hits for any sampled query"
