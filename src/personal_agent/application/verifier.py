from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter

from personal_agent.application.evidence_engine import EvidenceEngine
from personal_agent.kernel.observability import record_verification_result
from personal_agent.kernel.models import Citation, KnowledgeNote
from personal_agent.kernel.projections import MatchRef, match_ref_from_note

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ClaimVerification:
    claim: str
    status: str  # supported | contradicted | not_found
    supporting_evidence_ids: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass(slots=True)
class VerificationResult:
    evidence_score: float  # 0.0 (no evidence) to 1.0 (well-supported)
    citation_valid: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    claim_checks: list[ClaimVerification] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.issues) == 0

    @property
    def sufficient(self) -> bool:
        return self.evidence_score >= 0.4


class AnswerVerifier:
    """Post-generation answer quality check.

    Validates that every citation references a real note and computes
    an evidence-sufficiency score.  Does NOT modify the answer — it
    only flags problems so the caller can decide how to respond
    (log, warn, re-prompt, etc.).
    """

    # Phrases that suggest the LLM gave up or hallucinated
    _fallback_signals = (
        "暂时没有生成答案",
        "无法从你的个人知识库中找到足够依据",
        "我暂时无法",
        "暂无相关信息",
        "网络搜索未返回足够信息",
        "无法从网络搜索中找到",
    )

    def __init__(self, evidence_engine: EvidenceEngine | None = None) -> None:
        self._evidence_engine = evidence_engine or EvidenceEngine()

    def verify(
        self,
        question: str,
        answer: str,
        citations: list[Citation],
        matches: list[KnowledgeNote | MatchRef],
        web_enabled: bool = False,
        evidence: list | None = None,
        run_id: str | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
        step_id: str | None = None,
    ) -> VerificationResult:
        started = perf_counter()
        issues: list[str] = []
        warnings: list[str] = []
        match_refs = [
            match_ref_from_note(match) if isinstance(match, KnowledgeNote) else match
            for match in matches
        ]
        match_ids = {match.id for match in match_refs}

        # Separate note-based and web-based citations
        note_citations = [c for c in citations if c.source_type != "web"]
        web_citations = [c for c in citations if c.source_type == "web"]

        # 1. Citation validity — only check note citations for orphans
        orphan_citations = 0
        for citation in note_citations:
            if citation.note_id not in match_ids:
                orphan_citations += 1
        citation_valid = orphan_citations == 0
        if not citation_valid:
            issues.append(f"{orphan_citations} 条引用指向不存在的笔记。")

        # 2. Evidence sufficiency score
        score = 0.0

        # 2a. Match count (note-based only)
        match_count = len(matches)
        if match_count >= 3:
            score += 0.3
        elif match_count >= 1:
            score += 0.15

        # 2b. Valid note citation count
        valid_note_citations = len(note_citations) - orphan_citations
        if valid_note_citations >= 3:
            score += 0.3
        elif valid_note_citations >= 1:
            score += 0.15

        # 2c. Web citation count (slightly lower weight than note-based)
        valid_web_count = len(web_citations)
        if valid_web_count >= 3:
            score += 0.25
        elif valid_web_count >= 1:
            score += 0.1

        # 2d. Web bonus
        if web_enabled and valid_web_count > 0:
            score += 0.05

        # 2e. Evidence-based bonus (when unified EvidenceItem is provided)
        if evidence:
            graph_facts = [e for e in evidence if getattr(e, "source_type", None) == "graph_fact"]
            note_evidence = [e for e in evidence if getattr(e, "source_type", None) in ("note", "chunk")]
            web_evidence = [e for e in evidence if getattr(e, "source_type", None) == "web"]
            episode_evidence = [e for e in evidence if getattr(e, "source_type", None) == "episode"]

            orphan_facts = [e for e in graph_facts if getattr(e, "metadata", {}).get("orphan") is True]
            anchored_facts = len(graph_facts) - len(orphan_facts)

            if anchored_facts >= 3:
                score += 0.15
            elif anchored_facts >= 1:
                score += 0.08
            # Orphan facts contribute less
            if orphan_facts:
                score += min(len(orphan_facts) * 0.03, 0.06)

            if note_evidence and len(note_evidence) >= 2:
                score += 0.05

            if web_evidence and len(web_evidence) >= 2:
                score += 0.05

            if episode_evidence:
                score += 0.32 if len(episode_evidence) >= 2 else 0.25

        # 2f. Answer content checks
        answer_empty = not answer or not answer.strip()
        if answer_empty:
            issues.append("生成的回答为空。")
            score = 0.0
        else:
            # Check for fallback phrases
            for signal in self._fallback_signals:
                if signal in answer:
                    warnings.append(f"回答中包含兜底措辞: {signal}")
                    score = min(score, 0.2)
                    break

            # Answer length sanity — very short answers with evidence are suspicious
            has_episode_evidence = bool(evidence and any(getattr(e, "source_type", None) == "episode" for e in evidence))
            if len(answer) < 20 and (match_count > 0 or valid_web_count > 0 or has_episode_evidence):
                warnings.append("回答过短但存在匹配笔记、历史执行记录或网络结果，可能未充分使用证据。")

        # 3. Question-keyword coverage (lightweight sanity)
        has_episode_evidence = bool(evidence and any(getattr(e, "source_type", None) == "episode" for e in evidence))
        if match_count == 0 and valid_web_count == 0 and not has_episode_evidence:
            warnings.append("未命中任何知识库笔记、历史执行记录或网络结果，回答可能缺乏依据。")
            score = min(score, 0.15)

        # 4. Claim-level grounding against the selected evidence.
        claim_checks: list[ClaimVerification] = []
        if evidence and not answer_empty:
            claim_checks = self._grounding_checks(answer, evidence)
            if claim_checks:
                supported = [item for item in claim_checks if item.status == "supported"]
                partial = [item for item in claim_checks if item.status == "partially_supported"]
                contradicted = [item for item in claim_checks if item.status == "contradicted"]
                missing = [
                    item for item in claim_checks
                    if item.status in {"not_found", "unsupported"}
                ]
                support_ratio = (len(supported) + len(partial) * 0.5) / len(claim_checks)
                score += min(support_ratio * 0.25, 0.25)
                if partial:
                    warnings.append(f"{len(partial)} 个关键结论只有部分证据支撑。")
                if missing:
                    warnings.append(f"{len(missing)} 个关键结论未能在入选证据中找到直接支撑。")
                    if len(missing) == len(claim_checks):
                        issues.append("所有关键结论都未能在入选证据中找到直接支撑。")
                        score = min(score, 0.35)
                if contradicted:
                    issues.append(f"{len(contradicted)} 个关键结论可能与证据冲突。")
                    score = min(score, 0.25)

        score = max(0.0, min(1.0, round(score, 2)))

        result = VerificationResult(
            evidence_score=score,
            citation_valid=citation_valid,
            issues=issues,
            warnings=warnings,
            claim_checks=claim_checks,
        )

        if issues:
            logger.warning("Answer verification found issues score=%.2f issues=%s", score, issues)
        elif warnings:
            logger.info("Answer verification passed with warnings score=%.2f warnings=%s", score, warnings)
        else:
            logger.info("Answer verification passed score=%.2f", score)

        record_verification_result(
            question=question,
            answer=answer,
            result=result,
            matches_count=len(matches),
            citations_count=len(citations),
            web_enabled=web_enabled,
            evidence_count=len(evidence or []),
            latency_ms=round((perf_counter() - started) * 1000, 2),
            run_id=run_id,
            thread_id=thread_id,
            user_id=user_id,
            step_id=step_id,
        )

        return result

    def _grounding_checks(self, answer: str, evidence: list) -> list[ClaimVerification]:
        """Claim-level grounding hook. Subclasses may override the judgment
        strategy (e.g. entailment) while reusing all surrounding scoring."""
        return [
            ClaimVerification(
                claim=item.claim,
                status=item.status,
                supporting_evidence_ids=item.supporting_evidence_ids,
                reason=item.reason,
            )
            for item in self._evidence_engine.verify_claims(answer, evidence)
        ]


