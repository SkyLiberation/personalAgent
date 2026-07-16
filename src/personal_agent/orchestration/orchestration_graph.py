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
from personal_agent.orchestration.orchestration_models import RunCheckpoint
from personal_agent.orchestration.orchestration_nodes._entry import (
    _after_interrupt_clarify,
    _after_prepare_clarify,
    _node_finalize_entry_result,
    _node_interrupt_clarify,
    _node_normalize_entry,
    _node_prepare_clarify,
    _node_analyze_task,
)
from personal_agent.orchestration.orchestration_nodes._executive import (
    _after_action_resolution,
    _after_decision_admission,
    _after_apply_decision,
    _after_completion,
    _node_apply_decision,
    _node_admit_execution_route,
    _node_admit_decision,
    _node_decide,
    _node_compile_goal_graph,
    _node_create_or_revise_plan,
    _node_assess_coordination,
    _node_monitor_plan,
    _node_observe_action,
    _node_project_planning_facts,
    _node_project_control_state,
    _node_resolve_action,
    _node_handle_decision_denial,
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
    _after_invocation_batch,
    _node_confirm_step,
    _node_consume_step_tool_result,
    _node_execute_step,
    _node_handle_step_success,
    _node_prepare_invocation_batch,
    _node_select_next_step,
    _should_execute_step,
)

logger = logging.getLogger(__name__)


def _after_entry_route(state: RunCheckpoint) -> str:
    if state.task_analysis and state.task_analysis.requires_clarification:
        return "prepare_clarify_entry"
    return "return_to_parent"


def _after_entry_graph(state: RunCheckpoint) -> str:
    return "finalize" if state.answer_completed else "executive"


def _after_react_graph(state: RunCheckpoint) -> str:
    return "handle_success" if state.react.status == "completed" else "action_done"


def _after_observation(state: RunCheckpoint) -> str:
    return "retry" if state.control.disposition == "retry_invocation" else "verify"


def _after_goal_compile(state: RunCheckpoint) -> str:
    return "direct" if state.answer is not None else "planning"


def _after_coordination(state: RunCheckpoint) -> str:
    if state.coordination is not None and state.coordination.mode == "deliberative":
        return "plan"
    return "control"


def _after_plan_creation(state: RunCheckpoint) -> str:
    return "stop" if state.control.disposition == "terminate" else "control"


def _after_plan_monitor(state: RunCheckpoint) -> str:
    if state.coordination is None:
        return "planning"
    if state.control.disposition in {"patch_plan", "replace_plan"}:
        return "replan"
    if state.control.disposition in {"await_input", "terminate"}:
        return "stop"
    return "control"


def _after_goal_verification(state: RunCheckpoint) -> str:
    return "completion" if state.control.disposition == "propose_completion" else "monitor"


def build_entry_graph(contexts: GraphContexts):
    """Understand the user goal and resolve entry-level clarification only."""
    builder = StateGraph(RunCheckpoint)
    builder.add_node("normalize_entry", _node_normalize_entry)
    builder.add_node("analyze_task", lambda state: _node_analyze_task(state, deps=contexts.routing))
    builder.add_node("prepare_clarify_entry", _node_prepare_clarify)
    builder.add_node("interrupt_clarify_entry", _node_interrupt_clarify)
    builder.add_edge(START, "normalize_entry")
    builder.add_edge("normalize_entry", "analyze_task")
    builder.add_conditional_edges(
        "analyze_task",
        _after_entry_route,
        {"prepare_clarify_entry": "prepare_clarify_entry", "return_to_parent": END},
    )
    builder.add_conditional_edges(
        "prepare_clarify_entry",
        _after_prepare_clarify,
        {"analyze_task": "analyze_task", "interrupt_clarify_entry": "interrupt_clarify_entry"},
    )
    builder.add_conditional_edges(
        "interrupt_clarify_entry",
        _after_interrupt_clarify,
        {"analyze_task": "analyze_task", "finalize_entry_result": END},
    )
    return builder.compile()


def build_react_graph(contexts: GraphContexts):
    """Bounded executor-local ReAct loop."""
    builder = StateGraph(RunCheckpoint)
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
    builder = StateGraph(RunCheckpoint)
    builder.add_node("prepare_action", _node_prepare_invocation_batch)
    builder.add_node("select_action_step", _node_select_next_step)
    builder.add_node("execute_action_step", lambda state: _node_execute_step(state, deps=contexts.steps))
    builder.add_node("handle_action_success", lambda state: _node_handle_step_success(state, deps=contexts.steps))
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
            _after_invocation_batch,
            {
                "confirm_step": "confirm_action_step",
                "react_step": "react_action",
                "tool_node": "action_tool_node",
                "handle_success": "handle_action_success",
                "handle_failure": END,
            },
        )
    builder.add_edge("action_tool_node", "consume_action_tool_result")
    builder.add_conditional_edges(
        "react_action",
        _after_react_graph,
        {"handle_success": "handle_action_success", "action_done": END},
    )
    builder.add_edge("handle_action_success", "select_action_step")
    builder.add_conditional_edges(
        "confirm_action_step",
        _after_confirm_step,
        {
            "tool_node": "action_tool_node",
            "handle_success": "handle_action_success",
            "handle_failure": END,
        },
    )
    return builder.compile()


