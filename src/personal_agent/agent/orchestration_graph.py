"""Entry orchestration graph assembly."""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from ..core.config import Settings
from .orchestration_models import AgentGraphState
from .orchestration_nodes import (
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
    _node_confirm_step as _node_confirm_step,
    _node_execute_current_runtime_path as _node_execute_current_runtime_path,
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
    _node_validate_plan as _node_validate_plan,
    _react_llm_respond as _react_llm_respond,
    _resolve_allowed_tools_for_step as _resolve_allowed_tools_for_step,
    _should_continue_react as _should_continue_react,
    _should_execute_step as _should_execute_step,
    _should_plan as _should_plan,
    _summarize_react_tool_result as _summarize_react_tool_result,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_entry_orchestration_graph(runtime, checkpointer=None):
    """Build and compile the entry orchestration graph.

    Phase 1: normalize → route → execute → finalize (linear).
    Phase 2: plan-driven paths go through step-level loop with checkpoint
    at each step transition.
    """
    builder = StateGraph(AgentGraphState)

    # ---- Phase 1 nodes ----
    builder.add_node("normalize_entry", _node_normalize_entry)
    builder.add_node(
        "route_intent",
        lambda state: _node_route_intent(state, runtime=runtime),
    )
    builder.add_node(
        "plan_task",
        lambda state: _node_plan_task(state, runtime=runtime),
    )
    builder.add_node(
        "validate_plan",
        lambda state: _node_validate_plan(state, runtime=runtime),
    )
    builder.add_node(
        "execute_current_runtime_path",
        lambda state: _node_execute_current_runtime_path(state, runtime=runtime),
    )
    builder.add_node("finalize_entry_result", _node_finalize_entry_result)

    # ---- Phase 2: plan execution loop nodes ----
    builder.add_node("prepare_plan_execution", _node_prepare_plan_execution)
    builder.add_node("select_next_step", _node_select_next_step)
    builder.add_node(
        "execute_plan_step",
        lambda state: _node_execute_plan_step(state, runtime=runtime),
    )
    builder.add_node("handle_step_success", _node_handle_step_success)
    builder.add_node(
        "handle_step_failure",
        lambda state: _node_handle_step_failure(state, runtime=runtime),
    )
    builder.add_node(
        "confirm_step",
        lambda state: _node_confirm_step(state, runtime=runtime),
    )
    # Phase 4: ReAct subgraph node
    builder.add_node(
        "react_step",
        _build_react_subgraph(runtime),
    )
    builder.add_node("finalize_plan_execution", _node_finalize_plan_execution)

    # ---- Edges ----
    builder.add_edge(START, "normalize_entry")
    builder.add_edge("normalize_entry", "route_intent")

    # Phase 6: route_intent → should_plan? → plan_task → validate_plan
    builder.add_conditional_edges(
        "route_intent",
        _should_plan,
        {
            "plan_task": "plan_task",
            "execute_current_runtime_path": "execute_current_runtime_path",
        },
    )
    builder.add_edge("plan_task", "validate_plan")

    # After validation: either enter plan execution or fall back to legacy
    builder.add_conditional_edges(
        "validate_plan",
        _after_validate_plan,
        {
            "prepare_plan_execution": "prepare_plan_execution",
            "execute_current_runtime_path": "execute_current_runtime_path",
        },
    )

    # Legacy / non-planning path
    builder.add_edge("execute_current_runtime_path", "finalize_entry_result")

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
