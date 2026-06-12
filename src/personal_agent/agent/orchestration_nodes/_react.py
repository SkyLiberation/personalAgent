"""Bounded ReactGraph nodes used by the step execution graph."""

from __future__ import annotations

import logging

from ..orchestration_models import AgentGraphState, ReactSubState
from ._deps import (
    OrchestrationDeps,
    _REACT_MAX_ITERATIONS_CAP,
    _is_react_tool_blocked,
    _resolve_allowed_tools_for_step,
)
from . import _helpers
from ._steps import (
    _begin_tool_call,
    _clear_pending_tool_call,
    _latest_tool_artifact,
    _log_tool_invocation_event,
    _tool_result_event_payload,
)

logger = logging.getLogger(__name__)

# ===================================================================
# Phase 4: ReactGraph nodes (iteration-level checkpointing)
# ===================================================================


def _node_react_init(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Seed ReAct iteration state from the current execution step.

    Reads the step at ``current_step_index``, resolves allowed tools, and
    builds the initial LLM prompt.  The step status stays ``"running"`` —
    ReactGraph will mark it ``"completed"`` on finish.
    """
    if state.step_execution.current_step_index >= len(state.step_execution.steps):
        state.react = ReactSubState(done=True, status="failed", stop_reason="missing_step")
        return {"react": state.react}

    sd = state.step_execution.steps[state.step_execution.current_step_index]
    step = sd.to_execution_step()

    state.react = ReactSubState(
        step_id=step.step_id,
        max_iterations=min(step.max_iterations, _REACT_MAX_ITERATIONS_CAP),
        allowed_tools=list(_resolve_allowed_tools_for_step(step, deps)),
        status="running",
    )

    state.add_event("step_started", {
        "step_id": step.step_id,
        "action_type": "react",
        "description": step.description,
        "max_iterations": state.react.max_iterations,
    })

    logger.info(
        "react_init step_id=%s max_iterations=%d",
        step.step_id, state.react.max_iterations,
    )
    return {"react": state.react}


def _node_react_iterate(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Execute one ReAct iteration: LLM think -> parse -> tool act -> observe.

    On first call the prompt is built from ``react.step_id`` / step context;
    subsequent iterations append the previous thought/action/observation to
    ``react.user_prompt`` so the LLM sees the full history.
    """
    if state.react.done:
        return {}

    step_id = state.react.step_id
    idx = state.react.iteration_index
    max_iter = state.react.max_iterations
    allowed = set(state.react.allowed_tools)

    # ---- Build prompt (first iteration) ----
    if idx == 0 and not state.react.user_prompt:
        sd = state.step_execution.steps[state.step_execution.current_step_index]
        step = sd.to_execution_step()
        context_block = _helpers._build_react_context(step, state.step_execution.results)
        tools_block = _helpers._format_react_tools(allowed, deps)
        state.react.user_prompt = (
            f"## 步骤描述\n{step.description}\n\n"
            f"## 已有上下文\n{context_block}\n\n"
            f"## 可用工具\n{tools_block}\n\n"
            f"请开始推理（最多 {max_iter} 轮）。"
        )

    # ---- Call LLM ----
    raw = _call_react_llm(state.react.user_prompt, deps, allowed)
    if raw is None:
        logger.warning("ReAct LLM returned nothing at iteration %d for step %s", idx, step_id)
        state.react.done = True
        state.react.status = "failed"
        state.react.stop_reason = "llm_unavailable"
        state.react.result = {"answer": "", "react_iterations": len(state.react.iterations), "error": "LLM returned nothing"}
        state.add_event("react_iteration", {
            "step_id": step_id,
            "iteration": idx,
            "thought": "",
            "action_tool": "",
            "observation": "LLM 调用失败，终止 ReAct 循环。",
        })
        return {"react": state.react}

    parsed = _helpers._react_parse_response(raw)
    if parsed is None:
        # Parse failure — record and continue
        state.react.user_prompt += "\n\n观察：LLM 输出无法解析，请重新输出 JSON。"
        state.react.iteration_index = idx + 1
        state.add_event("react_iteration", {
            "step_id": step_id,
            "iteration": idx,
            "thought": "",
            "action_tool": "",
            "action_input": {},
            "observation": "LLM 输出无法解析为 JSON，跳过此轮。",
        })
        if state.react.iteration_index >= max_iter:
            state.react.done = True
            state.react.status = "exhausted"
            state.react.stop_reason = "parse_failures_exhausted"
            state.react.result = {"answer": "ReAct 循环未能产出结构化结果。", "react_iterations": len(state.react.iterations)}
        return {"react": state.react}

    # ---- LLM declared done ----
    if parsed.get("done"):
        result = parsed.get("result", {})
        state.react.done = True
        state.react.status = "completed"
        state.react.stop_reason = "llm_completed"
        state.react.result = result if isinstance(result, dict) else {"answer": str(result)}
        state.react.iterations.append({
            "iteration": idx,
            "thought": str(parsed.get("thought", ""))[:200],
            "done": True,
            "result": state.react.result,
        })
        state.add_event("react_iteration", {
            "step_id": step_id,
            "iteration": idx,
            "thought": str(parsed.get("thought", ""))[:200],
            "done": True,
        })
        return {"react": state.react}

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
        state.react.pending_thought = thought
        state.react.pending_tool = tool_name
        state.react.pending_input = normalized_input
        state.react.status = "waiting_tool"
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
            "tool_tracking": state.tool_tracking,
            "react": state.react,
            "events": state.events,
        }

    return _record_react_observation(state, thought, tool_name, tool_input, observation)


