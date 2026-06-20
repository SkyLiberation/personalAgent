"""Chunk quality scoring for the capture pipeline.

A chunk is a retrieval unit only if it carries self-contained, information-dense
content. Headers, footers, page numbers, navigation, and table-of-contents
fragments are structurally present but useless as evidence: scoring them low and
marking ``retrievable=False`` keeps them out of retrieval while preserving them
under the parent note for provenance.

The default scorer is deterministic and heuristic (no LLM), matching the
capture pipeline's no-LLM philosophy. ``ChunkQualityScorer`` is a Protocol so a
model-backed scorer can be plugged in later without touching the pipeline.
"""

from __future__ import annotations

import re
from typing import Protocol

from ..core.models import ChunkDraft

# Categories Unstructured assigns to non-content structural elements.
_NOISE_CATEGORIES = frozenset({
    "Header", "Footer", "PageNumber", "PageBreak", "UncategorizedText",
})
# Lines that are almost always navigation / boilerplate rather than knowledge.
_NOISE_PATTERNS = (
    re.compile(r"^\s*page\s+\d+\s*(of\s+\d+)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*$"),
    re.compile(r"^\s*(table of contents|目录|contents)\s*$", re.IGNORECASE),
    re.compile(r"^\s*(copyright|©|\(c\))", re.IGNORECASE),
)

# Below this score a chunk is dropped from retrieval units.
RETRIEVABLE_THRESHOLD = 0.35


class ChunkQualityScorer(Protocol):
    """Scores a chunk's fitness as a retrieval unit in [0, 1]."""

    def score(self, draft: ChunkDraft) -> float:
        ...


class HeuristicChunkQualityScorer:
    """Deterministic density/noise scorer; no model calls."""

    name = "heuristic"

    def score(self, draft: ChunkDraft) -> float:
        text = (draft.content or "").strip()
        if not text:
            return 0.0

        score = 0.5
        if draft.category in _NOISE_CATEGORIES:
            score -= 0.35
        for pattern in _NOISE_PATTERNS:
            if pattern.match(text):
                score -= 0.4
                break

        length = len(text)
        if length >= 200:
            score += 0.25
        elif length >= 80:
            score += 0.12
        elif length < 20:
            score -= 0.25

        # Information density: ratio of distinct word-ish tokens to total length.
        tokens = re.findall(r"[\w㐀-鿿]+", text)
        if tokens:
            distinct_ratio = len(set(tokens)) / len(tokens)
            score += 0.1 * distinct_ratio
        # Mostly punctuation/whitespace -> noise.
        alnum = sum(1 for ch in text if ch.isalnum())
        if alnum / max(length, 1) < 0.3:
            score -= 0.2

        return max(0.0, min(score, 1.0))


def score_drafts(
    drafts: list[ChunkDraft],
    scorer: ChunkQualityScorer | None = None,
) -> list[tuple[ChunkDraft, float, bool]]:
    """Return (draft, score, retrievable) triples for a list of drafts."""
    active = scorer or HeuristicChunkQualityScorer()
    out: list[tuple[ChunkDraft, float, bool]] = []
    for draft in drafts:
        value = active.score(draft)
        out.append((draft, value, value >= RETRIEVABLE_THRESHOLD))
    return out
