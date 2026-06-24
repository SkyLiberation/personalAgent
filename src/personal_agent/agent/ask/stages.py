"""The three bounded ask stages: retrieval, generation, verification.

These map 1:1 onto the ``ask-retrieve`` / ``ask-compose`` / ``ask-verify``
workflow steps. Each stage reads from and writes to the shared
:class:`AskRunContext`. Heavy collaborator logic (prompt building, the verifier,
the retry loop) lives on :class:`AskService`; the stages orchestrate it.

The web fallback is no longer a copy-paste of the main path: it appends web
evidence to the pool, then re-runs context assembly + generation + one
verify/retry pass by reusing the same stage objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from personal_agent.kernel.evidence import ContextPack, apply_rrf_fusion, compress_evidence
from personal_agent.agent.runtime_helpers import _annotate_answer
from personal_agent.agent.ask.evidence_ops import dedupe_evidence, selected_citations, selected_matches
from personal_agent.agent.ask.retrievers import RetrievalCoordinator

if TYPE_CHECKING:
    from personal_agent.agent.runtime_ask import AskService
    from personal_agent.agent.ask.context import AskRunContext


class RetrievalStage:
    """ask-retrieve: query understanding → multi-source recall → candidate
    enrichment + rerank → ContextPack. Owns the single expensive retrieval pass."""

    def __init__(self, service: "AskService") -> None:
        self._service = service
        self._coordinator = RetrievalCoordinator(service)

    def run(self, ctx: "AskRunContext") -> None:
        svc = self._service
        # Routed through the service so a test monkeypatching
        # ``runtime_ask.plan_retrieval`` still takes effect.
        understanding, retrieval_plan = svc._plan_retrieval(ctx.question, ctx.structured_context)
        ctx.understanding = understanding
        ctx.retrieval_plan = retrieval_plan
        ctx.effective_query = retrieval_plan.query or ctx.question
        ctx.add_trace(
            f"QueryPlan: sources={retrieval_plan.sources} parallel={retrieval_plan.parallel} "
            f"rewrite={ctx.effective_query[:60]} freshness={understanding.needs_freshness} "
            f"graph_reasoning={understanding.needs_graph_reasoning} "
            f"episodic={understanding.needs_episodic_context} "
            f"filters={retrieval_plan.filters.model_dump(exclude_defaults=True)}"
        )

        self._coordinator.run(ctx)
        self._assemble_context(ctx)

    def _assemble_context(self, ctx: "AskRunContext") -> None:
        """Dedupe pool → enrich candidates → rerank into a ContextPack, then
        derive selected matches/citations. Reused by the web fallback."""
        svc = self._service
        ctx.evidence_pool = dedupe_evidence(ctx.evidence_pool)
        ctx.evidence_pool = apply_rrf_fusion(ctx.evidence_pool)
        fused = sum(1 for it in ctx.evidence_pool if it.metadata.get("consensus_count", 1) > 1)
        if fused:
            ctx.add_trace(f"RRF 融合: 多路共识证据 consensus_items={fused}")
        components = svc._ask_components
        enriched = components.candidate_enricher.enrich(
            ctx.effective_query,
            evidence=ctx.evidence_pool,
            matches=ctx.combined_matches,
            citations=ctx.combined_citations,
            store=svc.memory,
            filters=ctx.retrieval_plan.filters,
        )
        ctx.combined_matches = enriched.matches
        ctx.combined_citations = enriched.citations
        if enriched.added_note_ids:
            ctx.add_trace(
                f"CandidateEnricher({components.candidate_enricher.name}): "
                f"added={len(enriched.added_note_ids)}"
            )
        context_pack: ContextPack = components.reranker.rerank(
            ctx.effective_query,
            _compressed_evidence(ctx, enriched.evidence, components),
            max_items=components.context_max_items,
            char_budget=components.context_char_budget,
            mmr_lambda=components.context_mmr_lambda,
        )
        ctx.context_pack = context_pack
        selected_graph_items = [
            item for item in context_pack.evidence
            if item.source_type == "graph_fact"
            or item.metadata.get("retrieved_by") in {"graphiti", "structural"}
        ]
        ctx.add_trace(
            f"ContextPack({components.reranker.name}): "
            f"selected={len(context_pack.selected)} dropped={len(context_pack.dropped)} "
            f"graph_selected={len(selected_graph_items)} "
            f"chars={context_pack.used_chars}/{context_pack.char_budget}"
        )
        ctx.selected_matches = selected_matches(ctx.combined_matches, context_pack.evidence)
        ctx.selected_citations = selected_citations(ctx.combined_citations, context_pack.evidence)


def _compressed_evidence(ctx, evidence, components):
    """Extractive sentence-level compression before rerank.

    Trims long note/chunk snippets to their most question-relevant sentences so
    the char budget admits more distinct evidence. Disabled when
    ``context_compress_max_sentences <= 0``."""
    max_sentences = components.context_compress_max_sentences
    if max_sentences <= 0:
        return evidence
    compressed = compress_evidence(
        ctx.effective_query, evidence, max_sentences=max_sentences
    )
    trimmed = sum(1 for it in compressed if it.metadata.get("compressed_from_chars"))
    if trimmed:
        ctx.add_trace(f"ContextCompressor: 句级压缩 trimmed_snippets={trimmed}")
    return compressed


class GenerationStage:
    """ask-compose: pure generation from the assembled ContextPack."""

    def __init__(self, service: "AskService") -> None:
        self._service = service

    def run(self, ctx: "AskRunContext") -> None:
        ctx.answer = self._service._compose_unified_answer(
            ctx.question,
            ctx.context_pack,
            ctx.selected_matches,
            ctx.selected_citations,
            ctx.working_context,
        )


class VerificationStage:
    """ask-verify: verify + retry, optional web fallback (re-assemble + re-compose
    + re-verify), then annotate the answer when still insufficient."""

    def __init__(self, service: "AskService", retrieval_stage: "RetrievalStage") -> None:
        self._service = service
        self._retrieval = retrieval_stage
        self._generation = GenerationStage(service)

    def run(self, ctx: "AskRunContext") -> None:
        svc = self._service
        verification = svc._verifier.verify(
            ctx.question,
            ctx.answer,
            ctx.selected_citations,
            svc._match_refs(ctx.selected_matches),
            web_enabled=ctx.web_search_enabled_for_selected,
            evidence=ctx.context_pack.evidence,
            thread_id=ctx.thread_key,
            user_id=ctx.user_id,
        )
        if ctx.selected_matches or ctx.selected_citations:
            retry_result = svc._retry_if_needed(
                ctx.question,
                ctx.answer,
                ctx.selected_citations,
                ctx.selected_matches,
                verification,
                web_enabled=ctx.web_search_enabled_for_selected,
                evidence=ctx.context_pack.evidence,
            )
            ctx.answer = retry_result.answer
            verification = retry_result.verification
        ctx.verification = verification
        ctx.add_trace(f"Verifier: score={verification.evidence_score:.2f} ok={verification.ok}")

        if self._should_seek_contrast(svc, ctx, verification):
            verification = self._contrastive_pass(ctx, verification)

        if not verification.sufficient and not ctx.web_tried and svc._web_search_available:
            verification = self._web_fallback(ctx)

        if not verification.ok or not verification.sufficient:
            ctx.answer = _annotate_answer(ctx.answer, verification)

    @staticmethod
    def _should_seek_contrast(svc, ctx: "AskRunContext", verification) -> bool:
        if not getattr(svc.settings.ask, "contrastive_retrieval", False):
            return False
        if ctx.contrastive_tried:
            return False
        checks = getattr(verification, "claim_checks", None) or []
        return any(c.status in ("contradicted", "not_found") for c in checks)

    def _flagged_claims(self, verification) -> list[str]:
        checks = getattr(verification, "claim_checks", None) or []
        return [c.claim for c in checks if c.status in ("contradicted", "not_found")]

    def _contrastive_pass(self, ctx: "AskRunContext", verification):
        """Recall opposing evidence for flagged claims, re-assemble + re-compose
        + re-verify so the answer accounts for both sides."""
        svc = self._service
        claims = self._flagged_claims(verification)
        if not self._retrieval._coordinator.add_contrastive_evidence(ctx, claims):
            return verification
        self._retrieval._assemble_context(ctx)
        self._generation.run(ctx)
        verification = svc._verifier.verify(
            ctx.question,
            ctx.answer,
            ctx.selected_citations,
            svc._match_refs(ctx.selected_matches),
            web_enabled=ctx.web_search_enabled_for_selected,
            evidence=ctx.context_pack.evidence,
            thread_id=ctx.thread_key,
            user_id=ctx.user_id,
        )
        ctx.verification = verification
        ctx.add_trace(
            f"反证补充后 Verifier: score={verification.evidence_score:.2f} ok={verification.ok}"
        )
        return verification

    def _web_fallback(self, ctx: "AskRunContext"):
        """Append web evidence, then reuse assembly + generation + one verify/retry."""
        svc = self._service
        if not self._retrieval._coordinator.add_web_fallback(ctx):
            return ctx.verification
        self._retrieval._assemble_context(ctx)
        self._generation.run(ctx)
        verification = svc._verifier.verify(
            ctx.question,
            ctx.answer,
            ctx.selected_citations,
            svc._match_refs(ctx.selected_matches),
            web_enabled=True,
            evidence=ctx.context_pack.evidence,
            thread_id=ctx.thread_key,
            user_id=ctx.user_id,
        )
        retry_result = svc._retry_if_needed(
            ctx.question,
            ctx.answer,
            ctx.selected_citations,
            ctx.selected_matches,
            verification,
            web_enabled=True,
            evidence=ctx.context_pack.evidence,
        )
        ctx.answer = retry_result.answer
        verification = retry_result.verification
        ctx.verification = verification
        ctx.add_trace(
            f"网络补充后 Verifier: score={verification.evidence_score:.2f} ok={verification.ok}"
        )
        return verification
