"""Unit tests for the router-decision harvester — pure parsing, no deps."""

from __future__ import annotations

from evals.harvest_router_cases import (
    decisions_to_draft_cases,
    parse_router_decisions,
)

_SAMPLE = """
2026-06-23 00:39:42,856 | INFO | personal_agent.agent.router | router.decision | {"goal_count": 1, "goals": ["ask"], "requires_clarification": false, "source_type": "text", "text_preview": "什么是DNS", "user_id": "default"}
2026-06-22 23:49:35,009 | INFO | personal_agent.agent.router | router.decision | {"goal_count": 0, "goals": [], "missing_information": ["具体目标或待处理内容"], "requires_clarification": true, "source_type": "text", "text_preview": "帮我", "user_id": "eval-user"}
2026-06-23 00:39:47,849 | INFO | personal_agent.core.llm_trace | llm.call | {"component": "solidify_draft", "model": "gpt-5-mini"}
2026-06-23 00:40:57,293 | INFO | personal_agent.agent.router | router.decision | {"goal_count": 1, "goals": ["ask"], "requires_clarification": false, "source_type": "text", "text_preview": "什么是DNS", "user_id": "default"}
"""


class TestParseRouterDecisions:
    def test_extracts_only_decision_lines(self):
        payloads = parse_router_decisions(_SAMPLE)
        # 3 router.decision lines (the llm.call line is ignored).
        assert len(payloads) == 3
        assert all("text_preview" in p for p in payloads)

    def test_ignores_malformed_json(self):
        bad = "x | router.decision | {not json}\n"
        assert parse_router_decisions(bad) == []


class TestDecisionsToDraftCases:
    def test_dedupes_by_text(self):
        payloads = parse_router_decisions(_SAMPLE)
        drafts = decisions_to_draft_cases(payloads)
        # "什么是DNS" appears twice -> one case; "帮我" -> one. Total 2.
        assert len(drafts) == 2
        texts = {d["text"] for d in drafts}
        assert texts == {"什么是DNS", "帮我"}

    def test_records_observed_not_gold(self):
        drafts = decisions_to_draft_cases(parse_router_decisions(_SAMPLE))
        dns = next(d for d in drafts if d["text"] == "什么是DNS")
        # The model's decision is recorded as a SUGGESTION...
        assert dns["observed_outcome"] == "ready"
        assert dns["observed_intents"] == ["ask"]
        # ...but gold is left UNSET for human review.
        assert dns["expected_outcome"] == ""
        assert dns["expected_intents"] == []

    def test_clarify_decision_captured(self):
        drafts = decisions_to_draft_cases(parse_router_decisions(_SAMPLE))
        vague = next(d for d in drafts if d["text"] == "帮我")
        assert vague["observed_outcome"] == "clarify"
        assert vague["observed_missing_information"] == ["具体目标或待处理内容"]
