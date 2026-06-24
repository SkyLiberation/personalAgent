from __future__ import annotations

from personal_agent.application.verifier import (
    AnswerVerifier,
    EntailmentAnswerVerifier,
    create_answer_verifier,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.evidence import EvidenceItem


def _ev(snippet: str, source_id: str = "n1") -> EvidenceItem:
    return EvidenceItem(source_type="note", source_id=source_id, title="t", snippet=snippet)


class TestEntailmentAnswerVerifier:
    def test_supported_claim_grounds(self):
        verifier = EntailmentAnswerVerifier()
        evidence = [_ev("系统使用 Redis 缓存来降低数据库负载和查询延迟。")]
        result = verifier.verify(
            "Redis 有什么用",
            "Redis 缓存用于降低数据库负载。",
            citations=[],
            matches=[],
            evidence=evidence,
        )
        statuses = {c.status for c in result.claim_checks}
        assert "supported" in statuses
        assert all(c.reason.startswith(("entailed", "contradicted", "not_enough_info")) for c in result.claim_checks)

    def test_contradiction_raises_issue(self):
        verifier = EntailmentAnswerVerifier()
        evidence = [_ev("实测表明 Redis 缓存不能降低数据库负载，反而增加了运维复杂度。")]
        result = verifier.verify(
            "Redis 有什么用",
            "Redis 缓存可以降低数据库负载。",
            citations=[],
            matches=[],
            evidence=evidence,
        )
        contradicted = [c for c in result.claim_checks if c.status == "contradicted"]
        assert contradicted
        # contradiction caps the score and is surfaced as an issue
        assert any("冲突" in issue for issue in result.issues)

    def test_unsupported_claim_marked_not_found(self):
        verifier = EntailmentAnswerVerifier()
        evidence = [_ev("今天的天气晴朗，适合户外活动。")]
        result = verifier.verify(
            "量子计算的影响",
            "量子计算将彻底颠覆现代密码学体系。",
            citations=[],
            matches=[],
            evidence=evidence,
        )
        assert all(c.status == "not_found" for c in result.claim_checks)
        assert all(c.supporting_evidence_ids == [] for c in result.claim_checks)


class TestVerifierFactory:
    def test_default_is_heuristic(self):
        settings = Settings()
        verifier = create_answer_verifier(settings)
        assert type(verifier) is AnswerVerifier

    def test_entailment_selected_by_config(self):
        settings = Settings()
        settings.ask.verifier = "entailment"
        verifier = create_answer_verifier(settings)
        assert isinstance(verifier, EntailmentAnswerVerifier)

    def test_unknown_verifier_raises(self):
        settings = Settings()
        settings.ask.verifier = "bogus"
        try:
            create_answer_verifier(settings)
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "bogus" in str(exc)
