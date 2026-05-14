from __future__ import annotations

from personal_agent.agent.verifier import AnswerVerifier, VerificationResult
from personal_agent.core.models import Citation, KnowledgeNote


def _note(note_id: str, title: str = "测试笔记") -> KnowledgeNote:
    return KnowledgeNote(
        id=note_id,
        title=title,
        content=f"{title}的正文内容。",
        summary=f"{title}摘要",
    )


def _citation(note_id: str, title: str = "测试笔记") -> Citation:
    return Citation(note_id=note_id, title=title, snippet="...", relation_fact=None)


class TestAnswerVerifier:
    def test_all_valid_citations_high_score(self):
        verifier = AnswerVerifier()
        notes = [_note("n1"), _note("n2"), _note("n3")]
        citations = [_citation("n1"), _citation("n2"), _citation("n3")]
        result = verifier.verify("问题", "很好的答案", citations, notes)
        assert result.citation_valid is True
        assert result.ok is True
        assert result.evidence_score >= 0.6

    def test_orphan_citation_detected(self):
        verifier = AnswerVerifier()
        notes = [_note("n1")]
        citations = [_citation("n1"), _citation("n2"), _citation("n3")]
        result = verifier.verify("问题", "答案", citations, notes)
        assert result.citation_valid is False
        assert len(result.issues) == 1
        assert "2 条引用指向不存在的笔记" in result.issues[0]

    def test_empty_answer_zero_score(self):
        verifier = AnswerVerifier()
        notes = [_note("n1")]
        citations = [_citation("n1")]
        result = verifier.verify("问题", "", citations, notes)
        assert result.evidence_score == 0.0
        assert any("空" in issue for issue in result.issues)

    def test_fallback_phrase_penalizes_score(self):
        verifier = AnswerVerifier()
        notes: list[KnowledgeNote] = []
        citations: list[Citation] = []
        result = verifier.verify(
            "复杂问题",
            "我暂时无法回答这个问题。",
            citations,
            notes,
        )
        assert result.evidence_score <= 0.2
        assert len(result.warnings) > 0
        assert any("兜底措辞" in w for w in result.warnings)

    def test_no_matches_warns(self):
        verifier = AnswerVerifier()
        result = verifier.verify("问题", "一个没有证据的答案", [], [])
        assert len(result.warnings) > 0
        assert any("未命中" in w for w in result.warnings)
        assert result.evidence_score <= 0.15

    def test_short_answer_with_matches_warns(self):
        verifier = AnswerVerifier()
        notes = [_note("n1"), _note("n2")]
        citations = [_citation("n1")]
        result = verifier.verify("问题", "短答案", citations, notes)
        assert any("过短" in w for w in result.warnings)

    def test_graph_enabled_adds_bonus(self):
        verifier = AnswerVerifier()
        notes = [_note("n1")]
        citations = [_citation("n1")]
        result_no_graph = verifier.verify("问题", "答案", citations, notes, graph_enabled=False)
        result_graph = verifier.verify("问题", "答案", citations, notes, graph_enabled=True)
        assert result_graph.evidence_score > result_no_graph.evidence_score

    def test_sufficient_threshold(self):
        verifier = AnswerVerifier()
        notes = [_note("n1"), _note("n2"), _note("n3"), _note("n4")]
        citations = [_citation("n1"), _citation("n2"), _citation("n3")]
        result = verifier.verify("问题", "一个有充分依据的答案", citations, notes)
        assert result.sufficient is True

    def test_insufficient_with_low_evidence(self):
        result = VerificationResult(evidence_score=0.1, citation_valid=True, issues=[], warnings=[])
        assert result.sufficient is False

    def test_all_orphan_citations_penalizes_score(self):
        verifier = AnswerVerifier()
        notes = [_note("n1")]
        citations = [_citation("n99"), _citation("n100")]
        result = verifier.verify("问题", "答案", citations, notes)
        assert result.citation_valid is False
        # Score should be low since both citations are orphan and only 1 match
        assert result.evidence_score < 0.4


class TestAnswerVerifierWebCitations:
    """Web citation scoring (source_type="web") regression coverage."""

    def _web_citation(self, title: str = "网络结果") -> Citation:
        return Citation(
            note_id="", title=title, snippet="来自网络的结果片段",
            source_type="web", url="https://example.com/article",
        )

    def test_web_citations_contribute_evidence_score(self):
        verifier = AnswerVerifier()
        notes: list[KnowledgeNote] = []
        citations = [
            self._web_citation("结果A"),
            self._web_citation("结果B"),
            self._web_citation("结果C"),
        ]
        result = verifier.verify("问题", "答案", citations, notes, web_enabled=True)
        assert result.evidence_score > 0.2

    def test_web_enabled_adds_bonus(self):
        verifier = AnswerVerifier()
        notes: list[KnowledgeNote] = []
        citations = [self._web_citation("结果A")]
        result_without = verifier.verify("问题", "答案", citations, notes, web_enabled=False)
        result_with = verifier.verify("问题", "答案", citations, notes, web_enabled=True)
        assert result_with.evidence_score >= result_without.evidence_score

    def test_web_citations_skip_orphan_check(self):
        verifier = AnswerVerifier()
        notes: list[KnowledgeNote] = [_note("n1")]
        citations = [
            self._web_citation("网络结果"),
            _citation("n99"),  # orphan note citation
        ]
        result = verifier.verify("问题", "答案", citations, notes, web_enabled=True)
        # Web citation (note_id="") should NOT count as orphan
        # Only the note citation (n99) should be flagged — exactly 1 orphan
        assert len(result.issues) == 1
        assert "引用指向不存在的笔记" in result.issues[0]