def _node_consume_react_tool_result(state: AgentGraphState, *, deps: OrchestrationDeps | None = None) -> dict:
    """Turn the shared ToolGateway result into a ReAct observation."""
    matches_iteration = state.tool_tracking.pending_react_iteration == state.react.iteration_index
    matches_step = state.tool_tracking.pending_step_id == state.react.step_id
    if state.tool_tracking.active_context != "react" or not matches_step or not matches_iteration:
        artifact = {
            "ok": False,
            "data": None,
            "error": "工具返回上下文与当前 ReAct 轮次不匹配。",
            "evidence": [],
        }
    else:
        artifact = _latest_tool_artifact(state)
    tool_call_id = state.tool_tracking.pending_call_id
    state.tool_results.append(artifact)
    if artifact.get("ok"):
        observation = _helpers._summarize_react_tool_result(artifact.get("data"))
    else:
        observation = f"工具执行失败：{artifact.get('error') or '未知错误'}"
    state.add_event("tool_result", _tool_result_event_payload(
        state,
        deps=deps,
        context="react",
        step_id=state.react.step_id,
        tool_call_id=tool_call_id,
        artifact=artifact,
    ))
    if deps is not None:
        _log_tool_invocation_event(state, deps, artifact, execution_mode="react")
    _clear_pending_tool_call(state)
    result = _record_react_observation(
        state,
        state.react.pending_thought,
        state.react.pending_tool,
        state.react.pending_input,
        observation,
    )
    result["tool_tracking"] = state.tool_tracking
    result["tool_results"] = state.tool_results
    state.react.pending_thought = ""
    state.react.pending_tool = ""
    state.react.pending_input = {}
    return result


def _record_react_observation(
    state: AgentGraphState,
    thought: str,
    tool_name: str,
    tool_input: object,
    observation: str,
) -> dict:
    normalized_input = tool_input if isinstance(tool_input, dict) else {}
    idx = state.react.iteration_index
    state.react.iterations.append({
        "iteration": idx,
        "thought": thought[:200],
        "action_tool": tool_name,
        "action_input": normalized_input,
        "observation": observation[:300],
    })
    state.add_event("react_iteration", {
        "step_id": state.react.step_id,
        "iteration": idx,
        "thought": thought[:200],
        "action_tool": tool_name,
        "action_input": normalized_input,
        "observation": observation[:300],
    })
    state.react.user_prompt += (
        f"\n\n思考：{thought}\n"
        f"动作：{tool_name}({_json_dumps_safe(normalized_input)})\n"
        f"观察：{observation}"
    )
    state.react.iteration_index = idx + 1
    state.react.status = "running"
    state.react.stop_reason = ""
    if state.react.iteration_index >= state.react.max_iterations:
        state.react.done = True
        state.react.status = "exhausted"
        state.react.stop_reason = "max_iterations"
        final_obs = [it.get("observation", "") for it in state.react.iterations if it.get("observation")]
        state.react.result = {
            "answer": "\n".join(final_obs) if final_obs else "",
            "react_iterations": len(state.react.iterations),
        }
    return {"react": state.react, "events": state.events}


def _node_react_finalize(state: AgentGraphState) -> dict:
    """Persist the terminal ReAct outcome and release loop working data."""
    step_id = state.react.step_id

    # Persist result — capture before clearing
    result_to_persist = dict(state.react.result) if state.react.result else {}
    if step_id:
        state.step_execution.results[step_id] = result_to_persist

    completed = state.react.status == "completed"
    failure_reason = state.react.stop_reason or "ReAct 未完成步骤。"
    failure_policy = "skip"
    failure_retry_count = 0
    if state.step_execution.current_step_index < len(state.step_execution.steps):
        sd = state.step_execution.steps[state.step_execution.current_step_index]
        if sd.step_id == step_id:
            if completed:
                sd.status = "completed"
            else:
                reason = (
                    str(result_to_persist.get("error") or "").strip()
                    or state.react.stop_reason
                    or "ReAct 未完成步骤。"
                )
                sd.status = "failed"
                sd.retry_count += 1
                sd.failure_reason = reason
                sd.recoverable = sd.on_failure == "retry" and sd.retry_count < sd.max_retries
                state.step_execution.retry_counts[step_id] = sd.retry_count
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
            "react_status": state.react.status,
            "react_stop_reason": state.react.stop_reason,
        })

    # Clear loop working data while retaining terminal outcome for audit/replay.
    react_outcome = ReactSubState(
        done=state.react.done,
        result=state.react.result,
        status=state.react.status,
        stop_reason=state.react.stop_reason,
    )
    state.react = react_outcome

    logger.info("react_finalize step_id=%s result_keys=%s", step_id, list(result_to_persist.keys()))
    return {
        "react": state.react,
        "step_execution": state.step_execution,
        "errors": state.errors,
        "events": state.events,
    }


def _should_continue_react(state: AgentGraphState) -> str:
    """Conditional edge: continue iterating or finalize."""
    if state.tool_tracking.active_context == "react":
        return "tool_node"
    if state.react.status in {"completed", "failed", "exhausted"}:
        return "finalize"
    if state.react.done or state.react.iteration_index >= state.react.max_iterations:
        return "finalize"
    return "iterate"


def _json_dumps_safe(obj: object) -> str:
    import json as _json

    if isinstance(obj, dict):
        return _json.dumps(obj, ensure_ascii=False)
    return str(obj)


def _call_react_llm(prompt: str, deps: OrchestrationDeps, allowed_tools: set[str]):
    try:
        return _helpers._react_llm_respond(prompt, deps, allowed_tools=allowed_tools)
    except TypeError as exc:
        if "allowed_tools" not in str(exc):
            raise
        return _helpers._react_llm_respond(prompt, deps)
