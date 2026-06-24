"""Heuristic pattern sets for content guards (prompt-injection + PII).

Kept separate from the engine so the rule corpus can grow (or be swapped for an
LLM/moderation backend) without touching evaluation logic. Patterns are bilingual
(English + Chinese) since the product is Chinese-first.
"""

from __future__ import annotations

import re

# --- Prompt-injection / jailbreak markers -------------------------------------
# Phrases an attacker uses to override the system prompt or exfiltrate it.
_INJECTION_SOURCES: tuple[str, ...] = (
    r"ignore\s+(?:all\s+|the\s+)?(?:previous|above|prior|earlier)\s+(?:instructions?|prompts?|messages?)",
    r"disregard\s+(?:all\s+|the\s+)?(?:previous|above|prior|earlier)\b",
    r"forget\s+(?:everything|all|the\s+above|previous\s+instructions?)",
    r"reveal\s+(?:your\s+|the\s+)?(?:system\s+)?prompt",
    r"(?:print|show|repeat)\s+(?:your\s+|the\s+)?(?:system\s+)?(?:prompt|instructions?)",
    r"you\s+are\s+now\s+(?:a|an|the)\b",
    r"developer\s+mode",
    r"do\s+anything\s+now",
    # Chinese
    r"忽略(?:以上|之前|前面|上述|先前)(?:的)?(?:所有)?(?:指令|提示|要求|对话|内容)",
    r"无视(?:以上|之前|前面|上述)(?:的)?(?:所有)?(?:指令|提示|要求)",
    r"忘(?:记|掉)(?:之前|以上|前面|所有)",
    r"(?:泄露|显示|输出|告诉我)(?:你的)?(?:系统)?(?:提示词|提示语|prompt|指令)",
    r"现在(?:你|您)(?:是|将扮演|来扮演)",
    r"进入开发者模式",
)
INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(src, re.IGNORECASE) for src in _INJECTION_SOURCES
)

# --- PII patterns -------------------------------------------------------------
# (category, pattern). Order matters: more specific before generic.
_PII_SOURCES: tuple[tuple[str, str], ...] = (
    ("api_key", r"\b(?:sk|pk|ghp|gho|xox[bpars])[-_][A-Za-z0-9]{16,}\b"),
    ("email", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    ("id_card", r"\b\d{17}[\dXx]\b"),
    ("credit_card", r"\b(?:\d[ -]?){15,16}\b"),
    ("phone_cn", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
)
PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(src)) for name, src in _PII_SOURCES
)

# Replacement marker for a neutralized injection phrase.
INJECTION_PLACEHOLDER = "[已移除疑似注入指令]"


def pii_placeholder(category: str) -> str:
    return f"[REDACTED:{category}]"


__all__ = [
    "INJECTION_PATTERNS",
    "INJECTION_PLACEHOLDER",
    "PII_PATTERNS",
    "pii_placeholder",
]
