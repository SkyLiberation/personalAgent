from __future__ import annotations

from personal_agent.agent.chunk_quality import (
    RETRIEVABLE_THRESHOLD,
    HeuristicChunkQualityScorer,
    score_drafts,
)
from personal_agent.core.models import ChunkDraft


def _draft(content: str, *, category: str = "NarrativeText") -> ChunkDraft:
    return ChunkDraft(title="t", content=content, source_span="s", category=category)


class TestHeuristicChunkQualityScorer:
    def test_dense_narrative_is_retrievable(self):
        scorer = HeuristicChunkQualityScorer()
        text = (
            "Redis stores hot order data in memory and reduces database "
            "pressure by absorbing read traffic for frequently accessed keys."
        )
        assert scorer.score(_draft(text)) >= RETRIEVABLE_THRESHOLD

    def test_page_number_noise_is_dropped(self):
        scorer = HeuristicChunkQualityScorer()
        assert scorer.score(_draft("Page 12 of 340")) < RETRIEVABLE_THRESHOLD

    def test_header_category_penalized(self):
        scorer = HeuristicChunkQualityScorer()
        assert scorer.score(_draft("Confidential", category="Header")) < RETRIEVABLE_THRESHOLD

    def test_empty_is_zero(self):
        assert HeuristicChunkQualityScorer().score(_draft("   ")) == 0.0

    def test_score_drafts_marks_retrievable_flag(self):
        drafts = [
            _draft("A well formed sentence carrying real information about a topic."),
            _draft("3", category="PageNumber"),
        ]
        scored = score_drafts(drafts)
        assert scored[0][2] is True
        assert scored[1][2] is False
