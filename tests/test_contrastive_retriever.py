from __future__ import annotations

from personal_agent.agent.ask.retrievers import ContrastiveRetriever, _claim_core_terms
from personal_agent.kernel.models import AgentState
from personal_agent.kernel.query_understanding import RetrievalFilters

from .note_factory import make_note


class _FakeService:
    """Minimal AskService stand-in: records queries, returns canned notes."""

    def __init__(self, notes_by_query=None):
        self._notes_by_query = notes_by_query or {}
        self.seen_queries = []

    def _run_local_retrieval(self, query, user_id, filters=None):
        self.seen_queries.append(query)
        matches = self._notes_by_query.get(query, [])
        return AgentState(
            mode="ask", question=query, user_id=user_id,
            matches=matches, citations=[], answer=None,
        )


class _FakeCtx:
    def __init__(self):
        self.user_id = "u1"
        self.evidence_pool = []


class TestClaimCoreTerms:
    def test_strips_citation_markers_and_fillers(self):
        assert "[1]" not in _claim_core_terms("因此 Redis 缓存能降低负载[1]")
        assert _claim_core_terms("因此 Redis 缓存能降低负载").startswith("Redis")

    def test_truncates_to_limit(self):
        long = "字" * 100
        assert len(_claim_core_terms(long, limit=40)) == 40


class TestContrastiveRetriever:
    def test_builds_opposition_queries(self):
        svc = _FakeService()
        retr = ContrastiveRetriever(svc)
        queries = retr._queries(["Redis 缓存能降低数据库负载"], max_claims=3)
        assert queries  # non-empty
        assert any("反对" in q for q in queries)
        assert any("Redis" in q for q in queries)

    def test_returns_counter_evidence_tagged(self):
        note = make_note(title="风险", content="Redis 缓存会增加运维复杂度", summary="缓存有风险")
        # all opposition queries resolve to the same counter-note
        svc = _FakeService()
        svc._notes_by_query = {q: [note] for q in
                               ContrastiveRetriever(svc)._queries(["Redis 缓存降低负载"], 3)}
        retr = ContrastiveRetriever(svc)
        contrib = retr.retrieve_for_claims(
            ["Redis 缓存降低负载"], RetrievalFilters(), _FakeCtx(),
        )
        assert contrib.evidence
        assert all(e.metadata.get("retrieved_by") == "contrastive" for e in contrib.evidence)
        assert contrib.trace

    def test_dedup_against_existing_pool(self):
        note = make_note(title="风险", content="缓存增加复杂度", summary="风险")
        svc = _FakeService()
        svc._notes_by_query = {q: [note] for q in
                               ContrastiveRetriever(svc)._queries(["缓存降低负载"], 3)}
        ctx = _FakeCtx()
        # pre-seed the pool with an evidence item carrying the same source_id
        from personal_agent.kernel.evidence import notes_to_evidence
        ctx.evidence_pool = notes_to_evidence([note])
        retr = ContrastiveRetriever(svc)
        contrib = retr.retrieve_for_claims(["缓存降低负载"], RetrievalFilters(), ctx)
        assert not contrib.evidence  # already present -> filtered out

    def test_no_claims_returns_empty(self):
        retr = ContrastiveRetriever(_FakeService())
        contrib = retr.retrieve_for_claims([], RetrievalFilters(), _FakeCtx())
        assert not contrib.evidence
        assert not contrib.trace
