from __future__ import annotations

from personal_agent.kernel.config import Settings
from tests.note_factory import make_note
from personal_agent.kernel.query_understanding import QueryUnderstanding, RetrievalFilters, RetrievalPlan

from evals.open_ragbench.loader import RAGBenchDoc, RAGBenchQuery
from evals.open_ragbench.runner import (
    AskPipelineStrategy,
    BenchmarkContext,
    RuntimeAskStrategy,
    StructuralRetrieverStrategy,
    get_strategy,
    run_open_ragbench,
    list_strategy_names,
)


def _context() -> BenchmarkContext:
    return BenchmarkContext(
        settings=Settings(),
        graphiti_user_id="test",
        reset_graphiti=True,
        graphiti_manifest_path=None,
        graphiti_note_mode="parent_sections",
        graphiti_continue_on_ingest_error=False,
    )


def test_structural_is_registered():
    assert "structural" in list_strategy_names()
    assert isinstance(get_strategy("structural"), StructuralRetrieverStrategy)


def test_ask_pipeline_eval_variants_are_registered():
    names = list_strategy_names()

    assert "ask_pipeline" in names
    assert "ask_pipeline_no_rewrite" in names
    assert "ask_pipeline_local_only" in names
    assert "ask_pipeline_no_planner" in names
    assert "current_runtime_ask" in names
    assert isinstance(get_strategy("ask_pipeline"), AskPipelineStrategy)
    assert isinstance(get_strategy("ask_pipeline_no_rewrite"), AskPipelineStrategy)
    assert isinstance(get_strategy("ask_pipeline_local_only"), AskPipelineStrategy)
    assert isinstance(get_strategy("ask_pipeline_no_planner"), AskPipelineStrategy)
    assert isinstance(get_strategy("current_runtime_ask"), RuntimeAskStrategy)


def test_structural_ranks_matching_section_or_parent():
    docs = {
        "paper-a": RAGBenchDoc(
            doc_id="paper-a",
            title="Redis cache architecture",
            abstract="This paper studies cache design.",
            sections=[
                "Redis stores hot order data and reduces database pressure.",
                "Unrelated deployment notes.",
            ],
        ),
        "paper-b": RAGBenchDoc(
            doc_id="paper-b",
            title="Payment user interface",
            abstract="This paper studies visual design.",
            sections=["Buttons and colors are evaluated."],
        ),
    }
    queries = [
        RAGBenchQuery(
            query_id="q1",
            query_text="How does Redis reduce database pressure for orders?",
            query_type="abstractive",
            relevant_doc_id="paper-a",
            relevant_section_idx=0,
            answer="Redis stores hot order data.",
        )
    ]

    rankings, relevance = StructuralRetrieverStrategy().evaluate(queries, docs, limit=3, context=_context())

    assert rankings[0][0] == "q1"
    assert rankings[0][1][0] in relevance["q1"]


def test_ask_pipeline_ablation_reuses_planner_cache(monkeypatch):
    calls: list[str] = []

    docs = {
        "paper-a": RAGBenchDoc(
            doc_id="paper-a",
            title="Redis cache architecture",
            abstract="This paper studies cache design.",
            sections=["Redis stores hot order data and reduces database pressure."],
        )
    }
    queries = [
        RAGBenchQuery(
            query_id="q1",
            query_text="How does Redis reduce database pressure for orders?",
            query_type="abstractive",
            relevant_doc_id="paper-a",
            relevant_section_idx=0,
            answer="Redis stores hot order data.",
        )
    ]

    def fake_load_benchmark(*, num_queries, seed, corpus_mode):
        return queries, docs

    def fake_plan_retrieval(question, conversation_context, settings):
        calls.append(question)
        return (
            QueryUnderstanding(
                needs_personal_memory=True,
                query_rewrite="redis hot order cache",
                filters=RetrievalFilters(),
            ),
            RetrievalPlan(
                sources=["local"],
                parallel=False,
                query="redis hot order cache",
                sub_queries=[],
                filters=RetrievalFilters(),
            ),
        )

    class FakeStore:
        def find_similar_notes(self, user_id, query, limit=8, filters=None):
            return [
                make_note(
                    id="ragbench_paper-a_sec_0",
                    user_id=user_id,
                    title="Redis",
                    content="Redis stores hot order data.",
                    summary="Redis stores hot order data.",
                    parent_note_id="ragbench_paper-a",
                )
            ]

    def fake_new_eval_store(settings, docs, user_id="ragbench_eval"):
        return FakeStore(), []

    monkeypatch.setattr("evals.open_ragbench.runner.load_benchmark", fake_load_benchmark)
    monkeypatch.setattr("personal_agent.agent.query_planner.plan_retrieval", fake_plan_retrieval)
    monkeypatch.setattr("evals.open_ragbench.runner._new_eval_store", fake_new_eval_store)

    results = run_open_ragbench(
        strategy_names=["ask_pipeline_local_only", "ask_pipeline_no_rewrite"],
        num_queries=1,
        settings=Settings(postgres_url="postgresql://unused"),
        graphiti_manifest_path=None,
    )

    assert calls == ["How does Redis reduce database pressure for orders?"]
    assert results[0].diagnostics[0]["planner"]["cache_hit"] is False
    assert results[1].diagnostics[0]["planner"]["cache_hit"] is True
