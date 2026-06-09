from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from time import perf_counter

from ..core.observability import record_verification_result
from ..core.models import Citation, KnowledgeNote
from ..core.projections import MatchRef, match_ref_from_note

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
            claim_checks = _verify_claims(answer, evidence)
            if claim_checks:
                supported = [item for item in claim_checks if item.status == "supported"]
                contradicted = [item for item in claim_checks if item.status == "contradicted"]
                missing = [item for item in claim_checks if item.status == "not_found"]
                support_ratio = len(supported) / len(claim_checks)
                score += min(support_ratio * 0.25, 0.25)
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


def _verify_claims(answer: str, evidence: list) -> list[ClaimVerification]:
    claims = _extract_claims(answer)
    evidence_items = [_evidence_record(item) for item in evidence]
    checks: list[ClaimVerification] = []
    for claim in claims:
        claim_terms = _terms(claim)
        if not claim_terms:
            continue
        best_overlap = 0
        best_ids: list[str] = []
        best_text = ""
        best_source_type = ""
        for evidence_id, text, source_type in evidence_items:
            evidence_terms = _terms(text)
            overlap = len(claim_terms & evidence_terms)
            if overlap > best_overlap:
                best_overlap = overlap
                best_ids = [evidence_id]
                best_text = text
                best_source_type = source_type
            elif overlap == best_overlap and overlap > 0:
                best_ids.append(evidence_id)
        support_threshold = max(2, min(5, len(claim_terms) // 3))
        coverage = best_overlap / max(len(claim_terms), 1)
        coverage_threshold = 0.35 if best_source_type == "episode" else 0.45
        if best_overlap >= support_threshold and coverage >= coverage_threshold:
            status = "supported"
            reason = f"overlap={best_overlap}/{len(claim_terms)}, coverage={coverage:.2f}"
            if _negation_mismatch(claim, best_text):
                status = "contradicted"
                reason += ", negation_mismatch"
            checks.append(ClaimVerification(
                claim=claim,
                status=status,
                supporting_evidence_ids=best_ids[:3],
                reason=reason,
            ))
        else:
            checks.append(ClaimVerification(
                claim=claim,
                status="not_found",
                supporting_evidence_ids=[],
                reason=f"best_overlap={best_overlap}/{len(claim_terms)}, coverage={coverage:.2f}",
            ))
    return checks


def _extract_claims(answer: str, limit: int = 8) -> list[str]:
    cleaned = re.sub(r"\[[Ee]?\d+\]", "", answer)
    parts = re.split(r"[。！？!?；;\n]+", cleaned)
    claims: list[str] = []
    skip_markers = ("校验提示", "注意", "证据不足", "不确定", "无法回答")
    for part in parts:
        claim = part.strip(" -:：\t\r")
        if len(claim) < 8:
            continue
        if any(marker in claim for marker in skip_markers):
            continue
        if claim not in claims:
            claims.append(claim)
        if len(claims) >= limit:
            break
    return claims


def _evidence_record(item) -> tuple[str, str, str]:
    evidence_id = str(getattr(item, "evidence_id", "") or getattr(item, "source_id", "") or "")
    source_type = str(getattr(item, "source_type", "") or "")
    parts = [
        str(getattr(item, "title", "") or ""),
        str(getattr(item, "fact", "") or ""),
        str(getattr(item, "snippet", "") or ""),
    ]
    metadata = getattr(item, "metadata", {}) or {}
    if isinstance(metadata, dict):
        parts.extend(str(value) for value in metadata.values() if isinstance(value, str))
    return evidence_id, " ".join(parts), source_type


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    lowered = text.lower()
    for token in re.findall(r"[a-z0-9_+-]{2,}", lowered):
        terms.add(token)
    for run in re.findall(r"[\u3400-\u9fff]{2,}", text):
        terms.add(run)
        for size in (2, 3):
            for index in range(0, max(0, len(run) - size + 1)):
                terms.add(run[index:index + size])
    return terms


def _negation_mismatch(claim: str, evidence_text: str) -> bool:
    claim_negated = _has_negation(claim)
    evidence_negated = _has_negation(evidence_text)
    return claim_negated != evidence_negated and bool(evidence_text)


def _has_negation(text: str) -> bool:
    return any(marker in text for marker in ("不", "没有", "未", "不能", "无法", "不会", "不是", "no ", "not "))