class EntailmentAnswerVerifier(AnswerVerifier):
    """Verifier whose claim grounding uses a three-way entailment judge.

    Reuses every citation / evidence-sufficiency / fallback-phrase check from
    :class:`AnswerVerifier` (via ``super().verify``) and only swaps the
    claim-grounding step: each claim is aligned to its best evidence by lexical
    overlap, then an :class:`~.entailment.EntailmentJudge` renders a three-way
    verdict. ``entailed`` -> supported, ``contradicted`` -> contradicted,
    ``not_enough_info`` -> not_found, so the downstream aggregation in
    ``AnswerVerifier.verify`` (which keys off those status strings) is
    unchanged. The richer signal is the contradiction precision: polarity /
    numeric / negation conflicts on *aligned* evidence, not just lexical miss.
    """

    _VERDICT_TO_STATUS = {
        "entailed": "supported",
        "contradicted": "contradicted",
        "not_enough_info": "not_found",
    }

    def __init__(self, judge=None) -> None:
        from personal_agent.application.entailment import HeuristicEntailmentJudge

        super().__init__(EvidenceEngine(entailment_judge=judge or HeuristicEntailmentJudge()))


def create_answer_verifier(settings) -> AnswerVerifier:
    name = (getattr(settings.ask, "verifier", "heuristic") or "heuristic").strip().lower()
    if name in {"heuristic", "default"}:
        return AnswerVerifier()
    if name == "entailment":
        return EntailmentAnswerVerifier()
    raise ValueError(
        "Unknown ask verifier '%s'. Available: heuristic, entailment" % name
    )
