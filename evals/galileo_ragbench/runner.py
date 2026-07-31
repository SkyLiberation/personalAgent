"""Run Galileo RAGBench sentence-level retrieval ablations.

This runner intentionally does not reuse Open RAGBench's paper-section
assumptions. Galileo rows already contain candidate documents and sentence-level
labels, so the relevant unit is a sentence evidence note.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from personal_agent.application.rerankers import SupportEvidenceReranker
from personal_agent.kernel.config import Settings
from personal_agent.kernel.evidence import EvidenceItem
from personal_agent.kernel.models import KnowledgeNote

from evals.shared_evidence_selector import (
    EvidenceUnit,
    SharedEvidencePolicy,
    SharedEvidenceSelectorConfig,
    apply_shared_evidence_policy,
    prepare_shared_evidence_corpus,
    select_shared_evidence,
    select_shared_evidence_policies,
)
from evals.open_ragbench.metrics import RetrievalReport, compute_report
from evals.open_ragbench.runner import (
    DATASET_AGNOSTIC_PROFILE,
    GALILEO_RAGBENCH_PROFILE,
    OPEN_RAGBENCH_PROFILE,
    _external_embedding_settings,
    _fuse_ranked_ids,
    _retrieval_eval_snapshot,
)

from .adapter import corpus_to_notes, relevance_by_query, sentence_note_id
from .loader import GalileoExample, Split, load_examples


class GalileoStrategy(Protocol):
    name: str
    description: str

    def evaluate(
        self,
        examples: list[GalileoExample],
        *,
        limit: int,
        context: "GalileoContext",
    ) -> list[tuple[str, list[str]]]:
        ...


@dataclass(frozen=True)
class GalileoContext:
    settings: Settings
    eval_snapshots: dict[str, list[dict]] | None = None
    strategy_configs: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True)
class GalileoRunResult:
    strategy: str
    description: str
    relevant_report: RetrievalReport
    utilized_report: RetrievalReport
    elapsed_seconds: float
    subset: str
    split: str
    num_queries: int
    strategy_config: dict[str, object]
    diagnostics: list[dict] | None = None

    def as_dict(self) -> dict:
        payload = {
            "strategy": self.strategy,
            "description": self.description,
            "elapsed_seconds": self.elapsed_seconds,
            "subset": self.subset,
            "split": self.split,
            "num_queries": self.num_queries,
            "strategy_config": self.strategy_config,
            "metrics": self.relevant_report.as_dict(),
            "utilized_metrics": self.utilized_report.as_dict(),
        }
        if self.diagnostics is not None:
            payload["diagnostics"] = self.diagnostics
        return payload


@dataclass(frozen=True)
class KeywordSentenceStrategy:
    name: str = "galileo_keyword_sentence"
    description: str = "No-DB keyword overlap baseline over sentence evidence notes."

    def evaluate(
        self,
        examples: list[GalileoExample],
        *,
        limit: int,
        context: GalileoContext,
    ) -> list[tuple[str, list[str]]]:
        rankings: list[tuple[str, list[str]]] = []
        for example in examples:
            ranked = _rank_keyword_sentences(example)[:limit]
            rankings.append((example.query_id, ranked))
            _record_snapshot(context, self.name, example, ranked, ranked, extra={
                "strategy_profile": DATASET_AGNOSTIC_PROFILE.name,
                "strategy_flags": _profile_flags(DATASET_AGNOSTIC_PROFILE),
            })
        return rankings


@dataclass(frozen=True)
class DocFirstLexicalSentenceStrategy:
    name: str = "galileo_doc_first_lexical"
    description: str = "No-DB Open-like document-first lexical sentence ranking ablation."

    def evaluate(
        self,
        examples: list[GalileoExample],
        *,
        limit: int,
        context: GalileoContext,
    ) -> list[tuple[str, list[str]]]:
        rankings: list[tuple[str, list[str]]] = []
        for example in examples:
            ranked = _rank_doc_first_sentences_from_example(example)[:limit]
            rankings.append((example.query_id, ranked))
            _record_snapshot(context, self.name, example, ranked, ranked, extra={
                "strategy_profile": OPEN_RAGBENCH_PROFILE.name,
                "strategy_flags": _profile_flags(OPEN_RAGBENCH_PROFILE),
                "doc_first_enabled": True,
                "slot_refine_enabled": False,
            })
        return rankings


@dataclass(frozen=True)
class ExternalSentenceEmbeddingStrategy:
    name: str = "galileo_external_sentence_embedding"
    description: str = "External embedding retrieval over sentence evidence notes only."

    def evaluate(
        self,
        examples: list[GalileoExample],
        *,
        limit: int,
        context: GalileoContext,
    ) -> list[tuple[str, list[str]]]:
        settings = _external_embedding_settings(context.settings)
        store, notes = _new_eval_store(settings, examples)
        sentence_ids = {note.id for note in notes if _is_sentence_id(note.id)}
        rankings: list[tuple[str, list[str]]] = []
        for example in examples:
            raw_ids = _note_ids(store.find_similar_notes(
                "galileo_ragbench_eval",
                example.question,
                limit=max(limit * 5, 50),
            ))
            ranked = [note_id for note_id in raw_ids if note_id in sentence_ids][:limit]
            rankings.append((example.query_id, ranked))
            _record_snapshot(context, self.name, example, ranked, raw_ids, extra={
                "strategy_profile": DATASET_AGNOSTIC_PROFILE.name,
                "strategy_flags": _profile_flags(DATASET_AGNOSTIC_PROFILE),
                **_retrieval_eval_snapshot(store),
            })
        return rankings


@dataclass(frozen=True)
class OpenLikeDocFirstSentenceFusionStrategy:
    name: str = "galileo_open_like_doc_first_fusion"
    description: str = (
        "Open-like structural-prior ablation: sentence embedding retrieval fused "
        "with document-first sentence ranking."
    )
    doc_first_weight: float = 0.2

    def evaluate(
        self,
        examples: list[GalileoExample],
        *,
        limit: int,
        context: GalileoContext,
    ) -> list[tuple[str, list[str]]]:
        settings = _external_embedding_settings(context.settings)
        store, notes = _new_eval_store(settings, examples)
        sentence_ids = {note.id for note in notes if _is_sentence_id(note.id)}
        notes_by_query = _notes_by_query(notes)
        rankings: list[tuple[str, list[str]]] = []
        for example in examples:
            raw_ids = _note_ids(store.find_similar_notes(
                "galileo_ragbench_eval",
                example.question,
                limit=max(limit * 5, 50),
            ))
            local_ids = [note_id for note_id in raw_ids if note_id in sentence_ids]
            doc_first_ids = _rank_doc_first_sentences(example, notes_by_query.get(example.query_id, []))
            ranked = _fuse_ranked_ids(
                local_ids,
                doc_first_ids,
                limit=limit,
                secondary_weight=self.doc_first_weight,
            )
            rankings.append((example.query_id, ranked))
            _record_snapshot(context, self.name, example, ranked, raw_ids, extra={
                "strategy_profile": OPEN_RAGBENCH_PROFILE.name,
                "strategy_flags": _profile_flags(OPEN_RAGBENCH_PROFILE),
                "doc_first_ids_top20": doc_first_ids[:20],
                "doc_first_weight": self.doc_first_weight,
                **_retrieval_eval_snapshot(store),
            })
        return rankings


@dataclass(frozen=True)
class GalileoProfileStrategy(ExternalSentenceEmbeddingStrategy):
    name: str = "galileo_profile_sentence_embedding"
    description: str = "Galileo profile: doc-first and same-doc slot refinement disabled."

    def evaluate(
        self,
        examples: list[GalileoExample],
        *,
        limit: int,
        context: GalileoContext,
    ) -> list[tuple[str, list[str]]]:
        rankings = super().evaluate(examples, limit=limit, context=context)
        if context.eval_snapshots and self.name in context.eval_snapshots:
            for snapshot in context.eval_snapshots[self.name]:
                snapshot["strategy_profile"] = GALILEO_RAGBENCH_PROFILE.name
                snapshot["strategy_flags"] = _profile_flags(GALILEO_RAGBENCH_PROFILE)
        return rankings


@dataclass(frozen=True)
class ProductionSupportSentenceStrategy:
    name: str = "galileo_production_support_sentence"
    description: str = (
        "Production support reranker over Galileo sentence evidence notes, "
        "with no document-first, section-slot, or dataset-specific priors."
    )

    def evaluate(
        self,
        examples: list[GalileoExample],
        *,
        limit: int,
        context: GalileoContext,
    ) -> list[tuple[str, list[str]]]:
        evidence_by_query = _sentence_evidence_by_query(corpus_to_notes(examples))
        reranker = SupportEvidenceReranker(context.settings)
        rankings: list[tuple[str, list[str]]] = []
        for example in examples:
            evidence = evidence_by_query.get(example.query_id, [])
            pack = reranker.rerank(
                example.question,
                evidence,
                max_items=limit,
                char_budget=max(1000, limit * 1000),
                mmr_lambda=1.0,
            )
            ranked = [
                item.evidence.evidence_id
                for item in pack.selected
                if _is_sentence_id(item.evidence.evidence_id)
            ][:limit]
            raw_ids = [item.evidence_id for item in evidence]
            rankings.append((example.query_id, ranked))
            _record_snapshot(context, self.name, example, ranked, raw_ids, extra={
                "strategy_profile": DATASET_AGNOSTIC_PROFILE.name,
                "strategy_flags": _profile_flags(DATASET_AGNOSTIC_PROFILE),
                "production_support_reranker": True,
                "doc_first_enabled": False,
                "slot_refine_enabled": False,
                "support_telemetry": dict(reranker.last_telemetry),
                "support_ranked_top20": [
                    {
                        "id": item.evidence.evidence_id,
                        "score": item.score,
                        "reason": item.reason,
                        "support_status": item.evidence.metadata.get("support_status"),
                        "support_coverage": item.evidence.metadata.get("support_coverage"),
                    }
                    for item in pack.selected[:20]
                ],
            })
        return rankings


@dataclass(frozen=True)
class SharedEvidenceSelectorSentenceStrategy:
    name: str = "galileo_shared_evidence_selector"
    description: str = (
        "Dataset-agnostic shared evidence selector over Galileo sentence units "
        "using lexical/support scoring, with no document-first prior."
    )
    external_embedding: bool = False
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
        examples: list[GalileoExample],
        *,
        limit: int,
        context: GalileoContext,
    ) -> list[tuple[str, list[str]]]:
        settings = _external_embedding_settings(context.settings) if self.external_embedding else context.settings
        store = None
        notes = corpus_to_notes(examples)
        if self.external_embedding:
            store, notes = _new_eval_store(settings, examples)
        sentence_ids = {note.id for note in notes if _is_sentence_id(note.id)}
        selector_config = SharedEvidenceSelectorConfig(
            embedding_weight=self.embedding_weight,
            lexical_rrf_weight=self.lexical_rrf_weight,
            lexical_weight=self.lexical_weight,
            support_weight=self.support_weight,
            include_parent_companions=self.include_parent_companions,
            exclude_low_information_units=self.exclude_low_information_units,
        )
        units_by_query = _sentence_units_by_query(notes)
        prepared_by_query = {
            query_id: prepare_shared_evidence_corpus(units, config=selector_config)
            for query_id, units in units_by_query.items()
        }
        unit_by_id = {
            unit.id: unit
            for corpus in prepared_by_query.values()
            for unit in corpus.units
        }
        model_client = None
        if self.use_policy_selector:
            from personal_agent.infra.structured_model import build_structured_model_client

            model_client = build_structured_model_client(settings.structured, settings.langsmith)

        records: list[dict[str, object]] = []
        policy_inputs: list[tuple[str, str, list[str]]] = []
        for example in examples:
            prepared_units = prepared_by_query.get(example.query_id)
            if prepared_units is None:
                prepared_units = prepare_shared_evidence_corpus([], config=selector_config)
            raw_ids = (
                _note_ids(store.find_similar_notes(
                    "galileo_ragbench_eval",
                    example.question,
                    limit=max(limit * 5, 50),
                ))
                if store is not None else []
            )
            embedding_ids = [note_id for note_id in raw_ids if note_id in sentence_ids]
            selection = select_shared_evidence(
                example.question,
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
                        example.query_id,
                        example.question,
                        selected_before_policy[:self.policy_top_m],
                    ))
            records.append({
                "example": example,
                "selection": selection,
                "selected_before_policy": selected_before_policy,
                "raw_ids": raw_ids,
                "embedding_ids": embedding_ids,
                "policy_applied_reason": policy_applied_reason,
                "retrieval_snapshot": _retrieval_eval_snapshot(store) if store is not None else {},
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
        for record in records:
            example = record["example"]
            assert isinstance(example, GalileoExample)
            selection = record["selection"]
            assert hasattr(selection, "ranked_ids")
            selected_before_policy = list(record["selected_before_policy"])
            raw_ids = list(record["raw_ids"])
            embedding_ids = list(record["embedding_ids"])
            policy = SharedEvidencePolicy()
            policy_error: str | None = None
            policy_retry_attempts = 0
            policy_retry_errors: list[str] = []
            policy_response_model: str | None = None
            policy_applied_reason = str(record["policy_applied_reason"])
            decision = policy_decisions.get(example.query_id)
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
            rankings.append((example.query_id, ranked))
            _record_snapshot(context, self.name, example, ranked, raw_ids or ranked, extra={
                "strategy_profile": DATASET_AGNOSTIC_PROFILE.name,
                "strategy_flags": _profile_flags(DATASET_AGNOSTIC_PROFILE),
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
                "slot_refine_enabled": False,
                "embedding_ids_top20": embedding_ids[:20],
                **selection.diagnostics,
                **record["retrieval_snapshot"],
            })
        return rankings


def list_strategy_names() -> list[str]:
    return [
        "galileo_keyword_sentence",
        "galileo_doc_first_lexical",
        "galileo_external_sentence_embedding",
        "galileo_open_like_doc_first_fusion",
        "galileo_profile_sentence_embedding",
        "galileo_production_support_sentence",
        "galileo_shared_evidence_selector",
        "galileo_shared_embedding_evidence_selector",
        "galileo_shared_evidence_policy_selector",
    ]


def get_strategy(name: str) -> GalileoStrategy:
    normalized = name.strip().lower()
    if normalized == "galileo_keyword_sentence":
        return KeywordSentenceStrategy()
    if normalized == "galileo_doc_first_lexical":
        return DocFirstLexicalSentenceStrategy()
    if normalized == "galileo_external_sentence_embedding":
        return ExternalSentenceEmbeddingStrategy()
    if normalized == "galileo_open_like_doc_first_fusion":
        return OpenLikeDocFirstSentenceFusionStrategy()
    if normalized == "galileo_profile_sentence_embedding":
        return GalileoProfileStrategy()
    if normalized == "galileo_production_support_sentence":
        return ProductionSupportSentenceStrategy()
    if normalized == "galileo_shared_evidence_selector":
        return SharedEvidenceSelectorSentenceStrategy()
    if normalized == "galileo_shared_embedding_evidence_selector":
        return SharedEvidenceSelectorSentenceStrategy(
            name="galileo_shared_embedding_evidence_selector",
            description=(
                "Dataset-agnostic shared evidence selector over Galileo sentence units "
                "using embedding-ranked candidates plus lexical/support scoring."
            ),
            external_embedding=True,
        )
    if normalized == "galileo_shared_evidence_policy_selector":
        return SharedEvidenceSelectorSentenceStrategy(
            name="galileo_shared_evidence_policy_selector",
            description=(
                "Dataset-agnostic shared evidence selector over Galileo sentence units "
                "with a shared LLM support/utilization policy selector."
            ),
            external_embedding=True,
            use_policy_selector=True,
        )
    available = ", ".join(list_strategy_names())
    raise ValueError(f"Unknown Galileo RAGBench strategy '{name}'. Available: {available}")


def run_galileo_ragbench(
    *,
    strategy_names: list[str],
    subset: str = "covidqa",
    split: Split = "test",
    num_queries: int | None = None,
    seed: int = 13,
    limit: int = 10,
    settings: Settings | None = None,
    cache_dir: Path | None = None,
) -> list[GalileoRunResult]:
    settings = settings or Settings.from_env()
    examples = load_examples(
        subset=subset,
        split=split,
        num_queries=num_queries,
        seed=seed,
        cache_dir=cache_dir,
    )
    relevant = relevance_by_query(examples, mode="relevant")
    utilized = relevance_by_query(examples, mode="utilized")

    eval_snapshots: dict[str, list[dict]] = {}
    context = GalileoContext(settings=settings, eval_snapshots=eval_snapshots)
    results: list[GalileoRunResult] = []
    for name in strategy_names:
        strategy = get_strategy(name)
        start = time.perf_counter()
        rankings = strategy.evaluate(examples, limit=limit, context=context)
        elapsed = round(time.perf_counter() - start, 3)
        config = _strategy_config(strategy)
        results.append(GalileoRunResult(
            strategy=strategy.name,
            description=strategy.description,
            relevant_report=compute_report(rankings, relevant),
            utilized_report=compute_report(rankings, utilized),
            elapsed_seconds=elapsed,
            subset=subset,
            split=split,
            num_queries=len(examples),
            strategy_config=config,
            diagnostics=eval_snapshots.get(strategy.name),
        ))
    return results


def _new_eval_store(settings: Settings, examples: list[GalileoExample]):
    import tempfile
    from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore

    tmp_dir = Path(tempfile.mkdtemp(prefix="galileo_ragbench_eval_"))
    store = PostgresMemoryStore(
        data_dir=tmp_dir,
        postgres_url=settings.postgres_url,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.openai.embedding_model,
        embedding_api_key=settings.openai.embedding_api_key or settings.openai.api_key,
        embedding_base_url=settings.openai.embedding_base_url or settings.openai.base_url,
    )
    store.ensure_schema()
    store.clear_user_data("galileo_ragbench_eval", remove_uploaded_files=False)
    notes = [
        note.model_copy(update={"user_id": "galileo_ragbench_eval"})
        for note in corpus_to_notes(examples)
    ]
    for note in notes:
        store.add_note(note)
    return store, notes


def _record_snapshot(
    context: GalileoContext,
    strategy_name: str,
    example: GalileoExample,
    ranked: list[str],
    raw_ids: list[str],
    *,
    extra: dict[str, object] | None = None,
) -> None:
    if context.eval_snapshots is None:
        return
    snapshot = {
        "query_id": example.query_id,
        "question": example.question,
        "dataset_name": example.dataset_name,
        "relevant_sentence_keys": list(example.relevant_sentence_keys),
        "utilized_sentence_keys": list(example.utilized_sentence_keys),
        "expected_relevant_ids": sorted(relevance_by_query([example], mode="relevant")[example.query_id]),
        "expected_utilized_ids": sorted(relevance_by_query([example], mode="utilized")[example.query_id]),
        "ranked_ids": ranked,
        "raw_retrieval_ids_top20": raw_ids[:20],
    }
    if extra:
        snapshot.update(extra)
    context.eval_snapshots.setdefault(strategy_name, []).append(snapshot)


def _strategy_config(strategy: GalileoStrategy) -> dict[str, object]:
    if isinstance(strategy, ProductionSupportSentenceStrategy):
        return {
            "strategy_profile": DATASET_AGNOSTIC_PROFILE.name,
            "strategy_flags": _profile_flags(DATASET_AGNOSTIC_PROFILE),
            "retrieval_backend": "lexical",
            "doc_first_enabled": False,
            "doc_first_weight": None,
            "slot_refine_enabled": False,
            "sentence_selector_enabled": True,
            "production_support_reranker": True,
            "relevance_modes": ["relevant", "utilized"],
        }
    if isinstance(strategy, SharedEvidenceSelectorSentenceStrategy):
        return {
            "strategy_profile": DATASET_AGNOSTIC_PROFILE.name,
            "strategy_flags": _profile_flags(DATASET_AGNOSTIC_PROFILE),
            "retrieval_backend": "postgres_embedding" if strategy.external_embedding else "lexical",
            "doc_first_enabled": False,
            "doc_first_weight": None,
            "slot_refine_enabled": False,
            "sentence_selector_enabled": True,
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
            "relevance_modes": ["relevant", "utilized"],
        }
    if isinstance(strategy, DocFirstLexicalSentenceStrategy):
        return {
            "strategy_profile": OPEN_RAGBENCH_PROFILE.name,
            "strategy_flags": _profile_flags(OPEN_RAGBENCH_PROFILE),
            "retrieval_backend": "lexical",
            "doc_first_enabled": True,
            "doc_first_weight": None,
            "slot_refine_enabled": False,
            "sentence_selector_enabled": True,
            "relevance_modes": ["relevant", "utilized"],
        }
    if isinstance(strategy, OpenLikeDocFirstSentenceFusionStrategy):
        return {
            "strategy_profile": OPEN_RAGBENCH_PROFILE.name,
            "strategy_flags": _profile_flags(OPEN_RAGBENCH_PROFILE),
            "doc_first_enabled": True,
            "doc_first_weight": strategy.doc_first_weight,
            "slot_refine_enabled": False,
            "sentence_selector_enabled": True,
            "relevance_modes": ["relevant", "utilized"],
        }
    profile = (
        GALILEO_RAGBENCH_PROFILE
        if isinstance(strategy, GalileoProfileStrategy)
        else DATASET_AGNOSTIC_PROFILE
    )
    return {
        "strategy_profile": profile.name,
        "strategy_flags": _profile_flags(profile),
        "retrieval_backend": "postgres_embedding" if not isinstance(strategy, KeywordSentenceStrategy) else "lexical",
        "doc_first_enabled": False,
        "doc_first_weight": None,
        "slot_refine_enabled": False,
        "sentence_selector_enabled": True,
        "relevance_modes": ["relevant", "utilized"],
    }


def _rank_doc_first_sentences(example: GalileoExample, notes: list[KnowledgeNote]) -> list[str]:
    parents = [note for note in notes if not _is_sentence_id(note.id)]
    children_by_parent: dict[str, list[KnowledgeNote]] = {}
    for note in notes:
        parent_id = note.parent_note_id
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(note)

    query_tokens = _tokens(example.question)
    parent_scores = [
        (_token_overlap(query_tokens, _tokens(parent.content)), parent.id)
        for parent in parents
    ]
    parent_scores.sort(key=lambda item: (-item[0], item[1]))
    ranked: list[str] = []
    for _, parent_id in parent_scores:
        children = children_by_parent.get(parent_id, [])
        children.sort(
            key=lambda note: (
                -_token_overlap(query_tokens, _tokens(note.content)),
                note.id,
            )
        )
        ranked.extend(note.id for note in children)
    return ranked


def _rank_keyword_sentences(example: GalileoExample) -> list[str]:
    query_tokens = _tokens(example.question)
    scored = [
        (
            _token_overlap(query_tokens, _tokens(sentence.text)),
            sentence_note_id(example.query_id, sentence.key),
        )
        for sentence in example.sentences
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [note_id for score, note_id in scored if score > 0] or [note_id for _, note_id in scored]


def _rank_doc_first_sentences_from_example(example: GalileoExample) -> list[str]:
    query_tokens = _tokens(example.question)
    doc_scores = [
        (_token_overlap(query_tokens, _tokens(document)), doc_index)
        for doc_index, document in enumerate(example.documents)
    ]
    doc_scores.sort(key=lambda item: (-item[0], item[1]))
    ranked: list[str] = []
    for _, doc_index in doc_scores:
        sentences = [
            sentence for sentence in example.sentences
            if sentence.document_index == doc_index
        ]
        sentences.sort(key=lambda sentence: (
            -_token_overlap(query_tokens, _tokens(sentence.text)),
            sentence.key,
        ))
        ranked.extend(sentence_note_id(example.query_id, sentence.key) for sentence in sentences)
    return ranked


def _notes_by_query(notes: list[KnowledgeNote]) -> dict[str, list[KnowledgeNote]]:
    grouped: dict[str, list[KnowledgeNote]] = {}
    for note in notes:
        match = re.match(r"galileo_(.+?)_(?:doc|sent)_", note.id)
        if not match:
            continue
        grouped.setdefault(match.group(1), []).append(note)
    return grouped


def _sentence_units_by_query(notes: list[KnowledgeNote]) -> dict[str, list[EvidenceUnit]]:
    grouped: dict[str, list[EvidenceUnit]] = {}
    for note in notes:
        if not _is_sentence_id(note.id):
            continue
        match = re.match(r"galileo_(.+?)_sent_", note.id)
        if not match:
            continue
        grouped.setdefault(match.group(1), []).append(EvidenceUnit(
            id=note.id,
            text=note.content or note.summary or note.title,
            title=note.title or "",
            parent_id=note.parent_note_id,
            kind="sentence",
        ))
    return grouped


def _sentence_evidence_by_query(notes: list[KnowledgeNote]) -> dict[str, list[EvidenceItem]]:
    grouped: dict[str, list[EvidenceItem]] = {}
    for note in notes:
        if not _is_sentence_id(note.id):
            continue
        match = re.match(r"galileo_(.+?)_sent_", note.id)
        if not match:
            continue
        text = note.content or note.summary or note.title
        grouped.setdefault(match.group(1), []).append(EvidenceItem(
            evidence_id=note.id,
            source_type="chunk",
            source_id=note.id,
            parent_note_id=note.parent_note_id,
            title=note.title or "",
            snippet=text,
            source_ref=note.id,
            metadata={
                "retrieved_by": "galileo_sentence_corpus",
                "candidate_source_type": "sparse",
            },
        ))
    return grouped


def _note_ids(notes: list[KnowledgeNote]) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for note in notes:
        if note.id in seen:
            continue
        seen.add(note.id)
        ids.append(note.id)
    return ids


def _is_sentence_id(note_id: str) -> bool:
    return "_sent_" in note_id


def _profile_flags(profile) -> dict[str, object]:
    return {
        "profile_name": profile.name,
        "doc_first_enabled": profile.doc_first_enabled,
        "doc_first_weight": profile.doc_first_weight,
        "slot_refine_enabled": profile.slot_refine_enabled,
        "sentence_selector_enabled": profile.sentence_selector_enabled,
        "policy_selector_enabled": profile.policy_selector_enabled,
        "group_prior_enabled": profile.group_prior_enabled,
    }


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z0-9_+-]+", text.lower())
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _token_overlap(query_tokens: set[str], candidate_tokens: set[str]) -> int:
    return len(query_tokens & candidate_tokens)


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was",
    "were", "which", "what", "how", "why", "when", "where", "who", "may",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Galileo RAGBench retrieval evals.")
    parser.add_argument("--strategy", action="append", dest="strategies", choices=list_strategy_names())
    parser.add_argument("--subset", default="covidqa")
    parser.add_argument("--split", default="test", choices=["train", "validation", "test"])
    parser.add_argument("--num-queries", type=int, default=10)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("evals/galileo_ragbench/results/latest.json"))
    args = parser.parse_args()

    strategies = args.strategies or list_strategy_names()
    results = run_galileo_ragbench(
        strategy_names=strategies,
        subset=args.subset,
        split=args.split,
        num_queries=args.num_queries,
        seed=args.seed,
        limit=args.limit,
    )
    payload = [result.as_dict() for result in results]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in results:
        print(f"\n{result.strategy}")
        print("Relevant:")
        print(result.relevant_report.summary())
        print("Utilized:")
        print(result.utilized_report.summary())


if __name__ == "__main__":
    main()
