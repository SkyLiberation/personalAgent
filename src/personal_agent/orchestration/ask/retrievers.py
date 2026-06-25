"""Unified retriever interface for the ask retrieval layer.

Each retriever wraps one recall source and returns a uniform
:class:`RetrievalContribution`. This collapses the six near-identical inline
``if use_x: ... extend ... add_trace`` blocks that previously lived in
``execute_ask`` into one ``retrieve`` contract, and lets the
:class:`RetrievalCoordinator` drive routing / parallelism / sub-queries.

The heavy provider logic (graph provider switching, structural retrieval, the
graphiti episode→note mapping, web search) still lives on ``AskService`` as
collaborator methods; retrievers hold a reference and call back into it. This
keeps behavior byte-for-byte equivalent — the blocks are *moved*, not rewritten.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from personal_agent.kernel.evidence import (
    EvidenceItem,
    episodes_to_evidence,
    graph_result_to_evidence,
    memory_items_to_evidence,
    notes_to_evidence,
    web_results_to_evidence,
)
from personal_agent.kernel.models import AgentState, Citation, KnowledgeNote
from personal_agent.kernel.query_understanding import RetrievalFilters
from personal_agent.governance.guardrails import get_content_guard
from personal_agent.orchestration.runtime_helpers import _merge_citations, _merge_notes
from personal_agent.orchestration.ask.evidence_ops import graph_matches_to_evidence

if TYPE_CHECKING:
    from personal_agent.orchestration.runtime_ask import AskService
    from personal_agent.orchestration.ask.context import AskRunContext

logger = logging.getLogger(__name__)


@dataclass
class RetrievalContribution:
    """Uniform output of any retriever."""

    evidence: list[EvidenceItem] = field(default_factory=list)
    matches: list[KnowledgeNote] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    # Name of the retrieval path; used as the RRF source key when an evidence
    # item carries no finer-grained ``retrieved_by`` (e.g. local/episodic).
    source: str = ""


class Retriever(Protocol):
    name: str

    def retrieve(
        self,
        query: str,
        filters: RetrievalFilters,
        ctx: "AskRunContext",
    ) -> RetrievalContribution:
        ...


class GraphRetriever:
    """Graph recall (Graphiti / structural / hybrid), incl. AgentState vs
    GraphAskResult dual-shape handling that used to be inline in execute_ask."""

    name = "graph"

    def __init__(self, service: "AskService") -> None:
        self._service = service

    def retrieve(self, query, filters, ctx, *, gate_evidence: bool = True) -> RetrievalContribution:
        svc = self._service
        provider = svc.settings.ask.graph_provider.strip().lower()
        graph_result = svc._run_graph_retrieval(
            provider, query, ctx.user_id, ctx.trace_id, filters,
        )
        return self._process(query, ctx.user_id, graph_result, filters, provider, gate_evidence)

    def _process(self, query, user_id, graph_result, filters, provider, gate_evidence) -> RetrievalContribution:
        svc = self._service
        out = RetrievalContribution(source=self.name)
        if isinstance(graph_result, AgentState):
            out.matches = _merge_notes([], graph_result.matches)
            out.citations = _merge_citations([], graph_result.citations)
            out.evidence.extend(graph_result.evidence)
            if gate_evidence:
                retrieved_by = sorted({
                    item.metadata.get("retrieved_by")
                    for item in graph_result.evidence
                    if item.metadata.get("retrieved_by")
                })
                provider_label = "+".join(retrieved_by) if retrieved_by else provider
                out.trace.append(
                    f"{provider_label} 候选已进入统一证据池 matches={len(graph_result.matches)} "
                    f"citations={len(graph_result.citations)} evidence={len(graph_result.evidence)}"
                )
            return out
        if graph_result and graph_result.enabled is True:
            matches, citations = svc._graph_matches_and_citations(
                user_id, query, graph_result, filters,
            )
            notes_by_episode = {
                n.graph.episode_uuid: n for n in matches if n.graph.episode_uuid is not None
            }
            # Sub-query expansion (gate_evidence=False) skips the _graph_has_evidence
            # gate and the per-source trace lines, matching the original inline path.
            if filters.active() and not matches and not citations:
                if gate_evidence:
                    out.trace.append("图谱结果未通过 metadata filters，已跳过")
            elif not gate_evidence or svc._graph_has_evidence(graph_result, matches, citations):
                out.matches = _merge_notes([], matches)
                out.citations = _merge_citations([], citations)
                out.evidence.extend(graph_result_to_evidence(graph_result, notes_by_episode, query))
                graph_note_evidence = graph_matches_to_evidence(
                    query, matches, citations,
                    mode=svc.settings.ask.graph_note_evidence_mode,
                    min_overlap=svc.settings.ask.graph_note_evidence_min_overlap,
                )
                out.evidence.extend(graph_note_evidence)
                if gate_evidence:
                    out.trace.append(
                        f"图谱候选已进入统一证据池 matches={len(matches)} citations={len(citations)} "
                        f"evidence={len(graph_note_evidence)}"
                    )
            elif gate_evidence:
                out.trace.append("图谱未返回可回答证据")
        return out


class LocalRetriever:
    name = "local"

    def __init__(self, service: "AskService") -> None:
        self._service = service

    def retrieve(self, query, filters, ctx) -> RetrievalContribution:
        state = self._service._run_local_retrieval(query, ctx.user_id, filters)
        out = RetrievalContribution(source=self.name)
        if state:
            out.matches = _merge_notes([], state.matches)
            out.citations = _merge_citations([], state.citations)
            out.evidence.extend(notes_to_evidence(state.matches))
            out.trace.append(
                f"本地候选已进入统一证据池 matches={len(state.matches)} "
                f"citations={len(state.citations)}"
            )
        else:
            out.trace.append("本地检索未返回可回答证据")
        return out


class EpisodicRetriever:
    name = "episodic"

    def __init__(self, service: "AskService") -> None:
        self._service = service

    def retrieve(self, query, filters, ctx) -> RetrievalContribution:
        svc = self._service
        out = RetrievalContribution(source=self.name)
        episodes = svc.memory.search_episodes(
            ctx.user_id, query, limit=5, session_id=ctx.session_id,
        )
        if not episodes:
            episodes = svc.memory.search_episodes(ctx.user_id, query, limit=5)
        if episodes:
            out.evidence.extend(episodes_to_evidence(episodes))
            out.trace.append(f"历史执行记录已进入统一证据池 episodes={len(episodes)}")
        else:
            out.trace.append("历史执行记录未返回可回答证据")
        return out


class ReflectionRetriever:
    name = "reflection"

    def __init__(self, service: "AskService") -> None:
        self._service = service

    def retrieve(self, query, filters, ctx) -> RetrievalContribution:
        svc = self._service
        out = RetrievalContribution(source=self.name)
        cfg = svc.settings.reflection_replay
        if not cfg.enabled:
            return out
        try:
            reflections = svc.memory.search_memory_items(
                ctx.user_id, query,
                memory_type="reflection",
                status=["candidate", "confirmed"],
                limit=cfg.max_items,
            )
        except Exception:
            reflections = []
        reflections = [item for item in reflections if item.confidence >= cfg.min_confidence]
        if reflections:
            out.evidence.extend(memory_items_to_evidence(reflections))
            out.trace.append(f"历史反思已进入统一证据池 reflections={len(reflections)}")
        return out


class WebRetriever:
    """Proactive + fallback web recall. The original question (not the rewritten
    query) is searched, matching prior behavior."""

    name = "web"

    def __init__(self, service: "AskService") -> None:
        self._service = service

    @property
    def available(self) -> bool:
        return self._service._web_search_available

    def retrieve(self, query, filters, ctx) -> RetrievalContribution:
        out = RetrievalContribution(source=self.name)
        if not self.available:
            return out
        web_results, web_citations = self._service._execute_web_search(ctx.question)
        if web_citations:
            out.citations = _merge_citations([], web_citations)
            guard = get_content_guard()
            out.evidence.extend(
                web_results_to_evidence(
                    web_results,
                    sanitize=lambda text: guard.sanitize_untrusted(text).text,
                )
            )
        return out


# Opposition cues appended to a claim to bias recall toward counter-evidence.
_CONTRAST_CUES = ("反对", "缺点", "风险", "局限", "例外", "争议", "失败", "问题")

# Strip leading verbs / fillers that add no recall signal but dilute the query.
_CLAIM_STOP = ("因此", "所以", "因为", "这", "那", "我们", "可以", "应该", "需要")


def _claim_core_terms(claim: str, limit: int = 40) -> str:
    """Reduce a claim sentence to a compact query string for counter-recall.

    Cheap and deterministic: drop citation markers and a few leading discourse
    fillers, then truncate. Good enough to seed an opposition query without a
    tokenizer dependency."""
    import re as _re

    text = _re.sub(r"\[[Ee]?\d+\]", "", claim).strip(" -:：\t\r")
    for stop in _CLAIM_STOP:
        if text.startswith(stop):
            text = text[len(stop):].strip()
    return text[:limit]


class ContrastiveRetriever:
    """Actively recall *opposing* evidence for the claims an answer makes.

    Standard retrieval is relevance-driven and tends to return evidence that
    agrees with the query, so a one-sided answer looks well-grounded. This
    retriever rewrites each flagged claim into opposition-biased sub-queries
    (claim core terms + contrast cues like 反对/风险/例外) and pulls whatever
    local — and optionally web — notes come back, tagging them
    ``retrieved_by="contrastive"`` so the verifier sees both sides.

    It does NOT implement the bare ``retrieve(query, filters, ctx)`` contract —
    it needs the claim list — so the coordinator drives it via
    :meth:`retrieve_for_claims` rather than the generic dispatch loop.
    """

    name = "contrastive"

    def __init__(self, service: "AskService") -> None:
        self._service = service

    def _queries(self, claims: list[str], max_claims: int) -> list[str]:
        queries: list[str] = []
        for claim in claims[:max_claims]:
            core = _claim_core_terms(claim)
            for cue in _CONTRAST_CUES[:2]:
                queries.append(f"{core} {cue}".strip())
        return queries

    def retrieve_for_claims(
        self, claims: list[str], filters, ctx: "AskRunContext", *, max_claims: int = 3,
    ) -> RetrievalContribution:
        out = RetrievalContribution(source=self.name)
        if not claims:
            return out
        seen_ids = {item.source_id for item in ctx.evidence_pool}
        for query in self._queries(claims, max_claims):
            state = self._service._run_local_retrieval(query, ctx.user_id, filters)
            if not state or not state.matches:
                continue
            fresh = [note for note in state.matches if note.id not in seen_ids]
            if not fresh:
                continue
            for note in fresh:
                seen_ids.add(note.id)
            evidence = notes_to_evidence(fresh)
            for item in evidence:
                item.metadata["retrieved_by"] = "contrastive"
                item.metadata["contrastive_query"] = query
            out.evidence.extend(evidence)
            out.matches = _merge_notes(out.matches, fresh)
        if out.evidence:
            out.trace.append(
                f"反证检索候选已进入统一证据池 queries={len(self._queries(claims, max_claims))} "
                f"counter_evidence={len(out.evidence)}"
            )
        return out


class RetrievalCoordinator:
    """Drives the retrieval layer: routing, graph+local parallelism, sub-query
    expansion. Merges every contribution into the run context's evidence pool."""

    def __init__(self, service: "AskService") -> None:
        self._service = service
        self.graph = GraphRetriever(service)
        self.local = LocalRetriever(service)
        self.episodic = EpisodicRetriever(service)
        self.reflection = ReflectionRetriever(service)
        self.web = WebRetriever(service)
        self.contrastive = ContrastiveRetriever(service)

    def _absorb(self, ctx: "AskRunContext", contrib: RetrievalContribution) -> None:
        # Tag each evidence item with its rank *within this source's* ranked
        # contribution, keyed by the source that produced it. Dedup later merges
        # these per-source ranks so apply_rrf_fusion can reward cross-source
        # consensus. Rank is 1-based; contributions arrive already ordered.
        for rank, item in enumerate(contrib.evidence, start=1):
            source = item.metadata.get("retrieved_by") or contrib.source or "unknown"
            source_ranks = dict(item.metadata.get("source_ranks") or {})
            source_ranks.setdefault(source, rank)
            item.metadata["source_ranks"] = source_ranks
        ctx.combined_matches = _merge_notes(ctx.combined_matches, contrib.matches)
        ctx.combined_citations = _merge_citations(ctx.combined_citations, contrib.citations)
        ctx.evidence_pool.extend(contrib.evidence)
        for line in contrib.trace:
            ctx.add_trace(line)

    def run(self, ctx: "AskRunContext") -> None:
        plan = ctx.retrieval_plan
        assert plan is not None
        query = ctx.effective_query
        filters = plan.filters
        use_graph = "graph" in plan.sources
        use_local = "local" in plan.sources
        use_web_proactive = "web" in plan.sources

        # Fetch graph + local. When planned, fetch concurrently — but absorb in a
        # fixed order (graph → sub-query → local → ...) so the evidence pool order
        # (and thus dedup / rerank tie-breaking) is identical to the prior inline
        # flow regardless of parallelism.
        graph_contrib: RetrievalContribution | None = None
        local_contrib: RetrievalContribution | None = None
        if plan.parallel and use_graph and use_local:
            with ThreadPoolExecutor(max_workers=2) as pool:
                graph_future = pool.submit(self.graph.retrieve, query, filters, ctx)
                local_future = pool.submit(self.local.retrieve, query, filters, ctx)
                graph_contrib = graph_future.result(timeout=60)
                local_contrib = local_future.result(timeout=30)
            parallel_done = True
        else:
            if use_graph:
                graph_contrib = self.graph.retrieve(query, filters, ctx)
            if use_local:
                local_contrib = self.local.retrieve(query, filters, ctx)
            parallel_done = False

        if parallel_done:
            ctx.add_trace("并行检索完成 (graph + local)")
        if graph_contrib is not None:
            self._absorb(ctx, graph_contrib)

        # --- sub-query expansion (graph only, matching prior behavior) ---
        for sub_q in plan.sub_queries:
            if use_graph:
                self._absorb(ctx, self.graph.retrieve(sub_q, filters, ctx, gate_evidence=False))
            ctx.add_trace(f"子查询检索已进入统一证据池: {sub_q[:40]}")

        if local_contrib is not None:
            self._absorb(ctx, local_contrib)

        # --- episodic / reflection / proactive web ---
        if ctx.understanding and ctx.understanding.needs_episodic_context:
            self._absorb(ctx, self.episodic.retrieve(query, filters, ctx))

        self._absorb(ctx, self.reflection.retrieve(query, filters, ctx))

        if use_web_proactive and self.web.available:
            ctx.web_tried = True
            contrib = self.web.retrieve(query, filters, ctx)
            if contrib.citations:
                self._absorb(ctx, contrib)
                ctx.add_trace(
                    f"主动网络搜索候选已进入统一证据池 citations={len(contrib.citations)}"
                )

    def add_web_fallback(self, ctx: "AskRunContext") -> bool:
        """Append web evidence to the pool for the verification-stage fallback.

        Returns True when web citations were added."""
        ctx.web_tried = True
        contrib = self.web.retrieve(ctx.effective_query, ctx.retrieval_plan.filters, ctx)
        if not contrib.citations:
            return False
        self._absorb(ctx, contrib)
        ctx.add_trace(
            f"知识库证据不足，网络搜索候选已进入统一证据池 citations={len(contrib.citations)}"
        )
        return True

    def add_contrastive_evidence(self, ctx: "AskRunContext", claims: list[str]) -> bool:
        """Append opposing evidence for ``claims`` to the pool (reactive hook
        for the verification stage). Returns True when counter-evidence landed."""
        ctx.contrastive_tried = True
        contrib = self.contrastive.retrieve_for_claims(
            claims, ctx.retrieval_plan.filters, ctx,
        )
        if not contrib.evidence:
            return False
        self._absorb(ctx, contrib)
        return True
