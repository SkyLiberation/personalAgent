"""ReAct inner-loop subgraph: react_init, react_iterate, react_finalize."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from ..orchestration_models import AgentGraphState
from ._deps import (
    OrchestrationDeps,
    _REACT_MAX_ITERATIONS_CAP,
    _is_react_tool_blocked,
    _resolve_allowed_tools_for_step,
)
from . import _helpers

if TYPE_CHECKING:
    from ._deps import PlanStep

logger = logging.getLogger(__name__)

# ===================================================================
# Phase 4: ReAct subgraph (iteration-level checkpointing)
# ===================================================================


def _node_react_init(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Seed ReAct iteration state from the current plan step.

    Reads the step at ``current_step_index``, resolves allowed tools, and
    builds the initial LLM prompt.  The step status stays ``"running"`` —
    the subgraph loop will mark it ``"completed"`` on finish.
    """
    if state.current_step_index >= len(state.plan_steps):
        state.react_done = True
        return {"react_done": True}

    sd = state.plan_steps[state.current_step_index]
    step = sd.to_plan_step()

    state.react_step_id = step.step_id
    state.react_max_iterations = min(step.max_iterations, _REACT_MAX_ITERATIONS_CAP)
    state.react_allowed_tools = list(_resolve_allowed_tools_for_step(step, deps))
    state.react_iteration_index = 0
    state.react_done = False
    state.react_result = {}
    state.react_iterations = []

    # Build initial prompt (same structure as ReActStepRunner.run)
    state.add_event("step_started", {
        "step_id": step.step_id,
        "action_type": "react",
        "description": step.description,
        "max_iterations": state.react_max_iterations,
    })

    logger.info(
        "react_init step_id=%s max_iterations=%d",
        step.step_id, state.react_max_iterations,
    )
    return {
        "react_step_id": step.step_id,
        "react_max_iterations": state.react_max_iterations,
        "react_allowed_tools": state.react_allowed_tools,
        "react_iteration_index": 0,
        "react_done": False,
        "react_result": {},
        "react_iterations": [],
    }


