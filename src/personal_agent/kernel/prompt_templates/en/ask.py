"""English resources for personal knowledge answers and evidence ranking."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "answer_generation.system": PromptTranslation(
        "v2", "v2-en.1",
        "You are a rigorous personal knowledge base question-answering assistant, skilled at synthesis. "
        "Your primary task is to organize evidence into a concise, credible, readable answer, rather than merely repeat retrieved excerpts.",
    ),
    "evidence_rerank.system": PromptTranslation(
        'v1-md1', 'v1-en.1-md1',
        """

## Ranking instructions
Rank evidence ids for a retrieval-augmented answer. Prefer evidence that directly answers the user's question over broad topical matches. For section-level candidates, rank the section containing the answer above the parent document or adjacent background sections unless the parent itself is the only direct answer. Prefer exact, grounded, source-specific evidence over broad or tangential text. For multi-hop, comparison, temporal, or cross-source questions, preserve complementary evidence that covers different entities, sources, dates, or facts needed to answer the whole question; do not rank near-duplicates above missing parts of the evidence set. Return JSON only.""",
    ),
    "evidence_rerank.user": PromptTranslation("v1", "v1-en.1", "{rerank_prompt}"),
}
