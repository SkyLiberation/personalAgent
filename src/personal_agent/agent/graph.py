from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..core.models import AgentState
from ..storage.memory_store import LocalMemoryStore
from .nodes import answer_node, capture_node, enrich_node, link_node, schedule_review_node


def build_capture_graph(store: LocalMemoryStore):
    graph = StateGraph(AgentState)
    graph.add_node("capture", lambda state: capture_node(state, store))
    graph.add_node("enrich", lambda state: enrich_node(state, store))
    graph.add_node("link", lambda state: link_node(state, store))
    graph.add_node("schedule_review", lambda state: schedule_review_node(state, store))

    graph.add_edge(START, "capture")
    graph.add_edge("capture", "enrich")
    graph.add_edge("enrich", "link")
    graph.add_edge("link", "schedule_review")
    graph.add_edge("schedule_review", END)
    return graph.compile()


def build_ask_graph(store: LocalMemoryStore):
    graph = StateGraph(AgentState)
    graph.add_node("answer", lambda state: answer_node(state, store))
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    return graph.compile()
