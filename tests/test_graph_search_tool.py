from __future__ import annotations

from types import SimpleNamespace

from personal_agent.governance import ToolExecutor
from personal_agent.kernel.graph_results import GraphRetrievalResult
from tests.test_tools import _scope
from personal_agent.tools.graph_search import build_graph_search_tool


class _GraphStore:
    def __init__(self):
        self.questions: list[str] = []

    def configured(self):
        return True

    def retrieve(self, question: str, user_id: str):
        self.questions.append(question)
        return SimpleNamespace(
            enabled=True,
            error="",
            entity_names=[],
            relation_facts=[],
            related_episode_uuids=[],
            node_refs=[],
            edge_refs=[],
            fact_refs=[],
            citation_hits=[],
        )


class _EmptyGraphStore(_GraphStore):
    def has_user_data(self, user_id: str):
        return False


class _RelationFactGraphStore(_GraphStore):
    def retrieve(self, question: str, user_id: str):
        self.questions.append(question)
        return GraphRetrievalResult(
            enabled=True,
            relation_facts=["Orion 已完成生产发布，所有租户默认启用。"],
        )


def test_graph_search_accepts_structured_context():
    graph = _GraphStore()
    executor = ToolExecutor()
    executor.register(build_graph_search_tool(graph))

    result = executor.invoke_direct(
        "graph_search",
        execution_scope=_scope("alice"),
        question="Agent Runtime SDK",
        user_id="alice",
        structured_context={
            "title": "OpenAI launches Agent Runtime SDK",
            "event_type": "product_release",
            "entities": ["OpenAI", "Agent Runtime SDK"],
            "source_domains": ["openai.com"],
            "summary": "OpenAI launches a runtime SDK.",
        },
    )

    assert result["ok"]
    assert "answer" not in result["data"]
    assert "event_type: product_release" in graph.questions[0]
    assert "entities: OpenAI, Agent Runtime SDK" in graph.questions[0]


def test_graph_search_skips_empty_user_graph():
    graph = _EmptyGraphStore()
    executor = ToolExecutor()
    executor.register(build_graph_search_tool(graph))

    result = executor.invoke_direct(
        "graph_search",
        execution_scope=_scope("alice"),
        question="Agent Runtime SDK",
        user_id="alice",
    )

    assert result["ok"]
    assert result["data"]["skipped_reason"] == "no_user_graph_data"
    assert graph.questions == []


def test_graph_search_exposes_relation_facts_as_canonical_evidence():
    graph = _RelationFactGraphStore()
    executor = ToolExecutor()
    executor.register(build_graph_search_tool(graph))

    result = executor.invoke_direct(
        "graph_search",
        execution_scope=_scope("alice"),
        question="Orion 的发布状态是什么？",
        user_id="alice",
    )

    assert result["ok"]
    assert result["data"]["relation_facts"] == [
        "Orion 已完成生产发布，所有租户默认启用。"
    ]
    assert [item["fact"] for item in result["evidence"]] == [
        "Orion 已完成生产发布，所有租户默认启用。"
    ]
