"""Eval runner for ask quality test cases.

These tests verify that the AnswerVerifier produces expected scores
for a curated set of question/answer/evidence scenarios.

This is NOT a model output eval — it validates that the verifier itself
produces reasonable results so that it can serve as a reliable guardrail.
"""

from __future__ import annotations

import pytest

from personal_agent.agent.verifier import AnswerVerifier

from .test_cases import ALL_ASK_CASES, DEGRADED, WELL_SUPPORTED


class TestAskQualityEval:
    @pytest.fixture
    def verifier(self):
        return AnswerVerifier()

    @pytest.mark.parametrize(
        "case",
        WELL_SUPPORTED,
        ids=[c.id for c in WELL_SUPPORTED],
    )
    def test_well_supported_case_meets_min_score(self, verifier, case):
        answer = _mock_answer(case)
        result = verifier.verify(
            question=case.question,
            answer=answer,
            citations=case.citations,
            matches=case.notes,
        )
        assert result.evidence_score >= case.min_score, (
            f"{case.id}: score={result.evidence_score} < min={case.min_score}\n"
            f"issues={result.issues}\nwarnings={result.warnings}"
        )
        for phrase in case.forbidden_phrases:
            assert phrase not in answer, f"{case.id}: answer contains '{phrase}'"

    @pytest.mark.parametrize(
        "case",
        DEGRADED,
        ids=[c.id for c in DEGRADED],
    )
    def test_degraded_case_stays_below_threshold(self, verifier, case):
        answer = _mock_answer(case)
        result = verifier.verify(
            question=case.question,
            answer=answer,
            citations=case.citations,
            matches=case.notes,
        )
        assert result.evidence_score <= 0.4, (
            f"{case.id}: expected low score but got {result.evidence_score}"
        )

    def test_all_cases_have_unique_ids(self):
        ids = [c.id for c in ALL_ASK_CASES]
        assert len(ids) == len(set(ids)), f"Duplicate eval case ids: {ids}"

    def test_well_supported_count(self):
        assert len(WELL_SUPPORTED) >= 3, "Should have at least 3 well-supported cases"

    def test_degraded_count(self):
        assert len(DEGRADED) >= 2, "Should have at least 2 degraded cases"


def _mock_answer(case) -> str:
    """Build a plausible mock answer from the case data.

    In a real eval pipeline, this would be the actual LLM output.
    For now, we construct an answer that references the available notes
    so that the verifier can score it meaningfully.
    """
    if not case.notes:
        return "我暂时无法回答这个问题。"
    titles = [note.title for note in case.notes[:3]]
    body = "；".join(f"{title}表明相关内容已被匹配" for title in titles)
    return f"根据知识库中的笔记：{body}。"
