"""Entry orchestration graph assembly."""

from __future__ import annotations

import logging

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg import connect
from psycopg.rows import dict_row

from ..core.config import Settings
from ..storage.postgres_common import normalize_postgres_url
from .orchestration_models import AgentGraphState
from .orchestration_nodes import (
    OrchestrationDeps,
    _after_confirm_step as _after_confirm_step,
    _after_step_execution as _after_step_execution,
    _after_step_failure as _after_step_failure,
    _after_step_success as _after_step_success,
    _after_validate_projected_steps as _after_validate_projected_steps,
    _build_react_context as _build_react_context,
    _dispatch_step as _dispatch_step,
    _format_react_tools as _format_react_tools,
    _is_react_tool_blocked as _is_react_tool_blocked,
    _node_capture_branch as _node_capture_branch,
    _after_interrupt_clarify as _after_interrupt_clarify,
    _after_prepare_clarify as _after_prepare_clarify,
    _node_interrupt_clarify as _node_interrupt_clarify,
    _node_prepare_clarify as _node_prepare_clarify,
    _node_confirm_step as _node_confirm_step,
    _node_direct_answer_branch as _node_direct_answer_branch,
    _node_execute_step as _node_execute_step,
    _node_consume_step_tool_result as _node_consume_step_tool_result,
    _node_finalize_entry_result as _node_finalize_entry_result,
    _node_finalize_step_execution as _node_finalize_step_execution,
    _node_handle_step_failure as _node_handle_step_failure,
    _node_handle_step_success as _node_handle_step_success,
    _node_normalize_entry as _node_normalize_entry,
    _node_project_workflow_steps as _node_project_workflow_steps,
    _node_prepare_step_execution as _node_prepare_step_execution,
    _node_react_finalize as _node_react_finalize,
    _node_react_init as _node_react_init,
    _node_react_iterate as _node_react_iterate,
    _node_consume_react_tool_result as _node_consume_react_tool_result,
    _node_route_intent as _node_route_intent,
    _node_select_next_step as _node_select_next_step,
    _node_summarize_branch as _node_summarize_branch,
    _node_validate_projected_steps as _node_validate_projected_steps,
    _react_llm_respond as _react_llm_respond,
    _resolve_allowed_tools_for_step as _resolve_allowed_tools_for_step,
    _should_continue_react as _should_continue_react,
    _should_execute_step as _should_execute_step,
    _summarize_react_tool_result as _summarize_react_tool_result,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def _route_by_intent(state: AgentGraphState) -> str:
    """Route the completed EntryGraph output to a parent workflow branch.

    Clarification is resolved inside EntryGraph. Cancellation or empty
    clarification completes there and is finalized directly by the parent.
    """
    if state.answer_completed:
        return "finalize_entry_result"
    if state.router_decision and state.router_decision.requires_clarification:
        return "finalize_entry_result"
    if state.router_decision and state.router_decision.requires_step_projection:
        return "step_execution_graph"
    intent = state.router_decision.route if state.router_decision else "unknown"
    if intent in ("capture_text", "capture_link", "capture_file"):
        return "capture_branch"
    if intent == "summarize_thread":
        return "summarize_branch"
    if intent == "direct_answer":
        return "direct_answer_branch"
    return "direct_answer_branch"


def _after_entry_route(state: AgentGraphState) -> str:
    """Keep clarification/resume entirely inside EntryGraph."""
    if state.router_decision and state.router_decision.requires_clarification:
        return "prepare_clarify_entry"
    return "return_to_parent"


def _after_step_execution_graph(state: AgentGraphState) -> str:
    """A rejected step projection returns to the parent for a user-visible answer."""
    if state.router_decision and not state.router_decision.requires_step_projection and not state.answer_completed:
        return "direct_answer_branch"
    return "finalize_entry_result"

def _after_react_graph(state: AgentGraphState) -> str:
    """Feed terminal ReactGraph outcomes through normal step handling."""
    if state.react.status == "completed":
        return "handle_success"
    return "handle_failure"


def build_entry_graph(deps: OrchestrationDeps):
    """Build entry classification and clarification as an isolated subgraph."""
    builder = StateGraph(AgentGraphState)
    builder.add_node("normalize_entry", _node_normalize_entry)
    builder.add_node(
        "route_intent",
        lambda state: _node_route_intent(state, deps=deps),
    )
    builder.add_node("prepare_clarify_entry", _node_prepare_clarify)
    builder.add_node("interrupt_clarify_entry", _node_interrupt_clarify)

    builder.add_edge(START, "normalize_entry")
    builder.add_edge("normalize_entry", "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        _after_entry_route,
        {
            "prepare_clarify_entry": "prepare_clarify_entry",
            "return_to_parent": END,
        },
    )
    builder.add_conditional_edges(
        "prepare_clarify_entry",
        _after_prepare_clarify,
        {
            "route_intent": "route_intent",
            "interrupt_clarify_entry": "interrupt_clarify_entry",
        },
    )
    builder.add_conditional_edges(
        "interrupt_clarify_entry",
        _after_interrupt_clarify,
        {
            "route_intent": "route_intent",
            "finalize_entry_result": END,
        },
    )
    return builder.compile()


def build_react_graph(deps: OrchestrationDeps):
    """Build the bounded ReAct loop with its own tool execution boundary."""
    builder = StateGraph(AgentGraphState)
    builder.add_node("react_init", lambda state: _node_react_init(state, deps=deps))
    builder.add_node("react_iterate", lambda state: _node_react_iterate(state, deps=deps))
    builder.add_node(
        "react_tool_node",
        deps.tool_executor.graph_node(),
    )
    builder.add_node(
        "consume_react_tool_result",
        lambda state: _node_consume_react_tool_result(state, deps=deps),
    )
    builder.add_node("react_finalize", _node_react_finalize)

    builder.add_edge(START, "react_init")
    builder.add_edge("react_init", "react_iterate")
    builder.add_conditional_edges(
        "react_iterate",
        _should_continue_react,
        {
            "iterate": "react_iterate",
            "tool_node": "react_tool_node",
            "finalize": "react_finalize",
        },
    )
    builder.add_edge("react_tool_node", "consume_react_tool_result")
    builder.add_conditional_edges(
        "consume_react_tool_result",
        _should_continue_react,
        {
            "iterate": "react_iterate",
            "tool_node": "react_tool_node",
            "finalize": "react_finalize",
        },
    )
    builder.add_edge("react_finalize", END)
    return builder.compile()


def build_step_execution_graph(deps: OrchestrationDeps):
    """Build step projection validation, deterministic execution, HITL, and ReAct dispatch."""
    builder = StateGraph(AgentGraphState)
    builder.add_node("project_workflow_steps", lambda state: _node_project_workflow_steps(state, deps=deps))
    builder.add_node("validate_projected_steps", lambda state: _node_validate_projected_steps(state, deps=deps))
    builder.add_node("prepare_step_execution", _node_prepare_step_execution)
    builder.add_node("select_next_step", _node_select_next_step)
    builder.add_node("execute_step", lambda state: _node_execute_step(state, deps=deps))
    builder.add_node("handle_step_success", lambda state: _node_handle_step_success(state, deps=deps))
    builder.add_node("handle_step_failure", lambda state: _node_handle_step_failure(state, deps=deps))
    builder.add_node("confirm_step", lambda state: _node_confirm_step(state, deps=deps))
    builder.add_node(
        "step_tool_node",
        deps.tool_executor.graph_node(),
    )
    builder.add_node(
        "consume_step_tool_result",
        lambda state: _node_consume_step_tool_result(state, deps=deps),
    )
    builder.add_node("react_graph", build_react_graph(deps))
    builder.add_node("finalize_step_execution", _node_finalize_step_execution)

    builder.add_edge(START, "project_workflow_steps")
    builder.add_edge("project_workflow_steps", "validate_projected_steps")
    builder.add_conditional_edges(
        "validate_projected_steps",
        _after_validate_projected_steps,
        {
            "prepare_step_execution": "prepare_step_execution",
            "direct_answer_branch": END,
        },
    )
    builder.add_edge("prepare_step_execution", "select_next_step")
    builder.add_conditional_edges(
        "select_next_step",
        _should_execute_step,
        {
            "execute_step": "execute_step",
            "finalize_steps": "finalize_step_execution",
        },
    )
    for node_name in ("execute_step", "consume_step_tool_result"):
        builder.add_conditional_edges(
            node_name,
            _after_step_execution,
            {
                "confirm_step": "confirm_step",
                "react_step": "react_graph",
                "tool_node": "step_tool_node",
                "handle_success": "handle_step_success",
                "handle_failure": "handle_step_failure",
            },
        )
    builder.add_edge("step_tool_node", "consume_step_tool_result")
    builder.add_conditional_edges(
        "react_graph",
        _after_react_graph,
        {
            "handle_success": "handle_step_success",
            "handle_failure": "handle_step_failure",
        },
    )
    builder.add_conditional_edges(
        "handle_step_success",
        _after_step_success,
        {"continue_loop": "select_next_step"},
    )
    builder.add_conditional_edges(
        "handle_step_failure",
        _after_step_failure,
        {
            "continue_loop": "select_next_step",
            "finalize_steps": "finalize_step_execution",
        },
    )
    builder.add_conditional_edges(
        "confirm_step",
        _after_confirm_step,
        {
            "tool_node": "step_tool_node",
            "handle_success": "handle_step_success",
            "handle_failure": "handle_step_failure",
        },
    )
    builder.add_edge("finalize_step_execution", END)
    return builder.compile()


def build_entry_orchestration_graph(deps: OrchestrationDeps, checkpointer=None):
    """Build the small parent graph that composes the three workflow layers."""
    if checkpointer is None:
        raise ValueError("A persistent Postgres checkpointer is required.")

    builder = StateGraph(AgentGraphState)

    builder.add_node("entry_graph", build_entry_graph(deps))
    builder.add_node(
        "capture_branch",
        lambda state: _node_capture_branch(state, deps=deps),
    )
    builder.add_node(
        "summarize_branch",
        lambda state: _node_summarize_branch(state, deps=deps),
    )
    builder.add_node(
        "direct_answer_branch",
        lambda state: _node_direct_answer_branch(state, deps=deps),
    )
    builder.add_node(
        "finalize_entry_result",
        lambda state: _node_finalize_entry_result(state, deps=deps),
    )
    builder.add_node("step_execution_graph", build_step_execution_graph(deps))

    # ---- Edges ----
    builder.add_edge(START, "entry_graph")
    builder.add_conditional_edges(
        "entry_graph",
        _route_by_intent,
        {
            "finalize_entry_result": "finalize_entry_result",
            "step_execution_graph": "step_execution_graph",
            "capture_branch": "capture_branch",
            "summarize_branch": "summarize_branch",
            "direct_answer_branch": "direct_answer_branch",
        },
    )
    builder.add_edge("capture_branch", "finalize_entry_result")
    builder.add_edge("summarize_branch", "finalize_entry_result")
    builder.add_edge("direct_answer_branch", "finalize_entry_result")
    builder.add_conditional_edges(
        "step_execution_graph",
        _after_step_execution_graph,
        {
            "direct_answer_branch": "direct_answer_branch",
            "finalize_entry_result": "finalize_entry_result",
        },
    )
    builder.add_edge("finalize_entry_result", END)

    return builder.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Helpers for the runtime integration
# ---------------------------------------------------------------------------


def _build_checkpointer(settings: Settings):
    connection = connect(
        normalize_postgres_url(settings.postgres_url),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    checkpointer = PostgresSaver(connection)
    try:
        checkpointer.setup()
    except Exception:
        connection.close()
        raise
    logger.info("Using PostgresSaver for LangGraph checkpoints")
    return checkpointer