def build_executive_graph(contexts: GraphContexts):
    """Durable task-level decide-act-observe-verify loop."""
    deps = contexts.executive
    builder = StateGraph(RunCheckpoint)
    builder.add_node("compile_goal_graph", lambda state: _node_compile_goal_graph(state, deps=deps))
    builder.add_node("project_planning_facts", lambda state: _node_project_planning_facts(state, deps=deps))
    builder.add_node("assess_coordination", lambda state: _node_assess_coordination(state, deps=deps))
    builder.add_node("create_or_revise_plan", lambda state: _node_create_or_revise_plan(state, deps=deps))
    builder.add_node("project_control_state", lambda state: _node_project_control_state(state, deps=deps))
    builder.add_node("decide", lambda state: _node_decide(state, deps=deps))
    builder.add_node("admit_decision", lambda state: _node_admit_decision(state, deps=deps))
    builder.add_node("handle_decision_denial", lambda state: _node_handle_decision_denial(state, deps=deps))
    builder.add_node("admit_execution_route", lambda state: _node_admit_execution_route(state, deps=deps))
    builder.add_node("apply_decision", lambda state: _node_apply_decision(state, deps=deps))
    builder.add_node("resolve_action", lambda state: _node_resolve_action(state, deps=deps))
    builder.add_node("action_execution", build_action_execution_graph(contexts))
    builder.add_node("observe_action", lambda state: _node_observe_action(state, deps=deps))
    builder.add_node("verify_goal_progress", lambda state: _node_verify_goal_progress(state, deps=deps))
    builder.add_node("verify_completion", lambda state: _node_verify_completion(state, deps=deps))
    builder.add_node("monitor_plan", lambda state: _node_monitor_plan(state, deps=deps))

    builder.add_edge(START, "compile_goal_graph")
    builder.add_conditional_edges(
        "compile_goal_graph",
        _after_goal_compile,
        {"direct": "verify_goal_progress", "planning": "project_planning_facts"},
    )
    builder.add_edge("project_planning_facts", "assess_coordination")
    builder.add_conditional_edges(
        "assess_coordination",
        _after_coordination,
        {"plan": "create_or_revise_plan", "control": "project_control_state"},
    )
    builder.add_conditional_edges(
        "create_or_revise_plan",
        _after_plan_creation,
        {"control": "project_control_state", "stop": END},
    )
    builder.add_edge("project_control_state", "decide")
    builder.add_edge("decide", "admit_decision")
    builder.add_conditional_edges(
        "admit_decision",
        _after_decision_admission,
        {"route": "admit_execution_route", "deny": "handle_decision_denial"},
    )
    builder.add_edge("handle_decision_denial", END)
    builder.add_edge("admit_execution_route", "apply_decision")
    builder.add_conditional_edges(
        "apply_decision",
        _after_apply_decision,
        {
            "loop": "project_control_state",
            "action": "resolve_action",
            "completion": "verify_completion",
            "stop": END,
        },
    )
    builder.add_conditional_edges(
        "resolve_action",
        _after_action_resolution,
        {"dispatch": "action_execution", "control": "project_control_state"},
    )
    builder.add_edge("action_execution", "observe_action")
    builder.add_conditional_edges(
        "observe_action",
        _after_observation,
        {"retry": "resolve_action", "verify": "verify_goal_progress"},
    )
    builder.add_conditional_edges(
        "verify_goal_progress",
        _after_goal_verification,
        {"completion": "verify_completion", "monitor": "monitor_plan"},
    )
    builder.add_conditional_edges(
        "monitor_plan",
        _after_plan_monitor,
        {
            "replan": "create_or_revise_plan",
            "planning": "project_planning_facts",
            "control": "project_control_state",
            "stop": END,
        },
    )
    builder.add_conditional_edges(
        "verify_completion",
        _after_completion,
        {"complete": END, "loop": "project_control_state"},
    )
    return builder.compile()


def build_entry_orchestration_graph(contexts: GraphContexts, checkpointer=None):
    if checkpointer is None:
        raise ValueError("A persistent Postgres checkpointer is required.")
    builder = StateGraph(RunCheckpoint)
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
