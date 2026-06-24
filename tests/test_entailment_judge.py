from __future__ import annotations

from personal_agent.application.entailment import (
    CONTRADICTED,
    ENTAILED,
    NOT_ENOUGH_INFO,
    HeuristicEntailmentJudge,
)


def _judge(claim, evidence, *, overlap, terms, coverage, source_type="note"):
    return HeuristicEntailmentJudge().judge(
        claim, evidence,
        overlap=overlap, claim_term_count=terms,
        coverage=coverage, source_type=source_type,
    )


class TestHeuristicEntailmentJudge:
    def test_strong_overlap_is_entailed(self):
        v = _judge(
            "Redis 缓存用于降低数据库负载",
            "系统使用 Redis 缓存来降低数据库负载和延迟",
            overlap=6, terms=8, coverage=0.75,
        )
        assert v.verdict == ENTAILED
        assert v.confidence > 0.5

    def test_negation_mismatch_on_aligned_evidence_is_contradicted(self):
        v = _judge(
            "Redis 缓存可以降低数据库负载",
            "Redis 缓存不能降低数据库负载，反而增加复杂度",
            overlap=6, terms=8, coverage=0.75,
        )
        assert v.verdict == CONTRADICTED
        assert "negation" in v.reason or "polarity" in v.reason

    def test_polarity_conflict_is_contradicted(self):
        v = _judge(
            "该方案能提高系统吞吐量",
            "该方案会降低系统吞吐量并带来抖动",
            overlap=5, terms=6, coverage=0.7,
        )
        assert v.verdict == CONTRADICTED
        assert "polarity" in v.reason

    def test_numeric_conflict_is_contradicted(self):
        v = _judge(
            "缓存命中率达到 95%",
            "实测缓存命中率只有 60%",
            overlap=4, terms=5, coverage=0.6,
        )
        assert v.verdict == CONTRADICTED
        assert "numeric" in v.reason

    def test_weak_overlap_is_not_enough_info(self):
        v = _judge(
            "量子计算将颠覆密码学体系",
            "Redis 缓存用于降低数据库负载",
            overlap=0, terms=6, coverage=0.0,
        )
        assert v.verdict == NOT_ENOUGH_INFO

    def test_unaligned_negation_does_not_flip(self):
        # Negation present but evidence is unrelated (low overlap) -> stays NEI,
        # not a spurious contradiction.
        v = _judge(
            "新功能提升了用户留存",
            "天气不错，今天没有下雨",
            overlap=1, terms=6, coverage=0.16,
        )
        assert v.verdict == NOT_ENOUGH_INFO

    def test_empty_evidence_is_not_enough_info(self):
        v = _judge("任意结论", "", overlap=0, terms=3, coverage=0.0)
        assert v.verdict == NOT_ENOUGH_INFO
