from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..core.models import AgentState
from ..extract import PreExtractService
from ..storage.postgres_memory_store import PostgresMemoryStore
from .nodes import (
    answer_node,
    capture_node,
    enrich_node,
    link_node,
    preextract_node,
    schedule_review_node,
)


def build_capture_graph(
    store: PostgresMemoryStore,
    preextract_service: PreExtractService,
):
    """Capture pipeline: capture -> preextract -> enrich -> link -> schedule_review.

    LangExtract pre-extraction is a mandatory step. Callers must pass a
    ``PreExtractService``; short docs / runtime errors are handled inside the
    node by recording status on the note rather than skipping the node.
    """
    graph = StateGraph(AgentState)
    graph.add_node("capture", lambda state: capture_node(state, store))
    graph.add_node(
        "preextract",
        lambda state: preextract_node(state, store, preextract_service),
    )
    graph.add_node("enrich", lambda state: enrich_node(state, store))
    graph.add_node("link", lambda state: link_node(state, store))
    graph.add_node("schedule_review", lambda state: schedule_review_node(state, store))

    graph.add_edge(START, "capture")
    graph.add_edge("capture", "preextract")
    graph.add_edge("preextract", "enrich")
    graph.add_edge("enrich", "link")
    graph.add_edge("link", "schedule_review")
    graph.add_edge("schedule_review", END)
    return graph.compile()


def build_ask_graph(store: PostgresMemoryStore):
    graph = StateGraph(AgentState)
    graph.add_node("answer", lambda state: answer_node(state, store))
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    return graph.compile()
