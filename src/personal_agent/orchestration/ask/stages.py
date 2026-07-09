"""The bounded ask stages: retrieval, generation, verification, repair.

These map 1:1 onto the ``ask-retrieve`` / ``ask-compose`` / ``ask-verify`` /
``ask-repair`` workflow steps. Each stage reads from and writes to the shared
:class:`AskRunContext`. Heavy collaborator logic (prompt building, the verifier,
the retry loop) lives on :class:`AskService`; the stages orchestrate it.

The repair stage is a first-class workflow step: it appends contrastive or web
evidence to the pool, then re-runs context assembly + generation + one
verify/retry pass by reusing the same stage objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from personal_agent.application.evidence_engine import EvidenceAssemblyRequest
from personal_agent.orchestration.runtime_helpers import _annotate_answer
from personal_agent.orchestration.ask.context import AskRepairEvent
from personal_agent.orchestration.ask.retrievers import RetrievalCoordinator

if TYPE_CHECKING:
    from personal_agent.orchestration.runtime_ask import AskService
    from personal_agent.orchestration.ask.context import AskRunContext


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
        ctx.retrieval_health["pre_enrichment_match_ids"] = [
            match.id for match in ctx.combined_matches
        ]
        ctx.retrieval_health["pre_enrichment_citation_note_ids"] = [
            citation.note_id for citation in ctx.combined_citations if citation.note_id
        ]
        ctx.retrieval_health["pre_enrichment_evidence_ids"] = [
            item.source_id for item in ctx.evidence_pool
        ]
        self._assemble_context(ctx)

    def _assemble_context(self, ctx: "AskRunContext") -> None:
        """Dedupe pool → enrich candidates → rerank into a ContextPack, then
        derive selected matches/citations. Reused by the web fallback."""
        svc = self._service
        components = svc._ask_components
        assembled = svc.evidence_engine.assemble_context(EvidenceAssemblyRequest(
            question=ctx.effective_query,
            evidence=ctx.evidence_pool,
            matches=ctx.combined_matches,
            citations=ctx.combined_citations,
            store=svc.memory,
            filters=ctx.retrieval_plan.filters,
            candidate_enricher=components.candidate_enricher,
            reranker=components.reranker,
            max_items=components.context_max_items,
            char_budget=components.context_char_budget,
            mmr_lambda=components.context_mmr_lambda,
            compress_max_sentences=components.context_compress_max_sentences,
        ))
        ctx.evidence_pool = assembled.evidence
        ctx.combined_matches = assembled.matches
        ctx.combined_citations = assembled.citations
        ctx.context_pack = assembled.context_pack
        ctx.selected_matches = assembled.selected_matches
        ctx.selected_citations = assembled.selected_citations
        ctx.retrieval_health["post_enrichment_match_ids"] = [
            match.id for match in ctx.combined_matches
        ]
        ctx.retrieval_health["post_enrichment_citation_note_ids"] = [
            citation.note_id for citation in ctx.combined_citations if citation.note_id
        ]
        ctx.retrieval_health["post_enrichment_evidence_ids"] = [
            item.source_id for item in ctx.evidence_pool
        ]
        ctx.retrieval_health["context_selected_evidence_ids"] = [
            item.evidence.source_id for item in ctx.context_pack.selected
        ]
        ctx.retrieval_health["context_selected_evidence_lineage"] = [
            {
                **item.evidence.lineage,
                "metadata_artifact_id": item.evidence.metadata.get("artifact_id"),
                "retrieved_by": item.evidence.metadata.get("retrieved_by"),
                "candidate": item.evidence.metadata.get("candidate"),
                "fusion_rank": item.evidence.metadata.get("fusion_rank"),
                "fusion_score": item.evidence.metadata.get("fusion_score"),
                "fusion_components": item.evidence.metadata.get("fusion_components"),
            }
            for item in ctx.context_pack.selected
        ]
        ctx.retrieval_health["context_selected_match_ids"] = [
            match.id for match in ctx.selected_matches
        ]
        ctx.retrieval_health["context_selected_match_source_refs"] = [
            str(match.source.ref or "") for match in ctx.selected_matches
        ]
        ctx.retrieval_health["context_selected_citation_note_ids"] = [
            citation.note_id for citation in ctx.selected_citations if citation.note_id
        ]
        ctx.retrieval_health["context_selected_citation_source_refs"] = [
            str(citation.source_ref or "") for citation in ctx.selected_citations
        ]
        ctx.retrieval_health["context_dropped_evidence_ids"] = [
            item.evidence.source_id for item in ctx.context_pack.dropped
        ]
        ctx.retrieval_health["context_dropped_evidence_reasons"] = [
            {
                "source_id": item.evidence.source_id,
                "source_ref": item.evidence.source_ref,
                "parent_note_id": item.evidence.parent_note_id,
                "source_type": item.evidence.source_type,
                "drop_reason": item.drop_reason,
            }
            for item in ctx.context_pack.dropped
        ]
        for line in assembled.trace:
            ctx.add_trace(line)


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
    """ask-verify: verify + bounded retry only."""

    def __init__(self, service: "AskService") -> None:
        self._service = service

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
        ctx.repair.mark_verification(verification)
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
            ctx.repair.record_retry(retry_result.attempts)
            if retry_result.attempts:
                ctx.repair.mark_verification(verification)
        ctx.verification = verification
        ctx.add_trace(f"Verifier: score={verification.evidence_score:.2f} ok={verification.ok}")


class RepairStage:
    """ask-repair: explicit repair loop after ask-verify."""

    def __init__(self, service: "AskService", retrieval_stage: "RetrievalStage") -> None:
        self._service = service
        self._retrieval = retrieval_stage
        self._generation = GenerationStage(service)

    def run(self, ctx: "AskRunContext") -> None:
        verification = ctx.verification
        if verification is None:
            return
        if self._should_seek_contrast(self._service, ctx, verification):
            verification = self._contrastive_pass(ctx, verification)

        if (
            not verification.sufficient
            and not ctx.web_tried
            and self._service._web_search_available
            and self._should_use_web_fallback(ctx)
        ):
            verification = self._web_fallback(ctx)

        if verification is not None and (not verification.ok or not verification.sufficient):
            ctx.answer = _annotate_answer(ctx.answer, verification)

    @staticmethod
    def _should_seek_contrast(svc, ctx: "AskRunContext", verification) -> bool:
        if not getattr(svc.settings.ask, "contrastive_retrieval", False):
            return False
        if ctx.contrastive_tried:
            return False
        checks = getattr(verification, "claim_checks", None) or []
        return any(c.status in ("contradicted", "not_found") for c in checks)

    @staticmethod
    def _should_use_web_fallback(ctx: "AskRunContext") -> bool:
        understanding = ctx.understanding
        answer_policy = getattr(understanding, "answer_policy", "")
        if answer_policy == "refuse_if_insufficient":
            return False
        needs_freshness = bool(getattr(understanding, "needs_freshness", False))
        question = ctx.question.lower()
        personal_markers = (
            "我的",
            "我上次",
            "上次",
            "之前",
            "曾经",
            "记过",
            "保存",
            "知识库",
            "笔记",
            "personal",
            "my ",
        )
        if not needs_freshness and any(marker in question for marker in personal_markers):
            return False
        return True

    def _flagged_claims(self, verification) -> list[str]:
        checks = getattr(verification, "claim_checks", None) or []
        return [c.claim for c in checks if c.status in ("contradicted", "not_found")]

    def _contrastive_pass(self, ctx: "AskRunContext", verification):
        """Recall opposing evidence for flagged claims, re-assemble + re-compose
        + re-verify so the answer accounts for both sides."""
        svc = self._service
        claims = self._flagged_claims(verification)
        before_count = len(ctx.evidence_pool)
        score_before = float(getattr(verification, "evidence_score", 0.0) or 0.0)
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
        ctx.repair.mark_verification(verification)
        ctx.verification = verification
        ctx.repair.record_repair(AskRepairEvent(
            source="contrastive",
            reason="claim_contradicted_or_not_found",
            added_evidence_count=max(0, len(ctx.evidence_pool) - before_count),
            flagged_claim_count=len(claims),
            verification_score_before=score_before,
            verification_score_after=float(verification.evidence_score),
            ok_after=bool(verification.ok),
            sufficient_after=bool(verification.sufficient),
        ))
        ctx.add_trace(
            f"反证补充后 Verifier: score={verification.evidence_score:.2f} ok={verification.ok}"
        )
        return verification

    def _web_fallback(self, ctx: "AskRunContext"):
        """Append web evidence, then reuse assembly + generation + one verify/retry."""
        svc = self._service
        before_count = len(ctx.evidence_pool)
        score_before = float(getattr(ctx.verification, "evidence_score", 0.0) or 0.0)
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
        ctx.repair.mark_verification(verification)
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
        ctx.repair.record_retry(retry_result.attempts)
        if retry_result.attempts:
            ctx.repair.mark_verification(verification)
        ctx.verification = verification
        ctx.repair.record_repair(AskRepairEvent(
            source="web",
            reason="evidence_insufficient",
            added_evidence_count=max(0, len(ctx.evidence_pool) - before_count),
            retry_attempts=retry_result.attempts,
            verification_score_before=score_before,
            verification_score_after=float(verification.evidence_score),
            ok_after=bool(verification.ok),
            sufficient_after=bool(verification.sufficient),
        ))
        ctx.add_trace(
            f"网络补充后 Verifier: score={verification.evidence_score:.2f} ok={verification.ok}"
        )
        return verification
