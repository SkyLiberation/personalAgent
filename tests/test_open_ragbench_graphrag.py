from __future__ import annotations

from personal_agent.core.config import Settings

from evals.open_ragbench.loader import RAGBenchDoc, RAGBenchQuery
from evals.open_ragbench.runner import BenchmarkContext, GraphRagStrategy, get_strategy, list_strategy_names


def _context() -> BenchmarkContext:
    return BenchmarkContext(
        settings=Settings(),
        graphiti_user_id="test",
        reset_graphiti=True,
        graphiti_manifest_path=None,
        graphiti_note_mode="parent_sections",
        graphiti_continue_on_ingest_error=False,
    )


def test_graphrag_is_registered():
    assert "graphrag" in list_strategy_names()
    assert isinstance(get_strategy("graphrag"), GraphRagStrategy)


def test_graphrag_ranks_matching_section_or_parent():
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

    rankings, relevance = GraphRagStrategy().evaluate(queries, docs, limit=3, context=_context())

    assert rankings[0][0] == "q1"
    assert rankings[0][1][0] in relevance["q1"]
