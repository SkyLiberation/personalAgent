from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS: dict[str, PromptSpec] = {
    "answer_generation.system": PromptSpec(
        name="answer_generation.system",
        version="v2",
        output_contract="free_text",
        template=(
            "你是一个严谨、善于归纳总结的个人知识库问答助手。"
            "你的首要任务不是复述检索片段，而是把证据整理成简洁、可信、可读的答案。"
        ),
    ),
    "evidence_rerank.system": PromptSpec(
        name="evidence_rerank.system",
        version="v1",
        output_contract="EvidenceRerank",
        template=(
            "Rank evidence ids for a retrieval-augmented answer. "
            "Prefer evidence that directly answers the user's question over broad topical matches. "
            "For section-level candidates, rank the section containing the answer above the parent "
            "document or adjacent background sections unless the parent itself is the only direct answer. "
            "Prefer exact, grounded, source-specific evidence over broad or tangential text. "
            "For multi-hop, comparison, temporal, or cross-source questions, preserve complementary "
            "evidence that covers different entities, sources, dates, or facts needed to answer the "
            "whole question; do not rank near-duplicates above missing parts of the evidence set. "
            "Return JSON only."
        ),
    ),
    "evidence_rerank.user": PromptSpec(
        name="evidence_rerank.user",
        version="v1",
        output_contract="EvidenceRerank",
        template="{rerank_prompt}",
    ),
}
