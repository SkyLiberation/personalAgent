"""Run MultiHopRAG retrieval evaluations across comparable strategies.

Mirrors ``evals.open_ragbench.runner`` but binds the MultiHopRAG loader/adapter
and reports metrics grouped by ``question_type``. Strategies operate over the
parent+chunk KnowledgeNote view produced by ``adapter.corpus_to_notes`` so they
stay dataset-agnostic; relevance is the multi-hop *set* of evidence parents.

The expensive Graphiti ingest is cached the same way Open RAGBench does it:
an in-process cache plus an on-disk manifest reused via ``--reuse-graphiti``.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from personal_agent.core.config import Settings
from personal_agent.core.models import KnowledgeNote
from personal_agent.graphiti.store import GraphitiStore
from personal_agent.graphiti.search_strategies import STRATEGIES
from personal_agent.ms_graphrag import MicrosoftGraphRagStore

# Reuse dataset-agnostic Graphiti ingest + manifest plumbing from open_ragbench.
from evals.open_ragbench.runner import (
    _attach_graph_episode_ids_to_store,
    _ensure_graphiti_corpus,
    _ranked_note_ids_from_graph_result,
)

from .adapter import (
    CorpusNoteMode,
    corpus_to_edges,
    corpus_to_notes,
    expected_note_ids,
)
from .loader import CorpusMode, MHRDoc, MHRQuery, load_benchmark
from .metrics import RetrievalReport, compute_grouped_report, format_grouped_report


class BenchmarkStrategy(Protocol):
    name: str
    description: str

    def evaluate(
        self,
        queries: list[MHRQuery],
        docs: dict[str, MHRDoc],
        *,
        limit: int,
        context: "BenchmarkContext",
    ) -> list[tuple[str, list[str]]]:
        ...


@dataclass(frozen=True)
class BenchmarkContext:
    settings: Settings
    graphiti_user_id: str
    reset_graphiti: bool
    graphiti_manifest_path: Path | None
    note_mode: CorpusNoteMode
    graphiti_continue_on_ingest_error: bool
    eval_snapshots: dict[str, list[dict]] | None = None


@dataclass(frozen=True)
class BenchmarkRunResult:
    strategy: str
    description: str
    grouped: dict[str, RetrievalReport]
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
            "metrics": self.grouped["overall"].as_dict(),
            "grouped_metrics": {
                qtype: report.as_dict() for qtype, report in self.grouped.items()
            },
        }
        if self.diagnostics is not None:
            payload["diagnostics"] = self.diagnostics
        return payload


def _relevance(queries: list[MHRQuery]) -> dict[str, set[str]]:
    return {q.query_id: expected_note_ids(q) for q in queries}


def _query_types(queries: list[MHRQuery]) -> dict[str, str]:
    return {q.query_id: q.question_type for q in queries}


def _record_eval_snapshot(context: BenchmarkContext, strategy_name: str, snapshot: dict) -> None:
    if context.eval_snapshots is None:
        return
    context.eval_snapshots.setdefault(strategy_name, []).append(snapshot)


# ----------------------------------------------------------------------------
# Local store provisioning (MHR-specific because notes come from MHR adapter)
# ----------------------------------------------------------------------------


def _new_eval_store(
    settings: Settings,
    docs: dict[str, MHRDoc],
    *,
    user_id: str,
    note_mode: CorpusNoteMode,
):
    import tempfile
    from personal_agent.storage.postgres_memory_store import PostgresMemoryStore

    tmp_dir = Path(tempfile.mkdtemp(prefix="multihoprag_eval_"))
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
        for note in corpus_to_notes(docs, mode=note_mode)
    ]
    for note in notes:
        store.add_note(note)
    return store, notes


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
        note_mode=context.note_mode,
        continue_on_ingest_error=context.graphiti_continue_on_ingest_error,
    )


# ----------------------------------------------------------------------------
# Strategies
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class KeywordSearchStrategy:
    name: str = "keyword"
    description: str = "Keyword-overlap baseline over parent+chunk notes."

    def evaluate(
        self,
        queries: list[MHRQuery],
        docs: dict[str, MHRDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> list[tuple[str, list[str]]]:
        all_notes = corpus_to_notes(docs, mode=context.note_mode)
        note_by_id = {note.id: note for note in all_notes}
        haystacks = {
            note.id: f"{note.title} {note.summary} {note.content}".lower()
            for note in all_notes
        }

        rankings: list[tuple[str, list[str]]] = []
        for query in queries:
            tokens = {t.lower() for t in query.query_text.split() if t.strip()}
            scored: list[tuple[int, str]] = []
            for note_id, haystack in haystacks.items():
                score = sum(1 for t in tokens if t in haystack)
                if score > 0:
                    scored.append((score, note_id))
            scored.sort(key=lambda item: item[0], reverse=True)

            result_ids: list[str] = []
            for _, note_id in scored:
                if len(result_ids) >= limit * 2:
                    break
                note = note_by_id[note_id]
                pid = note.parent_note_id
                # Collapse chunk hits onto their parent (relevance is parent-level).
                target = pid if pid is not None else note_id
                if target not in result_ids:
                    result_ids.append(target)
            rankings.append((query.query_id, result_ids[:limit]))
        return rankings


@dataclass(frozen=True)
class CitationRerankStrategy:
    name: str = "citation_reranker"
    description: str = (
        "Standalone relation-fact citation reranker over chunk-shaped pseudo edges."
    )

    def evaluate(
        self,
        queries: list[MHRQuery],
        docs: dict[str, MHRDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> list[tuple[str, list[str]]]:
        from personal_agent.graphiti.reranker import rank_graph_citation_hits

        edges, node_names = corpus_to_edges(docs)
        # episode "ep_{pid}_{idx}" -> parent note id "{pid}"
        ep_to_parent = {
            ep: ep.removeprefix("ep_").rsplit("_", 1)[0]
            for edge in edges
            for ep in edge.episodes
        }

        rankings: list[tuple[str, list[str]]] = []
        for query in queries:
            hits = rank_graph_citation_hits(
                query.query_text, edges, node_names, limit=limit * 3
            )
            result_ids: list[str] = []
            for hit in hits:
                pid = ep_to_parent.get(hit.episode_uuid)
                if pid and pid not in result_ids:
                    result_ids.append(pid)
                if len(result_ids) >= limit:
                    break
            rankings.append((query.query_id, result_ids[:limit]))
        return rankings


@dataclass(frozen=True)
class GraphRagStrategy:
    name: str = "graphrag"
    description: str = (
        "Offline GraphRAG-style baseline over a document-chunk graph with local "
        "chunk scoring and parent/sibling score propagation (collapsed to parents)."
    )

    def evaluate(
        self,
        queries: list[MHRQuery],
        docs: dict[str, MHRDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> list[tuple[str, list[str]]]:
        graph = _build_graphrag_index(docs)
        rankings: list[tuple[str, list[str]]] = []
        for query in queries:
            ranked_notes = _rank_graphrag_notes(query.query_text, graph, limit=limit * 3)
            # Collapse chunk note ids onto parents.
            result_ids: list[str] = []
            for note_id in ranked_notes:
                pid = note_id.split("_sec_")[0]
                if pid not in result_ids:
                    result_ids.append(pid)
                if len(result_ids) >= limit:
                    break
            rankings.append((query.query_id, result_ids[:limit]))
        return rankings


@dataclass(frozen=True)
class _GraphRagSection:
    note_id: str
    parent_id: str
    index: int
    tokens: set[str]


@dataclass(frozen=True)
class _GraphRagDoc:
    note_id: str
    tokens: set[str]
    sections: list[_GraphRagSection]


@dataclass(frozen=True)
class _GraphRagIndex:
    docs: list[_GraphRagDoc]
    sections: list[_GraphRagSection]
    document_frequency: dict[str, int]
    num_sections: int


def _build_graphrag_index(docs: dict[str, MHRDoc]) -> _GraphRagIndex:
    from .adapter import parent_note_id
    from personal_agent.core.chunking import chunk_content

    graph_docs: list[_GraphRagDoc] = []
    sections: list[_GraphRagSection] = []
    document_frequency: dict[str, int] = {}

    for url, doc in docs.items():
        pid = parent_note_id(url)
        doc_tokens = set(_graphrag_tokens(f"{doc.title}\n{doc.body[:500]}"))
        doc_sections: list[_GraphRagSection] = []
        for index, chunk in enumerate(chunk_content(doc.body, "text")):
            content = chunk.get("content", "").strip()
            if not content:
                continue
            section = _GraphRagSection(
                note_id=f"{pid}_sec_{index}",
                parent_id=pid,
                index=index,
                tokens=set(_graphrag_tokens(content)),
            )
            doc_sections.append(section)
            sections.append(section)
            for token in section.tokens:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        graph_docs.append(_GraphRagDoc(note_id=pid, tokens=doc_tokens, sections=doc_sections))

    return _GraphRagIndex(
        docs=graph_docs,
        sections=sections,
        document_frequency=document_frequency,
        num_sections=max(1, len(sections)),
    )


def _rank_graphrag_notes(query: str, graph: _GraphRagIndex, *, limit: int) -> list[str]:
    query_tokens = _graphrag_tokens(query)
    if not query_tokens:
        return []

    section_scores: dict[str, float] = {}
    parent_scores: dict[str, float] = {}

    for doc in graph.docs:
        doc_score = _token_score(query_tokens, doc.tokens, graph)
        if doc_score > 0:
            parent_scores[doc.note_id] = doc_score * 0.8

        best_section_score = 0.0
        for section in doc.sections:
            local_score = _token_score(query_tokens, section.tokens, graph)
            propagated = local_score + doc_score * 0.25
            if propagated <= 0:
                continue
            section_scores[section.note_id] = propagated
            best_section_score = max(best_section_score, local_score)

        if best_section_score > 0:
            parent_scores[doc.note_id] = max(
                parent_scores.get(doc.note_id, 0.0), best_section_score * 0.7
            )

    scored: list[tuple[float, str]] = []
    scored.extend((s, nid) for nid, s in section_scores.items())
    scored.extend((s, nid) for nid, s in parent_scores.items())
    scored.sort(key=lambda item: item[0], reverse=True)

    ranked: list[str] = []
    seen: set[str] = set()
    for _, note_id in scored:
        if note_id in seen:
            continue
        ranked.append(note_id)
        seen.add(note_id)
        if len(ranked) >= limit:
            break
    return ranked


def _token_score(query_tokens: list[str], candidate_tokens: set[str], graph: _GraphRagIndex) -> float:
    score = 0.0
    for token in query_tokens:
        if token not in candidate_tokens:
            continue
        df = graph.document_frequency.get(token, 0)
        idf = math.log((graph.num_sections + 1) / (df + 1)) + 1.0
        score += idf * (1.5 if len(token) >= 6 else 1.0)
    return score


def _graphrag_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9_+-]+|[一-鿿]+", text.lower()):
        if len(raw) < 2 or raw in _GRAPHRAG_STOPWORDS:
            continue
        tokens.append(raw)
    return tokens


_GRAPHRAG_STOPWORDS = {
    "the", "and", "for", "from", "with", "that", "this", "are", "was", "were",
    "into", "about", "what", "which", "where", "when", "how", "why", "who",
}


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
        queries: list[MHRQuery],
        docs: dict[str, MHRDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> list[tuple[str, list[str]]]:
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

        notes = corpus_to_notes(docs, mode=context.note_mode)
        episode_to_note_id = _ensure_graphiti_corpus(
            graph_store=graph_store,
            notes=notes,
            user_id=context.graphiti_user_id,
            reset=context.reset_graphiti,
            manifest_path=context.graphiti_manifest_path,
            note_mode=context.note_mode,
            continue_on_ingest_error=context.graphiti_continue_on_ingest_error,
        )

        rankings: list[tuple[str, list[str]]] = []
        for query in queries:
            result = graph_store.ask(query.query_text, context.graphiti_user_id)
            if not result.enabled:
                raise RuntimeError(f"Graphiti ask failed for {query.query_id}: {result.error}")
            ranked = _ranked_note_ids_from_graph_result(result, episode_to_note_id, limit * 3)
            # Collapse chunk hits onto parents (relevance is parent-level).
            collapsed: list[str] = []
            for nid in ranked:
                pid = nid.split("_sec_")[0]
                if pid not in collapsed:
                    collapsed.append(pid)
                if len(collapsed) >= limit:
                    break
            rankings.append((query.query_id, collapsed[:limit]))
        return rankings


@dataclass(frozen=True)
class RuntimeAskStrategy:
    """Full production runtime Ask path over the MultiHopRAG corpus."""

    name: str = "current_runtime_ask"
    description: str = (
        "Full AgentRuntime.execute_ask path over the eval corpus. "
        "Runs generation/verifier, so it is slower than retrieval-only strategies."
    )

    def evaluate(
        self,
        queries: list[MHRQuery],
        docs: dict[str, MHRDoc],
        *,
        limit: int,
        context: BenchmarkContext,
    ) -> list[tuple[str, list[str]]]:
        from personal_agent.agent.runtime import AgentRuntime

        settings = context.settings
        eval_user_id = context.graphiti_user_id
        store, all_notes = _new_eval_store(
            settings, docs, user_id=eval_user_id, note_mode=context.note_mode
        )
        graph_store = GraphitiStore(settings)
        if settings.ask.graph_provider.strip().lower() in {"graphiti", "hybrid"}:
            episode_to_note_id = _ensure_eval_graph_mapping(
                graph_store=graph_store, notes=all_notes, context=context
            )
            _attach_graph_episode_ids_to_store(store, all_notes, episode_to_note_id)
        ms_store = MicrosoftGraphRagStore(settings)
        if settings.ask.graph_provider.strip().lower() in {"ms_graphrag", "microsoft_graphrag", "graphrag"}:
            ms_store.clear_all_data()
            ms_store.ingest_notes(all_notes, trace_id="multihoprag-msgraphrag-ingest")
            ms_store.build_index()
        runtime = AgentRuntime(settings, store, graph_store, ms_graphrag_store=ms_store)

        rankings: list[tuple[str, list[str]]] = []
        for query in queries:
            result = runtime.execute_ask(
                query.query_text,
                user_id=eval_user_id,
                session_id=f"multihoprag_{query.query_id}",
            )
            collapsed: list[str] = []
            for match in result.matches:
                pid = match.id.split("_sec_")[0]
                if pid not in collapsed:
                    collapsed.append(pid)
            if (
                settings.ask.graph_provider.strip().lower() in {"ms_graphrag", "microsoft_graphrag", "graphrag"}
                and not collapsed
            ):
                projection_text = " ".join(
                    part for part in [result.answer, *[item.fact or item.snippet for item in result.evidence]]
                    if part
                )
                projected = store.find_similar_notes(eval_user_id, projection_text, limit=limit)
                for note in projected:
                    pid = note.id.split("_sec_")[0]
                    if pid not in collapsed:
                        collapsed.append(pid)
            rankings.append((query.query_id, collapsed[:limit]))
            _record_eval_snapshot(
                context,
                self.name,
                {
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "question_type": query.question_type,
                    "expected_note_ids": sorted(expected_note_ids(query)),
                    "ranked_ids": collapsed[:limit],
                    "citation_note_ids": [c.note_id for c in result.citations[:limit]],
                    "graph_provider": settings.ask.graph_provider,
                    "projection": "answer_to_local_notes" if settings.ask.graph_provider.strip().lower() in {"ms_graphrag", "microsoft_graphrag", "graphrag"} else "",
                },
            )
        return rankings


def list_strategy_names() -> list[str]:
    real_graph_names = [f"graphiti_{name}" for name in sorted(STRATEGIES)]
    return [
        "keyword",
        "citation_reranker",
        "graphrag",
        "current_runtime_ask",
        *real_graph_names,
    ]


def get_strategy(name: str) -> BenchmarkStrategy:
    normalized = name.strip().lower()
    if normalized == "keyword":
        return KeywordSearchStrategy()
    if normalized == "citation_reranker":
        return CitationRerankStrategy()
    if normalized == "graphrag":
        return GraphRagStrategy()
    if normalized == "current_runtime_ask":
        return RuntimeAskStrategy()
    if normalized.startswith("graphiti_"):
        graph_strategy_name = normalized.removeprefix("graphiti_")
        if graph_strategy_name in STRATEGIES:
            return GraphitiRetrievalStrategy(graph_strategy_name)

    available = ", ".join(list_strategy_names())
    raise ValueError(f"Unknown MultiHopRAG strategy '{name}'. Available: {available}")


def run_multihoprag(
    *,
    strategy_names: list[str],
    num_queries: int | None = None,
    seed: int = 42,
    corpus_mode: CorpusMode = "relevant",
    limit: int = 10,
    note_mode: CorpusNoteMode = "parent_chunks",
    settings: Settings | None = None,
    graphiti_user_id: str = "multihoprag_eval_graphiti",
    reset_graphiti: bool = True,
    graphiti_manifest_path: Path | None = Path(
        "evals/multihoprag/results/multihoprag_manifest.json"
    ),
    graphiti_continue_on_ingest_error: bool = False,
) -> list[BenchmarkRunResult]:
    queries, docs = load_benchmark(
        num_queries=num_queries, seed=seed, corpus_mode=corpus_mode
    )
    relevance = _relevance(queries)
    query_types = _query_types(queries)
    eval_snapshots: dict[str, list[dict]] = {}
    context = BenchmarkContext(
        settings=settings or Settings.from_env(),
        graphiti_user_id=graphiti_user_id,
        reset_graphiti=reset_graphiti,
        graphiti_manifest_path=graphiti_manifest_path,
        note_mode=note_mode,
        graphiti_continue_on_ingest_error=graphiti_continue_on_ingest_error,
        eval_snapshots=eval_snapshots,
    )
    results: list[BenchmarkRunResult] = []
    for strategy_name in strategy_names:
        strategy = get_strategy(strategy_name)
        started_at = time.perf_counter()
        rankings = strategy.evaluate(queries, docs, limit=limit, context=context)
        elapsed = time.perf_counter() - started_at
        grouped = compute_grouped_report(rankings, relevance, query_types)
        results.append(
            BenchmarkRunResult(
                strategy=strategy.name,
                description=strategy.description,
                grouped=grouped,
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
        default="keyword,graphrag",
        help=f"Comma-separated strategies. Available: {', '.join(list_strategy_names())}",
    )
    parser.add_argument("--num-queries", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--corpus-mode", choices=("relevant", "full"), default="relevant")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--note-mode",
        choices=("parent_only", "parent_chunks", "section_only"),
        default="parent_chunks",
        help="How to convert MultiHopRAG articles into notes/episodes.",
    )
    parser.add_argument("--graphiti-user-id", default="multihoprag_eval_graphiti")
    parser.add_argument("--reuse-graphiti", action="store_true")
    parser.add_argument(
        "--graphiti-manifest",
        type=Path,
        default=Path("evals/multihoprag/results/multihoprag_manifest.json"),
    )
    parser.add_argument("--graphiti-continue-on-ingest-error", action="store_true")
    parser.add_argument("--graph-search-limit", type=int, default=None)
    parser.add_argument("--graph-search-citation-limit", type=int, default=None)
    parser.add_argument("--ask-graph-provider", choices=("graphiti", "structural", "hybrid", "ms_graphrag"), default=None)
    parser.add_argument("--ask-reranker", choices=("heuristic", "llm"), default=None)
    parser.add_argument("--ask-candidate-enricher", choices=("parent_child", "none"), default=None)
    parser.add_argument(
        "--ask-graph-note-evidence-mode",
        choices=("none", "all", "cited_overlap"),
        default=None,
    )
    parser.add_argument("--ask-context-max-items", type=int, default=None)
    parser.add_argument("--ask-context-char-budget", type=int, default=None)
    parser.add_argument("--ask-llm-rerank-top-n", type=int, default=None)
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
        settings = settings.model_copy(update={"ask": settings.ask.model_copy(update=ask_updates)})
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
            update={"firecrawl": settings.firecrawl.model_copy(update={"api_key": None})}
        )
    return settings


def main() -> None:
    args = _parse_args()
    strategy_names = [name.strip() for name in args.strategies.split(",") if name.strip()]
    settings = _settings_from_args(args)
    results = run_multihoprag(
        strategy_names=strategy_names,
        num_queries=args.num_queries,
        seed=args.seed,
        corpus_mode=args.corpus_mode,
        limit=args.limit,
        note_mode=args.note_mode,
        settings=settings,
        graphiti_user_id=args.graphiti_user_id,
        reset_graphiti=not args.reuse_graphiti,
        graphiti_manifest_path=args.graphiti_manifest,
        graphiti_continue_on_ingest_error=args.graphiti_continue_on_ingest_error,
    )

    payload = [result.as_dict() for result in results]
    for result in results:
        print(f"\n[{result.strategy}] {result.elapsed_seconds:.2f}s")
        print(format_grouped_report(result.grouped))

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
