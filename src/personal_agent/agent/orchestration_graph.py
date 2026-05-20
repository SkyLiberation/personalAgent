"""Entry orchestration graph assembly."""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from ..core.config import Settings
from .orchestration_models import AgentGraphState
from .orchestration_nodes import (
    OrchestrationDeps,
    _after_confirm_step as _after_confirm_step,
    _after_step_execution as _after_step_execution,
    _after_step_failure as _after_step_failure,
    _after_step_success as _after_step_success,
    _after_validate_plan as _after_validate_plan,
    _build_react_context as _build_react_context,
    _build_react_subgraph as _build_react_subgraph,
    _dispatch_plan_step as _dispatch_plan_step,
    _format_react_tools as _format_react_tools,
    _is_react_tool_blocked as _is_react_tool_blocked,
    _node_ask_branch as _node_ask_branch,
    _node_capture_branch as _node_capture_branch,
    _after_clarify_entry as _after_clarify_entry,
    _node_clarify_entry as _node_clarify_entry,
    _node_confirm_step as _node_confirm_step,
    _node_direct_answer_branch as _node_direct_answer_branch,
    _node_execute_plan_step as _node_execute_plan_step,
    _node_finalize_entry_result as _node_finalize_entry_result,
    _node_finalize_plan_execution as _node_finalize_plan_execution,
    _node_handle_step_failure as _node_handle_step_failure,
    _node_handle_step_success as _node_handle_step_success,
    _node_normalize_entry as _node_normalize_entry,
    _node_plan_task as _node_plan_task,
    _node_prepare_plan_execution as _node_prepare_plan_execution,
    _node_react_finalize as _node_react_finalize,
    _node_react_init as _node_react_init,
    _node_react_iterate as _node_react_iterate,
    _node_route_intent as _node_route_intent,
    _node_select_next_step as _node_select_next_step,
    _node_summarize_branch as _node_summarize_branch,
    _node_validate_plan as _node_validate_plan,
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
    """Conditional edge: route by classified intent after ``route_intent`` node.

    Planning intents go to ``plan_task``; non-planning intents go directly to
    their branch node — no duplicate routing.
    """
    if state.requires_planning:
        return "plan_task"
    intent = state.intent
    if intent in ("capture_text", "capture_link", "capture_file"):
        return "capture_branch"
    if intent == "ask":
        return "ask_branch"
    if intent == "summarize_thread":
        return "summarize_branch"
    if intent == "direct_answer":
        return "direct_answer_branch"
    return "direct_answer_branch"


def build_entry_orchestration_graph(deps: OrchestrationDeps, checkpointer=None):
    """Build and compile the entry orchestration graph.

    Phase 1: normalize → route → execute → finalize (linear).
    Phase 2: plan-driven paths go through step-level loop with checkpoint
    at each step transition.
    """
    builder = StateGraph(AgentGraphState)

    # ---- Phase 1 nodes ----
    builder.add_node("normalize_entry", _node_normalize_entry)
    builder.add_node("clarify_entry", _node_clarify_entry)
    builder.add_node(
        "route_intent",
        lambda state: _node_route_intent(state, deps=deps),
    )
    builder.add_node(
        "plan_task",
        lambda state: _node_plan_task(state, deps=deps),
    )
    builder.add_node(
        "validate_plan",
        lambda state: _node_validate_plan(state, deps=deps),
    )
    # Non-planning branch nodes
    builder.add_node(
        "capture_branch",
        lambda state: _node_capture_branch(state, deps=deps),
    )
    builder.add_node(
        "ask_branch",
        lambda state: _node_ask_branch(state, deps=deps),
    )
    builder.add_node(
        "summarize_branch",
        lambda state: _node_summarize_branch(state, deps=deps),
    )
    builder.add_node(
        "direct_answer_branch",
        lambda state: _node_direct_answer_branch(state, deps=deps),
    )
    builder.add_node("finalize_entry_result", _node_finalize_entry_result)

    # ---- Phase 2: plan execution loop nodes ----
    builder.add_node("prepare_plan_execution", _node_prepare_plan_execution)
    builder.add_node("select_next_step", _node_select_next_step)
    builder.add_node(
        "execute_plan_step",
        lambda state: _node_execute_plan_step(state, deps=deps),
    )
    builder.add_node("handle_step_success", _node_handle_step_success)
    builder.add_node(
        "handle_step_failure",
        lambda state: _node_handle_step_failure(state, deps=deps),
    )
    builder.add_node(
        "confirm_step",
        lambda state: _node_confirm_step(state, deps=deps),
    )
    # Phase 4: ReAct subgraph node
    builder.add_node(
        "react_step",
        _build_react_subgraph(deps),
    )
    builder.add_node("finalize_plan_execution", _node_finalize_plan_execution)

    # ---- Edges ----
    builder.add_edge(START, "normalize_entry")
    builder.add_edge("normalize_entry", "clarify_entry")
    builder.add_conditional_edges(
        "clarify_entry",
        _after_clarify_entry,
        {
            "route_intent": "route_intent",
            "finalize_entry_result": "finalize_entry_result",
        },
    )

    # route_intent → route by intent to plan_task or non-planning branch
    builder.add_conditional_edges(
        "route_intent",
        _route_by_intent,
        {
            "plan_task": "plan_task",
            "capture_branch": "capture_branch",
            "ask_branch": "ask_branch",
            "summarize_branch": "summarize_branch",
            "direct_answer_branch": "direct_answer_branch",
        },
    )
    builder.add_edge("plan_task", "validate_plan")

    # After validation: either enter plan execution or ask for clarification.
    builder.add_conditional_edges(
        "validate_plan",
        _after_validate_plan,
        {
            "prepare_plan_execution": "prepare_plan_execution",
            "direct_answer_branch": "direct_answer_branch",
        },
    )

    # Non-planning branches → finalize
    builder.add_edge("capture_branch", "finalize_entry_result")
    builder.add_edge("ask_branch", "finalize_entry_result")
    builder.add_edge("summarize_branch", "finalize_entry_result")
    builder.add_edge("direct_answer_branch", "finalize_entry_result")

    # Plan execution loop
    builder.add_edge("prepare_plan_execution", "select_next_step")

    builder.add_conditional_edges(
        "select_next_step",
        _should_execute_step,
        {
            "execute_step": "execute_plan_step",
            "finalize_plan": "finalize_plan_execution",
        },
    )

    builder.add_conditional_edges(
        "execute_plan_step",
        _after_step_execution,
        {
            "confirm_step": "confirm_step",
            "react_step": "react_step",
            "handle_success": "handle_step_success",
            "handle_failure": "handle_step_failure",
        },
    )

    # ReAct subgraph → success handler (subgraph internally marks step completed)
    builder.add_edge("react_step", "handle_step_success")

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
            "finalize_plan": "finalize_plan_execution",
        },
    )

    builder.add_conditional_edges(
        "confirm_step",
        _after_confirm_step,
        {
            "handle_success": "handle_step_success",
            "handle_failure": "handle_step_failure",
        },
    )

    # Plan execution → finalize
    builder.add_edge("finalize_plan_execution", "finalize_entry_result")
    builder.add_edge("finalize_entry_result", END)

    # Compile
    checkpointer = checkpointer or MemorySaver()
    return builder.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Helpers for the runtime integration
# ---------------------------------------------------------------------------


def _build_checkpointer(settings: Settings):
    backend = settings.langgraph_checkpoint_backend

    if backend == "memory":
        return MemorySaver()

    if backend == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            from pathlib import Path

            checkpoint_path = Path(settings.langgraph_checkpoint_path)
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Using SqliteSaver at %s", checkpoint_path)
            return SqliteSaver.from_conn_string(str(checkpoint_path))
        except ImportError:
            logger.warning(
                "SqliteSaver not available; falling back to MemorySaver"
            )
            return MemorySaver()

    logger.warning(
        "Unknown checkpoint backend '%s'; falling back to MemorySaver", backend
    )
    return MemorySaver()
