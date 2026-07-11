"""LangGraph assembly for the goal-owned executive runtime."""

from __future__ import annotations

import logging

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg import connect
from psycopg.rows import dict_row

from personal_agent.infra.storage.postgres_common import normalize_postgres_url
from personal_agent.kernel.config import Settings
from personal_agent.orchestration.orchestration_contexts import GraphContexts
from personal_agent.orchestration.orchestration_models import AgentGraphState
from personal_agent.orchestration.orchestration_nodes._entry import (
    _after_interrupt_clarify,
    _after_prepare_clarify,
    _node_finalize_entry_result,
    _node_interrupt_clarify,
    _node_normalize_entry,
    _node_prepare_clarify,
    _node_route_intent,
)
from personal_agent.orchestration.orchestration_nodes._executive import (
    _after_apply_decision,
    _after_completion,
    _after_recovery,
    _node_apply_decision,
    _node_decide,
    _node_interpret_goal,
    _node_observe_action,
    _node_project_control_state,
    _node_recover_action,
    _node_validate_decision,
    _node_verify_completion,
    _node_verify_goal_progress,
)
from personal_agent.orchestration.orchestration_nodes._react import (
    _node_consume_react_tool_result,
    _node_react_finalize,
    _node_react_init,
    _node_react_iterate,
    _should_continue_react,
)
from personal_agent.orchestration.orchestration_nodes._steps import (
    _after_confirm_step,
    _after_step_execution,
    _node_confirm_step,
    _node_consume_step_tool_result,
    _node_execute_step,
    _node_handle_step_success,
    _node_prepare_step_execution,
    _node_select_next_step,
    _should_execute_step,
)

logger = logging.getLogger(__name__)


def _after_entry_route(state: AgentGraphState) -> str:
    if state.router_decision and state.router_decision.requires_clarification:
        return "prepare_clarify_entry"
    return "return_to_parent"


def _after_entry_graph(state: AgentGraphState) -> str:
    return "finalize" if state.answer_completed else "executive"


def _after_react_graph(state: AgentGraphState) -> str:
    return "handle_success" if state.react.status == "completed" else "recover"


def build_entry_graph(contexts: GraphContexts):
    """Understand the user goal and resolve entry-level clarification only."""
    builder = StateGraph(AgentGraphState)
    builder.add_node("normalize_entry", _node_normalize_entry)
    builder.add_node("route_intent", lambda state: _node_route_intent(state, deps=contexts.routing))
    builder.add_node("prepare_clarify_entry", _node_prepare_clarify)
    builder.add_node("interrupt_clarify_entry", _node_interrupt_clarify)
    builder.add_edge(START, "normalize_entry")
    builder.add_edge("normalize_entry", "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        _after_entry_route,
        {"prepare_clarify_entry": "prepare_clarify_entry", "return_to_parent": END},
    )
    builder.add_conditional_edges(
        "prepare_clarify_entry",
        _after_prepare_clarify,
        {"route_intent": "route_intent", "interrupt_clarify_entry": "interrupt_clarify_entry"},
    )
    builder.add_conditional_edges(
        "interrupt_clarify_entry",
        _after_interrupt_clarify,
        {"route_intent": "route_intent", "finalize_entry_result": END},
    )
    return builder.compile()


def build_react_graph(contexts: GraphContexts):
    """Bounded executor-local ReAct loop."""
    builder = StateGraph(AgentGraphState)
    builder.add_node("react_init", lambda state: _node_react_init(state, deps=contexts.react))
    builder.add_node("react_iterate", lambda state: _node_react_iterate(state, deps=contexts.react))
    builder.add_node("react_tool_node", contexts.react.tool_executor.graph_node())
    builder.add_node(
        "consume_react_tool_result",
        lambda state: _node_consume_react_tool_result(state, deps=contexts.react),
    )
    builder.add_node("react_finalize", _node_react_finalize)
    builder.add_edge(START, "react_init")
    builder.add_edge("react_init", "react_iterate")
    builder.add_conditional_edges(
        "react_iterate",
        _should_continue_react,
        {"iterate": "react_iterate", "tool_node": "react_tool_node", "finalize": "react_finalize"},
    )
    builder.add_edge("react_tool_node", "consume_react_tool_result")
    builder.add_conditional_edges(
        "consume_react_tool_result",
        _should_continue_react,
        {"iterate": "react_iterate", "tool_node": "react_tool_node", "finalize": "react_finalize"},
    )
    builder.add_edge("react_finalize", END)
    return builder.compile()


