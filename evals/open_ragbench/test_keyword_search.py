"""Benchmark LocalMemoryStore.find_similar_notes against Open RAG Benchmark."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from personal_agent.storage.memory_store import LocalMemoryStore

from .adapter import corpus_to_notes, expected_note_ids
from .metrics import RetrievalReport, compute_report


@pytest.fixture(scope="session")
def populated_store(benchmark_data):
    """Create a LocalMemoryStore populated with all corpus notes."""
    queries, docs = benchmark_data
    store_dir = Path(tempfile.mkdtemp(prefix="ragbench_store_"))
    store = LocalMemoryStore(store_dir)
    for note in corpus_to_notes(docs):
        store.add_note(note)
    return store


@pytest.fixture(scope="session")
def keyword_rankings(benchmark_data, populated_store):
    """Run all queries through find_similar_notes and collect rankings."""
    queries, _ = benchmark_data
    rankings: list[tuple[str, list[str]]] = []
    for query in queries:
        results = populated_store.find_similar_notes(
            user_id="ragbench_eval",
            query=query.query_text,
            limit=10,
        )
        ranked_ids = [note.id for note in results]
        rankings.append((query.query_id, ranked_ids))
    return rankings


@pytest.fixture(scope="session")
def keyword_relevance(benchmark_data):
    """Build relevance map: query_id -> set of relevant note IDs."""
    queries, _ = benchmark_data
    relevance: dict[str, set[str]] = {}
    for query in queries:
        section_id, parent_id = expected_note_ids(query)
        relevance[query.query_id] = {section_id, parent_id}
    return relevance


def test_keyword_search_metrics(keyword_rankings, keyword_relevance):
    """Compute and report keyword search retrieval quality."""
    report: RetrievalReport = compute_report(keyword_rankings, keyword_relevance)
    print(f"\n{report.summary()}")
    assert report.num_queries > 0, "No queries evaluated"


def test_keyword_search_returns_results(benchmark_data, populated_store):
    """Sanity: at least some queries return non-empty results."""
    queries, _ = benchmark_data
    non_empty = 0
    for query in queries[:50]:
        results = populated_store.find_similar_notes(
            user_id="ragbench_eval",
            query=query.query_text,
            limit=10,
        )
        if results:
            non_empty += 1
    assert non_empty > 0, "find_similar_notes returned empty for all sampled queries"
