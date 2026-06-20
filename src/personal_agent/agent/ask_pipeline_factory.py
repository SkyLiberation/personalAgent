from __future__ import annotations

from dataclasses import dataclass

from ..core.config import Settings
from ..core.candidate_enrichers import CandidateEnricher, create_candidate_enricher
from ..core.rerankers import EvidenceReranker, create_evidence_reranker


@dataclass(frozen=True)
class AskPipelineComponents:
    candidate_enricher: CandidateEnricher
    reranker: EvidenceReranker
    context_max_items: int
    context_char_budget: int
    context_mmr_lambda: float
    context_compress_max_sentences: int


class AskPipelineFactory:
    """Factory for swappable ask pipeline components.

    Runtime code should depend on this assembled component set instead of
    branching on individual config flags throughout the ask flow.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create(self) -> AskPipelineComponents:
        return AskPipelineComponents(
            candidate_enricher=create_candidate_enricher(self.settings),
            reranker=create_evidence_reranker(self.settings),
            context_max_items=self.settings.ask.context_max_items,
            context_char_budget=self.settings.ask.context_char_budget,
            context_mmr_lambda=self.settings.ask.context_mmr_lambda,
            context_compress_max_sentences=self.settings.ask.context_compress_max_sentences,
        )
