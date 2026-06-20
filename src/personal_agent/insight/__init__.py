"""Knowledge gap detection and proactive follow-up.

This package gives the agent a way to *look back at what it knows* and notice
gaps — entities that are mentioned but poorly connected (knowledge islands) and
notes that appear to contradict each other. Detected gaps are turned into a
single proactive question delivered over the existing review-digest channel, so
the user can answer and have that answer captured back into the knowledge base.

The detection itself is deterministic (graph topology degree analysis + note
polarity comparison); only the optional question phrasing may use an LLM. This
keeps the project's "code controls execution, LLM handles open semantics"
boundary intact.
"""

from .analyzer import KnowledgeGap, KnowledgeGapAnalyzer
from .job import (
    KnowledgeGapJob,
    KnowledgeGapJobResult,
    KnowledgeGapJobRunner,
    KnowledgeGapScheduler,
)

__all__ = [
    "KnowledgeGap",
    "KnowledgeGapAnalyzer",
    "KnowledgeGapJob",
    "KnowledgeGapJobResult",
    "KnowledgeGapJobRunner",
    "KnowledgeGapScheduler",
]
