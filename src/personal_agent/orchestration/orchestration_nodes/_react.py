"""Bounded ReactGraph nodes used by the step execution graph."""

from __future__ import annotations

import json
import logging

from personal_agent.orchestration.orchestration_models import RunCheckpoint, ReactSubState
from personal_agent.orchestration.orchestration_contexts import ReactContext
from personal_agent.kernel.contracts.capability import CapabilityEvidencePack
from personal_agent.kernel.contracts.agentic import ContextBudget, ContextItem, RuntimeSnapshotRef
from personal_agent.orchestration.orchestration_nodes._graph_helpers import (
    _REACT_MAX_ITERATIONS_CAP,
    _is_react_tool_blocked,
)
from personal_agent.orchestration.orchestration_nodes import _helpers
from personal_agent.orchestration.orchestration_nodes._tooling import (
    _begin_tool_call,
    _clear_pending_tool_call,
    _latest_tool_artifact,
    _log_tool_invocation_event,
    _tool_result_event_payload,
)
from personal_agent.orchestration.orchestration_nodes._steps import _update_task_runtime

logger = logging.getLogger(__name__)

# ===================================================================
# Phase 4: ReactGraph nodes (iteration-level checkpointing)
# ===================================================================


def _node_react_init(state: RunCheckpoint, *, deps: ReactContext) -> dict:
    """Seed ReAct iteration state from the current execution step.

    Reads the step at ``current_step_index``, resolves allowed tools, and
    builds the initial LLM prompt.  The step status stays ``"running"`` —
    ReactGraph will mark it ``"completed"`` on finish.
    """
    if state.invocation_batch.current_step_index >= len(state.invocation_batch.invocations):
        state.react = ReactSubState(done=True, status="failed", stop_reason="missing_step")
        return {"react": state.react}

    sd = state.invocation_batch.invocations[state.invocation_batch.current_step_index]
    step = sd
    state.react = ReactSubState(
        step_id=step.step_id,
        max_iterations=min(step.max_iterations, _REACT_MAX_ITERATIONS_CAP),
        allowed_tools=list(sd.allowed_tools),
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


def _node_react_iterate(state: RunCheckpoint, *, deps: ReactContext) -> dict:
    """Execute one ReAct iteration by consuming the model's native tool_calls.

    Directly consumes ``_NativeReactOutcome`` from ``_helpers._react_llm_native``
    to construct ``AIMessage``, avoiding the legacy ``json.dumps`` envelope and
    ``_react_parse_response`` round-trip. Tool execution still flows through the
    shared ``react_tool_node`` (``ToolGateway``), so governance, HITL,
    idempotency and audit are unchanged.
    """
    if state.react.done:
        return {}

    step_id = state.react.step_id
    idx = state.react.iteration_index
    max_iter = state.react.max_iterations
    allowed = set(state.react.allowed_tools)

    # ---- Build prompt (first iteration) ----
    if idx == 0 and not state.react.user_prompt:
        sd = state.invocation_batch.invocations[state.invocation_batch.current_step_index]
        step = sd
        tools_block = _helpers._format_react_tools(allowed, deps)
        state.react.user_prompt = (
            f"## 步骤描述\n{step.description}\n\n"
            f"## 可用工具\n{tools_block}\n\n"
            f"请开始推理（最多 {max_iter} 轮）。"
        )
        if step.execution_guidance:
            state.react.user_prompt += (
                "\n\n## 执行方法与停止条件\n- "
                + "\n- ".join(step.execution_guidance)
            )
        if _has_downstream_commit(state, step_id):
            state.react.user_prompt += (
                "\n\n本步骤只允许读取和诊断，绝不能直接修改状态。"
                "若证据足以建议变更，请通过 finish_react 的 proposed_commit 返回"
                "候选 tool_name 与 tool_input；没有充分依据时 proposed_commit 必须为 null。"
            )

    # ---- Call LLM (native tool calling) ----
    model_prompt = _materialize_react_prompt(state, deps)
    outcome = _helpers._react_llm_native(model_prompt, deps, allowed)
    if outcome is None:
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

    # ---- LLM declared done ----
    if outcome.done:
        result = outcome.result if isinstance(outcome.result, dict) else {"answer": str(outcome.result or "")}
        state.react.done = True
        state.react.status = "completed"
        state.react.stop_reason = "llm_completed"
        state.react.result = result
        state.react.iterations.append({
            "iteration": idx,
            "thought": outcome.thought[:200],
            "done": True,
            "result": state.react.result,
        })
        state.add_event("react_iteration", {
            "step_id": step_id,
            "iteration": idx,
            "thought": outcome.thought[:200],
            "done": True,
        })
        return {"react": state.react}

    # ---- No tool_calls produced: parse failure ----
    if outcome.parse_failed or not outcome.tool_name:
        state.react.iteration_index = idx + 1
        state.add_event("react_iteration", {
            "step_id": step_id,
            "iteration": idx,
            "thought": outcome.thought[:200],
            "action_tool": "",
            "action_input": {},
            "observation": "LLM 输出未包含 tool_calls，跳过此轮。",
        })
        if state.react.iteration_index >= max_iter:
            state.react.done = True
            state.react.status = "exhausted"
            state.react.stop_reason = "parse_failures_exhausted"
            state.react.result = {"answer": "ReAct 循环未能产出结构化结果。", "react_iterations": len(state.react.iterations)}
        return {"react": state.react}

    # ---- Tool call ----
    tool_name = outcome.tool_name
    tool_input = outcome.tool_input or {}
    thought = outcome.thought

    observation: str
    if tool_name not in allowed:
        observation = f"错误：工具 '{tool_name}' 不在允许列表 {list(allowed)} 中。"
    elif _is_react_tool_blocked(tool_name, deps):
        observation = f"错误：工具 '{tool_name}' 是高风险/写操作工具，不允许在 ReAct 中调用。"
    elif state.task_contract is not None and state.provider_call_count >= state.task_contract.constraints.max_provider_calls:
        observation = "错误：本任务的 provider 调用预算已耗尽。"
    else:
        state.provider_call_count += 1
        state.react.pending_thought = thought
        state.react.pending_tool = tool_name
        state.react.pending_input = tool_input
        state.react.status = "waiting_tool"
        return {
            "tool_messages": [_begin_tool_call(
                state,
                context="react",
                tool_name=tool_name,
                tool_input=tool_input,
                step_id=step_id,
                suffix=f"react:{step_id}:{idx}",
                iteration=idx,
                call_id=outcome.native_call_id,
            )],
            "tool_tracking": state.tool_tracking,
            "react": state.react,
            "provider_call_count": state.provider_call_count,
            "events": state.events,
        }

    return _record_react_observation(state, thought, tool_name, tool_input, observation)


def _node_consume_react_tool_result(state: RunCheckpoint, *, deps: ReactContext | None = None) -> dict:
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
        artifact = dict(_latest_tool_artifact(state))
    step = next(
        (item for item in state.invocation_batch.invocations if item.step_id == state.react.step_id),
        None,
    )
    artifact["_step_id"] = state.react.step_id
    artifact["_goal_id"] = step.goal_id if step is not None else ""
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
    _record_capability_execution(state, state.react.step_id, artifact)
    from personal_agent.planning.agentic import ContextAdmission

    state.context_inventory = ContextAdmission.admit_observation(
        state.context_inventory,
        ref_id=f"react:{tool_call_id or state.react.step_id}:{state.react.iteration_index}",
        kind="provider_observation",
        provenance=state.react.pending_tool or "react_tool",
        summary=observation,
        payload={"step_id": state.react.step_id, "ok": bool(artifact.get("ok"))},
    )
    state.add_event("context_admitted", {
        "step_id": state.react.step_id,
        "trust_tier": "untrusted",
        "admitted_as_instruction": False,
    })
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
    result["context_inventory"] = state.context_inventory
    state.react.pending_thought = ""
    state.react.pending_tool = ""
    state.react.pending_input = {}
    return result


def _record_react_observation(
    state: RunCheckpoint,
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


def _node_react_finalize(state: RunCheckpoint) -> dict:
    """Persist the terminal ReAct outcome and release loop working data."""
    step_id = state.react.step_id

    # Persist result — capture before clearing
    result_to_persist = dict(state.react.result) if state.react.result else {}
    if step_id:
        result_to_persist["evidence_pack"] = _build_evidence_pack(state, step_id).model_dump(mode="json")
        state.invocation_batch.results[step_id] = result_to_persist

    completed = state.react.status == "completed"
    failure_reason = state.react.stop_reason or "ReAct 未完成步骤。"
    failure_policy = "skip"
    failure_retry_count = 0
    if state.invocation_batch.current_step_index < len(state.invocation_batch.invocations):
        sd = state.invocation_batch.invocations[state.invocation_batch.current_step_index]
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
                state.invocation_batch.retry_counts[step_id] = sd.retry_count
                state.errors.append(f"[{step_id}] {reason}")
                failure_reason = reason
                failure_policy = sd.on_failure
                failure_retry_count = sd.retry_count

    if completed:
        state.add_event("step_completed", {
            "step_id": step_id,
            "result_summary": _helpers._summarize_result(result_to_persist),
        })
        _update_react_ledger(state, step_id, "completed")
    else:
        state.add_event("step_failed", {
            "step_id": step_id,
            "error": failure_reason,
            "on_failure": failure_policy,
            "retry_count": failure_retry_count,
            "react_status": state.react.status,
            "react_stop_reason": state.react.stop_reason,
        })
        _update_react_ledger(state, step_id, "blocked", failure_reason)

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
        "invocation_batch": state.invocation_batch,
        "task_runtime": state.task_runtime,
        "errors": state.errors,
        "events": state.events,
    }


def _update_react_ledger(
    state: RunCheckpoint,
    step_id: str,
    status: str,
    reason: str | None = None,
) -> None:
    step = next((item for item in state.invocation_batch.invocations if item.step_id == step_id), None)
    if step is None or not step.goal_id:
        return
    _update_task_runtime(
        state,
        goal_id=step.goal_id,
        status=status,
        replan_reason=reason,
    )


def _has_downstream_commit(state: RunCheckpoint, step_id: str) -> bool:
    by_id = {step.step_id: step for step in state.invocation_batch.invocations}
    pending = [candidate for candidate in by_id.values() if step_id in candidate.depends_on]
    seen: set[str] = set()
    while pending:
        candidate = pending.pop()
        if candidate.step_id in seen:
            continue
        seen.add(candidate.step_id)
        if candidate.action_type == "commit":
            return True
        pending.extend(
            item for item in by_id.values() if candidate.step_id in item.depends_on
        )
    return False


def _build_evidence_pack(state: RunCheckpoint, step_id: str) -> CapabilityEvidencePack:
    """Normalize a bounded ReAct run into the artifact consumed by compose."""
    resolution_payload: dict = {}
    for event in reversed(state.events):
        if getattr(event, "type", "") != "capability_resolution":
            continue
        payload = getattr(event, "payload", {})
        if isinstance(payload, dict) and payload.get("step_id") == step_id:
            resolution_payload = payload
            break
    tool_calls = tuple(
        {
            "tool_name": item.get("action_tool"),
            "input": item.get("action_input", {}),
            "observation": item.get("observation", ""),
        }
        for item in state.react.iterations
        if item.get("action_tool")
    )
    snippets = tuple(
        {"text": str(item.get("observation") or "")}
        for item in state.react.iterations
        if item.get("observation")
    )
    sources = tuple(
        {"evidence": item.get("evidence", [])}
        for item in state.tool_results
        if isinstance(item, dict) and item.get("evidence")
    )
    sufficient = bool(sources or snippets)
    return CapabilityEvidencePack(
        scope_id=str(resolution_payload.get("scope_id") or ""),
        resolution_id=str(resolution_payload.get("resolution_id") or ""),
        selected_capability_ids=tuple(str(item) for item in resolution_payload.get("selected_capability_ids", ())),
        denied_capability_ids=tuple(str(item) for item in resolution_payload.get("denied_capability_ids", ())),
        tool_calls=tool_calls,
        sources=sources,
        snippets=snippets,
        confidence=float(resolution_payload.get("confidence") or 0.0),
        evidence_sufficiency="sufficient" if sufficient else "insufficient",
        citation_coverage=1.0 if sources else 0.0,
        unresolved_questions=() if sufficient else ("No governed evidence was returned by the scoped tools.",),
    )


def _record_capability_execution(state: RunCheckpoint, step_id: str, artifact: dict) -> None:
    for event in reversed(state.events):
        if getattr(event, "type", "") != "capability_resolution":
            continue
        payload = getattr(event, "payload", {})
        if not isinstance(payload, dict) or payload.get("step_id") != step_id:
            continue
        state.add_event("capability_execution", {
            "scope_id": payload.get("scope_id", ""),
            "resolution_id": payload.get("resolution_id", ""),
            "step_id": step_id,
            "lifecycle_state": "executed" if artifact.get("ok") else "failed",
            "tool_name": state.react.pending_tool,
            "ok": bool(artifact.get("ok")),
        })
        return


def _should_continue_react(state: RunCheckpoint) -> str:
    """Conditional edge: continue iterating or finalize."""
    if state.tool_tracking.active_context == "react":
        return "tool_node"
    if state.react.status in {"completed", "failed", "exhausted"}:
        return "finalize"
    if state.react.done or state.react.iteration_index >= state.react.max_iterations:
        return "finalize"
    return "iterate"


def _materialize_react_prompt(state: RunCheckpoint, deps: ReactContext) -> str:
    runtime = ContextItem(
        item_id=f"react:{state.react.step_id}:objective",
        category="run",
        kind="react_objective",
        provenance="runtime",
        trust="runtime",
        summary=state.react.user_prompt[:2000],
        payload={
            "instruction": state.react.user_prompt,
            "iteration": state.react.iteration_index,
            "max_iterations": state.react.max_iterations,
            "allowed_tools": tuple(state.react.allowed_tools),
            "authority_tier": "system_policy",
        },
        admission="admitted",
    )
    prior_results = tuple(ContextItem(
        item_id=f"react:{state.react.step_id}:result:{step_id}",
        category="observation",
        kind="prior_action_result",
        provenance="action_execution",
        trust="untrusted",
        summary=_helpers._summarize_result(result),
        payload={"result": result},
        admission="candidate",
    ) for step_id, result in state.invocation_batch.results.items())
    observations = tuple(ContextItem(
        item_id=f"react:{state.react.step_id}:observation:{index}",
        category="observation",
        kind="provider_observation",
        provenance=str(item.get("action_tool") or "react"),
        trust="untrusted",
        summary=str(item.get("observation") or "")[:2000],
        payload={
            "tool": item.get("action_tool"),
            "observation": item.get("observation"),
        },
        admission="candidate",
    ) for index, item in enumerate(state.react.iterations))
    items = (runtime, *prior_results, *observations)
    task_contract = state.task_contract
    task_runtime = state.task_runtime
    projection = deps.context_manager.project(
        items,
        purpose="bounded_react",
        budget=ContextBudget(
            model_profile="runtime-default",
            tokenizer_profile="runtime-default",
            max_context_tokens=16_384,
            safety_margin=512,
            reserved_output_tokens=2_048,
        ),
        source_snapshot=RuntimeSnapshotRef(
            run_id=state.run_id,
            task_id=task_contract.task_id if task_contract is not None else None,
            task_revision=task_contract.revision if task_contract is not None else None,
            runtime_revision=task_runtime.revision if task_runtime is not None else 0,
            event_sequence=(
                task_runtime.last_event_sequence if task_runtime is not None else len(state.events)
            ),
        ),
    )
    state.context_projections.append(projection)
    materialized = deps.context_gateway.open(
        projection,
        items,
        purpose="bounded_react",
    )
    state.add_event("context_projected", projection.model_dump(mode="json"))
    state.add_event("context_materialized", {
        "projection_id": projection.projection_id,
        "purpose": "bounded_react",
        "materialized_refs": materialized.materialized_refs,
    })
    return json.dumps(materialized.model_payload(), ensure_ascii=False, default=str)
