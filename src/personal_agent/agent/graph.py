from __future__ import annotations

from collections.abc import Callable

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


def build_entry_graph(
    route_node: Callable[[AgentState], AgentState],
    capture_branch_node: Callable[[AgentState], AgentState],
    ask_branch_node: Callable[[AgentState], AgentState],
    summarize_branch_node: Callable[..., AgentState],
    unknown_branch_node: Callable[[AgentState], AgentState],
    direct_answer_branch_node: Callable[..., AgentState] | None = None,
):
    graph = StateGraph(AgentState)
    graph.add_node("route", route_node)
    graph.add_node("capture_branch", capture_branch_node)
    graph.add_node("ask_branch", ask_branch_node)
    graph.add_node("summarize_branch", summarize_branch_node)
    graph.add_node("unknown_branch", unknown_branch_node)
    if direct_answer_branch_node is not None:
        graph.add_node("direct_answer_branch", direct_answer_branch_node)

    graph.add_edge(START, "route")
    direct_answer_target = "direct_answer_branch" if direct_answer_branch_node is not None else "unknown_branch"
    graph.add_conditional_edges(
        "route",
        lambda state: state.intent,
        {
            "capture_text": "capture_branch",
            "capture_link": "capture_branch",
            "capture_file": "capture_branch",
            "ask": "ask_branch",
            "summarize_thread": "summarize_branch",
            "delete_knowledge": "unknown_branch",
            "solidify_conversation": "unknown_branch",
            "direct_answer": direct_answer_target,
            "unknown": "unknown_branch",
        },
    )
    graph.add_edge("capture_branch", END)
    graph.add_edge("ask_branch", END)
    graph.add_edge("summarize_branch", END)
    graph.add_edge("unknown_branch", END)
    if direct_answer_branch_node is not None:
        graph.add_edge("direct_answer_branch", END)
    return graph.compile()
