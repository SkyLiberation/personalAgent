from __future__ import annotations

from personal_agent.core.evidence import (
    EvidenceItem,
    rank_evidence_items,
    select_ranked_evidence,
)


def _ev(source_id: str, snippet: str, score: float) -> EvidenceItem:
    return EvidenceItem(
        source_type="note", source_id=source_id, title=source_id,
        snippet=snippet, score=score,
    )


QUESTION = "redis cache order data performance"
NEAR_DUP_A = "Redis caches hot order data in memory to reduce database load and improve performance"
NEAR_DUP_B = "Redis caches hot order data in memory reducing database load improving performance"
DIVERSE = "Horizontal sharding splits the order table across nodes for write scalability"


class TestMmrSelection:
    def test_diversity_prefers_distinct_content_over_near_duplicate(self):
        items = [_ev("a", NEAR_DUP_A, 0.9), _ev("b", NEAR_DUP_B, 0.88), _ev("c", DIVERSE, 0.6)]
        ranked = rank_evidence_items(QUESTION, items)
        pack = select_ranked_evidence(QUESTION, ranked, max_items=2, char_budget=10000, mmr_lambda=0.5)
        ids = [e.source_id for e in pack.evidence]
        assert "a" in ids and "c" in ids
        assert "b" not in ids

    def test_pure_relevance_lambda_keeps_top_scores(self):
        items = [_ev("a", NEAR_DUP_A, 0.9), _ev("b", NEAR_DUP_B, 0.88), _ev("c", DIVERSE, 0.6)]
        ranked = rank_evidence_items(QUESTION, items)
        pack = select_ranked_evidence(QUESTION, ranked, max_items=2, char_budget=10000, mmr_lambda=1.0)
        assert {e.source_id for e in pack.evidence} == {"a", "b"}

    def test_char_budget_still_enforced(self):
        big = "word " * 400
        items = [_ev("a", big, 0.9), _ev("b", DIVERSE, 0.8)]
        ranked = rank_evidence_items(QUESTION, items)
        pack = select_ranked_evidence(QUESTION, ranked, max_items=5, char_budget=300, mmr_lambda=0.7)
        # First item always selected even if over budget; second must not overflow.
        assert pack.used_chars <= pack.selected[0].estimated_chars

    def test_stale_versions_dropped(self):
        stale = _ev("old", DIVERSE, 0.95)
        stale.metadata["version_status"] = "superseded"
        fresh = _ev("new", NEAR_DUP_A, 0.5)
        ranked = rank_evidence_items(QUESTION, [stale, fresh])
        pack = select_ranked_evidence(QUESTION, ranked, max_items=5, char_budget=10000)
        assert [e.source_id for e in pack.evidence] == ["new"]
