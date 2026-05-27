"""Bounded ReactGraph nodes used by the plan execution graph."""

from __future__ import annotations

import logging

from ..orchestration_models import AgentGraphState
from ._deps import (
    OrchestrationDeps,
    _REACT_MAX_ITERATIONS_CAP,
    _is_react_tool_blocked,
    _resolve_allowed_tools_for_step,
)
from . import _helpers
from ._steps import _begin_tool_call, _clear_pending_tool_call, _latest_tool_artifact

logger = logging.getLogger(__name__)

# ===================================================================
# Phase 4: ReactGraph nodes (iteration-level checkpointing)
# ===================================================================


def _node_react_init(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Seed ReAct iteration state from the current plan step.

    Reads the step at ``current_step_index``, resolves allowed tools, and
    builds the initial LLM prompt.  The step status stays ``"running"`` —
    ReactGraph will mark it ``"completed"`` on finish.
    """
    if state.current_step_index >= len(state.plan_steps):
        state.react_done = True
        state.react_status = "failed"
        state.react_stop_reason = "missing_plan_step"
        return {
            "react_done": True,
            "react_status": state.react_status,
            "react_stop_reason": state.react_stop_reason,
        }

    sd = state.plan_steps[state.current_step_index]
    step = sd.to_plan_step()

    state.react_step_id = step.step_id
    state.react_max_iterations = min(step.max_iterations, _REACT_MAX_ITERATIONS_CAP)
    state.react_allowed_tools = list(_resolve_allowed_tools_for_step(step, deps))
    state.react_iteration_index = 0
    state.react_done = False
    state.react_result = {}
    state.react_iterations = []
    state.react_pending_thought = ""
    state.react_pending_tool = ""
    state.react_pending_input = {}
    state.react_status = "running"
    state.react_stop_reason = ""

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
        "react_pending_thought": "",
        "react_pending_tool": "",
        "react_pending_input": {},
        "react_status": "running",
        "react_stop_reason": "",
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
        state.react_status = "failed"
        state.react_stop_reason = "llm_unavailable"
        state.react_result = {"answer": "", "react_iterations": len(state.react_iterations), "error": "LLM returned nothing"}
        state.add_event("react_iteration", {
            "step_id": step_id,
            "iteration": idx,
            "thought": "",
            "action_tool": "",
            "observation": "LLM 调用失败，终止 ReAct 循环。",
        })
        return {
            "react_done": True,
            "react_result": state.react_result,
            "react_status": state.react_status,
            "react_stop_reason": state.react_stop_reason,
        }

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
            state.react_status = "exhausted"
            state.react_stop_reason = "parse_failures_exhausted"
            state.react_result = {"answer": "ReAct 循环未能产出结构化结果。", "react_iterations": len(state.react_iterations)}
            return {
                "react_done": True,
                "react_result": state.react_result,
                "react_iteration_index": state.react_iteration_index,
                "react_user_prompt": state.react_user_prompt,
                "react_status": state.react_status,
                "react_stop_reason": state.react_stop_reason,
            }
        return {"react_iteration_index": state.react_iteration_index, "react_user_prompt": state.react_user_prompt}

    # ---- LLM declared done ----
    if parsed.get("done"):
        result = parsed.get("result", {})
        state.react_done = True
        state.react_status = "completed"
        state.react_stop_reason = "llm_completed"
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
        return {
            "react_done": True,
            "react_result": state.react_result,
            "react_iterations": state.react_iterations,
            "react_status": state.react_status,
            "react_stop_reason": state.react_stop_reason,
        }

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
        normalized_input = tool_input if isinstance(tool_input, dict) else {}
        state.react_pending_thought = thought
        state.react_pending_tool = tool_name
        state.react_pending_input = normalized_input
        state.react_status = "waiting_tool"
        return {
            "tool_messages": [_begin_tool_call(
                state,
                context="react",
                tool_name=tool_name,
                tool_input=normalized_input,
                step_id=step_id,
                suffix=f"react:{step_id}:{idx}",
                iteration=idx,
            )],
            "active_tool_context": "react",
            "pending_tool_step_id": state.pending_tool_step_id,
            "pending_tool_call_id": state.pending_tool_call_id,
            "pending_react_iteration": idx,
            "react_pending_thought": thought,
            "react_pending_tool": tool_name,
            "react_pending_input": normalized_input,
            "react_status": "waiting_tool",
            "events": state.events,
        }

    return _record_react_observation(state, thought, tool_name, tool_input, observation)


def _node_consume_react_tool_result(state: AgentGraphState) -> dict:
    """Turn the shared ToolNode result into a ReAct observation."""
    matches_iteration = state.pending_react_iteration == state.react_iteration_index
    matches_step = state.pending_tool_step_id == state.react_step_id
    if state.active_tool_context != "react" or not matches_step or not matches_iteration:
        artifact = {
            "ok": False,
            "data": None,
            "error": "工具返回上下文与当前 ReAct 轮次不匹配。",
            "evidence": [],
        }
    else:
        artifact = _latest_tool_artifact(state)
    tool_call_id = state.pending_tool_call_id
    state.tool_results.append(artifact)
    if artifact.get("ok"):
        observation = _helpers._summarize_react_tool_result(artifact.get("data"))
    else:
        observation = f"工具执行失败：{artifact.get('error') or '未知错误'}"
    _clear_pending_tool_call(state)
    state.add_event("tool_result", {
        "context": "react",
        "step_id": state.react_step_id,
        "tool_call_id": tool_call_id,
        "ok": bool(artifact.get("ok")),
        "result_summary": _helpers._summarize_result(artifact.get("data")),
    })
    result = _record_react_observation(
        state,
        state.react_pending_thought,
        state.react_pending_tool,
        state.react_pending_input,
        observation,
    )
    result.update({
        "active_tool_context": None,
        "pending_tool_step_id": "",
        "pending_tool_call_id": "",
        "pending_react_iteration": None,
        "tool_results": state.tool_results,
        "react_pending_thought": "",
        "react_pending_tool": "",
        "react_pending_input": {},
    })
    state.react_pending_thought = ""
    state.react_pending_tool = ""
    state.react_pending_input = {}
    return result


def _record_react_observation(
    state: AgentGraphState,
    thought: str,
    tool_name: str,
    tool_input: object,
    observation: str,
) -> dict:
    normalized_input = tool_input if isinstance(tool_input, dict) else {}
    idx = state.react_iteration_index
    state.react_iterations.append({
        "iteration": idx,
        "thought": thought[:200],
        "action_tool": tool_name,
        "action_input": normalized_input,
        "observation": observation[:300],
    })
    state.add_event("react_iteration", {
        "step_id": state.react_step_id,
        "iteration": idx,
        "thought": thought[:200],
        "action_tool": tool_name,
        "action_input": normalized_input,
        "observation": observation[:300],
    })
    state.react_user_prompt += (
        f"\n\n思考：{thought}\n"
        f"动作：{tool_name}({_json_dumps_safe(normalized_input)})\n"
        f"观察：{observation}"
    )
    state.react_iteration_index = idx + 1
    state.react_status = "running"
    state.react_stop_reason = ""
    if state.react_iteration_index >= state.react_max_iterations:
        state.react_done = True
        state.react_status = "exhausted"
        state.react_stop_reason = "max_iterations"
        final_obs = [it.get("observation", "") for it in state.react_iterations if it.get("observation")]
        state.react_result = {
            "answer": "\n".join(final_obs) if final_obs else "",
            "react_iterations": len(state.react_iterations),
        }
    return {
        "react_done": state.react_done,
        "react_result": state.react_result,
        "react_iteration_index": state.react_iteration_index,
        "react_iterations": state.react_iterations,
        "react_user_prompt": state.react_user_prompt,
        "react_status": state.react_status,
        "react_stop_reason": state.react_stop_reason,
        "events": state.events,
    }


def _node_react_finalize(state: AgentGraphState) -> dict:
    """Persist the terminal ReAct outcome and release loop working data."""
    step_id = state.react_step_id

    # Persist result — capture before clearing react_result
    result_to_persist = dict(state.react_result) if state.react_result else {}
    if step_id:
        state.step_results[step_id] = result_to_persist

    completed = state.react_status == "completed"
    failure_reason = state.react_stop_reason or "ReAct 未完成步骤。"
    failure_policy = "skip"
    failure_retry_count = 0
    if state.current_step_index < len(state.plan_steps):
        sd = state.plan_steps[state.current_step_index]
        if sd.step_id == step_id:
            if completed:
                sd.status = "completed"
            else:
                reason = (
                    str(result_to_persist.get("error") or "").strip()
                    or state.react_stop_reason
                    or "ReAct 未完成步骤。"
                )
                sd.status = "failed"
                sd.retry_count += 1
                sd.failure_reason = reason
                sd.recoverable = sd.on_failure == "retry" and sd.retry_count < sd.max_retries
                state.plan_retry_counts[step_id] = sd.retry_count
                state.errors.append(f"[{step_id}] {reason}")
                failure_reason = reason
                failure_policy = sd.on_failure
                failure_retry_count = sd.retry_count

    if completed:
        state.add_event("step_completed", {
            "step_id": step_id,
            "result_summary": _helpers._summarize_result(result_to_persist),
        })
    else:
        state.add_event("step_failed", {
            "step_id": step_id,
            "error": failure_reason,
            "on_failure": failure_policy,
            "retry_count": failure_retry_count,
            "react_status": state.react_status,
            "react_stop_reason": state.react_stop_reason,
        })

    # Clear loop working data while retaining terminal outcome for audit/replay.
    state.react_step_id = ""
    state.react_iteration_index = 0
    state.react_max_iterations = 3
    state.react_allowed_tools = []
    state.react_user_prompt = ""
    state.react_pending_thought = ""
    state.react_pending_tool = ""
    state.react_pending_input = {}

    logger.info("react_finalize step_id=%s result_keys=%s", step_id, list(result_to_persist.keys()))
    return {
        "react_step_id": "",
        "react_iteration_index": 0,
        "react_max_iterations": 3,
        "react_allowed_tools": [],
        "react_user_prompt": "",
        "react_done": state.react_done,
        "react_result": state.react_result,
        "react_status": state.react_status,
        "react_stop_reason": state.react_stop_reason,
        "react_pending_thought": "",
        "react_pending_tool": "",
        "react_pending_input": {},
        "step_results": state.step_results,
        "plan_steps": state.plan_steps,
        "plan_retry_counts": state.plan_retry_counts,
        "errors": state.errors,
        "events": state.events,
    }


def _should_continue_react(state: AgentGraphState) -> str:
    """Conditional edge: continue iterating or finalize."""
    if state.active_tool_context == "react":
        return "tool_node"
    if state.react_status in {"completed", "failed", "exhausted"}:
        return "finalize"
    if state.react_done or state.react_iteration_index >= state.react_max_iterations:
        return "finalize"
    return "iterate"


def _json_dumps_safe(obj: object) -> str:
    import json as _json

    if isinstance(obj, dict):
        return _json.dumps(obj, ensure_ascii=False)
    return str(obj)