def build_action_execution_graph(contexts: GraphContexts):
    """Execute only the current bounded action or one deterministic protocol."""
    builder = StateGraph(AgentGraphState)
    builder.add_node("prepare_action", _node_prepare_step_execution)
    builder.add_node("select_action_step", _node_select_next_step)
    builder.add_node("execute_action_step", lambda state: _node_execute_step(state, deps=contexts.steps))
    builder.add_node("handle_action_success", lambda state: _node_handle_step_success(state, deps=contexts.steps))
    builder.add_node("recover_action", _node_recover_action)
    builder.add_node("confirm_action_step", lambda state: _node_confirm_step(state, deps=contexts.steps))
    builder.add_node("action_tool_node", contexts.steps.tool_executor.graph_node())
    builder.add_node(
        "consume_action_tool_result",
        lambda state: _node_consume_step_tool_result(state, deps=contexts.steps),
    )
    builder.add_node("react_action", build_react_graph(contexts))

    builder.add_edge(START, "prepare_action")
    builder.add_edge("prepare_action", "select_action_step")
    builder.add_conditional_edges(
        "select_action_step",
        _should_execute_step,
        {"execute_step": "execute_action_step", "finalize_steps": END},
    )
    for node_name in ("execute_action_step", "consume_action_tool_result"):
        builder.add_conditional_edges(
            node_name,
            _after_step_execution,
            {
                "confirm_step": "confirm_action_step",
                "react_step": "react_action",
                "tool_node": "action_tool_node",
                "handle_success": "handle_action_success",
                "handle_failure": "recover_action",
            },
        )
    builder.add_edge("action_tool_node", "consume_action_tool_result")
    builder.add_conditional_edges(
        "react_action",
        _after_react_graph,
        {"handle_success": "handle_action_success", "recover": "recover_action"},
    )
    builder.add_edge("handle_action_success", "select_action_step")
    builder.add_conditional_edges(
        "recover_action",
        _after_recovery,
        {"retry": "select_action_step", "action_done": END},
    )
    builder.add_conditional_edges(
        "confirm_action_step",
        _after_confirm_step,
        {
            "tool_node": "action_tool_node",
            "handle_success": "handle_action_success",
            "handle_failure": "recover_action",
        },
    )
    return builder.compile()


def build_executive_graph(contexts: GraphContexts):
    """Durable task-level decide-act-observe-verify loop."""
    deps = contexts.executive
    builder = StateGraph(AgentGraphState)
    builder.add_node("interpret_goal", lambda state: _node_interpret_goal(state, deps=deps))
    builder.add_node("project_control_state", lambda state: _node_project_control_state(state, deps=deps))
    builder.add_node("decide", lambda state: _node_decide(state, deps=deps))
    builder.add_node("validate_decision", lambda state: _node_validate_decision(state, deps=deps))
    builder.add_node("apply_decision", lambda state: _node_apply_decision(state, deps=deps))
    builder.add_node("action_execution", build_action_execution_graph(contexts))
    builder.add_node("observe_action", lambda state: _node_observe_action(state, deps=deps))
    builder.add_node("verify_goal_progress", lambda state: _node_verify_goal_progress(state, deps=deps))
    builder.add_node("verify_completion", lambda state: _node_verify_completion(state, deps=deps))

    builder.add_edge(START, "interpret_goal")
    builder.add_edge("interpret_goal", "project_control_state")
    builder.add_edge("project_control_state", "decide")
    builder.add_edge("decide", "validate_decision")
    builder.add_edge("validate_decision", "apply_decision")
    builder.add_conditional_edges(
        "apply_decision",
        _after_apply_decision,
        {
            "loop": "project_control_state",
            "action": "action_execution",
            "completion": "verify_completion",
            "stop": END,
        },
    )
    builder.add_edge("action_execution", "observe_action")
    builder.add_edge("observe_action", "verify_goal_progress")
    builder.add_edge("verify_goal_progress", "project_control_state")
    builder.add_conditional_edges(
        "verify_completion",
        _after_completion,
        {"complete": END, "loop": "project_control_state"},
    )
    return builder.compile()


def build_entry_orchestration_graph(contexts: GraphContexts, checkpointer=None):
    if checkpointer is None:
        raise ValueError("A persistent Postgres checkpointer is required.")
    builder = StateGraph(AgentGraphState)
    builder.add_node("entry_graph", build_entry_graph(contexts))
    builder.add_node("executive_graph", build_executive_graph(contexts))
    builder.add_node("finalize_entry_result", _node_finalize_entry_result)
    builder.add_edge(START, "entry_graph")
    builder.add_conditional_edges(
        "entry_graph",
        _after_entry_graph,
        {"executive": "executive_graph", "finalize": "finalize_entry_result"},
    )
    builder.add_edge("executive_graph", "finalize_entry_result")
    builder.add_edge("finalize_entry_result", END)
    return builder.compile(checkpointer=checkpointer)


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


__all__ = [
    "_build_checkpointer",
    "build_action_execution_graph",
    "build_entry_graph",
    "build_entry_orchestration_graph",
    "build_executive_graph",
    "build_react_graph",
]
