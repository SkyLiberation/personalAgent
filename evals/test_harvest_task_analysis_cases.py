"""Unit tests for the task-analysis harvester: pure parsing, no deps."""

from __future__ import annotations

from evals.harvest_task_analysis_cases import (
    analyses_to_draft_cases,
    parse_task_analyses,
)

_SAMPLE = """
2026-06-23 00:39:42,856 | INFO | personal_agent.planning.task_analyzer | task_analysis.completed | {"goal_count": 1, "result_contracts": ["response"], "outcome": "ready", "text_preview": "什么是DNS"}
2026-06-22 23:49:35,009 | INFO | personal_agent.planning.task_analyzer | task_analysis.completed | {"goal_count": 0, "result_contracts": [], "outcome": "clarify", "missing_information": ["具体目标或待处理内容"], "text_preview": "帮我"}
2026-06-23 00:39:47,849 | INFO | personal_agent.kernel.llm_trace | llm.call | {"component": "solidify_draft", "model": "gpt-5-mini"}
2026-06-23 00:40:57,293 | INFO | personal_agent.planning.task_analyzer | task_analysis.completed | {"goal_count": 1, "result_contracts": ["response"], "outcome": "ready", "text_preview": "什么是DNS"}
"""


class TestParseTaskAnalyses:
    def test_extracts_only_decision_lines(self):
        payloads = parse_task_analyses(_SAMPLE)
        # Three task-analysis lines; the unrelated llm.call line is ignored.
        assert len(payloads) == 3
        assert all("text_preview" in p for p in payloads)

    def test_ignores_malformed_json(self):
        bad = "x | task_analysis.completed | {not json}\n"
        assert parse_task_analyses(bad) == []


class TestDecisionsToDraftCases:
    def test_dedupes_by_text(self):
        payloads = parse_task_analyses(_SAMPLE)
        drafts = analyses_to_draft_cases(payloads)
        # "什么是DNS" appears twice -> one case; "帮我" -> one. Total 2.
        assert len(drafts) == 2
        texts = {d["text"] for d in drafts}
        assert texts == {"什么是DNS", "帮我"}

    def test_records_observed_not_gold(self):
        drafts = analyses_to_draft_cases(parse_task_analyses(_SAMPLE))
        dns = next(d for d in drafts if d["text"] == "什么是DNS")
        # The model's decision is recorded as a SUGGESTION...
        assert dns["observed_outcome"] == "ready"
        assert dns["observed_result_contracts"] == ["response"]
        # ...but gold is left UNSET for human review.
        assert dns["expected_outcome"] == ""
        assert dns["expected_result_contracts"] == []

    def test_clarify_decision_captured(self):
        drafts = analyses_to_draft_cases(parse_task_analyses(_SAMPLE))
        vague = next(d for d in drafts if d["text"] == "帮我")
        assert vague["observed_outcome"] == "clarify"
        assert vague["observed_missing_information"] == ["具体目标或待处理内容"]
