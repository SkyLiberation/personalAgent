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

from personal_agent.core.config import Settings
from personal_agent.core.models import KnowledgeNote
from personal_agent.graphiti.store import GraphAskResult, GraphitiStore
from personal_agent.graphiti.search_strategies import STRATEGIES

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


@dataclass(frozen=True)
class BenchmarkRunResult:
    strategy: str
    description: str
    report: RetrievalReport
    elapsed_seconds: float
    num_docs: int
    num_queries: int
    corpus_mode: str

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "description": self.description,
            "elapsed_seconds": self.elapsed_seconds,
            "num_docs": self.num_docs,
            "num_queries": self.num_queries,
            "corpus_mode": self.corpus_mode,
            "metrics": self.report.as_dict(),
        }


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
            from personal_agent.graphiti.reranker import rank_graph_citation_hits

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
class GraphRagStrategy:
    name: str = "graphrag"
    description: str = (
        "Offline GraphRAG-style baseline over a document-section graph with "
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
        graph = _build_graphrag_index(docs)

        rankings: list[tuple[str, list[str]]] = []
        relevance: dict[str, set[str]] = {}
        for query in queries:
            rankings.append((query.query_id, _rank_graphrag_notes(query.query_text, graph, limit=limit)))
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
        settings = context.settings.model_copy(update={"graph_search_strategy": self.graph_strategy_name})
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
    """Ingest the benchmark corpus into Graphiti once per runner process."""
    cache_key = f"{user_id}:{note_mode}:{len(notes)}:{','.join(note.id for note in notes[:5])}"
    if cache_key in _GRAPHITI_INGEST_CACHE:
        return _GRAPHITI_INGEST_CACHE[cache_key]

    expected_note_ids = {note.id for note in notes}
    if not reset:
        if manifest_path is None or not manifest_path.exists():
            raise RuntimeError("--reuse-graphiti requires a matching Graphiti manifest file.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_matches = (
            manifest.get("user_id") == user_id
            and manifest.get("graphiti_group_prefix") == graph_store.settings.graphiti_group_prefix
            and manifest.get("note_mode", "parent_sections") == note_mode
            and manifest.get("note_count") == len(notes)
            and set(manifest.get("note_ids", [])) == expected_note_ids
        )
        if not manifest_matches:
            raise RuntimeError(
                "--reuse-graphiti manifest does not match the selected corpus/user. "
                "Run without --reuse-graphiti to rebuild the eval graph."
            )
        episode_to_note_id = {
            str(episode_uuid): str(note_id)
            for episode_uuid, note_id in manifest.get("episode_to_note_id", {}).items()
        }
        if not episode_to_note_id:
            raise RuntimeError("--reuse-graphiti manifest has no episode mapping.")
        _GRAPHITI_INGEST_CACHE[cache_key] = episode_to_note_id
        return episode_to_note_id

    if reset:
        graph_store.clear_user_group(user_id)

    episode_to_note_id: dict[str, str] = {}
    ingest_errors: list[dict[str, str]] = []
    for index, original_note in enumerate(notes, start=1):
        note = original_note.model_copy(update={"user_id": user_id})
        result = graph_store.ingest_note(note, trace_id=f"ragbench-ingest-{index}")
        if not result.enabled or not result.episode_uuid:
            if continue_on_ingest_error:
                ingest_errors.append({
                    "note_id": note.id,
                    "error": result.error or "missing episode_uuid",
                })
                continue
            raise RuntimeError(
                f"Graphiti ingest failed for note {note.id}: {result.error or 'missing episode_uuid'}"
            )
        episode_to_note_id[result.episode_uuid] = original_note.id

    if not episode_to_note_id:
        detail = ingest_errors[:3]
        raise RuntimeError(f"Graphiti ingest produced no episodes. Sample errors: {detail}")

    _GRAPHITI_INGEST_CACHE[cache_key] = episode_to_note_id
    if manifest_path is not None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "user_id": user_id,
                    "graphiti_group_prefix": graph_store.settings.graphiti_group_prefix,
                    "note_mode": note_mode,
                    "note_count": len(notes),
                    "note_ids": sorted(expected_note_ids),
                    "episode_to_note_id": episode_to_note_id,
                    "ingest_errors": ingest_errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
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
class _GraphRagSection:
    note_id: str
    parent_id: str
    doc_id: str
    index: int
    tokens: set[str]


@dataclass(frozen=True)
class _GraphRagDoc:
    note_id: str
    doc_id: str
    tokens: set[str]
    sections: list[_GraphRagSection]


@dataclass(frozen=True)
class _GraphRagIndex:
    docs: list[_GraphRagDoc]
    sections: list[_GraphRagSection]
    document_frequency: dict[str, int]
    num_sections: int


def _build_graphrag_index(docs: dict[str, RAGBenchDoc]) -> _GraphRagIndex:
    graph_docs: list[_GraphRagDoc] = []
    sections: list[_GraphRagSection] = []
    document_frequency: dict[str, int] = {}

    for doc_id, doc in docs.items():
        parent_id = f"ragbench_{doc_id}"
        doc_tokens = set(_graphrag_tokens(f"{doc.title}\n{doc.abstract}"))
        doc_sections: list[_GraphRagSection] = []
        for index, section_text in enumerate(doc.sections):
            section = _GraphRagSection(
                note_id=f"{parent_id}_sec_{index}",
                parent_id=parent_id,
                doc_id=doc_id,
                index=index,
                tokens=set(_graphrag_tokens(section_text)),
            )
            doc_sections.append(section)
            sections.append(section)
            for token in section.tokens:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        graph_docs.append(
            _GraphRagDoc(
                note_id=parent_id,
                doc_id=doc_id,
                tokens=doc_tokens,
                sections=doc_sections,
            )
        )

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
    scored_items.sort(key=lambda item: (item[0], _graphrag_tiebreak(item[1], sections_by_id)), reverse=True)

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


def _token_score(query_tokens: list[str], candidate_tokens: set[str], graph: _GraphRagIndex) -> float:
    score = 0.0
    for token in query_tokens:
        if token not in candidate_tokens:
            continue
        document_frequency = graph.document_frequency.get(token, 0)
        inverse_document_frequency = math.log((graph.num_sections + 1) / (document_frequency + 1)) + 1.0
        score += inverse_document_frequency * (1.5 if len(token) >= 6 else 1.0)
    return score


def _graphrag_tiebreak(note_id: str, sections_by_id: dict[str, _GraphRagSection]) -> float:
    section = sections_by_id.get(note_id)
    if section is None:
        return 0.0
    return -float(section.index)


def _graphrag_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+", text.lower()):
        if len(raw) < 2 or raw in _GRAPHRAG_STOPWORDS:
            continue
        tokens.append(raw)
    return tokens


_GRAPHRAG_STOPWORDS = {
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


def list_strategy_names() -> list[str]:
    real_graph_names = [f"graphiti_{name}" for name in sorted(STRATEGIES)]
    return ["keyword", "citation_reranker", "graphrag", *real_graph_names]


def get_strategy(name: str) -> BenchmarkStrategy:
    normalized = name.strip().lower()
    if normalized == "keyword":
        return KeywordSearchStrategy()
    if normalized == "citation_reranker":
        return CitationRerankStrategy()
    if normalized == "graphrag":
        return GraphRagStrategy()
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
    context = BenchmarkContext(
        settings=settings or Settings.from_env(),
        graphiti_user_id=graphiti_user_id,
        reset_graphiti=reset_graphiti,
        graphiti_manifest_path=graphiti_manifest_path,
        graphiti_note_mode=graphiti_note_mode,
        graphiti_continue_on_ingest_error=graphiti_continue_on_ingest_error,
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
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    strategy_names = [name.strip() for name in args.strategies.split(",") if name.strip()]
    results = run_open_ragbench(
        strategy_names=strategy_names,
        num_queries=args.num_queries,
        seed=args.seed,
        corpus_mode=args.corpus_mode,
        limit=args.limit,
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
