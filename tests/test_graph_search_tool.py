from __future__ import annotations

from types import SimpleNamespace

from personal_agent.governance import ToolExecutor
from personal_agent.tools.graph_search import build_graph_search_tool


class _GraphStore:
    def __init__(self):
        self.questions: list[str] = []

    def configured(self):
        return True

    def ask(self, question: str, user_id: str):
        self.questions.append(question)
        return SimpleNamespace(
            enabled=True,
            error="",
            answer="ok",
            entity_names=[],
            relation_facts=[],
            related_episode_uuids=[],
            node_refs=[],
            edge_refs=[],
            fact_refs=[],
            citation_hits=[],
        )


def test_graph_search_accepts_structured_context():
    graph = _GraphStore()
    executor = ToolExecutor()
    executor.register(build_graph_search_tool(graph))

    result = executor.invoke_direct(
        "graph_search",
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
    assert "event_type: product_release" in graph.questions[0]
    assert "entities: OpenAI, Agent Runtime SDK" in graph.questions[0]
