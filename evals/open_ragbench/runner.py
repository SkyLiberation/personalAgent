"""Run Open RAGBench retrieval evaluations across comparable strategies."""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from personal_agent.kernel.config import Settings
from personal_agent.kernel.models import KnowledgeNote
from personal_agent.memory.graphiti.store import GraphAskResult, GraphitiStore
from personal_agent.memory.graphiti.search_strategies import STRATEGIES
from personal_agent.memory.ms_graphrag import MicrosoftGraphRagStore

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
    eval_snapshots: dict[str, list[dict]] | None = None
    planner_cache: dict[str, tuple[object, object]] | None = None


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

    def as_dict(self) -> dict:
        payload = {
            "strategy": self.strategy,
            "description": self.description,
            "elapsed_seconds": self.elapsed_seconds,
            "num_docs": self.num_docs,
            "num_queries": self.num_queries,
            "corpus_mode": self.corpus_mode,
            "metrics": self.report.as_dict(),
        }
        if self.diagnostics is not None:
            payload["diagnostics"] = self.diagnostics
        return payload


@dataclass(frozen=True)
class KeywordSearchStrategy:
    name: str = "keyword"
    description: str = "LocalMemoryStore.find_similar_notes keyword-overlap baseline."

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
            result = graph_store.ask(query.query_text, context.graphiti_user_id)
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
    result: GraphAskResult,
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


def _record_eval_snapshot(context: BenchmarkContext, strategy_name: str, snapshot: dict) -> None:
    if context.eval_snapshots is None:
        return
    context.eval_snapshots.setdefault(strategy_name, []).append(snapshot)


def _get_eval_plan(query: RAGBenchQuery, settings: Settings, context: BenchmarkContext):
    from personal_agent.agent.query_planner import plan_retrieval

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
            section = _StructuralSection(
                note_id=f"{parent_id}_sec_{index}",
                parent_id=parent_id,
                doc_id=doc_id,
                index=index,
                tokens=set(_structural_tokens(section_text)),
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
                graph_result = graph_store.ask(effective_query, context.graphiti_user_id)
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
        from personal_agent.agent.runtime import AgentRuntime

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
        ms_store = MicrosoftGraphRagStore(settings)
        if settings.ask.graph_provider.strip().lower() in {"ms_graphrag", "microsoft_graphrag", "graphrag"}:
            ms_store.clear_all_data()
            ms_store.ingest_notes(all_notes, trace_id="ragbench-msgraphrag-ingest")
            ms_store.build_index()
        runtime = AgentRuntime(settings, store, graph_store, ms_graphrag_store=ms_store)

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
            if (
                settings.ask.graph_provider.strip().lower() in {"ms_graphrag", "microsoft_graphrag", "graphrag"}
                and not ranked_ids
            ):
                projection_text = " ".join(
                    part for part in [result.answer, *[item.fact or item.snippet for item in result.evidence]]
                    if part
                )
                projected = store.find_similar_notes(eval_user_id, projection_text, limit=limit)
                ranked_ids = [note.id for note in projected]
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
                    "projection": "answer_to_local_notes" if settings.ask.graph_provider.strip().lower() in {"ms_graphrag", "microsoft_graphrag", "graphrag"} else "",
                },
            )
        return rankings, relevance


def list_strategy_names() -> list[str]:
    real_graph_names = [f"graphiti_{name}" for name in sorted(STRATEGIES)]
    return [
        "keyword",
        "citation_reranker",
        "structural",
        "ask_pipeline",
        "ask_pipeline_no_rewrite",
        "ask_pipeline_local_only",
        "ask_pipeline_no_planner",
        "current_runtime_ask",
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
        eval_snapshots=eval_snapshots,
        planner_cache=planner_cache,
    )
    results: list[BenchmarkRunResult] = []
    for strategy_name in strategy_names:
        strategy = get_strategy(strategy_name)
        started_at = time.perf_counter()
        rankings, relevance = strategy.evaluate(queries, docs, limit=limit, context=context)
        elapsed = time.perf_counter() - started_at
        report = compute_report(rankings, relevance)
        results.append(
            BenchmarkRunResult(
                strategy=strategy.name,
                description=strategy.description,
                report=report,
                elapsed_seconds=elapsed,
                num_docs=len(docs),
                num_queries=len(queries),
                corpus_mode=corpus_mode,
                diagnostics=eval_snapshots.get(strategy.name),
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
        choices=("graphiti", "structural", "hybrid", "ms_graphrag"),
        default=None,
        help="Override the production ask graph provider for current_runtime_ask.",
    )
    parser.add_argument(
        "--ask-reranker",
        choices=("heuristic", "llm"),
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
