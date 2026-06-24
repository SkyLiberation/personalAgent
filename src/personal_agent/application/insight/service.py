"""Application use case for on-demand knowledge-gap inspection."""

from __future__ import annotations

from pydantic import BaseModel, Field

from personal_agent.application.insight.analyzer import KnowledgeGap, KnowledgeGapAnalyzer


class KnowledgeGapReport(BaseModel):
    user_id: str
    gaps: list[dict] = Field(default_factory=list)
    text: str


class KnowledgeGapUseCase:
    def __init__(self, analyzer: KnowledgeGapAnalyzer) -> None:
        self._analyzer = analyzer

    def inspect(self, user_id: str) -> KnowledgeGapReport:
        gaps = self._analyzer.detect(user_id)
        return KnowledgeGapReport(
            user_id=user_id,
            gaps=[_gap_payload(gap) for gap in gaps],
            text=format_knowledge_gaps(gaps),
        )


def format_knowledge_gaps(gaps: list[KnowledgeGap]) -> str:
    if not gaps:
        return "当前没有检测到明显的知识孤岛或潜在冲突。"
    lines = ["我在整理你的知识库时发现几个可以补充的地方："]
    lines.extend(f"{index}. {gap.question}" for index, gap in enumerate(gaps, start=1))
    return "\n".join(lines)


def _gap_payload(gap: KnowledgeGap) -> dict:
    return {
        "gap_type": gap.gap_type,
        "key": gap.key,
        "question": gap.question,
        "entities": list(gap.entities),
        "note_ids": list(gap.note_ids),
    }
