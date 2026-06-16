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

from ...core.evidence import (
    EvidenceItem,
    episodes_to_evidence,
    graph_result_to_evidence,
    memory_items_to_evidence,
    notes_to_evidence,
    web_results_to_evidence,
)
from ...core.models import AgentState, Citation, KnowledgeNote
from ...core.query_understanding import RetrievalFilters
from ...graphiti.store import GraphAskResult
from ..runtime_helpers import _merge_citations, _merge_notes
from .evidence_ops import graph_matches_to_evidence

if TYPE_CHECKING:
    from ..runtime_ask import AskService
    from .context import AskRunContext

logger = logging.getLogger(__name__)


@dataclass
class RetrievalContribution:
    """Uniform output of any retriever."""

    evidence: list[EvidenceItem] = field(default_factory=list)
    matches: list[KnowledgeNote] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)


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
        out = RetrievalContribution()
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
        out = RetrievalContribution()
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
        out = RetrievalContribution()
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
        out = RetrievalContribution()
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
        out = RetrievalContribution()
        if not self.available:
            return out
        web_results, web_citations = self._service._execute_web_search(ctx.question)
        if web_citations:
            out.citations = _merge_citations([], web_citations)
            out.evidence.extend(web_results_to_evidence(web_results))
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

    def _absorb(self, ctx: "AskRunContext", contrib: RetrievalContribution) -> None:
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
