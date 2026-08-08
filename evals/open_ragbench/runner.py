"""Run Open RAGBench retrieval evaluations across comparable strategies."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from openai import OpenAI
from pydantic import BaseModel, Field, model_validator

from personal_agent.kernel.config import Settings
from personal_agent.kernel.models import KnowledgeNote
from personal_agent.kernel.graph_results import GraphRetrievalResult
from personal_agent.memory.graphiti.store import GraphitiStore
from personal_agent.memory.graphiti.search_strategies import STRATEGIES

from evals.shared_evidence_selector import (
    EvidenceUnit,
    SharedEvidencePolicy,
    SharedEvidenceSelectorConfig,
    apply_shared_evidence_policy,
    prepare_shared_evidence_corpus,
    select_shared_evidence,
    select_shared_evidence_policies,
)

from .adapter import CorpusNoteMode, corpus_to_edges, corpus_to_notes, expected_episode, expected_note_ids
from .loader import CorpusMode, RAGBenchDoc, RAGBenchQuery, load_benchmark
from .metrics import RetrievalReport, compute_report


class BenchmarkStrategy(Protocol):
    name: str
    description: str

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: "BenchmarkContext",
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        ...


@dataclass(frozen=True)
class BenchmarkContext:
    settings: Settings
    graphiti_user_id: str
    reset_graphiti: bool
    graphiti_manifest_path: Path | None
    graphiti_note_mode: CorpusNoteMode
    graphiti_continue_on_ingest_error: bool
    local_probe_limit: int = 100
    eval_snapshots: dict[str, list[dict]] | None = None
    planner_cache: dict[str, tuple[object, object]] | None = None
    strategy_configs: dict[str, dict[str, object]] = field(default_factory=dict)
    passage_embedding_cache: dict[str, list[float]] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkRunResult:
    strategy: str
    description: str
    report: RetrievalReport
    elapsed_seconds: float
    num_docs: int
    num_queries: int
    corpus_mode: str
    diagnostics: list[dict] | None = None
    diagnostic_summary: dict | None = None
    strategy_version: str = ""
    strategy_config: dict[str, object] | None = None

    def as_dict(self) -> dict:
        payload = {
            "strategy": self.strategy,
            "strategy_version": self.strategy_version,
            "description": self.description,
            "elapsed_seconds": self.elapsed_seconds,
            "num_docs": self.num_docs,
            "num_queries": self.num_queries,
            "corpus_mode": self.corpus_mode,
            "metrics": self.report.as_dict(),
        }
        if self.strategy_config is not None:
            payload["strategy_config"] = self.strategy_config
        if self.diagnostic_summary is not None:
            payload["diagnostic_summary"] = self.diagnostic_summary
        if self.diagnostics is not None:
            payload["diagnostics"] = self.diagnostics
        return payload


@dataclass(frozen=True)
class RetrievalStrategyProfile:
    """Dataset/task-level switches for retrieval eval strategy composition."""

    name: str
    description: str
    doc_first_enabled: bool = False
    doc_first_weight: float = 0.0
    slot_refine_enabled: bool = False
    sentence_selector_enabled: bool = False
    policy_selector_enabled: bool = False
    group_prior_enabled: bool = False


OPEN_RAGBENCH_PROFILE = RetrievalStrategyProfile(
    name="open_ragbench",
    description="Paper parent/section retrieval profile with doc-first and same-doc slot refinement.",
    doc_first_enabled=True,
    doc_first_weight=0.2,
    slot_refine_enabled=True,
    group_prior_enabled=True,
)

GALILEO_RAGBENCH_PROFILE = RetrievalStrategyProfile(
    name="galileo_ragbench",
    description="Sentence/support-utilization profile; disables Open-specific doc/section priors.",
    doc_first_enabled=False,
    doc_first_weight=0.0,
    slot_refine_enabled=False,
    sentence_selector_enabled=True,
    policy_selector_enabled=True,
)

DATASET_AGNOSTIC_PROFILE = RetrievalStrategyProfile(
    name="dataset_agnostic",
    description="Dataset-agnostic evidence profile using embedding plus passage/sentence selectors.",
    doc_first_enabled=False,
    doc_first_weight=0.0,
    slot_refine_enabled=False,
    sentence_selector_enabled=True,
    policy_selector_enabled=True,
)


def resolve_retrieval_strategy_profile(
    *,
    benchmark: str | None = None,
    task_type: str | None = None,
) -> RetrievalStrategyProfile:
    benchmark_key = (benchmark or "").strip().lower()
    task_key = (task_type or "").strip().lower()
    if benchmark_key == "open_ragbench":
        return OPEN_RAGBENCH_PROFILE
    if benchmark_key == "galileo_ragbench":
        return GALILEO_RAGBENCH_PROFILE
    if task_key in {"cross_doc_question", "generic_rag", "dataset_agnostic"}:
        return DATASET_AGNOSTIC_PROFILE
    return DATASET_AGNOSTIC_PROFILE


@dataclass(frozen=True)
class KeywordSearchStrategy:
    name: str = "keyword"
    description: str = "Deterministic offline keyword-overlap baseline."

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        all_notes = corpus_to_notes(docs)
        note_by_id = {note.id: note for note in all_notes}

        # Pre-compute haystacks once
        haystacks: dict[str, str] = {}
        for note in all_notes:
            haystacks[note.id] = f"{note.title} {note.summary} {note.content}".lower()

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            tokens = {token.lower() for token in query.query_text.split() if token.strip()}
            scored: list[tuple[int, str]] = []
            for note_id, haystack in haystacks.items():
                score = sum(1 for token in tokens if token in haystack)
                if score > 0:
                    scored.append((score, note_id))
            scored.sort(key=lambda item: item[0], reverse=True)

            seen_parents: set[str] = set()
            result_ids: list[str] = []
            for _, note_id in scored:
                if len(result_ids) >= limit * 2:
                    break
                note = note_by_id[note_id]
                pid = note.parent_note_id
                if pid is not None:
                    if pid in seen_parents:
                        continue
                    seen_parents.add(pid)
                    result_ids.append(note_id)
                    if pid not in result_ids:
                        result_ids.append(pid)
                else:
                    result_ids.append(note_id)

            rankings.append((query.query_id, result_ids[:limit]))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
        return rankings, relevance


@dataclass(frozen=True)
class CitationRerankStrategy:
    graph_strategy_name: str | None = None

    @property
    def name(self) -> str:
        if self.graph_strategy_name is None:
            return "citation_reranker"
        return f"citation_{self.graph_strategy_name}"

    @property
    def description(self) -> str:
        if self.graph_strategy_name is None:
            return "Standalone relation-fact citation reranker over section-shaped pseudo edges."
        graph_strategy = STRATEGIES[self.graph_strategy_name]
        return (
            f"{graph_strategy.description} Citation-only eval: this does not execute "
            "Graphiti retrieval, only the strategy citation ranking hook."
        )

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        edges, node_names = corpus_to_edges(docs)
        if self.graph_strategy_name is None:
            from personal_agent.memory.graphiti.reranker import rank_graph_citation_hits

            def citation_hits(question: str):
                return rank_graph_citation_hits(
                    question,
                    edges,
                    node_names,
                    limit=limit,
                )
        else:
            graph_strategy = STRATEGIES[self.graph_strategy_name]

            def citation_hits(question: str):
                return graph_strategy.citation_hits(
                    question,
                    edges,
                    node_names,
                )[:limit]

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            hits = citation_hits(query.query_text)
            rankings.append((query.query_id, [hit.episode_uuid for hit in hits]))
            relevance[query.query_id] = {expected_episode(query)}
        return rankings, relevance


@dataclass(frozen=True)
class StructuralRetrieverStrategy:
    name: str = "structural"
    description: str = (
        "Offline structural retriever baseline over a document-section graph with "
        "local section scoring and parent/sibling score propagation."
    )

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        graph = _build_structural_index(docs)

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            rankings.append((query.query_id, _rank_structural_notes(query.query_text, graph, limit=limit)))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
        return rankings, relevance


@dataclass(frozen=True)
class DocFirstSectionRerankStrategy:
    name: str = "doc_first_section"
    description: str = (
        "Offline two-stage baseline: rank documents first, then rerank sections "
        "within top documents. No graph/web/model calls."
    )
    top_docs: int = 5

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        graph = _build_structural_index(docs)

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            ranked = _rank_doc_first_sections(
                query.query_text,
                graph,
                limit=limit,
                top_docs=self.top_docs,
            )
            rankings.append((query.query_id, ranked))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "expected_note_ids": [section_id, parent_id],
                    "ranked_ids": ranked,
                    **_diagnose_retrieval(
                        section_id=section_id,
                        parent_id=parent_id,
                        ranked_ids=ranked,
                        local_probe_ids=ranked,
                        retrieval_health={},
                    ),
                },
            )
        return rankings, relevance


@dataclass(frozen=True)
class DocFirstFusionStrategy:
    name: str = "doc_first_fusion"
    description: str = (
        "Fusion baseline: keep Postgres local section retrieval, then add "
        "document-first structural ranking as a second RRF signal."
    )
    top_docs: int = 5
    external_embedding: bool = False
    profile: RetrievalStrategyProfile = OPEN_RAGBENCH_PROFILE
    doc_first_enabled: bool = True
    doc_first_weight: float = 0.2
    normalize_query: bool = False
    query_normalization_mode: str = "none"
    query_expansion_weight: float = 0.5
    section_refine: bool = False
    section_refine_mode: str = "lexical"
    section_refine_weight: float = 0.01
    section_refine_top_docs: int = 1

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        settings = _external_embedding_settings(context.settings) if self.external_embedding else context.settings
        store, _ = _new_eval_store(settings, docs)
        graph = _build_structural_index(docs)

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            normalization_mode = (
                "full" if self.normalize_query and self.query_normalization_mode == "none"
                else self.query_normalization_mode
            )
            effective_query = _normalized_query_for_mode(
                query.query_text,
                mode=normalization_mode,
            )
            candidate_limit = max(limit, context.local_probe_limit)
            if normalization_mode in {"yes_no_fusion", "yes_no_query_fusion"}:
                original_local_ids = _note_ids(store.find_similar_notes(
                    "ragbench_eval",
                    query.query_text,
                    limit=candidate_limit,
                ))
                expanded_query = _normalized_query_for_mode(query.query_text, mode="yes_no")
                expanded_local_ids = (
                    _note_ids(store.find_similar_notes(
                        "ragbench_eval",
                        expanded_query,
                        limit=candidate_limit,
                    ))
                    if expanded_query != query.query_text else []
                )
                local_ids = _fuse_ranked_ids(
                    original_local_ids,
                    expanded_local_ids,
                    limit=candidate_limit,
                    secondary_weight=self.query_expansion_weight,
                )
                if self.doc_first_enabled:
                    original_doc_first_ids = _rank_doc_first_sections(
                        query.query_text,
                        graph,
                        limit=candidate_limit,
                        top_docs=self.top_docs,
                    )
                    expanded_doc_first_ids = (
                        _rank_doc_first_sections(
                            expanded_query,
                            graph,
                            limit=candidate_limit,
                            top_docs=self.top_docs,
                        )
                        if expanded_query != query.query_text else []
                    )
                    doc_first_ids = _fuse_ranked_ids(
                        original_doc_first_ids,
                        expanded_doc_first_ids,
                        limit=candidate_limit,
                        secondary_weight=self.query_expansion_weight,
                    )
                else:
                    doc_first_ids = []
                effective_query = expanded_query
            else:
                local_ids = _note_ids(store.find_similar_notes(
                    "ragbench_eval",
                    effective_query,
                    limit=candidate_limit,
                ))
                doc_first_ids = (
                    _rank_doc_first_sections(
                        effective_query,
                        graph,
                        limit=candidate_limit,
                        top_docs=self.top_docs,
                    )
                    if self.doc_first_enabled else []
                )
            fusion_ranked = (
                _fuse_ranked_ids(
                    local_ids,
                    doc_first_ids,
                    limit=candidate_limit,
                    secondary_weight=self.doc_first_weight,
                )
                if self.doc_first_enabled
                else local_ids[:candidate_limit]
            )
            if self.section_refine and self.section_refine_mode == "passage_embedding":
                ranked = _refine_same_doc_sections_by_passage_embedding(
                    effective_query,
                    fusion_ranked,
                    graph,
                    settings=settings,
                    context=context,
                    limit=limit,
                    top_docs=self.section_refine_top_docs,
                    secondary_weight=self.section_refine_weight,
                )
            elif self.section_refine:
                ranked = _refine_same_doc_sections(
                    effective_query,
                    fusion_ranked,
                    graph,
                    limit=limit,
                    top_docs=self.section_refine_top_docs,
                    secondary_weight=self.section_refine_weight,
                )
            else:
                ranked = fusion_ranked[:limit]
            rankings.append((query.query_id, ranked))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "effective_query": effective_query,
                    "query_normalization_mode": normalization_mode,
                    "query_expansion_weight": self.query_expansion_weight,
                    "expected_note_ids": [section_id, parent_id],
                    "ranked_ids": ranked,
                    "fusion_before_section_refine_top20_ids": fusion_ranked[:20],
                    "strategy_profile": self.profile.name,
                    "doc_first_enabled": self.doc_first_enabled,
                    "doc_first_weight": self.doc_first_weight if self.doc_first_enabled else None,
                    "strategy_flags": _strategy_profile_flags(self.profile),
                    "section_refine_enabled": self.section_refine,
                    "section_refine_mode": self.section_refine_mode if self.section_refine else None,
                    "section_refine_weight": self.section_refine_weight if self.section_refine else None,
                    **_diagnose_retrieval(
                        section_id=section_id,
                        parent_id=parent_id,
                        ranked_ids=ranked,
                        local_probe_ids=local_ids,
                        retrieval_health={},
                    ),
                    "local_ids_top20": local_ids[:20],
                    "local_probe_top20_ids": local_ids[:20],
                    "doc_first_ids_top20": doc_first_ids[:20],
                    **_retrieval_eval_snapshot(store),
                    **_embedding_eval_snapshot(store),
                },
            )
        return rankings, relevance


@dataclass(frozen=True)
class SharedEvidenceSelectorStrategy:
    name: str = "ask_retrieve_shared_evidence_selector"
    description: str = (
        "Dataset-agnostic shared evidence selector over Open RAGBench notes: "
        "embedding-ranked candidates plus lexical/support evidence-unit scoring, "
        "with no doc-first, section-slot refinement, or yes/no expansion."
    )
    external_embedding: bool = True
    profile: RetrievalStrategyProfile = DATASET_AGNOSTIC_PROFILE
    embedding_weight: float = 1.0
    lexical_rrf_weight: float = 0.5
    lexical_weight: float = 0.30
    support_weight: float = 0.08
    include_parent_companions: bool = True
    exclude_low_information_units: bool = True
    use_policy_selector: bool = False
    policy_top_m: int = 10
    policy_concurrency: int = 3
    policy_confidence_threshold: float = 0.7
    policy_preserve_top_k: int = 5

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        settings = context.settings
        if self.external_embedding:
            settings = _external_embedding_settings(context.settings)
            store, notes = _new_eval_store(settings, docs)
        else:
            store = None
            notes = corpus_to_notes(docs)
        units = _notes_to_evidence_units(notes)
        selector_config = SharedEvidenceSelectorConfig(
            embedding_weight=self.embedding_weight,
            lexical_rrf_weight=self.lexical_rrf_weight,
            lexical_weight=self.lexical_weight,
            support_weight=self.support_weight,
            include_parent_companions=self.include_parent_companions,
            exclude_low_information_units=self.exclude_low_information_units,
        )
        prepared_units = prepare_shared_evidence_corpus(units, config=selector_config)
        unit_by_id = prepared_units.unit_by_id
        model_client = None
        if self.use_policy_selector:
            from personal_agent.infra.structured_model import build_structured_model_client

            model_client = build_structured_model_client(settings.structured, settings.langsmith)

        records: list[dict[str, object]] = []
        policy_inputs: list[tuple[str, str, list[str]]] = []
        for query in queries:
            candidate_limit = max(limit, context.local_probe_limit)
            embedding_ids = (
                _note_ids(store.find_similar_notes(
                    "ragbench_eval",
                    query.query_text,
                    limit=candidate_limit,
                ))
                if store is not None else []
            )
            selection = select_shared_evidence(
                query.query_text,
                prepared_units,
                limit=max(limit, self.policy_top_m) if self.use_policy_selector else limit,
                embedding_ranked_ids=embedding_ids,
                config=selector_config,
            )
            selected_before_policy = selection.ranked_ids
            policy_applied_reason = "disabled"
            if self.use_policy_selector:
                if model_client is None:
                    policy_applied_reason = "model_not_configured"
                else:
                    policy_applied_reason = "pending"
                    policy_inputs.append((
                        query.query_id,
                        query.query_text,
                        selected_before_policy[:self.policy_top_m],
                    ))
            section_id, parent_id = expected_note_ids(query)
            records.append({
                "query": query,
                "selection": selection,
                "selected_before_policy": selected_before_policy,
                "embedding_ids": embedding_ids,
                "policy_applied_reason": policy_applied_reason,
                "section_id": section_id,
                "parent_id": parent_id,
                "retrieval_snapshot": _retrieval_eval_snapshot(store) if store is not None else {},
                "embedding_snapshot": _embedding_eval_snapshot(store) if store is not None else {},
            })

        policy_decisions = (
            select_shared_evidence_policies(
                policy_inputs,
                unit_by_id,
                model_client,
                max_workers=self.policy_concurrency,
            )
            if self.use_policy_selector and model_client is not None else {}
        )

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for record in records:
            query = record["query"]
            assert isinstance(query, RAGBenchQuery)
            selection = record["selection"]
            assert hasattr(selection, "ranked_ids")
            selected_before_policy = list(record["selected_before_policy"])
            embedding_ids = list(record["embedding_ids"])
            section_id = str(record["section_id"])
            parent_id = str(record["parent_id"])
            policy = SharedEvidencePolicy()
            policy_error: str | None = None
            policy_retry_attempts = 0
            policy_retry_errors: list[str] = []
            policy_response_model: str | None = None
            policy_applied_reason = str(record["policy_applied_reason"])
            decision = policy_decisions.get(query.query_id)
            if decision is not None:
                policy = decision.policy
                policy_retry_attempts = decision.retry_attempts
                policy_retry_errors = decision.retry_errors
                policy_response_model = decision.response_model
                if decision.error:
                    policy_error = decision.error
                    policy_applied_reason = "policy_error"
                else:
                    selected_before_policy, policy_applied_reason = apply_shared_evidence_policy(
                        selected_before_policy,
                        policy,
                        limit=max(limit, self.policy_top_m),
                        confidence_threshold=self.policy_confidence_threshold,
                        preserve_top_k=self.policy_preserve_top_k,
                    )
            ranked = selected_before_policy[:limit]
            rankings.append((query.query_id, ranked))
            relevance[query.query_id] = {section_id, parent_id}
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "expected_note_ids": [section_id, parent_id],
                    "ranked_ids": ranked,
                    "strategy_profile": self.profile.name,
                    "strategy_flags": _strategy_profile_flags(self.profile),
                    "shared_evidence_selector": True,
                    "shared_policy_selector_enabled": self.use_policy_selector,
                    "shared_policy_candidate_ids": selection.ranked_ids[:self.policy_top_m],
                    "shared_policy_concurrency": self.policy_concurrency if self.use_policy_selector else None,
                    "shared_policy": policy.model_dump(),
                    "shared_policy_error": policy_error,
                    "shared_policy_response_model": policy_response_model,
                    "shared_policy_retry_attempts": policy_retry_attempts,
                    "shared_policy_retry_errors": policy_retry_errors,
                    "shared_policy_applied_reason": policy_applied_reason,
                    "doc_first_enabled": False,
                    "section_refine_enabled": False,
                    "query_normalization_mode": "none",
                    "embedding_ids_top20": embedding_ids[:20],
                    **selection.diagnostics,
                    **_diagnose_retrieval(
                        section_id=section_id,
                        parent_id=parent_id,
                        ranked_ids=ranked,
                        local_probe_ids=embedding_ids or ranked,
                        retrieval_health={},
                    ),
                    **record["retrieval_snapshot"],
                    **record["embedding_snapshot"],
                },
            )
        return rankings, relevance


def _strategy_profile_flags(profile: RetrievalStrategyProfile) -> dict[str, object]:
    return {
        "profile_name": profile.name,
        "doc_first_enabled": profile.doc_first_enabled,
        "doc_first_weight": profile.doc_first_weight,
        "slot_refine_enabled": profile.slot_refine_enabled,
        "sentence_selector_enabled": profile.sentence_selector_enabled,
        "policy_selector_enabled": profile.policy_selector_enabled,
        "group_prior_enabled": profile.group_prior_enabled,
    }


@dataclass(frozen=True)
class DocFirstExternalLlmTopMRerankStrategy:
    name: str = "doc_first_external_llm_topm_rerank"
    description: str = (
        "Controlled rerank: external 1024-d embedding + low-weight doc-first "
        "fusion first, then LLM reranks only the top-M candidates as a small "
        "additional signal."
    )
    top_docs: int = 5
    top_m: int = 20
    llm_weight: float = 0.01

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        from personal_agent.infra.structured_model import build_structured_model_client

        settings = _external_embedding_settings(context.settings)
        store, notes = _new_eval_store(settings, docs)
        note_by_id = {note.id: note for note in notes}
        graph = _build_structural_index(docs)
        model_client = build_structured_model_client(settings.structured, settings.langsmith)

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            candidate_limit = max(limit, self.top_m, context.local_probe_limit)
            local_ids = _note_ids(store.find_similar_notes(
                "ragbench_eval",
                query.query_text,
                limit=candidate_limit,
            ))
            doc_first_ids = _rank_doc_first_sections(
                query.query_text,
                graph,
                limit=candidate_limit,
                top_docs=self.top_docs,
            )
            fusion_ids = _fuse_ranked_ids(
                local_ids,
                doc_first_ids,
                limit=candidate_limit,
                secondary_weight=0.2,
            )
            top_m_ids = fusion_ids[:max(limit, self.top_m)]
            llm_ranked_ids: list[str] = []
            llm_error: str | None = None
            if model_client is not None and len(top_m_ids) > 1:
                try:
                    llm_ranked_ids = _llm_rerank_note_ids(
                        query.query_text,
                        top_m_ids,
                        note_by_id,
                        model_client,
                    )
                except Exception as exc:  # pragma: no cover - live defensive path
                    llm_error = str(exc)
            ranked = _blend_fusion_and_llm_ranks(
                fusion_ids,
                llm_ranked_ids,
                limit=limit,
                llm_weight=self.llm_weight,
            )
            rankings.append((query.query_id, ranked))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "expected_note_ids": [section_id, parent_id],
                    "ranked_ids": ranked,
                    **_diagnose_retrieval(
                        section_id=section_id,
                        parent_id=parent_id,
                        ranked_ids=ranked,
                        local_probe_ids=local_ids,
                        retrieval_health={},
                    ),
                    "local_ids_top20": local_ids[:20],
                    "local_probe_top20_ids": local_ids[:20],
                    "doc_first_ids_top20": doc_first_ids[:20],
                    "fusion_before_llm_top20_ids": fusion_ids[:20],
                    "llm_ranked_top20_ids": llm_ranked_ids[:20],
                    "llm_rerank_model_configured": model_client is not None,
                    "llm_rerank_error": llm_error,
                    "llm_rerank_top_m": self.top_m,
                    "llm_rerank_weight": self.llm_weight,
                    **_retrieval_eval_snapshot(store),
                    **_embedding_eval_snapshot(store),
                },
            )
        return rankings, relevance


@dataclass(frozen=True)
class DocFirstExternalLlmScoreRerankStrategy:
    name: str = "doc_first_external_llm_score_rerank"
    description: str = (
        "Controlled score rerank: external 1024-d embedding + low-weight doc-first "
        "fusion first, then LLM assigns direct-answer scores only within top-M."
    )
    top_docs: int = 5
    top_m: int = 20
    llm_weight: float = 0.08
    score_threshold: float = 0.9
    confidence_margin: float = 0.15
    excluded_query_types: tuple[str, ...] = ("yes_no",)

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        from personal_agent.infra.structured_model import build_structured_model_client

        settings = _external_embedding_settings(context.settings)
        store, notes = _new_eval_store(settings, docs)
        note_by_id = {note.id: note for note in notes}
        graph = _build_structural_index(docs)
        model_client = build_structured_model_client(settings.structured, settings.langsmith)

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            candidate_limit = max(limit, self.top_m, context.local_probe_limit)
            local_ids = _note_ids(store.find_similar_notes(
                "ragbench_eval",
                query.query_text,
                limit=candidate_limit,
            ))
            doc_first_ids = _rank_doc_first_sections(
                query.query_text,
                graph,
                limit=candidate_limit,
                top_docs=self.top_docs,
            )
            fusion_ids = _fuse_ranked_ids(
                local_ids,
                doc_first_ids,
                limit=candidate_limit,
                secondary_weight=0.2,
            )
            top_m_ids = fusion_ids[:max(limit, self.top_m)]
            llm_scores: dict[str, float] = {}
            llm_error: str | None = None
            query_type = _query_type_bucket(query.query_text)
            skip_reason: str | None = None
            if query_type in self.excluded_query_types:
                skip_reason = f"query_type:{query_type}"
            if skip_reason is None and model_client is not None and len(top_m_ids) > 1:
                try:
                    llm_scores = _llm_score_note_ids(
                        query.query_text,
                        top_m_ids,
                        note_by_id,
                        model_client,
                    )
                except Exception as exc:  # pragma: no cover - live defensive path
                    llm_error = str(exc)
            ranked = _blend_fusion_and_llm_scores(
                fusion_ids,
                llm_scores,
                limit=limit,
                llm_weight=self.llm_weight,
                score_threshold=self.score_threshold,
                confidence_margin=self.confidence_margin,
            )
            rankings.append((query.query_id, ranked))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "expected_note_ids": [section_id, parent_id],
                    "ranked_ids": ranked,
                    **_diagnose_retrieval(
                        section_id=section_id,
                        parent_id=parent_id,
                        ranked_ids=ranked,
                        local_probe_ids=local_ids,
                        retrieval_health={},
                    ),
                    "local_ids_top20": local_ids[:20],
                    "local_probe_top20_ids": local_ids[:20],
                    "doc_first_ids_top20": doc_first_ids[:20],
                    "fusion_before_llm_top20_ids": fusion_ids[:20],
                    "llm_scored_top20_ids": _rank_ids_by_llm_score(top_m_ids, llm_scores)[:20],
                    "llm_score_values": {note_id: round(score, 4) for note_id, score in llm_scores.items()},
                    "llm_rerank_model_configured": model_client is not None,
                    "llm_rerank_error": llm_error,
                    "llm_score_query_type": query_type,
                    "llm_score_skipped_reason": skip_reason,
                    "llm_score_excluded_query_types": list(self.excluded_query_types),
                    "llm_rerank_top_m": self.top_m,
                    "llm_rerank_weight": self.llm_weight,
                    "llm_score_threshold": self.score_threshold,
                    "llm_score_confidence_margin": self.confidence_margin,
                    **_retrieval_eval_snapshot(store),
                    **_embedding_eval_snapshot(store),
                },
            )
        return rankings, relevance


@dataclass(frozen=True)
class HighAccuracySemanticSelectorStrategy:
    name: str = "ask_retrieve_high_accuracy_semantic_selector"
    description: str = (
        "High-accuracy v2 candidate generator plus a gated LLM semantic selector "
        "that judges direct-answer evidence within the final top-M candidates."
    )
    top_docs: int = 5
    top_m: int = 10
    selector_weight: float = 0.0005
    score_threshold: float = 0.8
    confidence_margin: float = 0.2
    section_refine_weight: float = 0.02
    trigger_mode: Literal["all_queries", "triggered_only"] = "all_queries"
    preserve_top_k: int = 0

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        from personal_agent.infra.structured_model import build_structured_model_client

        settings = _external_embedding_settings(context.settings)
        store, notes = _new_eval_store(settings, docs)
        note_by_id = {note.id: note for note in notes}
        graph = _build_structural_index(docs)
        model_client = build_structured_model_client(settings.structured, settings.langsmith)

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            effective_query = _normalized_query_for_mode(
                query.query_text,
                mode="yes_no_guarded",
            )
            candidate_limit = max(limit, self.top_m, context.local_probe_limit)
            local_ids = _note_ids(store.find_similar_notes(
                "ragbench_eval",
                effective_query,
                limit=candidate_limit,
            ))
            doc_first_ids = _rank_doc_first_sections(
                effective_query,
                graph,
                limit=candidate_limit,
                top_docs=self.top_docs,
            )
            fusion_ids = _fuse_ranked_ids(
                local_ids,
                doc_first_ids,
                limit=candidate_limit,
                secondary_weight=0.2,
            )
            v2_ranked = _refine_same_doc_sections_by_passage_embedding(
                effective_query,
                fusion_ids,
                graph,
                settings=settings,
                context=context,
                limit=limit,
                top_docs=1,
                secondary_weight=self.section_refine_weight,
            )
            selector_candidate_ids = v2_ranked[:max(limit, self.top_m)]
            trigger_reason = _semantic_selector_trigger_reason(
                selector_candidate_ids,
                query_text=query.query_text,
                note_by_id=note_by_id,
                mode=self.trigger_mode,
            )
            judgments: dict[str, _EvidenceSelectionJudgment] = {}
            selector_error: str | None = None
            selector_retry_attempts = 0
            selector_retry_errors: list[str] = []
            selector_response_model: str | None = None
            skip_reason: str | None = None
            if trigger_reason is None:
                skip_reason = "no_semantic_ambiguity"
            elif model_client is None:
                skip_reason = "model_not_configured"
            elif len(selector_candidate_ids) <= 1:
                skip_reason = "not_enough_candidates"
            else:
                try:
                    (
                        judgments,
                        selector_retry_attempts,
                        selector_retry_errors,
                        selector_response_model,
                    ) = _llm_select_evidence(
                        query.query_text,
                        selector_candidate_ids,
                        note_by_id,
                        model_client,
                    )
                except Exception as exc:  # pragma: no cover - live defensive path
                    selector_error = str(exc)
            ranked = _blend_v2_and_semantic_selector(
                v2_ranked,
                judgments,
                limit=limit,
                selector_weight=self.selector_weight,
                score_threshold=self.score_threshold,
                confidence_margin=self.confidence_margin,
                preserve_top_k=self.preserve_top_k,
            )
            rankings.append((query.query_id, ranked))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "effective_query": effective_query,
                    "query_normalization_mode": "yes_no_guarded",
                    "expected_note_ids": [section_id, parent_id],
                    "ranked_ids": ranked,
                    **_diagnose_retrieval(
                        section_id=section_id,
                        parent_id=parent_id,
                        ranked_ids=ranked,
                        local_probe_ids=local_ids,
                        retrieval_health={},
                    ),
                    "local_ids_top20": local_ids[:20],
                    "local_probe_top20_ids": local_ids[:20],
                    "doc_first_ids_top20": doc_first_ids[:20],
                    "fusion_before_section_refine_top20_ids": fusion_ids[:20],
                    "v2_before_semantic_selector_top20_ids": v2_ranked[:20],
                    "semantic_selector_candidate_ids": selector_candidate_ids,
                    "semantic_selector_trigger_reason": trigger_reason,
                    "semantic_selector_skipped_reason": skip_reason,
                    "semantic_selector_model_configured": model_client is not None,
                    "semantic_selector_error": selector_error,
                    "semantic_selector_response_model": selector_response_model,
                    "semantic_selector_retry_attempts": selector_retry_attempts,
                    "semantic_selector_retry_errors": selector_retry_errors,
                    "semantic_selector_trigger_mode": self.trigger_mode,
                    "semantic_selector_query_type": _query_type_bucket(query.query_text),
                    "semantic_selector_top_m": self.top_m,
                    "semantic_selector_weight": self.selector_weight,
                    "semantic_selector_score_threshold": self.score_threshold,
                    "semantic_selector_confidence_margin": self.confidence_margin,
                    "semantic_selector_preserve_top_k": self.preserve_top_k,
                    "semantic_selector_judgments": {
                        note_id: _selector_judgment_snapshot(judgment)
                        for note_id, judgment in judgments.items()
                    },
                    "semantic_selector_ranked_top20_ids": _rank_ids_by_semantic_selector(
                        selector_candidate_ids,
                        judgments,
                    )[:20],
                    **_retrieval_eval_snapshot(store),
                    **_embedding_eval_snapshot(store),
                },
            )
        return rankings, relevance


@dataclass(frozen=True)
class HighAccuracySemanticPolicySelectorStrategy:
    name: str = "ask_retrieve_high_accuracy_semantic_policy_selector"
    description: str = (
        "High-accuracy v2 candidate generator plus an LLM semantic policy selector "
        "that decides whether and how to intervene within candidate boundaries."
    )
    top_docs: int = 5
    top_m: int = 10
    section_refine_weight: float = 0.02
    confidence_threshold: float = 0.7
    preserve_top_k: int = 5

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        from personal_agent.infra.structured_model import build_structured_model_client

        settings = _external_embedding_settings(context.settings)
        store, notes = _new_eval_store(settings, docs)
        note_by_id = {note.id: note for note in notes}
        graph = _build_structural_index(docs)
        model_client = build_structured_model_client(settings.structured, settings.langsmith)

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            effective_query = _normalized_query_for_mode(
                query.query_text,
                mode="yes_no_guarded",
            )
            candidate_limit = max(limit, self.top_m, context.local_probe_limit)
            local_ids = _note_ids(store.find_similar_notes(
                "ragbench_eval",
                effective_query,
                limit=candidate_limit,
            ))
            doc_first_ids = _rank_doc_first_sections(
                effective_query,
                graph,
                limit=candidate_limit,
                top_docs=self.top_docs,
            )
            fusion_ids = _fuse_ranked_ids(
                local_ids,
                doc_first_ids,
                limit=candidate_limit,
                secondary_weight=OPEN_RAGBENCH_PROFILE.doc_first_weight,
            )
            v2_ranked = _refine_same_doc_sections_by_passage_embedding(
                effective_query,
                fusion_ids,
                graph,
                settings=settings,
                context=context,
                limit=limit,
                top_docs=1,
                secondary_weight=self.section_refine_weight,
            )
            policy_candidate_ids = v2_ranked[:max(limit, self.top_m)]
            policy = _EvidenceSelectionPolicy()
            policy_error: str | None = None
            policy_retry_attempts = 0
            policy_retry_errors: list[str] = []
            policy_response_model: str | None = None
            skip_reason: str | None = None
            if model_client is None:
                skip_reason = "model_not_configured"
            elif len(policy_candidate_ids) <= 1:
                skip_reason = "not_enough_candidates"
            else:
                try:
                    (
                        policy,
                        policy_retry_attempts,
                        policy_retry_errors,
                        policy_response_model,
                    ) = _llm_select_evidence_policy(
                        query.query_text,
                        policy_candidate_ids,
                        note_by_id,
                        model_client,
                    )
                except Exception as exc:  # pragma: no cover - live defensive path
                    policy_error = str(exc)
            ranked, applied_reason = _apply_semantic_policy(
                v2_ranked,
                policy,
                limit=limit,
                confidence_threshold=self.confidence_threshold,
                preserve_top_k=self.preserve_top_k,
            )
            rankings.append((query.query_id, ranked))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "effective_query": effective_query,
                    "query_normalization_mode": "yes_no_guarded",
                    "expected_note_ids": [section_id, parent_id],
                    "ranked_ids": ranked,
                    **_diagnose_retrieval(
                        section_id=section_id,
                        parent_id=parent_id,
                        ranked_ids=ranked,
                        local_probe_ids=local_ids,
                        retrieval_health={},
                    ),
                    "local_ids_top20": local_ids[:20],
                    "local_probe_top20_ids": local_ids[:20],
                    "doc_first_ids_top20": doc_first_ids[:20],
                    "fusion_before_section_refine_top20_ids": fusion_ids[:20],
                    "v2_before_semantic_policy_top20_ids": v2_ranked[:20],
                    "semantic_policy_candidate_ids": policy_candidate_ids,
                    "semantic_policy_model_configured": model_client is not None,
                    "semantic_policy_skipped_reason": skip_reason,
                    "semantic_policy_error": policy_error,
                    "semantic_policy_response_model": policy_response_model,
                    "semantic_policy_retry_attempts": policy_retry_attempts,
                    "semantic_policy_retry_errors": policy_retry_errors,
                    "semantic_policy_confidence_threshold": self.confidence_threshold,
                    "semantic_policy_preserve_top_k": self.preserve_top_k,
                    "semantic_policy": _policy_snapshot(policy),
                    "semantic_policy_applied_reason": applied_reason,
                    **_retrieval_eval_snapshot(store),
                    **_embedding_eval_snapshot(store),
                },
            )
        return rankings, relevance


_GRAPHITI_INGEST_CACHE: dict[str, dict[str, str]] = {}


@dataclass(frozen=True)
class GraphitiRetrievalStrategy:
    graph_strategy_name: str

    @property
    def name(self) -> str:
        return f"graphiti_{self.graph_strategy_name}"

    @property
    def description(self) -> str:
        graph_strategy = STRATEGIES[self.graph_strategy_name]
        return f"Real Graphiti retrieval using {graph_strategy.name}: {graph_strategy.description}"

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        settings = context.settings.model_copy(
            update={
                "graphiti": context.settings.graphiti.model_copy(
                    update={"search_strategy": self.graph_strategy_name}
                )
            }
        )
        graph_store = GraphitiStore(settings)
        if not graph_store.configured():
            raise RuntimeError("Graphiti is not configured. Check Neo4j, OpenAI, and embedding settings.")

        notes = corpus_to_notes(docs, mode=context.graphiti_note_mode)
        episode_to_note_id = _ensure_graphiti_corpus(
            graph_store=graph_store,
            notes=notes,
            user_id=context.graphiti_user_id,
            reset=context.reset_graphiti,
            manifest_path=context.graphiti_manifest_path,
            note_mode=context.graphiti_note_mode,
            continue_on_ingest_error=context.graphiti_continue_on_ingest_error,
        )

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            result = graph_store.retrieve(query.query_text, context.graphiti_user_id)
            if not result.enabled:
                raise RuntimeError(f"Graphiti ask failed for {query.query_id}: {result.error}")
            rankings.append((
                query.query_id,
                _ranked_note_ids_from_graph_result(result, episode_to_note_id, limit),
            ))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
        return rankings, relevance


def _ensure_graphiti_corpus(
    *,
    graph_store: GraphitiStore,
    notes: list[KnowledgeNote],
    user_id: str,
    reset: bool,
    manifest_path: Path | None,
    note_mode: CorpusNoteMode,
    continue_on_ingest_error: bool,
) -> dict[str, str]:
    """Ingest the benchmark corpus into Graphiti, with incremental support.

    If a manifest already exists and `reset=False`, loads cached mappings for
    already-ingested notes and only ingests the new ones (incremental mode).
    If `reset=True`, clears the graph and re-ingests everything from scratch.
    """
    cache_key = f"{user_id}:{note_mode}:{len(notes)}:{','.join(note.id for note in notes[:5])}"
    if cache_key in _GRAPHITI_INGEST_CACHE:
        return _GRAPHITI_INGEST_CACHE[cache_key]

    expected_note_ids = {note.id for note in notes}

    # --- Incremental mode: load existing manifest, ingest only new notes ---
    existing_episode_map: dict[str, str] = {}
    existing_note_ids: set[str] = set()
    if not reset and manifest_path is not None and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("user_id") == user_id
            and manifest.get("graphiti_group_prefix") == graph_store.settings.graphiti.group_prefix
            and manifest.get("note_mode", "parent_sections") == note_mode
        ):
            existing_episode_map = {
                str(k): str(v) for k, v in manifest.get("episode_to_note_id", {}).items()
            }
            existing_note_ids = set(manifest.get("note_ids", []))

    # If manifest covers all requested notes exactly, reuse without ingest
    if existing_note_ids >= expected_note_ids and existing_episode_map:
        _GRAPHITI_INGEST_CACHE[cache_key] = existing_episode_map
        return existing_episode_map

    if reset:
        graph_store.clear_user_group(user_id)
        existing_episode_map = {}
        existing_note_ids = set()

    # Only ingest notes not already in the manifest
    new_notes = [n for n in notes if n.id not in existing_note_ids]
    episode_to_note_id: dict[str, str] = dict(existing_episode_map)
    ingest_errors: list[dict[str, str]] = []
    total = len(new_notes)

    import asyncio
    max_workers = 10

    async def _async_ingest_one(store, original_note, index, total_count):
        note = original_note.model_copy(update={"user_id": user_id})
        print(f"  Ingesting [{index}/{total_count}] {note.id[:40]}...", flush=True)
        try:
            result = await store._ingest_note(note, trace_id=f"ragbench-ingest-{index}")
            if not result.enabled or not result.episode_uuid:
                return (None, original_note.id, result.error or "missing episode_uuid")
            return (result.episode_uuid, original_note.id, None)
        except Exception as exc:
            return (None, original_note.id, str(exc)[:200])

    async def _run_all():
        sem = asyncio.Semaphore(max_workers)
        async def _limited(coro):
            async with sem:
                return await coro
        tasks = [
            _limited(_async_ingest_one(graph_store, new_notes[i], i + 1, total))
            for i in range(total)
        ]
        return await asyncio.gather(*tasks)

    all_results = asyncio.run(_run_all())
    for episode_uuid, note_id, error in all_results:
        if error:
            if continue_on_ingest_error:
                ingest_errors.append({"note_id": note_id, "error": error})
            else:
                raise RuntimeError(f"Graphiti ingest failed for note {note_id}: {error}")
        elif episode_uuid:
            episode_to_note_id[episode_uuid] = note_id

    print(f"  Ingest complete: {len(episode_to_note_id)} episodes, {len(ingest_errors)} errors", flush=True)

    if not episode_to_note_id:
        detail = ingest_errors[:3]
        raise RuntimeError(f"Graphiti ingest produced no episodes. Sample errors: {detail}")

    all_note_ids = existing_note_ids | expected_note_ids
    _GRAPHITI_INGEST_CACHE[cache_key] = episode_to_note_id
    if manifest_path is not None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "user_id": user_id,
                    "graphiti_group_prefix": graph_store.settings.graphiti.group_prefix,
                    "note_mode": note_mode,
                    "note_count": len(all_note_ids),
                    "note_ids": sorted(all_note_ids),
                    "episode_to_note_id": episode_to_note_id,
                    "ingest_errors": ingest_errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"  Manifest saved: {manifest_path} ({len(episode_to_note_id)} episodes, {len(ingest_errors)} errors)")
    return episode_to_note_id


def _ranked_note_ids_from_graph_result(
    result: GraphRetrievalResult,
    episode_to_note_id: dict[str, str],
    limit: int,
) -> list[str]:
    ranked_ids: list[str] = []
    seen: set[str] = set()

    for hit in result.citation_hits:
        note_id = episode_to_note_id.get(hit.episode_uuid)
        if note_id is None or note_id in seen:
            continue
        ranked_ids.append(note_id)
        seen.add(note_id)
        if len(ranked_ids) >= limit:
            return ranked_ids

    for episode_uuid in result.related_episode_uuids:
        note_id = episode_to_note_id.get(episode_uuid)
        if note_id is None or note_id in seen:
            continue
        ranked_ids.append(note_id)
        seen.add(note_id)
        if len(ranked_ids) >= limit:
            return ranked_ids

    return ranked_ids


@dataclass(frozen=True)
class _StructuralSection:
    note_id: str
    parent_id: str
    doc_id: str
    index: int
    tokens: set[str]
    token_sequence: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class _StructuralDoc:
    note_id: str
    doc_id: str
    tokens: set[str]
    sections: list[_StructuralSection]


@dataclass(frozen=True)
class _StructuralIndex:
    docs: list[_StructuralDoc]
    sections: list[_StructuralSection]
    document_frequency: dict[str, int]
    num_sections: int
    sections_by_id: dict[str, _StructuralSection]
    docs_by_parent_id: dict[str, _StructuralDoc]


class _NoteRerankResult(BaseModel):
    ranked_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_list(cls, data: object) -> object:
        if isinstance(data, list):
            return {"ranked_ids": data}
        return data


class _NoteScoreItem(BaseModel):
    id: str
    direct_answer_score: float = 0.0
    section_specificity: float = 0.0
    doc_relevance: float = 0.0
    background_penalty: float = 0.0


class _NoteScoreResult(BaseModel):
    scores: list[_NoteScoreItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_list(cls, data: object) -> object:
        if isinstance(data, list):
            return {"scores": data}
        return data


EvidenceSufficiency = Literal["sufficient", "partial", "background", "irrelevant"]
AnswerTypeMatch = Literal["yes_no", "definition", "method", "formula", "result", "unclear"]
PolicyAmbiguityType = Literal[
    "direct_answer_vs_background",
    "parent_vs_section",
    "neighboring_sections",
    "insufficient_evidence",
    "no_ambiguity",
]
PolicyAction = Literal[
    "no_op",
    "promote_primary_evidence",
    "reorder_within_top5",
    "request_more_retrieval",
]


class _EvidenceSelectionJudgment(BaseModel):
    candidate_id: str
    direct_answer_score: float = 0.0
    section_specificity: float = 0.0
    evidence_sufficiency: EvidenceSufficiency = "irrelevant"
    answer_type_match: AnswerTypeMatch = "unclear"
    should_be_primary_evidence: bool = False
    rationale: str = ""


class _EvidenceSelectionResult(BaseModel):
    judgments: list[_EvidenceSelectionJudgment] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_list(cls, data: object) -> object:
        if isinstance(data, list):
            return {"judgments": data}
        return data


class _EvidenceSelectionPolicy(BaseModel):
    should_intervene: bool = False
    ambiguity_type: PolicyAmbiguityType = "no_ambiguity"
    action: PolicyAction = "no_op"
    primary_candidate_id: str = ""
    confidence: float = 0.0
    rationale: str = ""


class _EvidenceSelectionPolicyResult(BaseModel):
    policy: _EvidenceSelectionPolicy = Field(default_factory=_EvidenceSelectionPolicy)

    @model_validator(mode="before")
    @classmethod
    def _wrap_policy(cls, data: object) -> object:
        if isinstance(data, dict) and "policy" not in data:
            return {"policy": data}
        return data


def _record_eval_snapshot(context: BenchmarkContext, strategy_name: str, snapshot: dict) -> None:
    if context.eval_snapshots is None:
        return
    strategy_config = context.strategy_configs.get(strategy_name)
    if strategy_config:
        snapshot = {
            "strategy_version": strategy_config.get("strategy_version", ""),
            "strategy_config": dict(strategy_config),
            **snapshot,
        }
    context.eval_snapshots.setdefault(strategy_name, []).append(_enrich_eval_snapshot(snapshot))


def _strategy_eval_config(strategy: BenchmarkStrategy, settings: Settings) -> dict[str, object]:
    version = _strategy_version(strategy)
    config: dict[str, object] = {
        "strategy_name": strategy.name,
        "strategy_version": version,
        "strategy_profile": None,
        "strategy_flags": {},
        "embedding_provider": settings.embedding_provider,
        "embedding_dim": None,
        "doc_first_enabled": False,
        "doc_first_weight": None,
        "query_expansion_mode": "none",
        "llm_rerank_mode": "none",
    }
    if isinstance(strategy, DocFirstFusionStrategy):
        embedding_settings = _external_embedding_settings(settings) if strategy.external_embedding else settings
        normalization_mode = (
            "full" if strategy.normalize_query and strategy.query_normalization_mode == "none"
            else strategy.query_normalization_mode
        )
        config.update({
            "strategy_profile": strategy.profile.name,
            "strategy_flags": _strategy_profile_flags(strategy.profile),
            "embedding_provider": embedding_settings.embedding_provider,
            "embedding_model": embedding_settings.openai.embedding_model,
            "embedding_dim": 1024 if strategy.external_embedding else None,
            "external_embedding": strategy.external_embedding,
            "doc_first_enabled": strategy.doc_first_enabled,
            "doc_first_top_docs": strategy.top_docs,
            "doc_first_weight": strategy.doc_first_weight if strategy.doc_first_enabled else None,
            "section_refine_enabled": strategy.section_refine,
            "section_refine_mode": strategy.section_refine_mode if strategy.section_refine else None,
            "section_refine_weight": strategy.section_refine_weight if strategy.section_refine else None,
            "section_refine_top_docs": strategy.section_refine_top_docs if strategy.section_refine else None,
            "query_expansion_mode": normalization_mode,
            "query_expansion_weight": strategy.query_expansion_weight,
        })
    elif isinstance(strategy, SharedEvidenceSelectorStrategy):
        embedding_settings = _external_embedding_settings(settings) if strategy.external_embedding else settings
        config.update({
            "strategy_profile": strategy.profile.name,
            "strategy_flags": _strategy_profile_flags(strategy.profile),
            "embedding_provider": embedding_settings.embedding_provider,
            "embedding_model": embedding_settings.openai.embedding_model if strategy.external_embedding else None,
            "embedding_dim": 1024 if strategy.external_embedding else None,
            "external_embedding": strategy.external_embedding,
            "doc_first_enabled": False,
            "section_refine_enabled": False,
            "query_expansion_mode": "none",
            "shared_evidence_selector": True,
            "shared_selector_embedding_weight": strategy.embedding_weight,
            "shared_selector_lexical_rrf_weight": strategy.lexical_rrf_weight,
            "shared_selector_lexical_weight": strategy.lexical_weight,
            "shared_selector_support_weight": strategy.support_weight,
            "shared_selector_include_parent_companions": strategy.include_parent_companions,
            "shared_selector_exclude_low_information_units": strategy.exclude_low_information_units,
            "shared_policy_selector_enabled": strategy.use_policy_selector,
            "shared_policy_top_m": strategy.policy_top_m if strategy.use_policy_selector else None,
            "shared_policy_concurrency": strategy.policy_concurrency if strategy.use_policy_selector else None,
            "shared_policy_confidence_threshold": (
                strategy.policy_confidence_threshold if strategy.use_policy_selector else None
            ),
            "shared_policy_preserve_top_k": strategy.policy_preserve_top_k if strategy.use_policy_selector else None,
        })
    elif isinstance(strategy, DocFirstExternalLlmTopMRerankStrategy):
        config.update({
            "embedding_provider": "openai",
            "embedding_model": "BAAI/bge-m3",
            "embedding_dim": 1024,
            "external_embedding": True,
            "doc_first_enabled": True,
            "doc_first_top_docs": strategy.top_docs,
            "doc_first_weight": 0.2,
            "query_expansion_mode": "none",
            "llm_rerank_mode": "ordered_topm",
            "llm_rerank_top_m": strategy.top_m,
            "llm_rerank_weight": strategy.llm_weight,
        })
    elif isinstance(strategy, DocFirstExternalLlmScoreRerankStrategy):
        config.update({
            "embedding_provider": "openai",
            "embedding_model": "BAAI/bge-m3",
            "embedding_dim": 1024,
            "external_embedding": True,
            "doc_first_enabled": True,
            "doc_first_top_docs": strategy.top_docs,
            "doc_first_weight": 0.2,
            "query_expansion_mode": "none",
            "llm_rerank_mode": "score_gated",
            "llm_rerank_top_m": strategy.top_m,
            "llm_rerank_weight": strategy.llm_weight,
            "llm_score_threshold": strategy.score_threshold,
            "llm_score_confidence_margin": strategy.confidence_margin,
            "llm_score_excluded_query_types": list(strategy.excluded_query_types),
        })
    elif isinstance(strategy, HighAccuracySemanticSelectorStrategy):
        config.update({
            "strategy_profile": OPEN_RAGBENCH_PROFILE.name,
            "strategy_flags": _strategy_profile_flags(OPEN_RAGBENCH_PROFILE),
            "embedding_provider": "openai",
            "embedding_model": "BAAI/bge-m3",
            "embedding_dim": 1024,
            "external_embedding": True,
            "doc_first_enabled": True,
            "doc_first_top_docs": strategy.top_docs,
            "doc_first_weight": 0.2,
            "query_expansion_mode": "yes_no_guarded",
            "section_refine_enabled": True,
            "section_refine_mode": "passage_embedding",
            "section_refine_weight": strategy.section_refine_weight,
            "section_refine_top_docs": 1,
            "llm_rerank_mode": "semantic_selector",
            "semantic_selector_trigger_mode": strategy.trigger_mode,
            "semantic_selector_top_m": strategy.top_m,
            "semantic_selector_weight": strategy.selector_weight,
            "semantic_selector_score_threshold": strategy.score_threshold,
            "semantic_selector_confidence_margin": strategy.confidence_margin,
            "semantic_selector_preserve_top_k": strategy.preserve_top_k,
        })
    elif isinstance(strategy, HighAccuracySemanticPolicySelectorStrategy):
        config.update({
            "strategy_profile": OPEN_RAGBENCH_PROFILE.name,
            "strategy_flags": {
                **_strategy_profile_flags(OPEN_RAGBENCH_PROFILE),
                "policy_selector_enabled": True,
            },
            "embedding_provider": "openai",
            "embedding_model": "BAAI/bge-m3",
            "embedding_dim": 1024,
            "external_embedding": True,
            "doc_first_enabled": True,
            "doc_first_top_docs": strategy.top_docs,
            "doc_first_weight": OPEN_RAGBENCH_PROFILE.doc_first_weight,
            "query_expansion_mode": "yes_no_guarded",
            "section_refine_enabled": True,
            "section_refine_mode": "passage_embedding",
            "section_refine_weight": strategy.section_refine_weight,
            "section_refine_top_docs": 1,
            "llm_rerank_mode": "semantic_policy_selector",
            "semantic_policy_top_m": strategy.top_m,
            "semantic_policy_confidence_threshold": strategy.confidence_threshold,
            "semantic_policy_preserve_top_k": strategy.preserve_top_k,
        })
    elif isinstance(strategy, RuntimeAskRetrievalKnowledgeAblationStrategy):
        config.update({
            "embedding_provider": "openai" if strategy.external_embedding else settings.embedding_provider,
            "embedding_model": "BAAI/bge-m3" if strategy.external_embedding else settings.openai.embedding_model,
            "embedding_dim": 1024 if strategy.external_embedding else None,
            "external_embedding": strategy.external_embedding,
            "ask_reranker": strategy.ask_reranker or (
                "llm_gated" if strategy.llm_gated else "llm" if strategy.llm_rerank else "heuristic"
            ),
            "knowledge_enabled": strategy.include_knowledge,
            "knowledge_only": strategy.knowledge_only,
            "force_claim_sensitive": strategy.force_claim_sensitive,
            "llm_rerank_mode": (
                "ask_llm_gated"
                if strategy.llm_gated
                else "ask_llm" if strategy.llm_rerank else "none"
            ),
        })
    return config


def _strategy_version(strategy: BenchmarkStrategy) -> str:
    if strategy.name == "ask_retrieve_open_profile":
        return "open_profile_high_accuracy_v2"
    if strategy.name == "ask_retrieve_galileo_profile":
        return "galileo_profile_external_embedding_v1"
    if strategy.name == "ask_retrieve_dataset_agnostic_profile":
        return "dataset_agnostic_external_embedding_v1"
    if strategy.name == "ask_retrieve_high_accuracy":
        if (
            isinstance(strategy, DocFirstFusionStrategy)
            and strategy.section_refine
            and strategy.section_refine_mode == "passage_embedding"
        ):
            return "high_accuracy_v2"
        return "high_accuracy_v1"
    if isinstance(strategy, DocFirstFusionStrategy):
        mode = (
            "full" if strategy.normalize_query and strategy.query_normalization_mode == "none"
            else strategy.query_normalization_mode
        )
        suffix = "external" if strategy.external_embedding else "local"
        if mode and mode != "none":
            suffix = f"{suffix}_{mode}"
        if strategy.section_refine:
            suffix = f"{suffix}_{strategy.section_refine_mode}_section_refine"
        return f"doc_first_fusion_v1_{suffix}"
    if isinstance(strategy, DocFirstExternalLlmScoreRerankStrategy):
        return "doc_first_llm_score_gated_v1"
    if isinstance(strategy, DocFirstExternalLlmTopMRerankStrategy):
        return "doc_first_llm_ordered_topm_v1"
    if isinstance(strategy, HighAccuracySemanticSelectorStrategy):
        if strategy.trigger_mode == "triggered_only" and strategy.preserve_top_k > 0:
            return f"high_accuracy_v2_semantic_selector_triggered_only_preserve_top{strategy.preserve_top_k}_v1"
        if strategy.trigger_mode == "triggered_only":
            return "high_accuracy_v2_semantic_selector_triggered_only_v1"
        return "high_accuracy_v2_semantic_selector_all_queries_v1"
    if isinstance(strategy, HighAccuracySemanticPolicySelectorStrategy):
        return "high_accuracy_v2_semantic_policy_selector_v1"
    return f"{strategy.name}_v1"


def _first_rank(ranked_ids: list[str], expected_ids: set[str]) -> int | None:
    for index, note_id in enumerate(ranked_ids, 1):
        if note_id in expected_ids:
            return index
    return None


def _parent_id(note_id: str) -> str:
    return re.sub(r"_sec_\d+$", "", note_id)


def _doc_rank(ranked_ids: list[str], parent_id: str) -> int | None:
    for index, note_id in enumerate(ranked_ids, 1):
        if _parent_id(note_id) == parent_id:
            return index
    return None


_DIAGNOSTIC_STAGE_KEYS = {
    "final": "ranked_ids",
    "fusion_before_llm": "fusion_before_llm_top20_ids",
    "llm_ranked": "llm_ranked_top20_ids",
    "llm_scored": "llm_scored_top20_ids",
    "v2_before_semantic_selector": "v2_before_semantic_selector_top20_ids",
    "v2_before_semantic_policy": "v2_before_semantic_policy_top20_ids",
    "semantic_selector_ranked": "semantic_selector_ranked_top20_ids",
    "raw_lexical": "raw_lexical_top20_ids",
    "raw_vector": "raw_vector_top20_ids",
    "merged": "merged_top20_ids",
    "expanded": "expanded_top20_ids",
    "local_probe": "local_probe_top20_ids",
}


def _ids_from_snapshot(snapshot: dict, key: str) -> list[str]:
    value = snapshot.get(key)
    return [str(item) for item in value] if isinstance(value, list) else []


def _unique_ids(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for note_id in group:
            if not note_id or note_id in seen:
                continue
            seen.add(note_id)
            merged.append(note_id)
    return merged


def _enrich_eval_snapshot(snapshot: dict) -> dict:
    expected_ids = [str(item) for item in snapshot.get("expected_note_ids", [])]
    if len(expected_ids) < 2:
        return snapshot

    section_id, parent_id = expected_ids[0], expected_ids[1]
    expected = {section_id, parent_id}
    stage_ranks: dict[str, dict[str, int | None]] = {}
    for stage, key in _DIAGNOSTIC_STAGE_KEYS.items():
        ids = _ids_from_snapshot(snapshot, key)
        if not ids:
            continue
        stage_ranks[stage] = {
            "section_rank": _first_rank(ids, {section_id}),
            "parent_rank": _first_rank(ids, {parent_id}),
            "any_rank": _first_rank(ids, expected),
            "doc_rank": _doc_rank(ids, parent_id),
        }

    if stage_ranks:
        snapshot["gold_stage_ranks"] = stage_ranks
    score_delta = _llm_score_rank_delta(snapshot, section_id, parent_id)
    if score_delta is not None:
        snapshot["llm_score_rank_delta"] = score_delta
    snapshot["final_drop_reason"] = _final_drop_reason(snapshot, section_id, parent_id)
    snapshot["section_drop_reason"] = _section_drop_reason(snapshot, section_id, parent_id)
    return snapshot


def _rank_effect(before_rank: int | None, after_rank: int | None) -> str:
    if before_rank is None and after_rank is None:
        return "absent"
    if before_rank is None:
        return "introduced"
    if after_rank is None:
        return "dropped"
    if after_rank < before_rank:
        return "improved"
    if after_rank > before_rank:
        return "harmed"
    return "same"


def _rank_delta(before_rank: int | None, after_rank: int | None) -> int | None:
    if before_rank is None or after_rank is None:
        return None
    return before_rank - after_rank


def _llm_score_rank_delta(snapshot: dict, section_id: str, parent_id: str) -> dict | None:
    fusion_ids = _ids_from_snapshot(snapshot, "fusion_before_llm_top20_ids")
    scored_ids = _ids_from_snapshot(snapshot, "llm_scored_top20_ids")
    final_ids = _ids_from_snapshot(snapshot, "ranked_ids")
    if not fusion_ids or not scored_ids:
        return None

    expected = {section_id, parent_id}
    fusion_any_rank = _first_rank(fusion_ids, expected)
    scored_any_rank = _first_rank(scored_ids, expected)
    final_any_rank = _first_rank(final_ids, expected)
    fusion_section_rank = _first_rank(fusion_ids, {section_id})
    scored_section_rank = _first_rank(scored_ids, {section_id})
    final_section_rank = _first_rank(final_ids, {section_id})

    return {
        "fusion_any_rank": fusion_any_rank,
        "llm_scored_any_rank": scored_any_rank,
        "final_any_rank": final_any_rank,
        "score_any_delta": _rank_delta(fusion_any_rank, scored_any_rank),
        "final_any_delta": _rank_delta(fusion_any_rank, final_any_rank),
        "score_any_effect": _rank_effect(fusion_any_rank, scored_any_rank),
        "final_any_effect": _rank_effect(fusion_any_rank, final_any_rank),
        "fusion_section_rank": fusion_section_rank,
        "llm_scored_section_rank": scored_section_rank,
        "final_section_rank": final_section_rank,
        "score_section_delta": _rank_delta(fusion_section_rank, scored_section_rank),
        "final_section_delta": _rank_delta(fusion_section_rank, final_section_rank),
        "score_section_effect": _rank_effect(fusion_section_rank, scored_section_rank),
        "final_section_effect": _rank_effect(fusion_section_rank, final_section_rank),
    }


def _final_drop_reason(snapshot: dict, section_id: str, parent_id: str) -> str | None:
    final_ids = _ids_from_snapshot(snapshot, "ranked_ids")
    expected = {section_id, parent_id}
    if _first_rank(final_ids, expected) is not None:
        return None

    dropped_ids = _ids_from_snapshot(snapshot, "context_dropped_evidence_ids")
    selected_ids = _projection_selected_evidence_ids(snapshot)
    expanded_ids = _ids_from_snapshot(snapshot, "expanded_top20_ids")
    merged_ids = _ids_from_snapshot(snapshot, "merged_top20_ids")
    raw_vector_ids = _ids_from_snapshot(snapshot, "raw_vector_top20_ids")
    raw_lexical_ids = _ids_from_snapshot(snapshot, "raw_lexical_top20_ids")
    fusion_ids = _ids_from_snapshot(snapshot, "fusion_before_llm_top20_ids")
    llm_ranked_ids = _ids_from_snapshot(snapshot, "llm_ranked_top20_ids")
    llm_scored_ids = _ids_from_snapshot(snapshot, "llm_scored_top20_ids")
    local_probe_ids = _ids_from_snapshot(snapshot, "local_probe_top20_ids")

    if _first_rank(dropped_ids, expected) is not None:
        return _context_drop_reason(snapshot, expected) or "budget_or_mmr_drop"
    if _first_rank(selected_ids, expected) is not None:
        return _projection_drop_reason(snapshot, section_id, parent_id, expected) or "projection_missing"
    if fusion_ids and _first_rank(fusion_ids, expected) is not None:
        return "post_fusion_selection_drop"
    if llm_ranked_ids and _first_rank(llm_ranked_ids, expected) is not None:
        return "post_llm_ordered_selection_drop"
    if llm_scored_ids and _first_rank(llm_scored_ids, expected) is not None:
        return "post_llm_score_selection_drop"
    if _first_rank(expanded_ids, expected) is not None:
        return "post_expansion_selection_drop"
    if _first_rank(merged_ids, expected) is not None:
        return "expansion_drop"
    if _first_rank(raw_vector_ids, expected) is not None or _first_rank(raw_lexical_ids, expected) is not None:
        return "merge_or_expansion_drop"
    if _doc_rank(local_probe_ids, parent_id) is not None:
        return "section_miss"
    if _doc_rank(final_ids, parent_id) is not None:
        return "same_doc_wrong_section"
    return "doc_miss"


def _section_drop_reason(snapshot: dict, section_id: str, parent_id: str) -> str | None:
    final_ids = _ids_from_snapshot(snapshot, "ranked_ids")
    if _first_rank(final_ids, {section_id}) is not None:
        return None

    dropped_ids = _ids_from_snapshot(snapshot, "context_dropped_evidence_ids")
    selected_ids = _projection_selected_evidence_ids(snapshot)
    if _first_rank(dropped_ids, {section_id}) is not None:
        reason = _context_drop_reason(snapshot, {section_id}) or "budget_or_mmr_drop"
        return f"section_{reason}"

    if _first_rank(selected_ids, {section_id}) is not None:
        if _first_rank(final_ids, {parent_id}) is not None:
            return "parent_replaced_child"
        return _projection_drop_reason(snapshot, section_id, parent_id, {section_id}) or "section_projection_missing"

    if _first_rank(final_ids, {parent_id}) is not None:
        return "parent_hit_section_miss"

    if _doc_rank(final_ids, parent_id) is not None:
        return "same_doc_wrong_section"

    expanded_ids = _ids_from_snapshot(snapshot, "expanded_top20_ids")
    merged_ids = _ids_from_snapshot(snapshot, "merged_top20_ids")
    raw_vector_ids = _ids_from_snapshot(snapshot, "raw_vector_top20_ids")
    raw_lexical_ids = _ids_from_snapshot(snapshot, "raw_lexical_top20_ids")
    if _first_rank(expanded_ids, {section_id}) is not None:
        return "post_expansion_selection_drop"
    if _first_rank(merged_ids, {section_id}) is not None:
        return "expansion_drop"
    if _first_rank(raw_vector_ids, {section_id}) is not None or _first_rank(raw_lexical_ids, {section_id}) is not None:
        return "merge_or_expansion_drop"
    if _doc_rank(_ids_from_snapshot(snapshot, "local_probe_top20_ids"), parent_id) is not None:
        return "section_miss"
    return "doc_miss"


def _projection_selected_evidence_ids(snapshot: dict) -> list[str]:
    return _unique_ids(
        _ids_from_snapshot(snapshot, "selected_evidence_resolved_note_ids"),
        _ids_from_snapshot(snapshot, "context_selected_evidence_ids"),
        _ids_from_snapshot(snapshot, "selected_evidence_ids"),
    )


def _projection_drop_reason(
    snapshot: dict,
    section_id: str,
    parent_id: str,
    expected_ids: set[str],
) -> str | None:
    final_ids = _ids_from_snapshot(snapshot, "ranked_ids")
    match_ids = _unique_ids(
        _ids_from_snapshot(snapshot, "selected_match_resolved_note_ids"),
        _ids_from_snapshot(snapshot, "selected_match_ids"),
    )
    citation_ids = _unique_ids(
        _ids_from_snapshot(snapshot, "selected_citation_resolved_note_ids"),
        _ids_from_snapshot(snapshot, "selected_citation_note_ids"),
    )
    projected_ids = _unique_ids(match_ids, citation_ids)

    if _first_rank(projected_ids, expected_ids) is not None:
        return "projection_limit_shadowed"

    same_doc_projected = [
        note_id for note_id in projected_ids
        if _parent_id(note_id) == parent_id and note_id not in {section_id, parent_id}
    ]
    same_doc_final = [
        note_id for note_id in final_ids
        if _parent_id(note_id) == parent_id and note_id not in {section_id, parent_id}
    ]
    if same_doc_projected or same_doc_final:
        return "same_doc_projection_shadow"

    raw_citation_ids = _ids_from_snapshot(snapshot, "selected_citation_note_ids")
    citation_source_refs = _ids_from_snapshot(snapshot, "selected_citation_source_refs")
    if citation_source_refs and not citation_ids:
        return "citation_mapping_failed"
    if raw_citation_ids and not citation_ids:
        return "citation_mapping_failed"
    if _first_rank(raw_citation_ids, expected_ids) is not None and _first_rank(citation_ids, expected_ids) is None:
        return "citation_mapping_failed"

    if not match_ids and not citation_ids:
        return "selected_match_citation_missing"
    if not match_ids:
        return "selected_match_missing"
    if not citation_ids:
        return "selected_citation_missing"
    return "selected_evidence_projection_missing"


def _context_drop_reason(snapshot: dict, expected_ids: set[str]) -> str | None:
    details = snapshot.get("context_dropped_evidence_reasons")
    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "")
            if source_id not in expected_ids:
                continue
            reason = str(item.get("drop_reason") or "").strip()
            if reason == "char_budget":
                return "char_budget_drop"
            if reason == "max_items":
                return "max_items_drop"
            if reason == "stale_version":
                return "stale_version_drop"
            if reason == "mmr_not_selected":
                return "mmr_drop"
            if reason:
                return f"{reason}_drop"
    return None


def _note_ids(notes: list[KnowledgeNote]) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for note in notes:
        if note.id in seen:
            continue
        seen.add(note.id)
        ids.append(note.id)
    return ids


def _notes_to_evidence_units(notes: list[KnowledgeNote]) -> list[EvidenceUnit]:
    return [
        EvidenceUnit(
            id=note.id,
            text=note.content or note.summary or note.title,
            title=note.title or "",
            parent_id=note.parent_note_id,
            kind="section" if note.parent_note_id else "document",
        )
        for note in notes
    ]


def _diagnose_retrieval(
    *,
    section_id: str,
    parent_id: str,
    ranked_ids: list[str],
    local_probe_ids: list[str],
    retrieval_health: dict,
) -> dict:
    expected = {section_id, parent_id}
    pre_ids = [str(item) for item in retrieval_health.get("pre_enrichment_match_ids", [])]
    post_ids = [str(item) for item in retrieval_health.get("post_enrichment_match_ids", [])]
    selected_ids = [str(item) for item in retrieval_health.get("context_selected_evidence_ids", [])]
    dropped_ids = [str(item) for item in retrieval_health.get("context_dropped_evidence_ids", [])]

    final_rank = _first_rank(ranked_ids, expected)
    local_probe_rank = _first_rank(local_probe_ids, expected)
    pre_rank = _first_rank(pre_ids, expected)
    post_rank = _first_rank(post_ids, expected)
    selected_rank = _first_rank(selected_ids, expected)
    dropped_rank = _first_rank(dropped_ids, expected)
    local_probe_doc_rank = _doc_rank(local_probe_ids, parent_id)
    final_doc_rank = _doc_rank(ranked_ids, parent_id)

    if final_rank is not None:
        miss_type = "hit"
    elif local_probe_doc_rank is None:
        miss_type = "doc_miss"
    elif local_probe_rank is None:
        miss_type = "section_miss"
    elif post_rank is None:
        miss_type = "enrichment_gap"
    elif dropped_rank is not None:
        miss_type = "budget_or_mmr_drop"
    elif selected_rank is not None:
        miss_type = "projection_gap"
    else:
        miss_type = "rerank_drop"

    return {
        "miss_type": miss_type,
        "final_rank": final_rank,
        "final_doc_rank": final_doc_rank,
        "local_probe_rank": local_probe_rank,
        "local_probe_doc_rank": local_probe_doc_rank,
        "pre_enrichment_rank": pre_rank,
        "post_enrichment_rank": post_rank,
        "context_selected_rank": selected_rank,
        "context_dropped_rank": dropped_rank,
        "gold_doc_in_local_probe": local_probe_doc_rank is not None,
        "gold_section_or_parent_in_local_probe": local_probe_rank is not None,
        "gold_section_or_parent_pre_enrichment": pre_rank is not None,
        "gold_section_or_parent_post_enrichment": post_rank is not None,
    }


def _summarize_diagnostics(diagnostics: list[dict] | None) -> dict | None:
    if not diagnostics:
        return None

    def ids_for(diag: dict, key: str) -> list[str]:
        value = diag.get(key)
        return [str(item) for item in value] if isinstance(value, list) else []

    def doc_hit(ids: list[str], parent_id: str, cutoff: int) -> bool:
        return any(_parent_id(note_id) == parent_id for note_id in ids[:cutoff])

    def section_hit(ids: list[str], section_id: str, cutoff: int) -> bool:
        return section_id in ids[:cutoff]

    summary: dict[str, object] = {"num_queries": len(diagnostics)}
    miss_counts: dict[str, int] = {}
    final_drop_counts: dict[str, int] = {}
    section_drop_counts: dict[str, int] = {}
    for diag in diagnostics:
        miss_type = str(diag.get("miss_type") or "unknown")
        miss_counts[miss_type] = miss_counts.get(miss_type, 0) + 1
        drop_reason = diag.get("final_drop_reason")
        if drop_reason:
            key = str(drop_reason)
            final_drop_counts[key] = final_drop_counts.get(key, 0) + 1
        section_drop_reason = diag.get("section_drop_reason")
        if section_drop_reason:
            key = str(section_drop_reason)
            section_drop_counts[key] = section_drop_counts.get(key, 0) + 1
    summary["miss_type_counts"] = miss_counts
    if final_drop_counts:
        summary["final_drop_reason_counts"] = final_drop_counts
    if section_drop_counts:
        summary["section_drop_reason_counts"] = section_drop_counts
    llm_score_health = _summarize_llm_score_health(diagnostics)
    if llm_score_health is not None:
        summary["llm_score_health"] = llm_score_health
    llm_score_delta_summary = _summarize_llm_score_deltas(diagnostics)
    if llm_score_delta_summary is not None:
        summary["llm_score_rank_delta"] = llm_score_delta_summary
    semantic_selector_summary = _summarize_semantic_selector(diagnostics)
    if semantic_selector_summary is not None:
        summary["semantic_selector"] = semantic_selector_summary
    semantic_policy_summary = _summarize_semantic_policy_selector(diagnostics)
    if semantic_policy_summary is not None:
        summary["semantic_policy"] = semantic_policy_summary
    section_gap_summary = _summarize_section_gaps(diagnostics)
    if section_gap_summary is not None:
        summary["section_gap_analysis"] = section_gap_summary

    stages = _DIAGNOSTIC_STAGE_KEYS
    cutoffs = (1, 3, 5, 10, 20)

    for stage, key in stages.items():
        observed = 0
        first_relevant_ranks: list[int] = []
        doc_ranks: list[int] = []
        section_hits = {cutoff: 0 for cutoff in cutoffs}
        doc_hits = {cutoff: 0 for cutoff in cutoffs}
        any_hits = {cutoff: 0 for cutoff in cutoffs}

        for diag in diagnostics:
            expected_ids = [str(item) for item in diag.get("expected_note_ids", [])]
            if len(expected_ids) < 2:
                continue
            section_id, parent_id = expected_ids[0], expected_ids[1]
            ids = ids_for(diag, key)
            if not ids:
                continue
            observed += 1
            expected = {section_id, parent_id}

            first_rank = _first_rank(ids, expected)
            if first_rank is not None:
                first_relevant_ranks.append(first_rank)
            doc_rank = _doc_rank(ids, parent_id)
            if doc_rank is not None:
                doc_ranks.append(doc_rank)

            for cutoff in cutoffs:
                top_ids = ids[:cutoff]
                if section_hit(top_ids, section_id, cutoff):
                    section_hits[cutoff] += 1
                if doc_hit(top_ids, parent_id, cutoff):
                    doc_hits[cutoff] += 1
                if expected & set(top_ids):
                    any_hits[cutoff] += 1

        if observed == 0:
            continue

        stage_summary: dict[str, object] = {
            "observed_queries": observed,
            "mean_first_relevant_rank": (
                round(sum(first_relevant_ranks) / len(first_relevant_ranks), 4)
                if first_relevant_ranks else None
            ),
            "mean_doc_rank": (
                round(sum(doc_ranks) / len(doc_ranks), 4)
                if doc_ranks else None
            ),
        }
        for cutoff in cutoffs:
            stage_summary[f"section_recall_{cutoff}"] = round(section_hits[cutoff] / observed, 4)
            stage_summary[f"doc_recall_{cutoff}"] = round(doc_hits[cutoff] / observed, 4)
            stage_summary[f"any_recall_{cutoff}"] = round(any_hits[cutoff] / observed, 4)
        summary[stage] = stage_summary

    return summary


def _summarize_section_gaps(diagnostics: list[dict]) -> dict | None:
    observed = 0
    doc_top1 = 0
    doc_top1_section_below_top3 = 0
    doc_top1_section_below_top5 = 0
    section_missing_final = 0
    doc_top1_gap_cases: list[dict[str, object]] = []
    same_doc_wrong_section_cases: list[dict[str, object]] = []

    for diag in diagnostics:
        expected_ids = [str(item) for item in diag.get("expected_note_ids", [])]
        if len(expected_ids) < 2:
            continue
        section_id, parent_id = expected_ids[0], expected_ids[1]
        final_ids = _ids_from_snapshot(diag, "ranked_ids")
        if not final_ids:
            continue
        observed += 1
        section_rank = _first_rank(final_ids, {section_id})
        parent_rank = _first_rank(final_ids, {parent_id})
        doc_rank = _doc_rank(final_ids, parent_id)
        same_doc_wrong_ids = [
            note_id for note_id in final_ids[:5]
            if _parent_id(note_id) == parent_id and note_id not in {section_id, parent_id}
        ]

        if section_rank is None:
            section_missing_final += 1
        if doc_rank == 1:
            doc_top1 += 1
            if section_rank is None or section_rank > 3:
                doc_top1_section_below_top3 += 1
                doc_top1_gap_cases.append({
                    "query_id": diag.get("query_id"),
                    "query_text": diag.get("query_text"),
                    "section_rank": section_rank,
                    "parent_rank": parent_rank,
                    "doc_rank": doc_rank,
                    "top5_ids": final_ids[:5],
                })
            if section_rank is None or section_rank > 5:
                doc_top1_section_below_top5 += 1
        if same_doc_wrong_ids and (section_rank is None or section_rank > 3):
            same_doc_wrong_section_cases.append({
                "query_id": diag.get("query_id"),
                "query_text": diag.get("query_text"),
                "section_rank": section_rank,
                "parent_rank": parent_rank,
                "same_doc_wrong_top5_ids": same_doc_wrong_ids,
            })

    if observed == 0:
        return None

    return {
        "observed_queries": observed,
        "doc_top1_count": doc_top1,
        "doc_top1_rate": round(doc_top1 / observed, 4),
        "doc_top1_section_below_top3_count": doc_top1_section_below_top3,
        "doc_top1_section_below_top3_rate": round(doc_top1_section_below_top3 / max(doc_top1, 1), 4),
        "doc_top1_section_below_top5_count": doc_top1_section_below_top5,
        "doc_top1_section_below_top5_rate": round(doc_top1_section_below_top5 / max(doc_top1, 1), 4),
        "section_missing_final_count": section_missing_final,
        "section_missing_final_rate": round(section_missing_final / observed, 4),
        "doc_top1_gap_cases": doc_top1_gap_cases[:10],
        "same_doc_wrong_section_cases": same_doc_wrong_section_cases[:10],
    }


def _summarize_llm_score_deltas(diagnostics: list[dict]) -> dict | None:
    observed = 0
    score_any_effect_counts: dict[str, int] = {}
    final_any_effect_counts: dict[str, int] = {}
    score_section_effect_counts: dict[str, int] = {}
    final_section_effect_counts: dict[str, int] = {}
    score_any_deltas: list[int] = []
    final_any_deltas: list[int] = []
    score_section_deltas: list[int] = []
    final_section_deltas: list[int] = []
    rescued_cases: list[dict[str, object]] = []
    harmed_cases: list[dict[str, object]] = []
    rescued_query_type_counts: dict[str, int] = {}
    harmed_query_type_counts: dict[str, int] = {}
    rescued_fusion_rank_bucket_counts: dict[str, int] = {}
    harmed_fusion_rank_bucket_counts: dict[str, int] = {}
    rescued_gold_section_bucket_counts: dict[str, int] = {}
    harmed_gold_section_bucket_counts: dict[str, int] = {}

    for diag in diagnostics:
        delta = diag.get("llm_score_rank_delta")
        if not isinstance(delta, dict):
            continue
        observed += 1

        def count(target: dict[str, int], key: str) -> None:
            value = str(delta.get(key) or "unknown")
            target[value] = target.get(value, 0) + 1

        count(score_any_effect_counts, "score_any_effect")
        count(final_any_effect_counts, "final_any_effect")
        count(score_section_effect_counts, "score_section_effect")
        count(final_section_effect_counts, "final_section_effect")

        for key, target in (
            ("score_any_delta", score_any_deltas),
            ("final_any_delta", final_any_deltas),
            ("score_section_delta", score_section_deltas),
            ("final_section_delta", final_section_deltas),
        ):
            value = delta.get(key)
            if isinstance(value, int):
                target.append(value)

        case = {
            "query_id": diag.get("query_id"),
            "query_text": diag.get("query_text"),
            "gold_section_bucket": _gold_section_bucket(diag),
            "fusion_any_rank": delta.get("fusion_any_rank"),
            "llm_scored_any_rank": delta.get("llm_scored_any_rank"),
            "final_any_rank": delta.get("final_any_rank"),
            "final_any_delta": delta.get("final_any_delta"),
            "fusion_section_rank": delta.get("fusion_section_rank"),
            "llm_scored_section_rank": delta.get("llm_scored_section_rank"),
            "final_section_rank": delta.get("final_section_rank"),
            "final_section_delta": delta.get("final_section_delta"),
        }
        final_effect = str(delta.get("final_any_effect") or "")
        if final_effect in {"improved", "introduced"}:
            rescued_cases.append(case)
            _increment_count(rescued_query_type_counts, _query_type_bucket(str(diag.get("query_text") or "")))
            _increment_count(
                rescued_fusion_rank_bucket_counts,
                _rank_bucket(delta.get("fusion_any_rank")),
            )
            _increment_count(rescued_gold_section_bucket_counts, _gold_section_bucket(diag))
        elif final_effect in {"harmed", "dropped"}:
            harmed_cases.append(case)
            _increment_count(harmed_query_type_counts, _query_type_bucket(str(diag.get("query_text") or "")))
            _increment_count(
                harmed_fusion_rank_bucket_counts,
                _rank_bucket(delta.get("fusion_any_rank")),
            )
            _increment_count(harmed_gold_section_bucket_counts, _gold_section_bucket(diag))

    if observed == 0:
        return None

    def mean(values: list[int]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    return {
        "observed_queries": observed,
        "score_any_effect_counts": score_any_effect_counts,
        "final_any_effect_counts": final_any_effect_counts,
        "score_section_effect_counts": score_section_effect_counts,
        "final_section_effect_counts": final_section_effect_counts,
        "mean_score_any_delta": mean(score_any_deltas),
        "mean_final_any_delta": mean(final_any_deltas),
        "mean_score_section_delta": mean(score_section_deltas),
        "mean_final_section_delta": mean(final_section_deltas),
        "rescued_query_type_counts": rescued_query_type_counts,
        "harmed_query_type_counts": harmed_query_type_counts,
        "rescued_fusion_rank_bucket_counts": rescued_fusion_rank_bucket_counts,
        "harmed_fusion_rank_bucket_counts": harmed_fusion_rank_bucket_counts,
        "rescued_gold_section_bucket_counts": rescued_gold_section_bucket_counts,
        "harmed_gold_section_bucket_counts": harmed_gold_section_bucket_counts,
        "rescued_cases": rescued_cases[:20],
        "harmed_cases": harmed_cases[:20],
    }


def _summarize_llm_score_health(diagnostics: list[dict]) -> dict | None:
    observed = 0
    configured = 0
    errors: dict[str, int] = {}
    skipped_counts: dict[str, int] = {}
    scored_counts: list[int] = []
    candidate_counts: list[int] = []
    full_score_coverage = 0
    gated_candidates: list[int] = []
    threshold_values: list[float] = []
    margin_values: list[float] = []

    for diag in diagnostics:
        has_scores = "llm_score_values" in diag
        has_skip = bool(diag.get("llm_score_skipped_reason"))
        if not has_scores and not has_skip:
            continue
        observed += 1
        if diag.get("llm_rerank_model_configured"):
            configured += 1
        skip_reason = diag.get("llm_score_skipped_reason")
        if skip_reason:
            key = str(skip_reason)
            skipped_counts[key] = skipped_counts.get(key, 0) + 1
        error = diag.get("llm_rerank_error")
        if error:
            key = str(error)[:160]
            errors[key] = errors.get(key, 0) + 1

        scores = diag.get("llm_score_values")
        score_values = [float(value) for value in scores.values()] if isinstance(scores, dict) else []
        candidates = _ids_from_snapshot(diag, "fusion_before_llm_top20_ids")
        scored_counts.append(len(score_values))
        candidate_counts.append(len(candidates))
        if candidates and len(score_values) >= len(candidates):
            full_score_coverage += 1

        threshold = diag.get("llm_score_threshold")
        margin = diag.get("llm_score_confidence_margin")
        if isinstance(threshold, (int, float)):
            threshold_values.append(float(threshold))
        if isinstance(margin, (int, float)):
            margin_values.append(float(margin))

        if score_values:
            threshold_value = float(threshold) if isinstance(threshold, (int, float)) else 0.0
            margin_value = float(margin) if isinstance(margin, (int, float)) else 0.0
            eligible = [value for value in score_values if value >= threshold_value]
            if margin_value > 0 and eligible:
                sorted_scores = sorted(eligible, reverse=True)
                top_score = sorted_scores[0]
                second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
                if top_score - second_score < margin_value:
                    eligible = []
            gated_candidates.append(len(eligible))

    if observed == 0:
        return None

    def mean(values: list[int | float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    return {
        "observed_queries": observed,
        "model_configured_queries": configured,
        "error_counts": errors,
        "skipped_counts": skipped_counts,
        "mean_scored_candidates": mean(scored_counts),
        "mean_candidate_count": mean(candidate_counts),
        "full_score_coverage_rate": round(full_score_coverage / observed, 4),
        "mean_gated_candidate_count": mean(gated_candidates),
        "score_threshold": mean(threshold_values),
        "confidence_margin": mean(margin_values),
    }


def _summarize_semantic_selector(diagnostics: list[dict]) -> dict | None:
    observed = 0
    configured = 0
    triggered = 0
    skipped_counts: dict[str, int] = {}
    trigger_counts: dict[str, int] = {}
    trigger_mode_counts: dict[str, int] = {}
    preserve_top_k_counts: dict[str, int] = {}
    response_model_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    effect_counts: dict[str, int] = {}
    sufficiency_counts: dict[str, int] = {}
    answer_type_counts: dict[str, int] = {}
    candidate_counts: list[int] = []
    judgment_counts: list[int] = []
    primary_counts: list[int] = []
    score_values: list[float] = []
    retry_attempts: list[int] = []
    retry_error_counts: dict[str, int] = {}
    rescued_cases: list[dict[str, object]] = []
    harmed_cases: list[dict[str, object]] = []

    for diag in diagnostics:
        if (
            "semantic_selector_candidate_ids" not in diag
            and "semantic_selector_skipped_reason" not in diag
            and "semantic_selector_judgments" not in diag
        ):
            continue
        observed += 1
        if diag.get("semantic_selector_model_configured"):
            configured += 1
        response_model = diag.get("semantic_selector_response_model")
        if response_model:
            _increment_count(response_model_counts, str(response_model))
        trigger_mode = diag.get("semantic_selector_trigger_mode")
        if trigger_mode:
            _increment_count(trigger_mode_counts, str(trigger_mode))
        preserve_top_k = diag.get("semantic_selector_preserve_top_k")
        if isinstance(preserve_top_k, int):
            _increment_count(preserve_top_k_counts, str(preserve_top_k))
        trigger = diag.get("semantic_selector_trigger_reason")
        if trigger:
            triggered += 1
            _increment_count(trigger_counts, str(trigger))
        skip = diag.get("semantic_selector_skipped_reason")
        if skip:
            _increment_count(skipped_counts, str(skip))
        error = diag.get("semantic_selector_error")
        if error:
            _increment_count(error_counts, str(error)[:160])
        retry_attempt = diag.get("semantic_selector_retry_attempts")
        if isinstance(retry_attempt, int):
            retry_attempts.append(retry_attempt)
        retry_errors = diag.get("semantic_selector_retry_errors")
        if isinstance(retry_errors, list):
            for retry_error in retry_errors:
                _increment_count(retry_error_counts, str(retry_error)[:160])

        candidates = _ids_from_snapshot(diag, "semantic_selector_candidate_ids")
        candidate_counts.append(len(candidates))
        judgments = diag.get("semantic_selector_judgments")
        judgment_map = judgments if isinstance(judgments, dict) else {}
        judgment_counts.append(len(judgment_map))
        primary_count = 0
        for raw in judgment_map.values():
            if not isinstance(raw, dict):
                continue
            sufficiency = str(raw.get("evidence_sufficiency") or "unknown")
            answer_type = str(raw.get("answer_type_match") or "unknown")
            _increment_count(sufficiency_counts, sufficiency)
            _increment_count(answer_type_counts, answer_type)
            if raw.get("should_be_primary_evidence"):
                primary_count += 1
            combined = raw.get("combined_score")
            if isinstance(combined, (int, float)):
                score_values.append(float(combined))
        primary_counts.append(primary_count)

        expected_ids = [str(item) for item in diag.get("expected_note_ids", [])]
        if len(expected_ids) < 2:
            continue
        expected = {expected_ids[0], expected_ids[1]}
        before_rank = _first_rank(_ids_from_snapshot(diag, "v2_before_semantic_selector_top20_ids"), expected)
        final_rank = _first_rank(_ids_from_snapshot(diag, "ranked_ids"), expected)
        effect = _rank_effect(before_rank, final_rank)
        _increment_count(effect_counts, effect)
        case = {
            "query_id": diag.get("query_id"),
            "query_text": diag.get("query_text"),
            "before_rank": before_rank,
            "final_rank": final_rank,
            "trigger_reason": trigger,
            "skip_reason": skip,
        }
        if effect in {"improved", "introduced"}:
            rescued_cases.append(case)
        elif effect in {"harmed", "dropped"}:
            harmed_cases.append(case)

    if observed == 0:
        return None

    def mean(values: list[int | float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    return {
        "observed_queries": observed,
        "model_configured_queries": configured,
        "triggered_queries": triggered,
        "trigger_counts": trigger_counts,
        "trigger_mode_counts": trigger_mode_counts,
        "preserve_top_k_counts": preserve_top_k_counts,
        "response_model_counts": response_model_counts,
        "skipped_counts": skipped_counts,
        "error_counts": error_counts,
        "effect_counts": effect_counts,
        "mean_candidate_count": mean(candidate_counts),
        "mean_judgment_count": mean(judgment_counts),
        "mean_primary_count": mean(primary_counts),
        "mean_combined_score": mean(score_values),
        "total_retry_attempts": sum(retry_attempts),
        "retry_query_count": sum(1 for value in retry_attempts if value > 0),
        "retry_error_counts": retry_error_counts,
        "sufficiency_counts": sufficiency_counts,
        "answer_type_counts": answer_type_counts,
        "rescued_cases": rescued_cases[:20],
        "harmed_cases": harmed_cases[:20],
    }


def _summarize_semantic_policy_selector(diagnostics: list[dict]) -> dict | None:
    observed = 0
    configured = 0
    intervened = 0
    action_counts: dict[str, int] = {}
    ambiguity_counts: dict[str, int] = {}
    applied_reason_counts: dict[str, int] = {}
    response_model_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    skipped_counts: dict[str, int] = {}
    effect_counts: dict[str, int] = {}
    retry_attempts: list[int] = []
    retry_error_counts: dict[str, int] = {}
    confidence_values: list[float] = []
    rescued_cases: list[dict[str, object]] = []
    harmed_cases: list[dict[str, object]] = []

    for diag in diagnostics:
        if "semantic_policy" not in diag and "semantic_policy_candidate_ids" not in diag:
            continue
        observed += 1
        if diag.get("semantic_policy_model_configured"):
            configured += 1
        response_model = diag.get("semantic_policy_response_model")
        if response_model:
            _increment_count(response_model_counts, str(response_model))
        skip = diag.get("semantic_policy_skipped_reason")
        if skip:
            _increment_count(skipped_counts, str(skip))
        error = diag.get("semantic_policy_error")
        if error:
            _increment_count(error_counts, str(error)[:160])
        applied_reason = diag.get("semantic_policy_applied_reason")
        if applied_reason:
            _increment_count(applied_reason_counts, str(applied_reason))
        retry_attempt = diag.get("semantic_policy_retry_attempts")
        if isinstance(retry_attempt, int):
            retry_attempts.append(retry_attempt)
        retry_errors = diag.get("semantic_policy_retry_errors")
        if isinstance(retry_errors, list):
            for retry_error in retry_errors:
                _increment_count(retry_error_counts, str(retry_error)[:160])

        policy = diag.get("semantic_policy")
        policy_map = policy if isinstance(policy, dict) else {}
        action = str(policy_map.get("action") or "unknown")
        ambiguity = str(policy_map.get("ambiguity_type") or "unknown")
        _increment_count(action_counts, action)
        _increment_count(ambiguity_counts, ambiguity)
        if policy_map.get("should_intervene"):
            intervened += 1
        confidence = policy_map.get("confidence")
        if isinstance(confidence, (int, float)):
            confidence_values.append(float(confidence))

        expected_ids = [str(item) for item in diag.get("expected_note_ids", [])]
        if len(expected_ids) < 2:
            continue
        expected = {expected_ids[0], expected_ids[1]}
        before_rank = _first_rank(_ids_from_snapshot(diag, "v2_before_semantic_policy_top20_ids"), expected)
        final_rank = _first_rank(_ids_from_snapshot(diag, "ranked_ids"), expected)
        effect = _rank_effect(before_rank, final_rank)
        _increment_count(effect_counts, effect)
        case = {
            "query_id": diag.get("query_id"),
            "query_text": diag.get("query_text"),
            "before_rank": before_rank,
            "final_rank": final_rank,
            "action": action,
            "ambiguity_type": ambiguity,
            "applied_reason": applied_reason,
        }
        if effect in {"improved", "introduced"}:
            rescued_cases.append(case)
        elif effect in {"harmed", "dropped"}:
            harmed_cases.append(case)

    if observed == 0:
        return None

    def mean(values: list[int | float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    return {
        "observed_queries": observed,
        "model_configured_queries": configured,
        "intervened_queries": intervened,
        "action_counts": action_counts,
        "ambiguity_counts": ambiguity_counts,
        "applied_reason_counts": applied_reason_counts,
        "response_model_counts": response_model_counts,
        "skipped_counts": skipped_counts,
        "error_counts": error_counts,
        "effect_counts": effect_counts,
        "mean_confidence": mean(confidence_values),
        "total_retry_attempts": sum(retry_attempts),
        "retry_query_count": sum(1 for value in retry_attempts if value > 0),
        "retry_error_counts": retry_error_counts,
        "rescued_cases": rescued_cases[:20],
        "harmed_cases": harmed_cases[:20],
    }


def _increment_count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _query_type_bucket(query_text: str) -> str:
    normalized = query_text.strip().lower()
    first = normalized.split(maxsplit=1)[0].strip(".,?!:;") if normalized else ""
    if first in {"is", "are", "was", "were", "do", "does", "did", "can", "could", "should", "would", "has", "have"}:
        return "yes_no"
    if first in {"what", "how", "why", "when", "where", "which", "who"}:
        return first
    return "other"


def _rank_bucket(rank: object) -> str:
    if not isinstance(rank, int):
        return "missing"
    if rank <= 1:
        return "top1"
    if rank <= 3:
        return "top3"
    if rank <= 5:
        return "top5"
    if rank <= 10:
        return "top10"
    return "over10"


def _gold_section_bucket(diag: dict) -> str:
    expected_ids = [str(item) for item in diag.get("expected_note_ids", [])]
    if not expected_ids:
        return "missing"
    return _section_position_bucket(expected_ids[0])


def _section_position_bucket(note_id: str) -> str:
    match = re.search(r"_sec_(\d+)$", note_id)
    if match is None:
        return "parent"
    index = int(match.group(1))
    if index == 0:
        return "sec0"
    if index <= 2:
        return "early_sec1_2"
    if index <= 5:
        return "early_mid_sec3_5"
    if index <= 10:
        return "mid_sec6_10"
    return "late_sec11_plus"


def _get_eval_plan(query: RAGBenchQuery, settings: Settings, context: BenchmarkContext):
    from personal_agent.planning.query_planner import plan_retrieval

    if context.planner_cache is None:
        return plan_retrieval(query.query_text, "", settings), False
    if query.query_id in context.planner_cache:
        return context.planner_cache[query.query_id], True
    result = plan_retrieval(query.query_text, "", settings)
    context.planner_cache[query.query_id] = result
    return result, False


def _new_eval_store(
    settings: Settings,
    docs: dict[str, RAGBenchDoc],
    *,
    user_id: str = "ragbench_eval",
):
    from pathlib import Path
    import tempfile
    from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore

    tmp_dir = Path(tempfile.mkdtemp(prefix="ragbench_eval_"))
    store = PostgresMemoryStore(
        data_dir=tmp_dir,
        postgres_url=settings.postgres_url,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.openai.embedding_model,
        embedding_api_key=settings.openai.embedding_api_key or settings.openai.api_key,
        embedding_base_url=settings.openai.embedding_base_url or settings.openai.base_url,
    )
    store.ensure_schema()
    store.clear_user_data(user_id, remove_uploaded_files=False)
    notes = [
        note.model_copy(update={"user_id": user_id})
        for note in corpus_to_notes(docs)
    ]
    for note in notes:
        store.add_note(note)
    return store, notes


def _attach_graph_episode_ids_to_store(store, notes: list[KnowledgeNote], episode_to_note_id: dict[str, str]) -> None:
    note_by_id = {note.id: note for note in notes}
    for episode_uuid, note_id in episode_to_note_id.items():
        note = note_by_id.get(note_id)
        if note is None:
            continue
        # graph_episode_uuid is a nested field (note.graph.episode_uuid); a flat
        # model_copy update is silently dropped by pydantic, so set it explicitly.
        updated = note.model_copy(deep=True)
        updated.graph.episode_uuid = episode_uuid
        store.add_note(updated)


def _ensure_eval_graph_mapping(
    *,
    graph_store: GraphitiStore,
    notes: list[KnowledgeNote],
    context: BenchmarkContext,
) -> dict[str, str]:
    if not graph_store.configured():
        return {}
    return _ensure_graphiti_corpus(
        graph_store=graph_store,
        notes=notes,
        user_id=context.graphiti_user_id,
        reset=context.reset_graphiti,
        manifest_path=context.graphiti_manifest_path,
        note_mode=context.graphiti_note_mode,
        continue_on_ingest_error=context.graphiti_continue_on_ingest_error,
    )


def _build_structural_index(docs: dict[str, RAGBenchDoc]) -> _StructuralIndex:
    graph_docs: list[_StructuralDoc] = []
    sections: list[_StructuralSection] = []
    document_frequency: dict[str, int] = {}

    for doc_id, doc in docs.items():
        parent_id = f"ragbench_{doc_id}"
        doc_tokens = set(_structural_tokens(f"{doc.title}\n{doc.abstract}"))
        doc_sections: list[_StructuralSection] = []
        for index, section_text in enumerate(doc.sections):
            token_sequence = tuple(_structural_tokens(section_text))
            section = _StructuralSection(
                note_id=f"{parent_id}_sec_{index}",
                parent_id=parent_id,
                doc_id=doc_id,
                index=index,
                tokens=set(token_sequence),
                token_sequence=token_sequence,
                text=section_text,
            )
            doc_sections.append(section)
            sections.append(section)
            for token in section.tokens:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        graph_docs.append(
            _StructuralDoc(
                note_id=parent_id,
                doc_id=doc_id,
                tokens=doc_tokens,
                sections=doc_sections,
            )
        )

    return _StructuralIndex(
        docs=graph_docs,
        sections=sections,
        document_frequency=document_frequency,
        num_sections=max(1, len(sections)),
        sections_by_id={section.note_id: section for section in sections},
        docs_by_parent_id={doc.note_id: doc for doc in graph_docs},
    )


def _rank_structural_notes(query: str, graph: _StructuralIndex, *, limit: int) -> list[str]:
    query_tokens = _structural_tokens(query)
    if not query_tokens:
        return []

    section_scores: dict[str, float] = {}
    parent_scores: dict[str, float] = {}
    sections_by_id = {section.note_id: section for section in graph.sections}

    for doc in graph.docs:
        doc_score = _token_score(query_tokens, doc.tokens, graph)
        if doc_score > 0:
            parent_scores[doc.note_id] = doc_score * 0.8

        best_section_score = 0.0
        for section in doc.sections:
            local_score = _token_score(query_tokens, section.tokens, graph)
            propagated_score = local_score + doc_score * 0.25
            if propagated_score <= 0:
                continue
            section_scores[section.note_id] = propagated_score
            best_section_score = max(best_section_score, local_score)

        if best_section_score > 0:
            parent_scores[doc.note_id] = max(parent_scores.get(doc.note_id, 0.0), best_section_score * 0.7)
            for section in doc.sections:
                if section.note_id in section_scores:
                    section_scores[section.note_id] += best_section_score * 0.1

    scored_items: list[tuple[float, str]] = []
    scored_items.extend((score, note_id) for note_id, score in section_scores.items())
    scored_items.extend((score, note_id) for note_id, score in parent_scores.items())
    scored_items.sort(key=lambda item: (item[0], _structural_tiebreak(item[1], sections_by_id)), reverse=True)

    ranked: list[str] = []
    seen: set[str] = set()
    for _, note_id in scored_items:
        if note_id in seen:
            continue
        ranked.append(note_id)
        seen.add(note_id)
        if len(ranked) >= limit:
            break
    return ranked


def _rank_doc_first_sections(
    query: str,
    graph: _StructuralIndex,
    *,
    limit: int,
    top_docs: int,
) -> list[str]:
    query_tokens = _structural_tokens(query)
    if not query_tokens:
        return []

    doc_scores: list[tuple[float, _StructuralDoc]] = []
    section_local_scores: dict[str, float] = {}
    for doc in graph.docs:
        doc_score = _token_score(query_tokens, doc.tokens, graph)
        best_section_score = 0.0
        for section in doc.sections:
            section_score = _token_score(query_tokens, section.tokens, graph)
            section_local_scores[section.note_id] = section_score
            best_section_score = max(best_section_score, section_score)
        combined = doc_score * 0.55 + best_section_score * 0.85
        if combined > 0:
            doc_scores.append((combined, doc))
    doc_scores.sort(key=lambda item: (item[0], item[1].note_id), reverse=True)

    ranked: list[str] = []
    seen: set[str] = set()
    for doc_score, doc in doc_scores[:max(1, top_docs)]:
        section_scores: list[tuple[float, str]] = []
        for section in doc.sections:
            section_score = section_local_scores.get(section.note_id, 0.0)
            propagated = section_score + doc_score * 0.2
            if propagated <= 0:
                continue
            section_scores.append((propagated, section.note_id))
        section_scores.sort(key=lambda item: (item[0], item[1]), reverse=True)
        for _, note_id in section_scores:
            if note_id not in seen:
                ranked.append(note_id)
                seen.add(note_id)
                if len(ranked) >= limit:
                    return ranked
        if doc.note_id not in seen:
            ranked.append(doc.note_id)
            seen.add(doc.note_id)
            if len(ranked) >= limit:
                return ranked
    return ranked


def _refine_same_doc_sections(
    query: str,
    ranked_ids: list[str],
    graph: _StructuralIndex,
    *,
    limit: int,
    top_docs: int,
    secondary_weight: float,
) -> list[str]:
    if not ranked_ids:
        return []
    query_tokens = _structural_tokens(query)
    if not query_tokens:
        return ranked_ids[:limit]

    selected_parent_ids: list[str] = []
    seen_parents: set[str] = set()
    for note_id in ranked_ids:
        parent_id = _parent_id(note_id)
        if parent_id not in graph.docs_by_parent_id or parent_id in seen_parents:
            continue
        selected_parent_ids.append(parent_id)
        seen_parents.add(parent_id)
        if len(selected_parent_ids) >= max(1, top_docs):
            break
    if not selected_parent_ids:
        return ranked_ids[:limit]

    candidate_ids = ranked_ids[:limit]
    original_rank = {note_id: rank for rank, note_id in enumerate(candidate_ids, 1)}
    ranked_set = set(candidate_ids)
    refine_scores: dict[str, float] = {}
    for parent_id in selected_parent_ids:
        doc = graph.docs_by_parent_id[parent_id]
        for section in doc.sections:
            if section.note_id not in ranked_set:
                continue
            score = _section_direct_answer_score(query_tokens, section, graph)
            if score <= 0:
                continue
            refine_scores[section.note_id] = score

    if not refine_scores:
        return ranked_ids[:limit]
    return _rerank_section_slots(
        candidate_ids,
        section_scores=refine_scores,
        original_rank=original_rank,
        secondary_weight=secondary_weight,
    )


def _section_direct_answer_score(
    query_tokens: list[str],
    section: _StructuralSection,
    graph: _StructuralIndex,
) -> float:
    unique_query_tokens = list(dict.fromkeys(query_tokens))
    if not unique_query_tokens:
        return 0.0

    overlap = [token for token in unique_query_tokens if token in section.tokens]
    coverage = len(overlap) / len(unique_query_tokens)

    weighted = _token_score(query_tokens, section.tokens, graph)
    max_weighted = _token_score(query_tokens, set(unique_query_tokens), graph)
    weighted_coverage = weighted / max(max_weighted, 1e-9)

    rare_tokens = [
        token for token in unique_query_tokens
        if graph.document_frequency.get(token, 0) <= max(2, int(graph.num_sections * 0.08))
    ]
    rare_overlap = [token for token in rare_tokens if token in section.tokens]
    rare_coverage = len(rare_overlap) / len(rare_tokens) if rare_tokens else coverage

    section_bigrams = set(zip(section.token_sequence, section.token_sequence[1:]))
    query_bigrams = list(zip(query_tokens, query_tokens[1:]))
    phrase_coverage = (
        sum(1 for bigram in query_bigrams if bigram in section_bigrams) / len(query_bigrams)
        if query_bigrams else 0.0
    )

    lower_text = section.text[:1200].lower()
    cue_score = _direct_answer_cue_score(lower_text)
    background_penalty = _background_section_penalty(lower_text, section.index, coverage)

    score = (
        weighted_coverage * 0.42
        + coverage * 0.24
        + rare_coverage * 0.18
        + phrase_coverage * 0.10
        + cue_score * 0.06
        - background_penalty
    )
    return max(0.0, score)


def _direct_answer_cue_score(lower_text: str) -> float:
    cues = (
        "we define",
        "defined as",
        "is defined",
        "we show",
        "we prove",
        "we find",
        "we conclude",
        "the result",
        "our results",
        "therefore",
        "because",
        "by using",
        "using the",
        "can be",
        "is given by",
        "is equivalent",
    )
    return min(1.0, sum(1 for cue in cues if cue in lower_text) / 3.0)


def _background_section_penalty(lower_text: str, section_index: int, coverage: float) -> float:
    first_line = lower_text.splitlines()[0] if lower_text.splitlines() else lower_text[:80]
    background_headings = ("abstract", "introduction", "background", "related work", "preliminaries", "overview")
    if not any(heading in first_line for heading in background_headings):
        return 0.0
    if coverage >= 0.55:
        return 0.02
    return 0.04 if section_index <= 1 else 0.03


def _refine_same_doc_sections_by_passage_embedding(
    query: str,
    ranked_ids: list[str],
    graph: _StructuralIndex,
    *,
    settings: Settings,
    context: BenchmarkContext,
    limit: int,
    top_docs: int,
    secondary_weight: float,
) -> list[str]:
    if not ranked_ids:
        return []
    candidate_ids = ranked_ids[:limit]
    selected_parent_ids: list[str] = []
    seen_parents: set[str] = set()
    for note_id in candidate_ids:
        parent_id = _parent_id(note_id)
        if parent_id not in graph.docs_by_parent_id or parent_id in seen_parents:
            continue
        selected_parent_ids.append(parent_id)
        seen_parents.add(parent_id)
        if len(selected_parent_ids) >= max(1, top_docs):
            break
    if not selected_parent_ids:
        return candidate_ids

    original_rank = {note_id: rank for rank, note_id in enumerate(candidate_ids, 1)}
    candidate_set = set(candidate_ids)
    sections: list[_StructuralSection] = []
    for parent_id in selected_parent_ids:
        doc = graph.docs_by_parent_id[parent_id]
        sections.extend(section for section in doc.sections if section.note_id in candidate_set)
    if not sections:
        return candidate_ids

    query_vector = _embed_eval_texts(settings, [query], context.passage_embedding_cache).get(query)
    if query_vector is None:
        return candidate_ids

    passage_refs: list[tuple[str, str]] = []
    passage_texts: list[str] = []
    for section in sections:
        for passage in _section_passages(section.text):
            passage_refs.append((passage, section.note_id))
            passage_texts.append(passage)
    passage_vectors = _embed_eval_texts(settings, passage_texts, context.passage_embedding_cache)
    section_scores: dict[str, float] = {}
    for passage, section_id in passage_refs:
        vector = passage_vectors.get(passage)
        if vector is None:
            continue
        similarity = _cosine_similarity(query_vector, vector)
        section_scores[section_id] = max(section_scores.get(section_id, -1.0), similarity)
    if not section_scores:
        return candidate_ids

    return _rerank_section_slots(
        candidate_ids,
        section_scores=section_scores,
        original_rank=original_rank,
        secondary_weight=secondary_weight,
    )


def _rerank_section_slots(
    candidate_ids: list[str],
    *,
    section_scores: dict[str, float],
    original_rank: dict[str, int],
    secondary_weight: float,
) -> list[str]:
    section_positions = [
        index for index, note_id in enumerate(candidate_ids)
        if note_id in section_scores
    ]
    if len(section_positions) <= 1:
        return candidate_ids

    section_ids = [candidate_ids[index] for index in section_positions]
    reranked_section_ids = sorted(
        section_ids,
        key=lambda note_id: (
            -(
                1.0 / (60 + original_rank[note_id])
                + secondary_weight * max(0.0, section_scores.get(note_id, 0.0))
            ),
            original_rank[note_id],
            note_id,
        ),
    )
    reranked = list(candidate_ids)
    for position, note_id in zip(section_positions, reranked_section_ids, strict=False):
        reranked[position] = note_id
    return reranked


def _section_passages(text: str, *, max_chars: int = 900, overlap_chars: int = 120) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    passages: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if current and len(current) + len(sentence) + 1 > max_chars:
            passages.append(current)
            overlap = current[-overlap_chars:].strip()
            current = f"{overlap} {sentence}".strip() if overlap else sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence
    if current:
        passages.append(current)
    return passages[:8]


def _embed_eval_texts(
    settings: Settings,
    texts: list[str],
    cache: dict[str, list[float]],
    *,
    batch_size: int = 32,
) -> dict[str, list[float]]:
    cleaned = [text[:8000] for text in texts if text.strip()]
    if not cleaned:
        return {}

    api_key = settings.openai.embedding_api_key or settings.openai.api_key
    base_url = settings.openai.embedding_base_url or settings.openai.base_url
    model = settings.openai.embedding_model
    if not api_key:
        return {}

    result: dict[str, list[float]] = {}
    missing: list[str] = []
    for text in cleaned:
        key = _embedding_cache_key(model, text)
        vector = cache.get(key)
        if vector is None:
            missing.append(text)
        else:
            result[text] = vector

    if missing:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
        for start in range(0, len(missing), batch_size):
            batch = missing[start:start + batch_size]
            response = client.embeddings.create(model=model, input=batch)
            for text, item in zip(batch, response.data, strict=False):
                vector = [float(value) for value in item.embedding]
                cache[_embedding_cache_key(model, text)] = vector
                result[text] = vector

    return result


def _embedding_cache_key(model: str, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return f"{model}:{digest}"


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


_LATEX_QUERY_ALIASES = {
    r"\alpha": "alpha",
    r"\beta": "beta",
    r"\gamma": "gamma",
    r"\delta": "delta",
    r"\epsilon": "epsilon",
    r"\lambda": "lambda",
    r"\mu": "mu",
    r"\sigma": "sigma",
    r"\theta": "theta",
    r"\pi": "pi",
    r"\ldots": "ellipsis",
    r"\dots": "ellipsis",
    r"\infty": "infinity",
    r"\mathbb": " ",
    r"\mathcal": " ",
    r"\mathrm": " ",
    r"\mathbf": " ",
}


def _normalized_query_for_mode(query: str, *, mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized in {"", "none", "off", "false"}:
        return query
    if normalized in {"full", "all", "true"}:
        return _normalize_open_ragbench_query(query)
    if normalized in {"latex", "latex_only"}:
        return _normalize_open_ragbench_query(query, expand_yes_no=False)
    if normalized in {"yes_no", "yes_no_only", "yes_no_fusion", "yes_no_query_fusion"}:
        return _normalize_open_ragbench_query(query, clean_latex=False)
    if normalized in {"yes_no_compact", "yes_no_compact_only"}:
        return _normalize_open_ragbench_query(query, clean_latex=False, compact_yes_no_body=True)
    if normalized in {"yes_no_guarded", "yes_no_guarded_compact"}:
        return _normalize_open_ragbench_query(
            query,
            clean_latex=False,
            compact_yes_no_body=True,
            guard_yes_no_body=True,
        )
    if normalized in {"yes_no_article", "yes_no_article_only"}:
        return _normalize_open_ragbench_query(query, clean_latex=False, strip_yes_no_article=True)
    raise ValueError(f"Unknown query normalization mode: {mode}")


def _normalize_open_ragbench_query(
    query: str,
    *,
    clean_latex: bool = True,
    expand_yes_no: bool = True,
    compact_yes_no_body: bool = False,
    strip_yes_no_article: bool = False,
    guard_yes_no_body: bool = False,
) -> str:
    normalized = query.strip()
    if clean_latex:
        for latex, replacement in _LATEX_QUERY_ALIASES.items():
            normalized = normalized.replace(latex, replacement)
        normalized = re.sub(r"\\[a-zA-Z]+\{([^{}]+)\}", r"\1", normalized)
        normalized = re.sub(r"[$]", " ", normalized)
        normalized = normalized.replace("\\(", " ").replace("\\)", " ")
        normalized = normalized.replace("\\[", " ").replace("\\]", " ")
        normalized = re.sub(r"[{}]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" ?")

    if expand_yes_no and not (guard_yes_no_body and _skip_yes_no_expansion(normalized)):
        declarative = _yes_no_query_body(
            normalized,
            compact=compact_yes_no_body,
            strip_article=strip_yes_no_article,
        )
        if declarative and declarative.lower() != normalized.lower():
            normalized = f"{normalized} {declarative}"
    return normalized or query


def _skip_yes_no_expansion(query: str) -> bool:
    """Skip yes/no expansion when the appended fragment is likely to distort rank.

    These guards are intentionally structural: math-heavy questions already rely
    on exact symbolic terms, and ``is it necessary for ...`` questions tend to
    produce a broad nominal fragment that over-ranks background sections.
    """
    stripped = query.strip()
    lowered = stripped.lower()
    if "$" in stripped or "\\" in stripped:
        return True
    if re.match(r"^is\s+it\s+necessary\s+for\s+", lowered):
        return True
    return False


def _yes_no_query_body(
    query: str,
    *,
    compact: bool = False,
    strip_article: bool = False,
) -> str:
    match = re.match(
        r"^(?:is|are|was|were|do|does|did|can|could|should|would|has|have)\s+(.+)$",
        query.strip(),
        flags=re.I,
    )
    if not match:
        return ""
    body = match.group(1).strip(" ?")
    if compact:
        body = re.sub(r"^(?:it|this|that)\s+(?=[a-zA-Z])", "", body, flags=re.I)
    if compact or strip_article:
        body = re.sub(r"^the\s+(?=[a-zA-Z])", "", body, flags=re.I)
    return body if len(body) >= 8 else ""


def _fuse_ranked_ids(
    primary_ids: list[str],
    secondary_ids: list[str],
    *,
    limit: int,
    secondary_weight: float = 1.0,
) -> list[str]:
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    order = 0
    for weight, ids in ((1.0, primary_ids), (secondary_weight, secondary_ids)):
        for rank, note_id in enumerate(ids, 1):
            if note_id not in first_seen:
                first_seen[note_id] = order
                order += 1
            scores[note_id] = scores.get(note_id, 0.0) + weight / (60 + rank)
    ranked = sorted(
        scores,
        key=lambda note_id: (-scores[note_id], first_seen[note_id], note_id),
    )
    return ranked[:limit]


def _blend_fusion_and_llm_ranks(
    fusion_ids: list[str],
    llm_ranked_ids: list[str],
    *,
    limit: int,
    llm_weight: float,
) -> list[str]:
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    for rank, note_id in enumerate(fusion_ids, 1):
        first_seen.setdefault(note_id, rank)
        scores[note_id] = scores.get(note_id, 0.0) + 1.0 / (60 + rank)
    for rank, note_id in enumerate(llm_ranked_ids, 1):
        if note_id not in scores:
            continue
        scores[note_id] += llm_weight / (60 + rank)
    ranked = sorted(
        scores,
        key=lambda note_id: (-scores[note_id], first_seen[note_id], note_id),
    )
    return ranked[:limit]


def _blend_fusion_and_llm_scores(
    fusion_ids: list[str],
    llm_scores: dict[str, float],
    *,
    limit: int,
    llm_weight: float,
    score_threshold: float = 0.0,
    confidence_margin: float = 0.0,
) -> list[str]:
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    for rank, note_id in enumerate(fusion_ids, 1):
        first_seen.setdefault(note_id, rank)
        scores[note_id] = scores.get(note_id, 0.0) + 1.0 / (60 + rank)
    usable_scores = {
        note_id: max(0.0, min(1.0, llm_score))
        for note_id, llm_score in llm_scores.items()
        if note_id in scores and llm_score >= score_threshold
    }
    if confidence_margin > 0 and usable_scores:
        sorted_scores = sorted(usable_scores.values(), reverse=True)
        top_score = sorted_scores[0]
        second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
        if top_score - second_score < confidence_margin:
            usable_scores = {}
    for note_id, llm_score in usable_scores.items():
        scores[note_id] += llm_weight * llm_score / 60
    ranked = sorted(
        scores,
        key=lambda note_id: (-scores[note_id], first_seen[note_id], note_id),
    )
    return ranked[:limit]


def _rank_ids_by_llm_score(candidate_ids: list[str], llm_scores: dict[str, float]) -> list[str]:
    return sorted(
        candidate_ids,
        key=lambda note_id: (-llm_scores.get(note_id, 0.0), candidate_ids.index(note_id), note_id),
    )


def _llm_rerank_note_ids(
    question: str,
    candidate_ids: list[str],
    note_by_id: dict[str, KnowledgeNote],
    model_client: object,
) -> list[str]:
    from personal_agent.infra.structured_model import StructuredModelRequest
    from personal_agent.capabilities.contracts.model import sealed_context_projection_ref

    valid_ids = [note_id for note_id in candidate_ids if note_id in note_by_id]
    if len(valid_ids) <= 1:
        return valid_ids
    messages = [
        {
            "role": "system",
            "content": (
                "Rank candidate evidence sections for answering the question. "
                "Prefer the section that directly answers the question over "
                "background, parent abstracts, adjacent sections, or broad topical matches. "
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": _note_rerank_prompt(question, valid_ids, note_by_id),
        },
    ]
    response = model_client.generate(StructuredModelRequest(
        operation="open_ragbench_note_rerank",
        version="v1",
        temperature=0,
        max_tokens=900,
        kind="structured",
        messages=messages,
        output_type=_NoteRerankResult,
        context_projection_ref=sealed_context_projection_ref(
            purpose="open_ragbench_note_rerank",
            messages=messages,
        ),
        metadata={"component": "open_ragbench_controlled_rerank", "candidate_count": len(valid_ids)},
    ))
    valid = set(valid_ids)
    return [note_id for note_id in response.value.ranked_ids if note_id in valid]


def _llm_score_note_ids(
    question: str,
    candidate_ids: list[str],
    note_by_id: dict[str, KnowledgeNote],
    model_client: object,
) -> dict[str, float]:
    from personal_agent.infra.structured_model import StructuredModelRequest
    from personal_agent.capabilities.contracts.model import sealed_context_projection_ref

    valid_ids = [note_id for note_id in candidate_ids if note_id in note_by_id]
    if len(valid_ids) <= 1:
        return {note_id: 1.0 for note_id in valid_ids}
    messages = [
        {
            "role": "system",
            "content": (
                "Score candidate evidence sections for answering the question. "
                "Use calibrated numeric scores from 0 to 1. Prefer sections that "
                "directly answer the question. Penalize broad background, adjacent "
                "sections, parent abstracts, and merely topical matches. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": _note_score_prompt(question, valid_ids, note_by_id),
        },
    ]
    response = model_client.generate(StructuredModelRequest(
        operation="open_ragbench_note_score_rerank",
        version="v1",
        temperature=0,
        max_tokens=1400,
        kind="structured",
        messages=messages,
        output_type=_NoteScoreResult,
        context_projection_ref=sealed_context_projection_ref(
            purpose="open_ragbench_note_score_rerank",
            messages=messages,
        ),
        metadata={"component": "open_ragbench_score_rerank", "candidate_count": len(valid_ids)},
    ))
    valid = set(valid_ids)
    scored: dict[str, float] = {}
    for item in response.value.scores:
        if item.id not in valid:
            continue
        scored[item.id] = _combined_llm_note_score(item)
    return scored


def _llm_select_evidence(
    question: str,
    candidate_ids: list[str],
    note_by_id: dict[str, KnowledgeNote],
    model_client: object,
) -> tuple[dict[str, _EvidenceSelectionJudgment], int, list[str], str | None]:
    from personal_agent.infra.structured_model import StructuredModelRequest
    from personal_agent.capabilities.contracts.model import sealed_context_projection_ref

    valid_ids = [note_id for note_id in candidate_ids if note_id in note_by_id]
    if len(valid_ids) <= 1:
        return {}, 0, [], None
    messages = [
        {
            "role": "system",
            "content": (
                "Judge whether each candidate evidence item directly answers the question. "
                "Do not rerank globally. Do not invent ids. Prefer precise answer sections "
                "over background, parent abstracts, neighboring context, or merely topical text. "
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": _semantic_selector_prompt(question, valid_ids, note_by_id),
        },
    ]
    response = model_client.generate(StructuredModelRequest(
        operation="open_ragbench_semantic_evidence_selector",
        version="v1",
        temperature=0,
        max_tokens=1800,
        kind="structured",
        messages=messages,
        output_type=_EvidenceSelectionResult,
        context_projection_ref=sealed_context_projection_ref(
            purpose="open_ragbench_semantic_evidence_selector",
            messages=messages,
        ),
        metadata={"component": "open_ragbench_semantic_selector", "candidate_count": len(valid_ids)},
    ))
    valid = set(valid_ids)
    judgments: dict[str, _EvidenceSelectionJudgment] = {}
    for item in response.value.judgments:
        if item.candidate_id not in valid:
            continue
        judgments[item.candidate_id] = item
    return (
        judgments,
        int(getattr(response, "retry_attempts", 0) or 0),
        list(getattr(response, "retry_errors", []) or []),
        getattr(response, "model", None),
    )


def _llm_select_evidence_policy(
    question: str,
    candidate_ids: list[str],
    note_by_id: dict[str, KnowledgeNote],
    model_client: object,
) -> tuple[_EvidenceSelectionPolicy, int, list[str], str | None]:
    from personal_agent.infra.structured_model import StructuredModelRequest
    from personal_agent.capabilities.contracts.model import sealed_context_projection_ref

    valid_ids = [note_id for note_id in candidate_ids if note_id in note_by_id]
    if len(valid_ids) <= 1:
        return _EvidenceSelectionPolicy(), 0, [], None
    messages = [
        {
            "role": "system",
            "content": (
                "Decide whether retrieval evidence needs semantic intervention. "
                "Do not invent ids. Prefer no_op when the current top evidence is already specific. "
                "Use promote_primary_evidence only for a clearly better candidate, reorder_within_top5 "
                "only when the best candidate is already in the original top five, and request_more_retrieval "
                "only when none of the candidates is sufficient. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": _semantic_policy_prompt(question, valid_ids, note_by_id),
        },
    ]
    response = model_client.generate(StructuredModelRequest(
        operation="open_ragbench_semantic_policy_selector",
        version="v1",
        temperature=0,
        max_tokens=1200,
        kind="structured",
        messages=messages,
        output_type=_EvidenceSelectionPolicyResult,
        context_projection_ref=sealed_context_projection_ref(
            purpose="open_ragbench_semantic_policy_selector",
            messages=messages,
        ),
        metadata={"component": "open_ragbench_semantic_policy_selector", "candidate_count": len(valid_ids)},
    ))
    return (
        response.value.policy,
        int(getattr(response, "retry_attempts", 0) or 0),
        list(getattr(response, "retry_errors", []) or []),
        getattr(response, "model", None),
    )


def _apply_semantic_policy(
    ranked_ids: list[str],
    policy: _EvidenceSelectionPolicy,
    *,
    limit: int,
    confidence_threshold: float,
    preserve_top_k: int,
) -> tuple[list[str], str]:
    if not ranked_ids:
        return [], "empty_candidates"
    if not policy.should_intervene or policy.action == "no_op":
        return ranked_ids[:limit], "no_op"
    if policy.action == "request_more_retrieval":
        return ranked_ids[:limit], "request_more_retrieval_diagnostic"
    if policy.confidence < confidence_threshold:
        return ranked_ids[:limit], "low_confidence"
    candidate_id = policy.primary_candidate_id
    if candidate_id not in ranked_ids:
        return ranked_ids[:limit], "invalid_candidate"
    if policy.action == "reorder_within_top5":
        protected_k = min(max(1, preserve_top_k), len(ranked_ids))
        protected = ranked_ids[:protected_k]
        if candidate_id not in protected:
            return ranked_ids[:limit], "candidate_outside_preserved_top_k"
        return ([candidate_id] + [note_id for note_id in protected if note_id != candidate_id] + ranked_ids[protected_k:])[:limit], "applied_reorder_within_top_k"
    if policy.action == "promote_primary_evidence":
        return ([candidate_id] + [note_id for note_id in ranked_ids if note_id != candidate_id])[:limit], "applied_promote_primary_evidence"
    return ranked_ids[:limit], "unsupported_action"


def _policy_snapshot(policy: _EvidenceSelectionPolicy) -> dict[str, object]:
    return {
        "should_intervene": policy.should_intervene,
        "ambiguity_type": policy.ambiguity_type,
        "action": policy.action,
        "primary_candidate_id": policy.primary_candidate_id,
        "confidence": policy.confidence,
        "rationale": policy.rationale[:240],
    }


def _blend_v2_and_semantic_selector(
    v2_ids: list[str],
    judgments: dict[str, _EvidenceSelectionJudgment],
    *,
    limit: int,
    selector_weight: float,
    score_threshold: float,
    confidence_margin: float,
    preserve_top_k: int = 0,
) -> list[str]:
    if not judgments:
        return v2_ids[:limit]
    original_rank = {note_id: rank for rank, note_id in enumerate(v2_ids, 1)}
    eligible_scores = {
        note_id: _combined_semantic_selector_score(judgment)
        for note_id, judgment in judgments.items()
        if note_id in original_rank
        and judgment.should_be_primary_evidence
        and judgment.evidence_sufficiency in {"sufficient", "partial"}
    }
    eligible_scores = {
        note_id: score
        for note_id, score in eligible_scores.items()
        if score >= score_threshold
    }
    if not eligible_scores:
        return v2_ids[:limit]
    if confidence_margin > 0 and len(eligible_scores) > 1:
        sorted_scores = sorted(eligible_scores.values(), reverse=True)
        if sorted_scores[0] - sorted_scores[1] < confidence_margin:
            return v2_ids[:limit]

    def blended_sort(ids: list[str]) -> list[str]:
        return sorted(
            ids,
            key=lambda note_id: (
                -(
                    1.0 / (60 + original_rank[note_id])
                    + selector_weight * eligible_scores.get(note_id, 0.0)
                ),
                original_rank[note_id],
                note_id,
            ),
        )

    if preserve_top_k > 0:
        protected = v2_ids[:preserve_top_k]
        remainder = v2_ids[preserve_top_k:]
        return (blended_sort(protected) + remainder)[:limit]

    scored_ids = blended_sort(v2_ids)
    return scored_ids[:limit]


def _combined_semantic_selector_score(judgment: _EvidenceSelectionJudgment) -> float:
    sufficiency_score = {
        "sufficient": 1.0,
        "partial": 0.55,
        "background": 0.15,
        "irrelevant": 0.0,
    }.get(judgment.evidence_sufficiency, 0.0)
    score = (
        0.45 * _zero_to_one(judgment.direct_answer_score, max_value=5.0)
        + 0.30 * _zero_to_one(judgment.section_specificity, max_value=5.0)
        + 0.25 * sufficiency_score
    )
    if not judgment.should_be_primary_evidence:
        score *= 0.7
    return max(0.0, min(1.0, score))


def _zero_to_one(value: float, *, max_value: float) -> float:
    return max(0.0, min(1.0, float(value) / max_value))


def _rank_ids_by_semantic_selector(
    candidate_ids: list[str],
    judgments: dict[str, _EvidenceSelectionJudgment],
) -> list[str]:
    return sorted(
        candidate_ids,
        key=lambda note_id: (
            -_combined_semantic_selector_score(judgments[note_id]) if note_id in judgments else 0.0,
            candidate_ids.index(note_id),
            note_id,
        ),
    )


def _selector_judgment_snapshot(judgment: _EvidenceSelectionJudgment) -> dict[str, object]:
    return {
        "direct_answer_score": judgment.direct_answer_score,
        "section_specificity": judgment.section_specificity,
        "evidence_sufficiency": judgment.evidence_sufficiency,
        "answer_type_match": judgment.answer_type_match,
        "should_be_primary_evidence": judgment.should_be_primary_evidence,
        "combined_score": round(_combined_semantic_selector_score(judgment), 4),
        "rationale": judgment.rationale[:240],
    }


def _semantic_selector_trigger_reason(
    candidate_ids: list[str],
    *,
    query_text: str = "",
    note_by_id: dict[str, KnowledgeNote] | None = None,
    mode: Literal["all_queries", "triggered_only"] = "all_queries",
) -> str | None:
    if len(candidate_ids) <= 1:
        return None
    if mode == "all_queries":
        return "all_queries"

    top_parent = _parent_id(candidate_ids[0])
    if not re.search(r"_sec_\d+$", candidate_ids[0]) and any(
        re.search(r"_sec_\d+$", note_id) and _parent_id(note_id) == top_parent
        for note_id in candidate_ids[1:5]
    ):
        return "parent_top_with_specific_sections"

    same_doc_top5 = [note_id for note_id in candidate_ids[:5] if _parent_id(note_id) == top_parent]
    same_doc_specific = [
        note_id
        for note_id in same_doc_top5
        if re.search(r"_sec_\d+$", note_id) and not _semantic_selector_background_like(note_id, note_by_id)
    ]
    direct_answer_query = _query_type_bucket(query_text) in {"yes_no", "what", "how", "which"}
    if _semantic_selector_background_like(candidate_ids[0], note_by_id) and same_doc_specific:
        return "background_top_with_specific_sections"
    if (
        direct_answer_query
        and len(same_doc_top5) >= 4
        and any(_semantic_selector_background_like(note_id, note_by_id) for note_id in candidate_ids[:3])
        and same_doc_specific
    ):
        return "background_competing_sections"
    return None


def _section_index(note_id: str) -> int | None:
    match = re.search(r"_sec_(\d+)$", note_id)
    return int(match.group(1)) if match else None


def _semantic_selector_background_like(
    note_id: str,
    note_by_id: dict[str, KnowledgeNote] | None = None,
) -> bool:
    if not re.search(r"_sec_\d+$", note_id):
        return True
    section_index = _section_index(note_id)
    if section_index in {0, 1}:
        return True
    note = note_by_id.get(note_id) if note_by_id is not None else None
    if note is None:
        return False
    heading = f"{note.title}\n{note.content[:240]}".lower()
    return bool(re.search(r"\b(abstract|introduction|background|overview|related work)\b", heading))


def _combined_llm_note_score(item: _NoteScoreItem) -> float:
    score = (
        0.55 * item.direct_answer_score
        + 0.25 * item.section_specificity
        + 0.20 * item.doc_relevance
        - 0.20 * item.background_penalty
    )
    return max(0.0, min(1.0, score))


def _note_rerank_prompt(
    question: str,
    candidate_ids: list[str],
    note_by_id: dict[str, KnowledgeNote],
) -> str:
    lines = [f"Question: {question}", "", "Candidates:"]
    for rank, note_id in enumerate(candidate_ids, 1):
        note = note_by_id[note_id]
        kind = "section" if note.chunk.parent_note_id else "parent"
        lines.append(
            "\n".join([
                f"- id: {note_id}",
                f"  fusion_rank: {rank}",
                f"  kind: {kind}",
                f"  parent_id: {note.chunk.parent_note_id or ''}",
                f"  title: {note.body.title[:180]}",
                f"  summary: {note.body.summary[:260]}",
                f"  text: {note.body.content[:900]}",
            ])
        )
    lines.append("")
    lines.append(
        "Return {\"ranked_ids\": [...]} using only candidate ids. Rank direct-answer "
        "sections first. Keep parent abstracts or background sections lower unless "
        "they are the only direct answer."
    )
    return "\n".join(lines)


def _note_score_prompt(
    question: str,
    candidate_ids: list[str],
    note_by_id: dict[str, KnowledgeNote],
) -> str:
    lines = [f"Question: {question}", "", "Candidates:"]
    for rank, note_id in enumerate(candidate_ids, 1):
        note = note_by_id[note_id]
        kind = "section" if note.chunk.parent_note_id else "parent"
        lines.append(
            "\n".join([
                f"- id: {note_id}",
                f"  fusion_rank: {rank}",
                f"  kind: {kind}",
                f"  parent_id: {note.chunk.parent_note_id or ''}",
                f"  title: {note.body.title[:180]}",
                f"  summary: {note.body.summary[:260]}",
                f"  text: {note.body.content[:900]}",
            ])
        )
    lines.append("")
    lines.append(
        "Return JSON as {\"scores\": [{\"id\": string, \"direct_answer_score\": number, "
        "\"section_specificity\": number, \"doc_relevance\": number, "
        "\"background_penalty\": number}]}. Include exactly one score item for every "
        "candidate id, even when the score is low. Use only candidate ids. "
        "direct_answer_score means the text itself answers the question. "
        "section_specificity means the section is the precise answer location, not "
        "a neighboring or overview section. doc_relevance means the candidate is from "
        "the correct paper or topic. background_penalty is high for background, "
        "abstract-only, survey, or merely topical text."
    )
    return "\n".join(lines)


def _semantic_selector_prompt(
    question: str,
    candidate_ids: list[str],
    note_by_id: dict[str, KnowledgeNote],
) -> str:
    lines = [
        f"Question: {question}",
        "",
        "Judge every candidate independently. Use direct_answer_score and section_specificity from 0 to 5.",
        "evidence_sufficiency must be one of: sufficient, partial, background, irrelevant.",
        "answer_type_match must be one of: yes_no, definition, method, formula, result, unclear.",
        "",
        "Candidates:",
    ]
    for rank, note_id in enumerate(candidate_ids, 1):
        note = note_by_id[note_id]
        kind = "section" if note.chunk.parent_note_id else "parent"
        heading_hint = _candidate_heading_hint(note)
        lines.append(
            "\n".join([
                f"- candidate_id: {note_id}",
                f"  v2_rank: {rank}",
                f"  kind: {kind}",
                f"  parent_id: {note.chunk.parent_note_id or ''}",
                f"  heading_hint: {heading_hint}",
                f"  title: {note.body.title[:180]}",
                f"  summary: {note.body.summary[:260]}",
                f"  text: {note.body.content[:1200]}",
            ])
        )
    lines.append("")
    lines.append(
        "Return JSON as {\"judgments\": [{\"candidate_id\": string, "
        "\"direct_answer_score\": number, \"section_specificity\": number, "
        "\"evidence_sufficiency\": \"sufficient|partial|background|irrelevant\", "
        "\"answer_type_match\": \"yes_no|definition|method|formula|result|unclear\", "
        "\"should_be_primary_evidence\": boolean, \"rationale\": string}]}. "
        "Include exactly one judgment for every candidate_id. "
        "Mark should_be_primary_evidence true only when the candidate itself is a precise "
        "primary answer location, not merely a useful background or neighboring section."
    )
    return "\n".join(lines)


def _semantic_policy_prompt(
    question: str,
    candidate_ids: list[str],
    note_by_id: dict[str, KnowledgeNote],
) -> str:
    lines = [
        f"Question: {question}",
        "",
        "Current candidates are ordered by the retriever. Decide whether semantic intervention is needed.",
        "Choose exactly one action: no_op, promote_primary_evidence, reorder_within_top5, request_more_retrieval.",
        "Use no_op when rank 1 is already sufficiently direct and specific.",
        "Use request_more_retrieval only when the candidate set lacks sufficient evidence.",
        "",
        "Candidates:",
    ]
    for rank, note_id in enumerate(candidate_ids, 1):
        note = note_by_id[note_id]
        kind = "section" if note.chunk.parent_note_id else "parent"
        heading_hint = _candidate_heading_hint(note)
        lines.append(
            "\n".join([
                f"- candidate_id: {note_id}",
                f"  current_rank: {rank}",
                f"  kind: {kind}",
                f"  parent_id: {note.chunk.parent_note_id or ''}",
                f"  heading_hint: {heading_hint}",
                f"  title: {note.body.title[:180]}",
                f"  summary: {note.body.summary[:260]}",
                f"  text: {note.body.content[:1200]}",
            ])
        )
    lines.append("")
    lines.append(
        "Return JSON as {\"policy\": {\"should_intervene\": boolean, "
        "\"ambiguity_type\": \"direct_answer_vs_background|parent_vs_section|neighboring_sections|insufficient_evidence|no_ambiguity\", "
        "\"action\": \"no_op|promote_primary_evidence|reorder_within_top5|request_more_retrieval\", "
        "\"primary_candidate_id\": string, \"confidence\": number, \"rationale\": string}}. "
        "primary_candidate_id must be empty for no_op or request_more_retrieval. "
        "confidence must be between 0 and 1."
    )
    return "\n".join(lines)


def _candidate_heading_hint(note: KnowledgeNote) -> str:
    text = note.body.content.strip()
    first_line = text.splitlines()[0].strip() if text else ""
    if first_line.startswith("#"):
        return first_line[:120]
    lowered = first_line.lower()
    if "abstract" in lowered:
        return "abstract"
    if "introduction" in lowered:
        return "introduction"
    if "conclusion" in lowered:
        return "conclusion"
    return first_line[:120]


def _token_score(query_tokens: list[str], candidate_tokens: set[str], graph: _StructuralIndex) -> float:
    score = 0.0
    for token in query_tokens:
        if token not in candidate_tokens:
            continue
        document_frequency = graph.document_frequency.get(token, 0)
        inverse_document_frequency = math.log((graph.num_sections + 1) / (document_frequency + 1)) + 1.0
        score += inverse_document_frequency * (1.5 if len(token) >= 6 else 1.0)
    return score


def _structural_tiebreak(note_id: str, sections_by_id: dict[str, _StructuralSection]) -> float:
    section = sections_by_id.get(note_id)
    if section is None:
        return 0.0
    return -float(section.index)


def _structural_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+", text.lower()):
        if len(raw) < 2 or raw in _STRUCTURAL_STOPWORDS:
            continue
        tokens.append(raw)
    return tokens


_STRUCTURAL_STOPWORDS = {
    "the",
    "and",
    "for",
    "from",
    "with",
    "that",
    "this",
    "are",
    "was",
    "were",
    "into",
    "about",
    "what",
    "which",
    "where",
    "when",
    "how",
    "why",
    "who",
}


@dataclass(frozen=True)
class AskPipelineStrategy:
    """Retrieval-only proxy for the Ask pipeline.

    This intentionally stops before answer generation. It evaluates whether the
    query planner and retrieval sources put relevant note IDs in the top-k.
    """

    name: str = "ask_pipeline"
    description: str = (
        "Ask retrieval proxy with QueryUnderstanding + RetrievalPlan: "
        "query rewrite, graph/local retrieval, sub-query decomposition, note-id normalized output."
    )
    use_planner: bool = True
    use_rewrite: bool = True
    include_graph: bool = True
    include_subqueries: bool = True
    local_only: bool = False

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        settings = context.settings
        store, all_notes = _new_eval_store(settings, docs)
        graph_store = GraphitiStore(settings)
        episode_to_note_id: dict[str, str] = {}
        if self.include_graph and not self.local_only:
            episode_to_note_id = _ensure_eval_graph_mapping(
                graph_store=graph_store,
                notes=all_notes,
                context=context,
            )
            _attach_graph_episode_ids_to_store(store, all_notes, episode_to_note_id)

        from personal_agent.kernel.query_understanding import QueryUnderstanding, RetrievalFilters, RetrievalPlan

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}

        for query in queries:
            planner_cache_hit = False
            if self.use_planner:
                (understanding, plan), planner_cache_hit = _get_eval_plan(query, settings, context)
            else:
                understanding = QueryUnderstanding(
                    needs_personal_memory=True,
                    query_rewrite=query.query_text,
                    filters=RetrievalFilters(),
                )
                plan = RetrievalPlan(
                    sources=["local"],
                    parallel=False,
                    query=query.query_text,
                    sub_queries=[],
                    filters=RetrievalFilters(),
                )

            effective_query = (plan.query or query.query_text) if self.use_rewrite else query.query_text
            sources = ["local"] if self.local_only else list(plan.sources)
            if not self.include_graph and "graph" in sources:
                sources = [source for source in sources if source != "graph"]
            if "local" not in sources:
                sources.append("local")

            result_ids: list[str] = []
            local_ids: list[str] = []
            graph_ids: list[str] = []
            subquery_ids: list[str] = []

            if "local" in sources:
                local_matches = store.find_similar_notes(
                    "ragbench_eval",
                    effective_query,
                    limit=limit,
                    filters=plan.filters,
                )
                for match in local_matches:
                    local_ids.append(match.id)
                    if match.id not in result_ids:
                        result_ids.append(match.id)

            if "graph" in sources and graph_store.configured() and episode_to_note_id:
                graph_result = graph_store.retrieve(
                    effective_query,
                    context.graphiti_user_id,
                )
                if graph_result.enabled:
                    for hit in graph_result.citation_hits:
                        note_id = episode_to_note_id.get(hit.episode_uuid)
                        if note_id is None:
                            continue
                        graph_ids.append(note_id)
                        if note_id not in result_ids:
                            result_ids.append(note_id)
                    for episode_uuid in graph_result.related_episode_uuids:
                        note_id = episode_to_note_id.get(episode_uuid)
                        if note_id is None:
                            continue
                        graph_ids.append(note_id)
                        if note_id not in result_ids:
                            result_ids.append(note_id)

            sub_queries = plan.sub_queries if self.include_subqueries else []
            for sub_q in sub_queries:
                sub_matches = store.find_similar_notes(
                    "ragbench_eval",
                    sub_q,
                    limit=limit,
                    filters=plan.filters,
                )
                for match in sub_matches:
                    subquery_ids.append(match.id)
                    if match.id not in result_ids:
                        result_ids.append(match.id)

            rankings.append((query.query_id, result_ids[:limit]))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "expected_note_ids": [section_id, parent_id],
                    "planner": {
                        "enabled": self.use_planner,
                        "sources": list(plan.sources),
                        "effective_sources": sources,
                        "rewrite": plan.query,
                        "used_query": effective_query,
                        "sub_queries": list(sub_queries),
                        "filters": plan.filters.model_dump(exclude_defaults=True),
                        "needs_freshness": understanding.needs_freshness,
                        "needs_graph_reasoning": understanding.needs_graph_reasoning,
                        "cache_hit": planner_cache_hit,
                    },
                    "local_ids": local_ids[:limit],
                    "graph_note_ids": graph_ids[:limit],
                    "subquery_ids": subquery_ids[:limit],
                    "ranked_ids": result_ids[:limit],
                },
            )

        return rankings, relevance


@dataclass(frozen=True)
class RuntimeAskStrategy:
    """Full production runtime Ask path, used as an explicit diagnostic strategy."""

    name: str = "current_runtime_ask"
    description: str = (
        "Full AgentRuntime.execute_ask path over the eval corpus. "
        "Runs generation/verifier, so it is slower than retrieval-only strategies."
    )

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        from personal_agent.orchestration.runtime import AgentRuntime

        settings = context.settings
        eval_user_id = context.graphiti_user_id
        store, all_notes = _new_eval_store(settings, docs, user_id=eval_user_id)
        graph_store = GraphitiStore(settings)
        if settings.ask.graph_provider.strip().lower() in {"graphiti", "hybrid"}:
            episode_to_note_id = _ensure_eval_graph_mapping(
                graph_store=graph_store,
                notes=all_notes,
                context=context,
            )
            _attach_graph_episode_ids_to_store(store, all_notes, episode_to_note_id)
        runtime = AgentRuntime(settings, store, graph_store)

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            result = runtime.execute_ask(
                query.query_text,
                user_id=eval_user_id,
                session_id=f"ragbench_{query.query_id}",
            )
            ranked_ids: list[str] = []
            for match in result.matches:
                if match.id not in ranked_ids:
                    ranked_ids.append(match.id)
            rankings.append((query.query_id, ranked_ids[:limit]))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "expected_note_ids": [section_id, parent_id],
                    "ranked_ids": ranked_ids[:limit],
                    "citation_note_ids": [citation.note_id for citation in result.citations[:limit]],
                    "evidence_ids": [item.source_id for item in result.evidence[:limit]],
                    "graph_provider": settings.ask.graph_provider,
                },
            )
        return rankings, relevance


@dataclass(frozen=True)
class RuntimeAskKnowledgeAblationStrategy:
    """Full Ask path with graph/web disabled, optionally seeding Knowledge.

    The pair ``current_runtime_ask_no_knowledge`` / ``current_runtime_ask_knowledge``
    isolates the effect of ``KnowledgeRetriever`` on the final Ask evidence
    ranking. Both variants use the same local note corpus and the same disabled
    graph/web settings; the knowledge variant additionally ingests the corpus
    into ``KnowledgeService`` and maps knowledge citations back to RAGBench note
    ids through artifact ``source_ref``.
    """

    include_knowledge: bool = False

    @property
    def name(self) -> str:
        return (
            "current_runtime_ask_knowledge"
            if self.include_knowledge else "current_runtime_ask_no_knowledge"
        )

    @property
    def description(self) -> str:
        suffix = "with Knowledge corpus seeded" if self.include_knowledge else "without Knowledge corpus"
        return (
            "Full AgentRuntime.execute_ask path with graph/web/structured semantic "
            f"extraction disabled, {suffix}."
        )

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        from personal_agent.orchestration.runtime import AgentRuntime

        eval_user_id = context.graphiti_user_id
        settings = _knowledge_ablation_settings(context.settings)
        store, all_notes = _new_eval_store(settings, docs, user_id=eval_user_id)
        graph_store = GraphitiStore(settings)
        runtime = AgentRuntime(settings, store, graph_store)
        runtime.knowledge_service = _fixture_knowledge_service(settings)

        source_ref_to_note_id: dict[str, str] = {}
        if self.include_knowledge:
            source_ref_to_note_id = _seed_knowledge_from_notes(
                runtime,
                all_notes,
                user_id=eval_user_id,
            )

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            result = runtime.execute_ask(
                query.query_text,
                user_id=eval_user_id,
                session_id=f"ragbench_{query.query_id}",
            )
            ranked_ids = _ranked_note_ids_from_ask_result(
                result,
                source_ref_to_note_id=source_ref_to_note_id,
                limit=limit,
            )
            rankings.append((query.query_id, ranked_ids))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "expected_note_ids": [section_id, parent_id],
                    "ranked_ids": ranked_ids,
                    "match_ids": [match.id for match in result.matches[:limit]],
                    "citation_note_ids": [citation.note_id for citation in result.citations[:limit]],
                    "evidence_ids": [item.source_id for item in result.evidence[:limit]],
                    "knowledge_enabled": self.include_knowledge,
                    "graph_provider": settings.ask.graph_provider,
                    "web_enabled": settings.web_search_available,
                    "structured_enabled": bool(settings.structured.api_key),
                },
            )
        return rankings, relevance


@dataclass(frozen=True)
class RuntimeAskRetrievalKnowledgeAblationStrategy:
    """Ask retrieval stage only, with graph/web/langextract disabled.

    This is the fast ablation for ``KnowledgeRetriever``. It executes the real
    Ask retrieval stage and context assembly, then projects selected knowledge
    citations back to Open RAGBench note ids through their artifact ``source_ref``.
    It intentionally skips answer generation, verifier, and repair.
    """

    include_knowledge: bool = False
    force_claim_sensitive: bool = False
    knowledge_only: bool = False
    high_accuracy: bool = False
    llm_rerank: bool = False
    llm_gated: bool = False
    external_embedding: bool = False
    force_default_planner: bool = False
    ask_reranker: str | None = None

    @property
    def name(self) -> str:
        if self.ask_reranker == "support":
            return "ask_retrieve_support"
        if self.llm_gated:
            return "ask_retrieve_llm_gated"
        if self.llm_rerank and self.external_embedding:
            return "ask_retrieve_external_llm_rerank"
        if self.llm_rerank:
            return "ask_retrieve_llm_rerank"
        if self.external_embedding:
            return "ask_retrieve_external_embedding"
        if self.high_accuracy:
            return "ask_retrieve_high_accuracy"
        if self.knowledge_only:
            return "ask_retrieve_knowledge_evidence_only"
        if self.force_claim_sensitive:
            return "ask_retrieve_knowledge_forced_claim_sensitive"
        return "ask_retrieve_knowledge" if self.include_knowledge else "ask_retrieve_no_knowledge"

    @property
    def description(self) -> str:
        if self.knowledge_only:
            suffix = "with only Knowledge evidence enabled"
        elif self.llm_gated:
            suffix = "with gated LLM rerank enabled and default planner forced"
        elif self.ask_reranker == "support":
            suffix = "with support reranker enabled and default planner forced"
        elif self.llm_rerank and self.external_embedding:
            suffix = "with external embedding and LLM rerank enabled"
        elif self.llm_rerank:
            suffix = "with LLM rerank enabled and default planner forced"
        elif self.external_embedding:
            suffix = "with configured external embedding profile"
        elif self.high_accuracy:
            suffix = "with high-accuracy local recall/context profile"
        elif self.force_claim_sensitive:
            suffix = "with Knowledge corpus seeded and claim-sensitive routing forced"
        else:
            suffix = "with Knowledge corpus seeded" if self.include_knowledge else "without Knowledge corpus"
        return (
            "Real AskService.run_retrieval_stage with graph/web/langextract disabled, "
            f"{suffix}; skips generation/verifier."
        )

    def evaluate(
        self,
        queries: list[RAGBenchQuery],
        docs: dict[str, RAGBenchDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> tuple[list[tuple[str, list[str]]], dict[str, set[str]]]:
        from personal_agent.orchestration.runtime import AgentRuntime

        eval_user_id = context.graphiti_user_id
        settings = _knowledge_ablation_settings(
            context.settings,
            preserve_structured=self.llm_rerank or self.llm_gated,
        )
        if self.high_accuracy:
            settings = _high_accuracy_ask_settings(settings)
        if self.llm_gated:
            settings = _llm_gated_ask_settings(settings)
        if self.llm_rerank:
            settings = _llm_rerank_ask_settings(settings)
        if self.ask_reranker is not None:
            settings = _ask_reranker_settings(settings, self.ask_reranker)
        if self.external_embedding:
            settings = _external_embedding_settings(settings)
        store, all_notes = _new_eval_store(settings, docs, user_id=eval_user_id)
        graph_store = GraphitiStore(settings)
        runtime = AgentRuntime(settings, store, graph_store)
        runtime.knowledge_service = _fixture_knowledge_service(settings)

        source_ref_to_note_id: dict[str, str] = {}
        if self.include_knowledge:
            source_ref_to_note_id = _seed_knowledge_from_notes(
                runtime,
                all_notes,
                user_id=eval_user_id,
            )

        ask_service = runtime._ask_service()
        if self.force_default_planner or self.llm_rerank or self.llm_gated:
            ask_service._plan_retrieval = _default_eval_planner()  # type: ignore[method-assign]
        if self.force_claim_sensitive or self.knowledge_only:
            ask_service._plan_retrieval = _forced_knowledge_eval_planner(  # type: ignore[method-assign]
                force_knowledge_only=self.knowledge_only,
            )
        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            ctx = ask_service.build_run_context(
                query.query_text,
                user_id=eval_user_id,
                session_id=f"ragbench_{query.query_id}",
            )
            ask_service.run_retrieval_stage(ctx)
            ranked_ids = _ranked_note_ids_from_ask_context(
                ctx,
                source_ref_to_note_id=source_ref_to_note_id,
                limit=limit,
            )
            rankings.append((query.query_id, ranked_ids))
            section_id, parent_id = expected_note_ids(query)
            relevance[query.query_id] = {section_id, parent_id}
            local_probe_ids = _note_ids(store.find_similar_notes(
                eval_user_id,
                ctx.effective_query or query.query_text,
                limit=max(limit, context.local_probe_limit),
                filters=ctx.retrieval_plan.filters if ctx.retrieval_plan is not None else None,
            ))
            evidence = ctx.context_pack.evidence if ctx.context_pack is not None else []
            knowledge_evidence = [
                item for item in evidence
                if item.metadata.get("retrieved_by") == "knowledge"
                or item.source_ref in source_ref_to_note_id
            ]

            def resolved_match_note_id(match) -> str:
                if match.source.type in {"knowledge_claim", "knowledge_evidence"}:
                    return source_ref_to_note_id.get(str(match.source.ref or ""), "")
                return str(match.id or "")

            def resolved_citation_note_id(citation) -> str:
                if citation.source_type == "knowledge":
                    return source_ref_to_note_id.get(str(citation.source_ref or ""), "")
                return str(citation.note_id or "")

            def resolved_evidence_note_ids(item) -> list[str]:
                ids: list[str] = []

                def add(note_id: str | None) -> None:
                    if note_id and note_id not in ids:
                        ids.append(note_id)

                source_ref = str(item.source_ref or "")
                metadata = item.metadata or {}
                add(source_ref_to_note_id.get(source_ref))
                add(source_ref_to_note_id.get(str(metadata.get("artifact_id") or "")))
                source_id = str(item.source_id or "")
                if source_id.startswith("ragbench_"):
                    add(source_id)
                elif str(item.parent_note_id or "").startswith("ragbench_"):
                    add(str(item.parent_note_id))
                return ids

            selected_evidence_resolved_note_ids = _unique_ids(
                *[resolved_evidence_note_ids(item) for item in evidence[:limit]]
            )
            diagnostic = _diagnose_retrieval(
                section_id=section_id,
                parent_id=parent_id,
                ranked_ids=ranked_ids,
                local_probe_ids=local_probe_ids,
                retrieval_health=ctx.retrieval_health,
            )
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "expected_note_ids": [section_id, parent_id],
                    "ranked_ids": ranked_ids,
                    **diagnostic,
                    "local_probe_limit": max(limit, context.local_probe_limit),
                    "local_probe_ids": local_probe_ids[:limit],
                    "local_probe_top20_ids": local_probe_ids[:20],
                    **_retrieval_eval_snapshot(store),
                    "trace": list(ctx.trace_steps),
                    "reranker_telemetry": _reranker_telemetry_from_trace(ctx.trace_steps),
                    "retrieval_health": dict(ctx.retrieval_health),
                    "ask_reranker": settings.ask.reranker,
                    "llm_rerank_model_configured": bool(settings.structured.api_key and settings.structured.base_url),
                    **_embedding_eval_snapshot(store),
                    "knowledge_enabled": self.include_knowledge,
                    "knowledge_evidence_count": len(knowledge_evidence),
                    "selected_match_ids": [match.id for match in ctx.selected_matches[:limit]],
                    "selected_match_resolved_note_ids": [
                        note_id for note_id in (
                            resolved_match_note_id(match) for match in ctx.selected_matches[:limit]
                        )
                        if note_id
                    ],
                    "selected_citation_note_ids": [
                        citation.note_id for citation in ctx.selected_citations[:limit]
                    ],
                    "selected_citation_source_refs": [
                        str(citation.source_ref or "") for citation in ctx.selected_citations[:limit]
                    ],
                    "selected_citation_resolved_note_ids": [
                        note_id for note_id in (
                            resolved_citation_note_id(citation) for citation in ctx.selected_citations[:limit]
                        )
                        if note_id
                    ],
                    "selected_evidence_ids": [item.source_id for item in evidence[:limit]],
                    "selected_evidence_source_refs": [
                        str(item.source_ref or "") for item in evidence[:limit]
                    ],
                    "selected_evidence_resolved_note_ids": selected_evidence_resolved_note_ids,
                    "context_selected_evidence_lineage": list(
                        ctx.retrieval_health.get("context_selected_evidence_lineage", [])
                    ),
                    "context_dropped_evidence_reasons": list(
                        ctx.retrieval_health.get("context_dropped_evidence_reasons", [])
                    ),
                    "graph_provider": settings.ask.graph_provider,
                    "web_enabled": settings.web_search_available,
                    "structured_enabled": bool(settings.structured.api_key),
                    "langextract_enabled": bool(settings.langextract.api_key),
                },
            )
        return rankings, relevance


def _knowledge_ablation_settings(
    settings: Settings,
    *,
    preserve_structured: bool = False,
) -> Settings:
    """Disable web, graph, and structured semantic extraction for the ablation."""
    structured = settings.structured if preserve_structured else settings.structured.model_copy(update={"api_key": None})
    return settings.model_copy(
        update={
            "ask": settings.ask.model_copy(
                update={
                    "graph_provider": "graphiti",
                    "reranker": "heuristic",
                }
            ),
            "graphiti": settings.graphiti.model_copy(update={"enabled": False}),
            "web_search": settings.web_search.model_copy(update={"api_key": None}),
            "structured": structured,
            "langextract": settings.langextract.model_copy(update={"api_key": None}),
        }
    )


def _high_accuracy_ask_settings(settings: Settings) -> Settings:
    """Use the best observed high-accuracy Ask profile for benchmark checks."""
    ask = settings.ask
    settings = _external_embedding_settings(settings)
    return settings.model_copy(
        update={
            "ask": ask.model_copy(
                update={
                    "local_retrieval_limit": max(int(getattr(ask, "local_retrieval_limit", 12)), 12),
                }
            )
        }
    )


def _llm_rerank_ask_settings(settings: Settings) -> Settings:
    ask = settings.ask
    return settings.model_copy(
        update={
            "ask": ask.model_copy(
                update={
                    "reranker": "llm",
                    "llm_rerank_top_n": max(int(getattr(ask, "llm_rerank_top_n", 20)), 30),
                    "local_retrieval_limit": max(int(getattr(ask, "local_retrieval_limit", 12)), 20),
                }
            )
        }
    )


def _llm_gated_ask_settings(settings: Settings) -> Settings:
    ask = settings.ask
    return settings.model_copy(
        update={
            "ask": ask.model_copy(
                update={
                    "reranker": "llm_gated",
                    "llm_rerank_top_n": max(int(getattr(ask, "llm_rerank_top_n", 20)), 20),
                }
            )
        }
    )


def _ask_reranker_settings(settings: Settings, reranker: str) -> Settings:
    return settings.model_copy(
        update={
            "ask": settings.ask.model_copy(update={"reranker": reranker})
        }
    )


def _external_embedding_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "embedding_provider": "openai",
            "openai": settings.openai.model_copy(update={"embedding_model": "BAAI/bge-m3"}),
        }
    )


def _embedding_eval_snapshot(store) -> dict[str, object]:
    return {
        "embedding_configured_provider": getattr(store, "embedding_provider", ""),
        "embedding_configured_model": getattr(store, "embedding_model", ""),
        "embedding_provider": getattr(store, "last_embedding_provider", getattr(store, "embedding_provider", "")),
        "embedding_model": getattr(store, "last_embedding_model", getattr(store, "embedding_model", "")),
        "embedding_original_dimensions": getattr(store, "last_embedding_original_dimensions", None),
        "embedding_output_dimensions": getattr(store, "last_embedding_output_dimensions", None),
        "embedding_index_dimensions": getattr(store, "last_embedding_index_dimensions", None),
        "embedding_used_fallback": bool(getattr(store, "last_embedding_used_fallback", False)),
        "embedding_fallback_reason": getattr(store, "last_embedding_fallback_reason", None),
        "embedding_api_configured": bool(getattr(store, "embedding_api_key", None)),
    }


def _retrieval_eval_snapshot(store) -> dict[str, object]:
    debug = getattr(store, "last_retrieval_debug", {}) or {}
    raw_lexical_ids = [str(item) for item in debug.get("raw_lexical_ids", [])]
    raw_vector_ids = [str(item) for item in debug.get("raw_vector_ids", [])]
    merged_ids = [str(item) for item in debug.get("merged_ids", [])]
    expanded_ids = [str(item) for item in debug.get("expanded_ids", [])]
    return {
        "raw_lexical_top20_ids": raw_lexical_ids[:20],
        "raw_vector_top20_ids": raw_vector_ids[:20],
        "merged_top20_ids": merged_ids[:20],
        "expanded_top20_ids": expanded_ids[:20],
        "raw_lexical_count": int(debug.get("lexical_candidates", 0) or 0),
        "raw_vector_count": int(debug.get("vector_candidates", 0) or 0),
        "merged_count": int(debug.get("merged_candidates", 0) or 0),
        "expanded_count": int(debug.get("result_count", 0) or 0),
    }


def _fixture_knowledge_service(settings: Settings):
    """Build KnowledgeService with local fixture semantic components only."""
    from personal_agent.application.knowledge import KnowledgeService
    from personal_agent.infra.storage.postgres_knowledge_store import PostgresKnowledgeStore

    return KnowledgeService(PostgresKnowledgeStore(settings.postgres_url, settings.data_dir))


def _default_eval_planner():
    from personal_agent.kernel.query_understanding import QueryUnderstanding, RetrievalFilters, RetrievalPlan

    def _planner(question: str, structured_context: str):
        filters = RetrievalFilters()
        understanding = QueryUnderstanding(
            needs_personal_memory=True,
            claim_sensitive=False,
            retrieval_mode="evidence_dominant",
            query_rewrite=question,
            filters=filters,
        )
        plan = RetrievalPlan(
            sources=["graph", "local"],
            parallel=True,
            query=question,
            filters=filters,
            claim_sensitive=False,
            retrieval_mode="evidence_dominant",
        )
        return understanding, plan

    return _planner


def _forced_knowledge_eval_planner(*, force_knowledge_only: bool):
    from personal_agent.kernel.query_understanding import QueryUnderstanding, RetrievalFilters, RetrievalPlan

    def _planner(question: str, structured_context: str):
        filters = RetrievalFilters()
        understanding = QueryUnderstanding(
            needs_personal_memory=True,
            claim_sensitive=True,
            retrieval_mode="claim_expand_to_evidence",
            query_rewrite=question,
            filters=filters,
        )
        plan = RetrievalPlan(
            sources=[] if force_knowledge_only else ["local"],
            parallel=False,
            query=question,
            filters=filters,
            claim_sensitive=True,
            retrieval_mode="claim_expand_to_evidence",
        )
        return understanding, plan

    return _planner


def _seed_knowledge_from_notes(runtime, notes: list[KnowledgeNote], *, user_id: str) -> dict[str, str]:
    from personal_agent.application.knowledge.models import (
        Artifact,
        EvidenceBlock,
        EvidenceSpan,
        ExtractionRun,
        stable_hash,
    )

    source_ref_to_note_id: dict[str, str] = {}
    store = runtime.knowledge_service.store
    for note in notes:
        source_ref = f"open_ragbench://{note.id}"
        source_ref_to_note_id[source_ref] = note.id
        content = note.body.content
        content_hash = stable_hash(content)
        stable_suffix = re.sub(r"[^A-Za-z0-9_]+", "_", note.id)[:120]
        artifact = Artifact(
            artifact_id=source_ref,
            owner_id=user_id,
            user_id=user_id,
            source_type="open_ragbench",
            source_ref=source_ref,
            content_hash=content_hash,
            raw_location=note.id,
            text=content,
            metadata={"note_id": note.id},
        )
        extraction_run = ExtractionRun(
            extraction_run_id=f"xrun_{stable_suffix}",
            artifact_id=artifact.artifact_id,
            owner_id=user_id,
            extractor="open-ragbench-fixture",
            parser_version="open-ragbench-fixture-v1",
            input_hash=content_hash,
            evidence_block_ids=[f"eblk_{stable_suffix}"],
            evidence_span_ids=[f"espn_{stable_suffix}"],
            parsed_region_count=1,
            semantic_region_count=0,
        )
        block = EvidenceBlock(
            evidence_block_id=extraction_run.evidence_block_ids[0],
            artifact_id=artifact.artifact_id,
            owner_id=user_id,
            locator=note.id,
            title_path=[note.body.title],
            char_range=(0, len(content)),
            full_context=content,
            source_type="open_ragbench",
            extraction_run_id=extraction_run.extraction_run_id,
        )
        span = EvidenceSpan(
            evidence_span_id=extraction_run.evidence_span_ids[0],
            evidence_block_id=block.evidence_block_id,
            owner_id=user_id,
            start_offset=0,
            end_offset=len(content),
            text_span=content,
            normalized_meaning=content[:500],
            locator=note.id,
            quote_hash=stable_hash(content),
        )
        store.save_artifact(artifact)
        store.save_extraction_run(extraction_run)
        store.save_evidence_blocks([block])
        store.save_evidence_spans([span])
    return source_ref_to_note_id


def _ranked_note_ids_from_ask_result(
    result,
    *,
    source_ref_to_note_id: dict[str, str],
    limit: int,
) -> list[str]:
    ranked: list[str] = []

    def add(note_id: str | None) -> None:
        if note_id and note_id not in ranked:
            ranked.append(note_id)

    for match in result.matches:
        if match.source.type in {"knowledge_claim", "knowledge_evidence"}:
            add(source_ref_to_note_id.get(str(match.source.ref or "")))
        else:
            add(match.id)
        if len(ranked) >= limit:
            return ranked[:limit]

    for citation in result.citations:
        if citation.source_type == "knowledge":
            add(source_ref_to_note_id.get(str(citation.source_ref or "")))
        else:
            add(citation.note_id)
        if len(ranked) >= limit:
            return ranked[:limit]

    for item in result.evidence:
        source_ref = str(item.source_ref or "")
        metadata = item.metadata or {}
        add(source_ref_to_note_id.get(source_ref))
        add(source_ref_to_note_id.get(str(metadata.get("artifact_id") or "")))
        if item.source_id.startswith("ragbench_"):
            add(item.source_id)
        if len(ranked) >= limit:
            return ranked[:limit]

    return ranked[:limit]


def _ranked_note_ids_from_ask_context(
    ctx,
    *,
    source_ref_to_note_id: dict[str, str],
    limit: int,
) -> list[str]:
    ranked: list[str] = []

    def add(note_id: str | None) -> None:
        if note_id and note_id not in ranked:
            ranked.append(note_id)

    for match in ctx.selected_matches:
        if match.source.type in {"knowledge_claim", "knowledge_evidence"}:
            add(source_ref_to_note_id.get(str(match.source.ref or "")))
        else:
            add(match.id)
        if len(ranked) >= limit:
            return ranked[:limit]

    for citation in ctx.selected_citations:
        if citation.source_type == "knowledge":
            add(source_ref_to_note_id.get(str(citation.source_ref or "")))
        else:
            add(citation.note_id)
        if len(ranked) >= limit:
            return ranked[:limit]

    evidence = ctx.context_pack.evidence if ctx.context_pack is not None else []
    for item in evidence:
        source_ref = str(item.source_ref or "")
        metadata = item.metadata or {}
        add(source_ref_to_note_id.get(source_ref))
        add(source_ref_to_note_id.get(str(metadata.get("artifact_id") or "")))
        if item.source_id.startswith("ragbench_"):
            add(item.source_id)
        if len(ranked) >= limit:
            return ranked[:limit]

    return ranked[:limit]


def _reranker_telemetry_from_trace(trace_steps: list[str]) -> dict[str, object]:
    telemetry: dict[str, object] = {}
    for line in trace_steps:
        if not line.startswith("RerankerTelemetry("):
            continue
        match = re.match(r"RerankerTelemetry\((?P<name>[^)]+)\):\s*(?P<body>.*)", line)
        if not match:
            continue
        telemetry["reranker"] = match.group("name")
        for part in match.group("body").split():
            if "=" not in part:
                continue
            key, raw_value = part.split("=", 1)
            if raw_value in {"True", "False"}:
                telemetry[key] = raw_value == "True"
            elif raw_value.isdigit():
                telemetry[key] = int(raw_value)
            else:
                telemetry[key] = raw_value
    return telemetry


def list_strategy_names() -> list[str]:
    real_graph_names = [f"graphiti_{name}" for name in sorted(STRATEGIES)]
    return [
        "keyword",
        "citation_reranker",
        "structural",
        "doc_first_section",
        "doc_first_fusion",
        "doc_first_external_fusion",
        "doc_first_external_fusion_normalized",
        "doc_first_external_fusion_normalized_latex",
        "doc_first_external_fusion_normalized_yes_no",
        "doc_first_external_fusion_normalized_yes_no_compact",
        "doc_first_external_fusion_normalized_yes_no_guarded",
        "doc_first_external_fusion_normalized_yes_no_article",
        "doc_first_external_fusion_yes_no_query_fusion",
        "doc_first_external_fusion_section_refine",
        "doc_first_external_llm_topm_rerank",
        "doc_first_external_llm_score_rerank",
        "ask_pipeline",
        "ask_pipeline_no_rewrite",
        "ask_pipeline_local_only",
        "ask_pipeline_no_planner",
        "ask_retrieve_no_knowledge",
        "ask_retrieve_support",
        "ask_retrieve_high_accuracy",
        "ask_retrieve_shared_evidence_selector_lexical",
        "ask_retrieve_shared_evidence_selector",
        "ask_retrieve_shared_evidence_policy_selector",
        "ask_retrieve_open_profile",
        "ask_retrieve_galileo_profile",
        "ask_retrieve_dataset_agnostic_profile",
        "ask_retrieve_high_accuracy_section_refine",
        "ask_retrieve_high_accuracy_passage_refine",
        "ask_retrieve_high_accuracy_semantic_selector",
        "ask_retrieve_high_accuracy_semantic_selector_all_queries",
        "ask_retrieve_high_accuracy_semantic_selector_triggered_only",
        "ask_retrieve_high_accuracy_semantic_policy_selector",
        "ask_retrieve_llm_gated",
        "ask_retrieve_llm_rerank",
        "ask_retrieve_external_embedding",
        "ask_retrieve_external_llm_rerank",
        "ask_retrieve_knowledge",
        "ask_retrieve_knowledge_forced_claim_sensitive",
        "ask_retrieve_knowledge_evidence_only",
        "current_runtime_ask",
        "current_runtime_ask_no_knowledge",
        "current_runtime_ask_knowledge",
        *real_graph_names,
    ]


def get_strategy(name: str) -> BenchmarkStrategy:
    normalized = name.strip().lower()
    if normalized == "keyword":
        return KeywordSearchStrategy()
    if normalized == "citation_reranker":
        return CitationRerankStrategy()
    if normalized == "structural":
        return StructuralRetrieverStrategy()
    if normalized == "doc_first_section":
        return DocFirstSectionRerankStrategy()
    if normalized == "doc_first_fusion":
        return DocFirstFusionStrategy()
    if normalized == "doc_first_external_fusion":
        return DocFirstFusionStrategy(
            name="doc_first_external_fusion",
            description=(
                "Fusion baseline with external 1024-d embedding local retrieval "
                "plus document-first structural RRF signal."
            ),
            external_embedding=True,
        )
    if normalized == "doc_first_external_fusion_normalized":
        return DocFirstFusionStrategy(
            name="doc_first_external_fusion_normalized",
            description=(
                "External 1024-d embedding + low-weight doc-first fusion with "
                "deterministic Open RAGBench query normalization."
            ),
            external_embedding=True,
            normalize_query=True,
        )
    if normalized == "doc_first_external_fusion_normalized_latex":
        return DocFirstFusionStrategy(
            name="doc_first_external_fusion_normalized_latex",
            description=(
                "External 1024-d embedding + low-weight doc-first fusion with "
                "only LaTeX/symbol query cleanup."
            ),
            external_embedding=True,
            query_normalization_mode="latex",
        )
    if normalized == "doc_first_external_fusion_normalized_yes_no":
        return DocFirstFusionStrategy(
            name="doc_first_external_fusion_normalized_yes_no",
            description=(
                "External 1024-d embedding + low-weight doc-first fusion with "
                "only yes/no declarative-body query expansion."
            ),
            external_embedding=True,
            query_normalization_mode="yes_no",
        )
    if normalized == "doc_first_external_fusion_normalized_yes_no_compact":
        return DocFirstFusionStrategy(
            name="doc_first_external_fusion_normalized_yes_no_compact",
            description=(
                "External 1024-d embedding + low-weight doc-first fusion with "
                "compact yes/no declarative-body query expansion."
            ),
            external_embedding=True,
            query_normalization_mode="yes_no_compact",
        )
    if normalized == "doc_first_external_fusion_normalized_yes_no_guarded":
        return DocFirstFusionStrategy(
            name="doc_first_external_fusion_normalized_yes_no_guarded",
            description=(
                "External 1024-d embedding + low-weight doc-first fusion with "
                "compact yes/no query expansion guarded for math and necessity-modal queries."
            ),
            external_embedding=True,
            query_normalization_mode="yes_no_guarded",
        )
    if normalized == "doc_first_external_fusion_normalized_yes_no_article":
        return DocFirstFusionStrategy(
            name="doc_first_external_fusion_normalized_yes_no_article",
            description=(
                "External 1024-d embedding + low-weight doc-first fusion with "
                "yes/no query expansion that strips a leading article from the appended body."
            ),
            external_embedding=True,
            query_normalization_mode="yes_no_article",
        )
    if normalized == "doc_first_external_fusion_yes_no_query_fusion":
        return DocFirstFusionStrategy(
            name="doc_first_external_fusion_yes_no_query_fusion",
            description=(
                "External 1024-d embedding + low-weight doc-first fusion with "
                "original yes/no query retrieval fused with declarative-body expansion."
            ),
            external_embedding=True,
            query_normalization_mode="yes_no_fusion",
            query_expansion_weight=0.5,
        )
    if normalized == "doc_first_external_fusion_section_refine":
        return DocFirstFusionStrategy(
            name="doc_first_external_fusion_section_refine",
            description=(
                "External 1024-d embedding + low-weight doc-first fusion with "
                "weak same-doc direct-section refinement over fusion candidates."
            ),
            external_embedding=True,
            section_refine=True,
            section_refine_weight=0.01,
        )
    if normalized == "doc_first_external_llm_topm_rerank":
        return DocFirstExternalLlmTopMRerankStrategy()
    if normalized == "doc_first_external_llm_score_rerank":
        return DocFirstExternalLlmScoreRerankStrategy()
    if normalized == "ask_pipeline":
        return AskPipelineStrategy()
    if normalized == "ask_pipeline_no_rewrite":
        return AskPipelineStrategy(
            name="ask_pipeline_no_rewrite",
            description=(
                "Ask retrieval proxy with planner routing but original query text; "
                "used to isolate query rewrite impact."
            ),
            use_rewrite=False,
        )
    if normalized == "ask_pipeline_local_only":
        return AskPipelineStrategy(
            name="ask_pipeline_local_only",
            description=(
                "Ask retrieval proxy constrained to local Postgres retrieval; "
                "used to isolate graph contribution and latency."
            ),
            include_graph=False,
            local_only=True,
        )
    if normalized == "ask_pipeline_no_planner":
        return AskPipelineStrategy(
            name="ask_pipeline_no_planner",
            description=(
                "Local retrieval over the original query with no LLM planner; "
                "used as the current Postgres hybrid baseline."
            ),
            use_planner=False,
            use_rewrite=False,
            include_graph=False,
            include_subqueries=False,
            local_only=True,
        )
    if normalized == "current_runtime_ask":
        return RuntimeAskStrategy()
    if normalized == "ask_retrieve_no_knowledge":
        return RuntimeAskRetrievalKnowledgeAblationStrategy(
            include_knowledge=False,
            force_default_planner=True,
        )
    if normalized == "ask_retrieve_support":
        return RuntimeAskRetrievalKnowledgeAblationStrategy(
            include_knowledge=False,
            force_default_planner=True,
            ask_reranker="support",
        )
    if normalized == "ask_retrieve_shared_evidence_selector_lexical":
        return SharedEvidenceSelectorStrategy(
            name="ask_retrieve_shared_evidence_selector_lexical",
            description=(
                "Dataset-agnostic shared evidence selector over Open RAGBench notes "
                "using lexical/support evidence-unit scoring only."
            ),
            external_embedding=False,
        )
    if normalized == "ask_retrieve_shared_evidence_selector":
        return SharedEvidenceSelectorStrategy()
    if normalized == "ask_retrieve_shared_evidence_policy_selector":
        return SharedEvidenceSelectorStrategy(
            name="ask_retrieve_shared_evidence_policy_selector",
            description=(
                "Dataset-agnostic shared evidence selector over Open RAGBench notes "
                "with a shared LLM support/utilization policy selector."
            ),
            external_embedding=True,
            use_policy_selector=True,
        )
    if normalized == "ask_retrieve_high_accuracy":
        return DocFirstFusionStrategy(
            name="ask_retrieve_high_accuracy",
            description=(
                "High-accuracy benchmark profile: external 1024-d embedding "
                "plus low-weight document-first RRF, guarded compact yes/no query expansion, "
                "and slot-preserving passage-level section refinement."
            ),
            external_embedding=True,
            query_normalization_mode="yes_no_guarded",
            section_refine=True,
            section_refine_mode="passage_embedding",
            section_refine_weight=0.02,
        )
    if normalized == "ask_retrieve_open_profile":
        return DocFirstFusionStrategy(
            name="ask_retrieve_open_profile",
            description=(
                "Explicit Open RAGBench profile: external embedding, low-weight doc-first, "
                "guarded yes/no expansion, and same-doc slot-preserving passage refinement."
            ),
            external_embedding=True,
            profile=OPEN_RAGBENCH_PROFILE,
            doc_first_enabled=True,
            doc_first_weight=OPEN_RAGBENCH_PROFILE.doc_first_weight,
            query_normalization_mode="yes_no_guarded",
            section_refine=True,
            section_refine_mode="passage_embedding",
            section_refine_weight=0.02,
        )
    if normalized == "ask_retrieve_galileo_profile":
        return DocFirstFusionStrategy(
            name="ask_retrieve_galileo_profile",
            description=(
                "Galileo-style structural-prior ablation: external embedding with Open-specific "
                "doc-first and same-doc slot refinement disabled."
            ),
            external_embedding=True,
            profile=GALILEO_RAGBENCH_PROFILE,
            doc_first_enabled=False,
            doc_first_weight=0.0,
            query_normalization_mode="yes_no_guarded",
            section_refine=False,
        )
    if normalized == "ask_retrieve_dataset_agnostic_profile":
        return DocFirstFusionStrategy(
            name="ask_retrieve_dataset_agnostic_profile",
            description=(
                "Dataset-agnostic evidence profile: external embedding plus guarded query expansion, "
                "without Open RAGBench doc-first or same-doc slot refinement priors."
            ),
            external_embedding=True,
            profile=DATASET_AGNOSTIC_PROFILE,
            doc_first_enabled=False,
            doc_first_weight=0.0,
            query_normalization_mode="yes_no_guarded",
            section_refine=False,
        )
    if normalized == "ask_retrieve_high_accuracy_section_refine":
        return DocFirstFusionStrategy(
            name="ask_retrieve_high_accuracy_section_refine",
            description=(
                "High-accuracy ablation: external 1024-d embedding, low-weight "
                "document-first RRF, guarded compact yes/no expansion, and weak "
                "same-doc direct-section refinement."
            ),
            external_embedding=True,
            query_normalization_mode="yes_no_guarded",
            section_refine=True,
            section_refine_weight=0.01,
        )
    if normalized == "ask_retrieve_high_accuracy_passage_refine":
        return DocFirstFusionStrategy(
            name="ask_retrieve_high_accuracy_passage_refine",
            description=(
                "High-accuracy ablation: external 1024-d embedding, low-weight "
                "document-first RRF, guarded compact yes/no expansion, and same-doc "
                "passage-level embedding refinement inside final candidates."
            ),
            external_embedding=True,
            query_normalization_mode="yes_no_guarded",
            section_refine=True,
            section_refine_mode="passage_embedding",
            section_refine_weight=0.02,
        )
    if normalized == "ask_retrieve_high_accuracy_semantic_selector":
        return HighAccuracySemanticSelectorStrategy()
    if normalized == "ask_retrieve_high_accuracy_semantic_selector_all_queries":
        return HighAccuracySemanticSelectorStrategy(
            name="ask_retrieve_high_accuracy_semantic_selector_all_queries",
            description=(
                "High-accuracy v2 candidate generator plus structured LLM semantic selector "
                "called for every query; used as the all-query ablation."
            ),
            trigger_mode="all_queries",
        )
    if normalized == "ask_retrieve_high_accuracy_semantic_selector_triggered_only":
        return HighAccuracySemanticSelectorStrategy(
            name="ask_retrieve_high_accuracy_semantic_selector_triggered_only",
            description=(
                "High-accuracy v2 candidate generator plus structured LLM semantic selector "
                "called only for parent/background-vs-section ambiguity cases, with the "
                "original top-5 candidate set preserved during blending."
            ),
            trigger_mode="triggered_only",
            preserve_top_k=5,
        )
    if normalized == "ask_retrieve_high_accuracy_semantic_policy_selector":
        return HighAccuracySemanticPolicySelectorStrategy()
    if normalized == "ask_retrieve_llm_gated":
        return RuntimeAskRetrievalKnowledgeAblationStrategy(llm_gated=True)
    if normalized == "ask_retrieve_llm_rerank":
        return RuntimeAskRetrievalKnowledgeAblationStrategy(llm_rerank=True)
    if normalized == "ask_retrieve_external_embedding":
        return RuntimeAskRetrievalKnowledgeAblationStrategy(external_embedding=True)
    if normalized == "ask_retrieve_external_llm_rerank":
        return RuntimeAskRetrievalKnowledgeAblationStrategy(
            llm_rerank=True,
            external_embedding=True,
        )
    if normalized == "ask_retrieve_knowledge":
        return RuntimeAskRetrievalKnowledgeAblationStrategy(include_knowledge=True)
    if normalized == "ask_retrieve_knowledge_forced_claim_sensitive":
        return RuntimeAskRetrievalKnowledgeAblationStrategy(
            include_knowledge=True,
            force_claim_sensitive=True,
        )
    if normalized == "ask_retrieve_knowledge_evidence_only":
        return RuntimeAskRetrievalKnowledgeAblationStrategy(
            include_knowledge=True,
            force_claim_sensitive=True,
            knowledge_only=True,
        )
    if normalized == "current_runtime_ask_no_knowledge":
        return RuntimeAskKnowledgeAblationStrategy(include_knowledge=False)
    if normalized == "current_runtime_ask_knowledge":
        return RuntimeAskKnowledgeAblationStrategy(include_knowledge=True)
    if normalized.startswith("graphiti_"):
        graph_strategy_name = normalized.removeprefix("graphiti_")
        if graph_strategy_name in STRATEGIES:
            return GraphitiRetrievalStrategy(graph_strategy_name)

    available = ", ".join(list_strategy_names())
    raise ValueError(f"Unknown Open RAGBench strategy '{name}'. Available: {available}")


def run_open_ragbench(
    *,
    strategy_names: list[str],
    num_queries: int | None = None,
    seed: int = 42,
    corpus_mode: CorpusMode = "relevant",
    limit: int = 10,
    settings: Settings | None = None,
    graphiti_user_id: str = "ragbench_eval_graphiti",
    reset_graphiti: bool = True,
    graphiti_manifest_path: Path | None = Path("evals/open_ragbench/results/graphiti_manifest.json"),
    graphiti_note_mode: CorpusNoteMode = "parent_sections",
    graphiti_continue_on_ingest_error: bool = False,
    local_probe_limit: int = 100,
) -> list[BenchmarkRunResult]:
    queries, docs = load_benchmark(
        num_queries=num_queries,
        seed=seed,
        corpus_mode=corpus_mode,
    )
    eval_snapshots: dict[str, list[dict]] = {}
    planner_cache: dict[str, tuple[object, object]] = {}
    context = BenchmarkContext(
        settings=settings or Settings.from_env(),
        graphiti_user_id=graphiti_user_id,
        reset_graphiti=reset_graphiti,
        graphiti_manifest_path=graphiti_manifest_path,
        graphiti_note_mode=graphiti_note_mode,
        graphiti_continue_on_ingest_error=graphiti_continue_on_ingest_error,
        local_probe_limit=local_probe_limit,
        eval_snapshots=eval_snapshots,
        planner_cache=planner_cache,
    )
    results: list[BenchmarkRunResult] = []
    for strategy_name in strategy_names:
        strategy = get_strategy(strategy_name)
        strategy_config = _strategy_eval_config(strategy, context.settings)
        context.strategy_configs[strategy.name] = strategy_config
        started_at = time.perf_counter()
        rankings, relevance = strategy.evaluate(queries, docs, limit=limit, context=context)
        elapsed = time.perf_counter() - started_at
        report = compute_report(rankings, relevance)
        diagnostics = eval_snapshots.get(strategy.name)
        results.append(
            BenchmarkRunResult(
                strategy=strategy.name,
                description=strategy.description,
                report=report,
                elapsed_seconds=elapsed,
                num_docs=len(docs),
                num_queries=len(queries),
                corpus_mode=corpus_mode,
                diagnostics=diagnostics,
                diagnostic_summary=_summarize_diagnostics(diagnostics),
                strategy_version=str(strategy_config.get("strategy_version", "")),
                strategy_config=strategy_config,
            )
        )
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strategies",
        default="keyword,citation_reranker",
        help=f"Comma-separated strategies. Available: {', '.join(list_strategy_names())}",
    )
    parser.add_argument("--num-queries", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--corpus-mode", choices=("relevant", "full"), default="relevant")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--graphiti-user-id",
        default="ragbench_eval_graphiti",
        help="User/group id used for real Graphiti eval strategies.",
    )
    parser.add_argument(
        "--reuse-graphiti",
        action="store_true",
        help="Reuse an existing Graphiti eval group when the manifest matches the selected corpus.",
    )
    parser.add_argument(
        "--graphiti-manifest",
        type=Path,
        default=Path("evals/open_ragbench/results/graphiti_manifest.json"),
        help="Path used to persist episode_uuid -> note_id mapping for real Graphiti eval.",
    )
    parser.add_argument(
        "--graphiti-note-mode",
        choices=("parent_sections", "parent_only", "section_only"),
        default="parent_sections",
        help="How to convert RAGBench docs into Graphiti episodes.",
    )
    parser.add_argument(
        "--graphiti-continue-on-ingest-error",
        action="store_true",
        help="Keep evaluating when individual Graphiti episodes fail to ingest.",
    )
    parser.add_argument(
        "--graph-search-limit",
        type=int,
        default=None,
        help="Override Graphiti search_config.limit for real Graphiti/current_runtime_ask evals.",
    )
    parser.add_argument(
        "--graph-search-citation-limit",
        type=int,
        default=None,
        help="Override project-side Graphiti citation hit limit for episode -> note mapping.",
    )
    parser.add_argument(
        "--ask-graph-provider",
        choices=("graphiti", "structural", "hybrid"),
        default=None,
        help="Override the production ask graph provider for current_runtime_ask.",
    )
    parser.add_argument(
        "--ask-reranker",
        choices=("heuristic", "llm", "llm_gated"),
        default=None,
        help="Override the production ask reranker for current_runtime_ask.",
    )
    parser.add_argument(
        "--ask-candidate-enricher",
        choices=("parent_child", "none"),
        default=None,
        help="Override parent/child candidate enrichment before production ask rerank.",
    )
    parser.add_argument(
        "--ask-local-retrieval-limit",
        type=int,
        default=None,
        help="Override Ask local memory matches before enrichment/rerank.",
    )
    parser.add_argument(
        "--ask-graph-note-evidence-mode",
        choices=("none", "all", "cited_overlap"),
        default=None,
        help="Control whether Graphiti mapped notes enter production ContextPack evidence.",
    )
    parser.add_argument(
        "--ask-context-max-items",
        type=int,
        default=None,
        help="Override the maximum number of evidence items selected into ContextPack.",
    )
    parser.add_argument(
        "--ask-context-char-budget",
        type=int,
        default=None,
        help="Override the ContextPack character budget.",
    )
    parser.add_argument(
        "--ask-llm-rerank-top-n",
        type=int,
        default=None,
        help="Override the number of heuristic candidates sent to the LLM reranker.",
    )
    parser.add_argument(
        "--local-probe-limit",
        type=int,
        default=100,
        help="Diagnostic local retrieval depth recorded in ask_retrieve snapshots.",
    )
    parser.add_argument(
        "--ask-disable-web",
        action="store_true",
        help="Disable production web fallback during eval to keep corpus-only metrics clean.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    return parser.parse_args()


def _settings_from_args(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    ask_updates: dict[str, object] = {}
    if args.ask_graph_provider is not None:
        ask_updates["graph_provider"] = args.ask_graph_provider
    if args.ask_reranker is not None:
        ask_updates["reranker"] = args.ask_reranker
    if args.ask_candidate_enricher is not None:
        ask_updates["candidate_enricher"] = args.ask_candidate_enricher
    if args.ask_local_retrieval_limit is not None:
        ask_updates["local_retrieval_limit"] = args.ask_local_retrieval_limit
    if args.ask_graph_note_evidence_mode is not None:
        ask_updates["graph_note_evidence_mode"] = args.ask_graph_note_evidence_mode
    if args.ask_context_max_items is not None:
        ask_updates["context_max_items"] = args.ask_context_max_items
    if args.ask_context_char_budget is not None:
        ask_updates["context_char_budget"] = args.ask_context_char_budget
    if args.ask_llm_rerank_top_n is not None:
        ask_updates["llm_rerank_top_n"] = args.ask_llm_rerank_top_n
    if ask_updates:
        settings = settings.model_copy(
            update={"ask": settings.ask.model_copy(update=ask_updates)}
        )
    graph_updates: dict[str, object] = {}
    if args.graph_search_limit is not None:
        graph_updates["search_limit"] = args.graph_search_limit
    if args.graph_search_citation_limit is not None:
        graph_updates["search_citation_limit"] = args.graph_search_citation_limit
    if graph_updates:
        settings = settings.model_copy(
            update={"graphiti": settings.graphiti.model_copy(update=graph_updates)}
        )
    if args.ask_disable_web:
        settings = settings.model_copy(
            update={"web_search": settings.web_search.model_copy(update={"api_key": None})}
        )
    return settings


def main() -> None:
    args = _parse_args()
    strategy_names = [name.strip() for name in args.strategies.split(",") if name.strip()]
    settings = _settings_from_args(args)
    results = run_open_ragbench(
        strategy_names=strategy_names,
        num_queries=args.num_queries,
        seed=args.seed,
        corpus_mode=args.corpus_mode,
        limit=args.limit,
        settings=settings,
        graphiti_user_id=args.graphiti_user_id,
        reset_graphiti=not args.reuse_graphiti,
        graphiti_manifest_path=args.graphiti_manifest,
        graphiti_note_mode=args.graphiti_note_mode,
        graphiti_continue_on_ingest_error=args.graphiti_continue_on_ingest_error,
        local_probe_limit=args.local_probe_limit,
    )

    payload = [result.as_dict() for result in results]
    for result in results:
        print(f"\n[{result.strategy}] {result.elapsed_seconds:.2f}s")
        print(result.report.summary())

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