def _node_react_iterate(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Execute one ReAct iteration: LLM think → parse → tool act → observe.

    On first call the prompt is built from ``react_step_id`` / step context;
    subsequent iterations append the previous thought/action/observation to
    ``react_user_prompt`` so the LLM sees the full history.
    """
    if state.react_done:
        return {}

    step_id = state.react_step_id
    idx = state.react_iteration_index
    max_iter = state.react_max_iterations
    allowed = set(state.react_allowed_tools)

    # ---- Build prompt (first iteration) ----
    if idx == 0 and not state.react_user_prompt:
        sd = state.plan_steps[state.current_step_index]
        step = sd.to_plan_step()
        context_block = _helpers._build_react_context(step, state.step_results)
        tools_block = _helpers._format_react_tools(allowed, deps)
        state.react_user_prompt = (
            f"## 步骤描述\n{step.description}\n\n"
            f"## 已有上下文\n{context_block}\n\n"
            f"## 可用工具\n{tools_block}\n\n"
            f"请开始推理（最多 {max_iter} 轮）。"
        )

    # ---- Call LLM ----
    raw = _helpers._react_llm_respond(state.react_user_prompt, deps)
    if raw is None:
        logger.warning("ReAct LLM returned nothing at iteration %d for step %s", idx, step_id)
        state.react_done = True
        state.react_result = {"answer": "", "react_iterations": len(state.react_iterations), "error": "LLM returned nothing"}
        state.add_event("react_iteration", {
            "step_id": step_id,
            "iteration": idx,
            "thought": "",
            "action_tool": "",
            "observation": "LLM 调用失败，终止 ReAct 循环。",
        })
        return {"react_done": True, "react_result": state.react_result}

    parsed = _helpers._react_parse_response(raw)
    if parsed is None:
        # Parse failure — record and continue
        state.react_user_prompt += "\n\n观察：LLM 输出无法解析，请重新输出 JSON。"
        state.react_iteration_index = idx + 1
        state.add_event("react_iteration", {
            "step_id": step_id,
            "iteration": idx,
            "thought": "",
            "action_tool": "",
            "action_input": {},
            "observation": "LLM 输出无法解析为 JSON，跳过此轮。",
        })
        if state.react_iteration_index >= max_iter:
            state.react_done = True
            state.react_result = {"answer": "ReAct 循环未能产出结构化结果。", "react_iterations": len(state.react_iterations)}
            return {"react_done": True, "react_result": state.react_result, "react_iteration_index": state.react_iteration_index, "react_user_prompt": state.react_user_prompt}
        return {"react_iteration_index": state.react_iteration_index, "react_user_prompt": state.react_user_prompt}

    # ---- LLM declared done ----
    if parsed.get("done"):
        result = parsed.get("result", {})
        state.react_done = True
        state.react_result = result if isinstance(result, dict) else {"answer": str(result)}
        state.react_iterations.append({
            "iteration": idx,
            "thought": str(parsed.get("thought", ""))[:200],
            "done": True,
            "result": state.react_result,
        })
        state.add_event("react_iteration", {
            "step_id": step_id,
            "iteration": idx,
            "thought": str(parsed.get("thought", ""))[:200],
            "done": True,
        })
        return {"react_done": True, "react_result": state.react_result, "react_iterations": state.react_iterations}

    # ---- Tool call ----
    tool_name = str(parsed.get("tool", ""))
    tool_input = parsed.get("input", {})
    thought = str(parsed.get("thought", ""))

    observation: str
    if not tool_name:
        observation = "错误：未指定工具名。请输出合法 JSON。"
    elif tool_name not in allowed:
        observation = f"错误：工具 '{tool_name}' 不在允许列表 {list(allowed)} 中。"
    elif _is_react_tool_blocked(tool_name, deps):
        observation = f"错误：工具 '{tool_name}' 是高风险/写操作工具，不允许在 ReAct 中调用。"
    else:
        tool_result = deps.tool_registry.execute(tool_name, **tool_input)
        if tool_result is not None and hasattr(tool_result, "ok") and tool_result.ok:
            observation = _helpers._summarize_react_tool_result(tool_result.data if hasattr(tool_result, "data") else None)
        elif tool_result is not None and hasattr(tool_result, "error"):
            observation = f"工具执行失败：{tool_result.error}"
        else:
            observation = "工具执行失败：未知错误"

    state.react_iterations.append({
        "iteration": idx,
        "thought": thought[:200],
        "action_tool": tool_name,
        "action_input": tool_input if isinstance(tool_input, dict) else {},
        "observation": observation[:300],
    })
    state.add_event("react_iteration", {
        "step_id": step_id,
        "iteration": idx,
        "thought": thought[:200],
        "action_tool": tool_name,
        "action_input": tool_input if isinstance(tool_input, dict) else {},
        "observation": observation[:300],
    })

    # Append to prompt for next iteration
    state.react_user_prompt += (
        f"\n\n思考：{thought}\n"
        f"动作：{tool_name}({_json_dumps_safe(tool_input)})\n"
        f"观察：{observation}"
    )
    state.react_iteration_index = idx + 1

    # Check max iterations
    if state.react_iteration_index >= max_iter:
        state.react_done = True
        final_obs = [it.get("observation", "") for it in state.react_iterations if it.get("observation")]
        state.react_result = {
            "answer": "\n".join(final_obs) if final_obs else "",
            "react_iterations": len(state.react_iterations),
        }
        return {
            "react_done": True,
            "react_result": state.react_result,
            "react_iteration_index": state.react_iteration_index,
            "react_iterations": state.react_iterations,
            "react_user_prompt": state.react_user_prompt,
        }

    return {
        "react_iteration_index": state.react_iteration_index,
        "react_iterations": state.react_iterations,
        "react_user_prompt": state.react_user_prompt,
    }


def _node_react_finalize(state: AgentGraphState) -> dict:
    """Write ReAct results into ``step_results``, mark step completed, and
    clear ephemeral ReAct state fields."""
    step_id = state.react_step_id

    # Persist result — capture before clearing react_result
    result_to_persist = dict(state.react_result) if state.react_result else {}
    if step_id:
        state.step_results[step_id] = result_to_persist

    # Mark step completed in plan_steps
    if state.current_step_index < len(state.plan_steps):
        sd = state.plan_steps[state.current_step_index]
        if sd.step_id == step_id:
            sd.status = "completed"

    state.add_event("step_completed", {
        "step_id": step_id,
        "result_summary": _helpers._summarize_result(result_to_persist),
    })

    # Clear ephemeral ReAct fields
    state.react_step_id = ""
    state.react_iteration_index = 0
    state.react_max_iterations = 3
    state.react_allowed_tools = []
    state.react_user_prompt = ""
    state.react_done = False
    state.react_result = {}

    logger.info("react_finalize step_id=%s result_keys=%s", step_id, list(result_to_persist.keys()))
    return {
        "react_step_id": "",
        "react_iteration_index": 0,
        "react_max_iterations": 3,
        "react_allowed_tools": [],
        "react_user_prompt": "",
        "react_done": False,
        "react_result": {},
        "step_results": state.step_results,
        "plan_steps": state.plan_steps,
    }


def _should_continue_react(state: AgentGraphState) -> str:
    """Conditional edge: continue iterating or finalize."""
    if state.react_done or state.react_iteration_index >= state.react_max_iterations:
        return "finalize"
    return "iterate"


def _json_dumps_safe(obj: object) -> str:
    import json as _json

    if isinstance(obj, dict):
        return _json.dumps(obj, ensure_ascii=False)
    return str(obj)


def _build_react_subgraph(deps: OrchestrationDeps):
    """Build and compile the ReAct inner-loop subgraph.

    The subgraph uses ``AgentGraphState`` and checkpoints at every
    iteration boundary (react_iterate self-loop).
    """
    builder = StateGraph(AgentGraphState)

    builder.add_node(
        "react_init",
        lambda state: _node_react_init(state, deps=deps),
    )
    builder.add_node(
        "react_iterate",
        lambda state: _node_react_iterate(state, deps=deps),
    )
    builder.add_node("react_finalize", _node_react_finalize)

    builder.add_edge(START, "react_init")
    builder.add_edge("react_init", "react_iterate")

    builder.add_conditional_edges(
        "react_iterate",
        _should_continue_react,
        {
            "iterate": "react_iterate",
            "finalize": "react_finalize",
        },
    )

    builder.add_edge("react_finalize", END)

    # Use the same MemorySaver so checkpoints are in the same store
    return builder.compile(checkpointer=MemorySaver())


