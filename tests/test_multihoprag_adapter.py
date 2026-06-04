from __future__ import annotations

import pytest

from evals.multihoprag.adapter import (
    corpus_to_edges,
    corpus_to_notes,
    expected_episodes,
    expected_note_ids,
    parent_note_id,
)
from evals.multihoprag.loader import MHRDoc, MHRQuery
from evals.multihoprag.metrics import compute_grouped_report


def _docs() -> dict[str, MHRDoc]:
    # Production chunker keeps content < 2000 chars as a single chunk, so make
    # Article A long enough to actually split across its two headings.
    filler_one = "First section discusses the initial topic in depth. " * 50
    filler_two = "Second section pivots to a distinct subject entirely. " * 50
    long_body = (
        f"## Heading One\n\n{filler_one}\n\n"
        f"## Heading Two\n\n{filler_two}"
    )
    return {
        "http://a.com/x": MHRDoc(
            doc_id="http://a.com/x",
            title="Article A",
            source="The Verge",
            published_at="2023-09-28T12:00:00+00:00",
            category="technology",
            body=long_body,
        ),
        "http://b.com/y": MHRDoc(
            doc_id="http://b.com/y",
            title="Article B",
            source="TechCrunch",
            published_at="2023-10-01T14:00:29+00:00",
            category="technology",
            body="Single short article body about another topic entirely.",
        ),
    }


def _query() -> MHRQuery:
    return MHRQuery(
        query_id="mhr_00000",
        query_text="who did what according to two sources?",
        question_type="inference_query",
        answer="Someone",
        evidence_urls=("http://a.com/x", "http://b.com/y"),
    )


def test_parent_note_id_is_stable_and_safe():
    nid = parent_note_id("http://a.com/x")
    assert nid.startswith("mhr_")
    assert "/" not in nid and ":" not in nid
    assert nid == parent_note_id("http://a.com/x")  # deterministic


def test_corpus_to_notes_parent_chunks_builds_parent_and_children():
    notes = corpus_to_notes(_docs(), mode="parent_chunks")
    pid_a = parent_note_id("http://a.com/x")

    parents = [n for n in notes if n.parent_note_id is None]
    children = [n for n in notes if n.parent_note_id is not None]

    assert len(parents) == 2
    assert children, "expected at least one chunk child note"
    # Every child links back to a real parent and carries a chunk index.
    parent_ids = {p.id for p in parents}
    for child in children:
        assert child.parent_note_id in parent_ids
        assert child.chunk_index is not None
    # Article A (multi-paragraph + heading) should split into >=2 chunks.
    a_children = [c for c in children if c.parent_note_id == pid_a]
    assert len(a_children) >= 2


def test_corpus_to_notes_modes():
    docs = _docs()
    parent_only = corpus_to_notes(docs, mode="parent_only")
    assert all(n.parent_note_id is None for n in parent_only)
    assert len(parent_only) == 2

    section_only = corpus_to_notes(docs, mode="section_only")
    assert all(n.parent_note_id is not None for n in section_only)


def test_corpus_to_notes_unknown_mode():
    with pytest.raises(ValueError, match="Unknown corpus note mode"):
        corpus_to_notes(_docs(), mode="missing")


def test_expected_note_ids_is_multi_doc_set():
    relevant = expected_note_ids(_query())
    assert relevant == {
        parent_note_id("http://a.com/x"),
        parent_note_id("http://b.com/y"),
    }
    assert len(relevant) == 2  # multi-hop: two distinct evidence docs


def test_corpus_to_edges_episodes_map_back_to_parents():
    edges, node_names = corpus_to_edges(_docs())
    assert edges
    assert node_names
    # Episode ids embed the parent note id so citation eval can collapse to parent.
    pid_a = parent_note_id("http://a.com/x")
    assert any(ep.startswith(f"ep_{pid_a}_") for edge in edges for ep in edge.episodes)


def test_expected_episodes_returns_parent_doc_nodes():
    eps = expected_episodes(_query())
    assert eps == {
        f"node_doc_{parent_note_id('http://a.com/x')}",
        f"node_doc_{parent_note_id('http://b.com/y')}",
    }


def test_compute_grouped_report_buckets_by_question_type():
    pid_a = parent_note_id("http://a.com/x")
    pid_b = parent_note_id("http://b.com/y")
    rankings = [
        ("q1", [pid_a, pid_b]),
        ("q2", ["wrong_id"]),
    ]
    relevance = {"q1": {pid_a, pid_b}, "q2": {pid_a}}
    query_types = {"q1": "inference_query", "q2": "comparison_query"}

    grouped = compute_grouped_report(rankings, relevance, query_types)

    assert "overall" in grouped
    assert "inference_query" in grouped
    assert "comparison_query" in grouped
    assert grouped["inference_query"].num_queries == 1
    assert grouped["comparison_query"].num_queries == 1
    assert grouped["overall"].num_queries == 2
    # q1 fully retrieved both relevant docs at ranks 1-2.
    assert grouped["inference_query"].recall_3 == 1.0
    # q2 retrieved nothing relevant.
    assert grouped["comparison_query"].mrr == 0.0
