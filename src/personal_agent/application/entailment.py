"""Entailment-level grounding judgment for answer verification.

The baseline :class:`AnswerVerifier` grounds each answer claim by lexical
overlap and a single negation-parity flip. That conflates "no supporting
evidence" with "evidence actively disagrees", and misses numeric / polarity
contradictions. This module separates the *judgment* into a pluggable
``EntailmentJudge``: given one claim and the aligned evidence text, return a
three-way verdict (entailed / contradicted / not_enough_info) with a reason.

The heuristic implementation here is deterministic and LLM-free (consistent
with the rest of the capture/ask heuristics). The Protocol leaves room to drop
in a real NLI / LLM judge later without touching the verifier wiring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

# Three-way entailment verdicts.
ENTAILED = "entailed"
CONTRADICTED = "contradicted"
NOT_ENOUGH_INFO = "not_enough_info"

_NEGATION_MARKERS = (
    "不", "没有", "未", "不能", "无法", "不会", "不是", "并非", "绝非",
    "no ", "not ", "never ", "cannot", "n't",
)

# Antonym-ish polarity pairs that signal a direct contradiction when one side
# appears in the claim and the other in the evidence (with shared context).
_POLARITY_PAIRS = (
    ("增加", "减少"), ("上升", "下降"), ("提高", "降低"), ("提升", "下降"),
    ("支持", "反对"), ("成功", "失败"), ("有效", "无效"), ("允许", "禁止"),
    ("开启", "关闭"), ("启用", "禁用"), ("正确", "错误"), ("可行", "不可行"),
    ("increase", "decrease"), ("rise", "fall"), ("enable", "disable"),
    ("success", "failure"), ("valid", "invalid"), ("allow", "forbid"),
)

_NUM_PATTERN = re.compile(r"-?\d+(?:\.\d+)?%?")


@dataclass(slots=True)
class EntailmentVerdict:
    """Per-claim judgment against its aligned evidence."""

    verdict: str  # entailed | contradicted | not_enough_info
    confidence: float  # 0.0 - 1.0
    reason: str = ""


class EntailmentJudge(Protocol):
    name: str

    def judge(
        self,
        claim: str,
        evidence_text: str,
        *,
        overlap: int,
        claim_term_count: int,
        coverage: float,
        source_type: str,
    ) -> EntailmentVerdict:
        """Judge whether ``evidence_text`` entails ``claim``.

        ``overlap`` / ``coverage`` are precomputed lexical-alignment signals
        from the verifier (shared term count and its ratio to claim terms), so
        a judge can stay cheap or ignore them and re-derive its own.
        """
        ...


def _has_negation(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _NEGATION_MARKERS)


def _numbers(text: str) -> list[str]:
    return _NUM_PATTERN.findall(text)


def _polarity_conflict(claim: str, evidence_text: str) -> bool:
    """True when claim and evidence sit on opposite sides of an antonym pair."""
    claim_l, ev_l = claim.lower(), evidence_text.lower()
    for left, right in _POLARITY_PAIRS:
        if (left in claim_l and right in ev_l) or (right in claim_l and left in ev_l):
            return True
    return False


def _numeric_conflict(claim: str, evidence_text: str) -> bool:
    """True when the claim asserts a number the well-aligned evidence omits.

    Conservative: only fires when the claim carries numbers, the evidence
    carries numbers too, and *none* of the claim's numbers appear in the
    evidence. Pure prose claims (no numbers) never trigger this.
    """
    claim_nums = _numbers(claim)
    if not claim_nums:
        return False
    ev_nums = _numbers(evidence_text)
    if not ev_nums:
        return False
    return not (set(claim_nums) & set(ev_nums))


class HeuristicEntailmentJudge:
    """Deterministic, LLM-free three-way entailment judge.

    Decision order (first match wins):
      1. polarity conflict (antonym pair across claim/evidence) -> contradicted
      2. negation parity mismatch on well-aligned evidence       -> contradicted
      3. numeric conflict on well-aligned evidence               -> contradicted
      4. strong lexical coverage                                 -> entailed
      5. otherwise                                               -> not_enough_info

    A "contradicted" verdict requires the evidence to be *about the same thing*
    (decent overlap) — otherwise an unrelated negated sentence would spuriously
    flip an unrelated claim. That gate is the ``aligned`` check below.
    """

    name = "heuristic"

    def judge(
        self,
        claim: str,
        evidence_text: str,
        *,
        overlap: int,
        claim_term_count: int,
        coverage: float,
        source_type: str,
    ) -> EntailmentVerdict:
        if not evidence_text:
            return EntailmentVerdict(NOT_ENOUGH_INFO, 0.0, "no aligned evidence")
        support_threshold = max(2, min(5, claim_term_count // 3))
        coverage_threshold = 0.35 if source_type == "episode" else 0.45
        aligned = overlap >= max(2, support_threshold - 1) and coverage >= 0.25

        if aligned and _polarity_conflict(claim, evidence_text):
            return EntailmentVerdict(CONTRADICTED, 0.7, "polarity_conflict")
        if aligned and _has_negation(claim) != _has_negation(evidence_text):
            return EntailmentVerdict(CONTRADICTED, 0.6, "negation_mismatch")
        if aligned and _numeric_conflict(claim, evidence_text):
            return EntailmentVerdict(CONTRADICTED, 0.55, "numeric_conflict")
        if overlap >= support_threshold and coverage >= coverage_threshold:
            return EntailmentVerdict(
                ENTAILED, min(1.0, 0.5 + coverage / 2),
                f"overlap={overlap}/{claim_term_count}, coverage={coverage:.2f}",
            )
        return EntailmentVerdict(
            NOT_ENOUGH_INFO, 0.0,
            f"weak_alignment overlap={overlap}/{claim_term_count}, coverage={coverage:.2f}",
        )
