from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..core.models import Citation, KnowledgeNote

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VerificationResult:
    evidence_score: float  # 0.0 (no evidence) to 1.0 (well-supported)
    citation_valid: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

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
        matches: list[KnowledgeNote],
        web_enabled: bool = False,
        evidence: list | None = None,
    ) -> VerificationResult:
        issues: list[str] = []
        warnings: list[str] = []
        match_ids = {note.id for note in matches}

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
            if len(answer) < 20 and (match_count > 0 or valid_web_count > 0):
                warnings.append("回答过短但存在匹配笔记或网络结果，可能未充分使用证据。")

        # 3. Question-keyword coverage (lightweight sanity)
        if match_count == 0 and valid_web_count == 0:
            warnings.append("未命中任何知识库笔记或网络结果，回答可能缺乏依据。")
            score = min(score, 0.15)

        score = max(0.0, min(1.0, round(score, 2)))

        result = VerificationResult(
            evidence_score=score,
            citation_valid=citation_valid,
            issues=issues,
            warnings=warnings,
        )

        if issues:
            logger.warning("Answer verification found issues score=%.2f issues=%s", score, issues)
        elif warnings:
            logger.info("Answer verification passed with warnings score=%.2f warnings=%s", score, warnings)
        else:
            logger.info("Answer verification passed score=%.2f", score)

        return result
