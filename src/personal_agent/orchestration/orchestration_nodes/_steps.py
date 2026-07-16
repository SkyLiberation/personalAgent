"""execution step execution loop nodes, step dispatchers, and conditional edge functions."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from langgraph.types import interrupt

from personal_agent.kernel.models import Citation
from personal_agent.kernel.contracts.agent import AgentGatewayContext, AgentTask
from personal_agent.kernel.contracts.executive import ResolvedActionSpec
from personal_agent.kernel.contracts.interaction import InteractionRequest
from personal_agent.kernel.prompts import render_prompt
from personal_agent.orchestration.orchestration_models import (
    RunCheckpoint,
    ExecutableInvocation,
    InvocationBatchState,
    ReactSubState,
)
from personal_agent.orchestration.orchestration_contexts import StepExecutionContext
from personal_agent.orchestration.orchestration_nodes._graph_helpers import (
    _REACT_MAX_ITERATIONS_CAP,
    _default_step_answer,
    _inject_draft_text_into_steps,
    _inject_note_id_into_steps,
    _skip_step_dependents,
    _topological_sort_steps,
)
from personal_agent.orchestration.orchestration_nodes import _helpers
from personal_agent.orchestration.orchestration_nodes._tooling import (
    _begin_tool_call,
    _clear_pending_tool_call,
    _latest_tool_artifact,
    _log_tool_invocation_event,
    _pending_tool_updates,
    _tool_result_event_payload,
)
from personal_agent.planning.ledger import TaskRuntimeProjector, next_execution_event

logger = logging.getLogger(__name__)


def _update_task_runtime(
    state: RunCheckpoint,
    *,
    goal_id: str,
    status: str | None = None,
    coverage: tuple = (),
    evidence_gaps: tuple[str, ...] | None = None,
    replan_reason: str | None = None,
) -> None:
    """Append executor facts and project them through the canonical ledger projector."""
    ledger = state.task_runtime
    if ledger is None or not goal_id:
        return
    projector = TaskRuntimeProjector()

    def append(event_type: str, payload: dict | None = None) -> None:
        if state.task_runtime is None:
            return
        event = next_execution_event(
            state.task_runtime,
            event_type,
            goal_id=goal_id,
            payload=payload,
        )
        state.task_runtime = projector.project(state.task_runtime, (event,))
        state.execution_events.append(event)
        state.add_event("plan_runtime_updated", {
            "execution_event": event.model_dump(mode="json"),
            "ledger_revision": state.task_runtime.revision,
        })

    if coverage or evidence_gaps is not None:
        append("coverage_recorded", {
            "coverage": [item.model_dump(mode="json") for item in coverage],
            "evidence_gaps": list(evidence_gaps or ()),
        })
    if replan_reason is not None:
        append("plan_revised", {"replan_reason": replan_reason})
    item = next((item for item in state.goals if item.goal_id == goal_id), None)
    target_event = {
        "running": "goal_activated",
        "active": "goal_activated",
        "completed": "goal_activated",
        "verified": "goal_candidate_complete",
        "candidate_complete": "goal_candidate_complete",
        "blocked": "goal_blocked",
    }.get(status or "")
    if target_event is not None and item is not None:
        target_status = {
            "goal_activated": "active",
            "goal_candidate_complete": "candidate_complete",
            "goal_blocked": "blocked",
        }[target_event]
        if item.status != target_status:
            append(target_event, {"evidence_gaps": list(evidence_gaps or item.evidence_gaps)})


def _admit_untrusted_observation(
    state: RunCheckpoint,
    *,
    ref_id: str,
    provenance: str,
    summary: str,
    payload: dict | None = None,
) -> None:
    """Record provider output as an observation, never as an instruction."""
    from personal_agent.planning.agentic import ContextAdmission

    state.context_inventory = ContextAdmission.admit_observation(
        state.context_inventory,
        ref_id=ref_id,
        kind="provider_observation",
        provenance=provenance,
        summary=summary,
        payload=payload,
    )
    state.add_event("context_admitted", {
        "ref_id": ref_id,
        "provenance": provenance,
        "trust_tier": "untrusted",
        "admitted_as_instruction": False,
    })


def _reserve_provider_call(state: RunCheckpoint) -> None:
    task = state.task_contract
    if task is not None and state.provider_call_count >= task.constraints.max_provider_calls:
        raise RuntimeError("Task provider-call budget is exhausted.")
    state.provider_call_count += 1


# Staged ask execution. The ask flow is split across retrieve→compose→verify
# step nodes that now do real, bounded work: retrieve runs query understanding +
# multi-source recall + context assembly (the ~18s pass), compose generates from
# the assembled ContextPack, verify runs verification + web fallback + annotate.
# The run-scoped AskRunContext threads the large payload (evidence/context_pack)
# between ask steps via deps.ask_run_context_store. The store persists a durable
# artifact payload, so only summary counts go into RunCheckpoint and compose /
# verify can recover without bloating LangGraph checkpoints.


_DELETE_CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "note_id": {"type": ["string", "null"]},
    },
    "required": ["thought", "note_id"],
    "additionalProperties": False,
}

_SOLIDIFY_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "selected_turn_ids": {"type": "array", "items": {"type": "string"}},
        "title": {"type": "string"},
        "content": {"type": "string"},
    },
    "required": ["thought", "selected_turn_ids", "title", "content"],
    "additionalProperties": False,
}

# ===================================================================
# Phase 2: step execution loop nodes (step-level checkpointing)
# ===================================================================


def _node_prepare_invocation_batch(state: RunCheckpoint) -> dict:
    """Sort execution steps and initialise execution state."""
    if not state.invocation_batch.invocations:
        logger.info("prepare_invocation_batch: no steps to execute")
        state.invocation_batch.aborted = True
        return {"invocation_batch": state.invocation_batch}

    # Topologically sort steps
    sorted_steps = _topological_sort_steps(state.invocation_batch.invocations)
    state.invocation_batch = InvocationBatchState(
        invocations=sorted_steps,
        current_step_index=0,
        results=state.invocation_batch.results or {},
        aborted=False,
        retry_counts=state.invocation_batch.retry_counts or {},
    )

    state.add_event("step_started", {
        "step_id": "__steps__",
        "description": f"开始执行 {len(sorted_steps)} 个步骤",
    })
    logger.info(
        "prepare_invocation_batch run_id=%s steps=%d",
        state.run_id, len(sorted_steps),
    )
    return {
        "invocation_batch": state.invocation_batch,
        "events": state.events,
    }


def _node_select_next_step(state: RunCheckpoint) -> dict:
    """Find the next unexecuted step and set current_step_index.

    Skips steps with status 'skipped' or 'completed'.
    Returns with updated current_step_index or leaves it unchanged
    when no more steps remain (checked by the conditional edge).
    """
    for i, sd in enumerate(state.invocation_batch.invocations):
        if sd.status in ("planned",):
            state.invocation_batch.current_step_index = i
            sd.status = "running"
            _update_task_runtime(state, goal_id=sd.goal_id, status="running")
            state.add_event("step_started", {
                "step_id": sd.step_id,
                "action_type": sd.action_type,
                "description": sd.description,
            })
            logger.info(
                "select_next_step run_id=%s step=%s index=%d",
                state.run_id, sd.step_id, i,
            )
            return {
                "invocation_batch": state.invocation_batch,
                "events": state.events,
            }

    # Submit all independent work before polling child runs. Remote subagents
    # can progress while the parent executes the remaining ready actions.
    step_count = len(state.invocation_batch.invocations)
    for offset in range(1, step_count + 1):
        i = (state.invocation_batch.current_step_index + offset) % step_count
        sd = state.invocation_batch.invocations[i]
        if sd.status == "submitted":
            state.invocation_batch.current_step_index = i
            sd.status = "running"
            return {"invocation_batch": state.invocation_batch}

    # No more steps
    logger.info("select_next_step run_id=%s: no more steps", state.run_id)
    return {}


def _node_execute_step(state: RunCheckpoint, *, deps: StepExecutionContext) -> dict:
    """Dispatch a single execution step.  Raises on failure; retry/replan handled
    by the handle_step_result node.

    Idempotency: if a tool_call step already has a result in results,
    skip execution.

    ReAct steps are *not* dispatched here: the state is seeded and the
    StepExecutionGraph routes into ReactGraph. Tool calls are prepared as LangChain
    messages so the appropriate subgraph ``ToolGateway`` performs execution.
    """
    if state.invocation_batch.current_step_index >= len(state.invocation_batch.invocations):
        return {}

    sd = state.invocation_batch.invocations[state.invocation_batch.current_step_index]
    step = sd
    _prepare_entry_tool_input(sd, step, state)
    _persist_step_artifact(
        state,
        sd,
        deps,
        phase="input",
        payload={
            "procedure_id": step.procedure_id,
            "procedure_version": step.procedure_version,
            "step_id": step.step_id,
            "action_type": step.action_type,
            "tool_name": step.tool_name,
            "agent_id": step.agent_id,
            "tool_input": step.tool_input,
            "task_id": step.goal_id,
            "task_input": step.task_input,
        },
    )

    # Idempotency: skip side-effect steps that already ran
    if step.action_type == "tool_call" and step.tool_name:
        idem_key = step.step_id
        if idem_key in state.invocation_batch.results:
            logger.info(
                "Skipping already-executed tool_call step %s (idempotent)",
                step.step_id,
            )
            sd.status = "completed"
            state.add_event("step_completed", {
                "step_id": step.step_id,
                "result_summary": "跳过（已执行）",
            })
            return {
                "invocation_batch": state.invocation_batch,
                "events": state.events,
            }

    resolved_spec = _resolved_spec_for_step(state, step)

    # ---- ReAct branch: consume the already resolved scope ----
    if getattr(step, "execution_mode", "deterministic") == "react":
        if resolved_spec is None:
            return _fail_current_step(
                state,
                step,
                RuntimeError("ReAct dispatch requires a ResolvedActionSpec."),
                deps=deps,
            )
        state.react = ReactSubState(
            step_id=step.step_id,
            max_iterations=min(step.max_iterations, _REACT_MAX_ITERATIONS_CAP),
            allowed_tools=list(step.allowed_tools),
            status="running",
        )
        logger.info(
            "Seeded ReAct state for step %s (max_iter=%d, tools=%s)",
            step.step_id, state.react.max_iterations, state.react.allowed_tools,
        )
        return {
            "invocation_batch": state.invocation_batch,
            "react": state.react,
            "events": state.events,
        }

    if step.action_type == "tool_call":
        if resolved_spec is None:
            return _fail_current_step(
                state,
                step,
                RuntimeError("Tool dispatch requires a ResolvedActionSpec."),
                deps=deps,
            )
        if not step.tool_name:
            return _fail_current_step(
                state,
                step,
                ValueError("tool_call step missing tool_name"),
                deps=deps,
            )
        from personal_agent.planning.memory_admission import MemoryAdmissionGate

        admission = MemoryAdmissionGate().evaluate(state.task_contract, tool_name=step.tool_name)
        state.add_event("memory_admission", {
            "step_id": step.step_id,
            "tool_name": step.tool_name,
            **admission.model_dump(mode="json"),
        })
        if admission.status == "denied":
            return _fail_current_step(
                state,
                step,
                PermissionError(admission.reason),
                deps=deps,
            )
        if admission.status == "requires_confirmation" and state.confirmed_step_id != step.step_id:
            state.pending_confirmation = InteractionRequest(
                kind="confirmation_required",
                action_type="memory_admission",
                step_id=step.step_id,
                title="确认知识变更",
                summary=admission.reason,
                description=step.description,
            )
            sd.status = "awaiting_confirmation"
            state.add_event(
                "confirmation_required", state.pending_confirmation.model_dump(mode="json"),
            )
            return {
                "invocation_batch": state.invocation_batch,
                "pending_confirmation": state.pending_confirmation,
                "events": state.events,
            }
        if step.tool_name not in step.allowed_tools:
            return _fail_current_step(
                state,
                step,
                PermissionError(
                    f"Resolved action did not admit deterministic tool {step.tool_name}."
                ),
                deps=deps,
            )
        try:
            _reserve_provider_call(state)
        except Exception as exc:
            return _fail_current_step(state, step, exc, deps=deps)
        return {
            "provider_call_count": state.provider_call_count,
            "tool_messages": [_begin_tool_call(
                state,
                context="invocation_batch",
                tool_name=step.tool_name,
                tool_input=step.tool_input,
                step_id=step.step_id,
                suffix=step.step_id,
            )],
            "tool_tracking": state.tool_tracking,
            "invocation_batch": state.invocation_batch,
            "events": state.events,
        }

    if step.action_type == "agent_call":
        if resolved_spec is None:
            return _fail_current_step(
                state,
                step,
                RuntimeError("Agent dispatch requires a ResolvedActionSpec."),
                deps=deps,
            )
        if not step.agent_id:
            return _fail_current_step(
                state,
                step,
                ValueError("agent_call step missing agent_id"),
                deps=deps,
            )
        expected_ref = f"agent:{step.agent_id}"
        if expected_ref not in resolved_spec.capability_refs:
            return _fail_current_step(
                state,
                step,
                PermissionError(f"Resolved action did not admit agent {step.agent_id}."),
                deps=deps,
            )
        try:
            existing = state.invocation_batch.results.get(step.step_id)
            if not isinstance(existing, dict) or not existing.get("agent_run_id"):
                _reserve_provider_call(state)
            completed = _execute_agent_call_step(step, sd, state, deps)
        except Exception as exc:
            return _fail_current_step(state, step, exc, deps=deps)
        if not completed:
            sd.status = "submitted"
            return {
                "invocation_batch": state.invocation_batch,
                "provider_call_count": state.provider_call_count,
                "events": state.events,
            }
        return _complete_current_step(state, step, deps=deps)

    try:
        _dispatch_step(step, sd, state, deps)
    except Exception as exc:
        return _fail_current_step(state, step, exc, deps=deps)

    return _complete_current_step(state, step, deps=deps)


def _node_consume_step_tool_result(state: RunCheckpoint, *, deps: StepExecutionContext | None = None) -> dict:
    """Consume the latest ToolGateway artifact for a deterministic execution step."""
    if state.invocation_batch.current_step_index >= len(state.invocation_batch.invocations):
        _clear_pending_tool_call(state)
        return _pending_tool_updates(state)
    sd = state.invocation_batch.invocations[state.invocation_batch.current_step_index]
    step = sd
    if state.tool_tracking.active_context != "invocation_batch" or state.tool_tracking.pending_step_id != step.step_id:
        _clear_pending_tool_call(state)
        return _fail_current_step(
            state,
            step,
            RuntimeError("工具返回上下文与当前计划步骤不匹配。"),
            deps=deps,
        )
    artifact = dict(_latest_tool_artifact(state))
    artifact["_step_id"] = step.step_id
    artifact["_goal_id"] = step.goal_id
    tool_call_id = state.tool_tracking.pending_call_id
    state.tool_results.append(artifact)
    state.add_event("tool_result", _tool_result_event_payload(
        state,
        deps=deps,
        context="invocation_batch",
        step_id=step.step_id,
        tool_call_id=tool_call_id,
        artifact=artifact,
    ))
    _record_capability_execution(state, step.step_id, artifact)
    _admit_untrusted_observation(
        state,
        ref_id=f"tool:{tool_call_id or step.step_id}",
        provenance=str(step.tool_name or "tool"),
        summary=_helpers._summarize_result(artifact.get("data")),
        payload={"step_id": step.step_id, "ok": bool(artifact.get("ok"))},
    )
    if deps is not None:
        _log_tool_invocation_event(state, deps, artifact, execution_mode="deterministic")
    _clear_pending_tool_call(state)
    if not artifact.get("ok"):
        return _fail_current_step(
            state,
            step,
            RuntimeError(artifact.get("error") or f"Tool {step.tool_name} returned failure"),
            deps=deps,
        )

    result_data = artifact.get("data") if artifact.get("data") is not None else {"ok": True}
    state.invocation_batch.results[step.step_id] = result_data
    _apply_tool_result_to_state(step, result_data, state)
    if isinstance(result_data, dict) and result_data.get("pending_confirmation"):
        state.pending_confirmation = InteractionRequest(
            kind="confirmation_required",
            step_id=step.step_id,
            action_type="delete_note",
            resource_id=(str(result_data.get("note_id")) if result_data.get("note_id") else None),
            title=str(result_data.get("title") or ""),
            summary=str(result_data.get("summary") or ""),
            description=str(result_data.get("description") or ""),
        )
    else:
        state.pending_confirmation = None
    return _complete_current_step(state, step, deps=deps)


def _fail_current_step(
    state: RunCheckpoint,
    step: "ExecutableInvocation",
    exc: Exception,
    *,
    deps: StepExecutionContext | None = None,
) -> dict:
    sd = state.invocation_batch.invocations[state.invocation_batch.current_step_index]
    err_msg = f"{type(exc).__name__}: {exc}"
    logger.warning("execution step %s failed: %s", step.step_id, err_msg)
    sd.status = "failed"
    sd.retry_count = sd.retry_count + 1
    sd.failure_reason = err_msg
    sd.recoverable = step.on_failure == "retry" and sd.retry_count < sd.max_retries
    state.invocation_batch.retry_counts[step.step_id] = sd.retry_count
    state.errors.append(f"[{step.step_id}] {err_msg}")
    state.add_event("step_failed", {
        "step_id": step.step_id,
        "error": err_msg,
        "on_failure": step.on_failure,
        "retry_count": sd.retry_count,
    })
    _update_task_runtime(
        state,
        goal_id=step.goal_id,
        status="blocked",
        replan_reason=err_msg,
    )
    if deps is not None:
        _persist_step_artifact(
            state,
            sd,
            deps,
            phase="error",
            payload={
                "step_id": step.step_id,
                "error": err_msg,
                "retry_count": sd.retry_count,
            },
        )
    result = {
        "invocation_batch": state.invocation_batch,
        "task_runtime": state.task_runtime,
        "provider_call_count": state.provider_call_count,
        "context_inventory": state.context_inventory,
        "errors": state.errors,
        "events": state.events,
    }
    result.update(_pending_tool_updates(state))
    return result


def _complete_current_step(
    state: RunCheckpoint,
    step: "ExecutableInvocation",
    *,
    deps: StepExecutionContext | None = None,
) -> dict:
    sd = state.invocation_batch.invocations[state.invocation_batch.current_step_index]
    if state.pending_confirmation is not None:
        sd.status = "awaiting_confirmation"
        state.add_event(
            "confirmation_required", state.pending_confirmation.model_dump(mode="json"),
        )
        logger.info("Step %s awaiting confirmation", step.step_id)
        result = {
            "invocation_batch": state.invocation_batch,
            "answer": state.answer,
            "pending_confirmation": state.pending_confirmation,
            "events": state.events,
        }
        result.update(_pending_tool_updates(state))
        return result

    sd.status = "completed"
    _update_task_runtime(
        state,
        goal_id=step.goal_id,
        status="candidate_complete" if step.action_type == "verify" else "active",
    )
    display_output = _step_display_output(step, state.invocation_batch.results.get(step.step_id))
    sd.output_label = display_output.get("output_label", "")
    sd.output_title = display_output.get("output_title", "")
    sd.output_preview = display_output.get("output_preview", "")
    if deps is not None:
        _persist_step_artifact(
            state,
            sd,
            deps,
            phase="output",
            payload={
                "step_id": step.step_id,
                "status": "completed",
                "result": state.invocation_batch.results.get(step.step_id),
                "answer": state.answer,
                "citations": [
                    citation.model_dump(mode="json")
                    if hasattr(citation, "model_dump")
                    else citation
                    for citation in state.citations
                ],
            },
        )
    completion_payload = {
        "step_id": step.step_id,
        "description": step.description,
        "result_summary": _helpers._summarize_result(state.invocation_batch.results.get(step.step_id)),
    }
    completion_payload.update(display_output)
    state.add_event("step_completed", completion_payload)
    if step.action_type == "verify":
        state.add_event("verification_completed", {
            "step_id": step.step_id,
            "goal_id": step.goal_id,
            "output_contract": step.output_contract,
        })
    result = {
        "invocation_batch": state.invocation_batch,
        "task_runtime": state.task_runtime,
        "provider_call_count": state.provider_call_count,
        "context_inventory": state.context_inventory,
        "answer": state.answer,
        "citations": state.citations,
        "matches": state.matches,
        "pending_confirmation": state.pending_confirmation,
        "events": state.events,
    }
    result.update(_pending_tool_updates(state))
    return result


def _persist_step_artifact(
    state: RunCheckpoint,
    sd: ExecutableInvocation,
    deps: StepExecutionContext,
    *,
    phase: str,
    payload: dict,
) -> None:
    artifact_id = f"step:{state.run_id}:{sd.step_id}:{phase}"
    try:
        deps.execution_artifact_store.put_artifact(
            artifact_id=artifact_id,
            run_id=state.run_id,
            step_id=sd.step_id,
            kind=f"step_{phase}",
            payload=payload,
            schema_version=1,
            summary=_helpers._summarize_result(payload),
            created_by_step=sd.step_id,
            user_id=state.user_id,
        )
    except Exception:
        logger.exception(
            "Failed to persist step artifact run_id=%s step=%s phase=%s",
            state.run_id,
            sd.step_id,
            phase,
        )
        return
    if phase == "input":
        sd.input_artifact_id = artifact_id
    elif phase == "output":
        sd.output_artifact_id = artifact_id
    elif phase == "error":
        sd.error_artifact_id = artifact_id
    state.add_event(
        "artifact_written",
        {
            "artifact_id": artifact_id,
            "kind": f"step_{phase}",
            "step_id": sd.step_id,
        },
    )


def _record_capability_execution(
    state: RunCheckpoint,
    step_id: str,
    artifact: dict,
) -> None:
    """Link the concrete gateway result back to its admitted resolution."""
    for event in reversed(state.events):
        if event.type != "capability_resolution":
            continue
        payload = event.payload
        if not isinstance(payload, dict) or payload.get("step_id") != step_id:
            continue
        state.add_event("capability_execution", {
            "scope_id": payload.get("scope_id", ""),
            "resolution_id": payload.get("resolution_id", ""),
            "step_id": step_id,
            "lifecycle_state": "executed" if artifact.get("ok") else "failed",
            "tool_name": state.tool_tracking.pending_tool_name,
            "ok": bool(artifact.get("ok")),
        })
        return


def _step_display_output(step, result_data: object) -> dict[str, str]:
    if not isinstance(result_data, dict):
        return {}
    if step.action_type == "compose" and result_data.get("answer"):
        return {
            "output_label": "生成草稿",
            "output_preview": str(result_data["answer"])[:800],
        }
    if step.action_type == "agent_call" and result_data.get("report"):
        return {
            "output_label": "外部 Agent 报告",
            "output_preview": str(result_data["report"])[:800],
        }
    if step.action_type == "tool_call" and step.tool_name == "capture_text":
        preview = str(result_data.get("content_preview") or "").strip()
        if preview:
            return {
                "output_label": "已写入知识",
                "output_title": str(result_data.get("title") or ""),
                "output_preview": preview,
            }
    return {}


def _node_handle_step_success(state: RunCheckpoint, *, deps: StepExecutionContext) -> dict:
    """Post-success: inject dependency outputs into downstream planned steps."""
    if state.invocation_batch.current_step_index >= len(state.invocation_batch.invocations):
        return {}

    sd = state.invocation_batch.invocations[state.invocation_batch.current_step_index]
    step = sd
    result_data = state.invocation_batch.results.get(step.step_id)
    matched_edge = next((
        edge for edge in step.conditional_edges
        if _procedure_condition_matches(result_data, edge.condition)
    ), None)
    if matched_edge is not None and matched_edge.target in {"clarify", "abort"}:
        target = matched_edge.target
        sd.status = "failed"
        sd.failure_reason = (
            f"procedure branch {matched_edge.condition} -> {target}"
        )
        state.invocation_batch.aborted = True
        _skip_step_dependents(step.step_id, state.invocation_batch.invocations)
        state.add_event("procedure_branch_selected", {
            "procedure_id": step.procedure_id,
            "procedure_node_id": step.procedure_node_id,
            "condition": matched_edge.get("condition"),
            "target": target,
        })
        return {"invocation_batch": state.invocation_batch, "events": state.events}

    # Inject resolved note_id into dependent tool_call steps
    if step.action_type == "resolve":
        result_data = state.invocation_batch.results.get(step.step_id)
        if isinstance(result_data, dict) and result_data.get("note_id"):
            _inject_note_id_into_steps(
                step.step_id, str(result_data["note_id"]), state.user_id, state.invocation_batch.invocations,
            )

    # Inject compose draft text into dependent capture_text steps
    if step.action_type == "compose":
        result_data = state.invocation_batch.results.get(step.step_id)
        if isinstance(result_data, dict) and result_data.get("answer"):
            _inject_draft_text_into_steps(
                step.step_id, str(result_data["answer"]), state.user_id, state.invocation_batch.invocations,
            )

    # Inject fetched/extracted artifact text into dependent capture_text steps.
    if step.action_type == "tool_call" and step.tool_name in {"capture_url", "capture_upload", "inspect_artifact"}:
        result_data = state.invocation_batch.results.get(step.step_id)
        if isinstance(result_data, dict) and result_data.get("text"):
            source_type = "link" if step.tool_name == "capture_url" else str(result_data.get("source_type") or "file")
            _inject_capture_text_from_tool_result(
                step.step_id,
                str(result_data["text"]),
                state.user_id,
                source_type,
                state.invocation_batch.invocations,
            )

    logger.info(
        "handle_step_success run_id=%s step=%s",
        state.run_id, step.step_id,
    )
    return {"invocation_batch": state.invocation_batch, "events": state.events}


def _procedure_condition_matches(result: object, condition: str) -> bool:
    if not condition or not isinstance(result, dict):
        return False
    if bool(result.get(condition)):
        return True
    declared = result.get("conditions")
    if isinstance(declared, (list, tuple, set)) and condition in declared:
        return True
    if condition == "no_candidate":
        return result.get("candidate_count") == 0 or result.get("candidates") == []
    return False


def _node_confirm_step(state: RunCheckpoint, *, deps: StepExecutionContext) -> dict:
    """Pause the graph for human confirmation via ``interrupt()``.

    First invocation: ``interrupt()`` pauses the graph and returns an
    ``__interrupt__`` payload from ``graph.invoke()``. On resume (re-entered
    via ``Command(resume=...)``), ``interrupt()`` returns the user's decision
    dict and the node processes the confirm / reject action.
    """
    if state.invocation_batch.current_step_index >= len(state.invocation_batch.invocations):
        return {}

    sd = state.invocation_batch.invocations[state.invocation_batch.current_step_index]
    step = sd
    pending = state.pending_confirmation

    # ---- Build the interrupt payload (presented to the caller) ----
    confirm_payload = {
        "step_id": step.step_id,
        "action_type": pending.action_type if pending else step.action_type,
        "note_id": pending.resource_id if pending else None,
        "title": pending.title if pending else "",
        "summary": pending.summary if pending else "",
        "description": pending.description if pending else "",
        "message": (
            step.description
            or f"确认执行 {pending.action_type if pending else step.action_type} 操作？"
        ),
    }

    # First call pauses the graph; on resume it returns the resume value.
    resume_value = interrupt(confirm_payload)

    # ---- Process the resume decision ----
    decision = "reject"
    if isinstance(resume_value, dict):
        decision = str(resume_value.get("decision", "reject")).lower()

    if decision == "confirm":
        tool_input = dict(step.tool_input or {})
        tool_input["confirmed"] = True
        tool_input.setdefault(
            "idempotency_key",
            f"{state.thread_id}:{state.run_id}:{step.step_id}:confirmed",
        )
        sd.status = "running"
        state.pending_confirmation = None
        state.confirmation_decision = "confirmed"
        state.confirmed_step_id = step.step_id
        state.add_event("confirmation_resumed", {
            "step_id": step.step_id,
            "decision": "confirmed",
        })
        logger.info("Step %s confirmed; dispatching through main ToolGateway", step.step_id)
        return {
            "tool_messages": [_begin_tool_call(
                state,
                context="invocation_batch",
                tool_name=step.tool_name or "",
                tool_input=tool_input,
                step_id=step.step_id,
                suffix=f"{step.step_id}:confirmed",
            )],
            "tool_tracking": state.tool_tracking,
            "invocation_batch": state.invocation_batch,
            "pending_confirmation": None,
            "confirmation_decision": "confirmed",
            "confirmed_step_id": step.step_id,
            "events": state.events,
        }

    # Reject (or unknown decision)
    sd.status = "skipped"
    _skip_step_dependents(step.step_id, state.invocation_batch.invocations)
    state.confirmation_decision = "rejected"
    state.pending_confirmation = None
    if not state.answer:
        state.answer = f"操作已取消：{step.description or (pending.action_type if pending else '')}"

    state.add_event("confirmation_resumed", {
        "step_id": step.step_id,
        "decision": "rejected",
    })
    state.add_event("step_failed", {
        "step_id": step.step_id,
        "error": "用户取消操作",
    })
    logger.info("Step %s rejected by user", step.step_id)
    return {
        "invocation_batch": state.invocation_batch,
        "confirmation_decision": "rejected",
    }


def _node_finalize_invocation_batch(state: RunCheckpoint, *, deps: StepExecutionContext | None = None) -> dict:
    """Compose default answer if none was set, mark execution complete."""
    if not state.answer:
        state.answer = _default_step_answer(state.invocation_batch.invocations)

    state.add_event("invocation_batch_completed", {"answer_candidate": state.answer})
    logger.info(
        "finalize_invocation_batch run_id=%s answer_len=%d trace_items=%d",
        state.run_id, len(state.answer or ""), len(state.execution_trace),
    )
    return {
        "answer": state.answer,
        "events": state.events,
        "updated_at": state.updated_at,
    }


def _prepare_entry_tool_input(sd: ExecutableInvocation, step: "ExecutableInvocation", state: RunCheckpoint) -> None:
    """Fill deterministic workflow tool arguments from the entry/checkpoint state."""
    if getattr(step, "execution_mode", "deterministic") == "react":
        entry_input = state.entry_input
        tool_input = dict(step.tool_input or {})
        tool_input.setdefault("user_id", state.user_id)
        request = step.task_input or (
            (entry_input.text if entry_input is not None else state.entry_text) or ""
        )
        if request.strip():
            tool_input.setdefault("request", request.strip())
        sd.tool_input = tool_input
        step.tool_input = tool_input
        return
    if step.action_type != "tool_call" or not step.tool_name:
        return
    entry_input = state.entry_input
    metadata = dict(entry_input.metadata) if entry_input is not None else {}
    tool_input = dict(step.tool_input or {})
    if step.tool_name == "capture_text":
        tool_input.setdefault("user_id", state.user_id)
        tool_input.setdefault("source_type", str(metadata.get("source_type") or "text"))
        if "text" not in tool_input:
            text = step.task_input or (
                (entry_input.text if entry_input is not None else state.entry_text) or ""
            )
            if text.strip():
                tool_input["text"] = text

    elif step.tool_name == "capture_url":
        if "url" not in tool_input:
            url = metadata.get("url") or _helpers._first_url(
                step.task_input or (
                    (entry_input.text if entry_input is not None else state.entry_text) or ""
                )
            )
            if url:
                tool_input["url"] = str(url)

    elif step.tool_name == "capture_upload":
        file_path = str(metadata.get("file_path") or "")
        if file_path:
            tool_input.setdefault("file_path", file_path)
            tool_input.setdefault(
                "filename",
                str(metadata.get("original_filename") or metadata.get("filename") or Path(file_path).name),
            )
            if "content_type" not in tool_input:
                content_type = metadata.get("content_type")
                if content_type:
                    tool_input["content_type"] = str(content_type)

    elif step.tool_name == "inspect_artifact":
        artifact = (entry_input.artifacts[0] if entry_input is not None and entry_input.artifacts else None)
        if artifact is not None:
            tool_input.setdefault("file_path", artifact.file_path)
            tool_input.setdefault("filename", artifact.filename)
            if artifact.content_type:
                tool_input.setdefault("content_type", artifact.content_type)
            tool_input.setdefault("source_type", artifact.source_type)
        else:
            file_path = str(metadata.get("file_path") or "")
            if file_path:
                tool_input.setdefault("file_path", file_path)
                tool_input.setdefault(
                    "filename",
                    str(metadata.get("original_filename") or metadata.get("filename") or Path(file_path).name),
                )
                if metadata.get("content_type"):
                    tool_input.setdefault("content_type", str(metadata["content_type"]))
                if metadata.get("source_type"):
                    tool_input.setdefault("source_type", str(metadata["source_type"]))
        request = step.task_input or (
            (entry_input.text if entry_input is not None else state.entry_text) or ""
        )
        if request.strip():
            tool_input.setdefault("question", request.strip())

    elif step.tool_name in {"review_digest", "inspect_knowledge_gaps"}:
        tool_input.setdefault("user_id", state.user_id)

    elif step.tool_name == "consolidate_knowledge":
        tool_input.setdefault("user_id", state.user_id)
        topic = step.task_input or (
            (entry_input.text if entry_input is not None else state.entry_text) or ""
        )
        if topic.strip():
            tool_input.setdefault("topic", topic.strip())

    elif step.tool_name == "research_prepare_run":
        tool_input.setdefault("user_id", state.user_id)
        topic = step.task_input or (
            (entry_input.text if entry_input is not None else state.entry_text) or ""
        )
        if topic.strip():
            tool_input.setdefault("topic", topic.strip())
        instructions = metadata.get("instructions")
        if instructions:
            tool_input.setdefault("instructions", str(instructions))
        max_items = metadata.get("max_items")
        if max_items:
            try:
                tool_input.setdefault("max_items", int(max_items))
            except (TypeError, ValueError):
                pass
        else:
            inferred_max_items = _infer_research_max_items(topic)
            if inferred_max_items is not None:
                tool_input.setdefault("max_items", inferred_max_items)
        lookback_hours = metadata.get("lookback_hours")
        if lookback_hours:
            try:
                tool_input.setdefault("lookback_hours", int(lookback_hours))
            except (TypeError, ValueError):
                pass

    elif step.tool_name in {
        "research_initialize_state",
        "research_run_loop",
        "research_synthesize_digest",
        "research_verify_digest",
    }:
        tool_input.setdefault("user_id", state.user_id)
        _inject_research_pipeline_inputs(tool_input, state, metadata)

    elif step.tool_name == "create_research_subscription":
        tool_input.setdefault("user_id", state.user_id)
        request = step.task_input or (
            (entry_input.text if entry_input is not None else state.entry_text) or ""
        )
        if request.strip():
            tool_input.setdefault("request", request.strip())
        target_id = metadata.get("chat_id") or metadata.get("target_id")
        if target_id:
            tool_input.setdefault("target_id", str(target_id))

    sd.tool_input = tool_input
    step.tool_input = tool_input


def _infer_research_max_items(text: str) -> int | None:
    match = re.search(
        r"(?:最多|至多|不超过)[^0-9一二两三四五六七八九十]{0,12}"
        r"([0-9一二两三四五六七八九十]+)\s*(?:条|个|项)",
        text,
    )
    if not match:
        return None
    raw = match.group(1)
    chinese_digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    try:
        value = int(raw)
    except ValueError:
        value = chinese_digits.get(raw)
    if value is None:
        return None
    return min(max(value, 1), 20)


def _inject_research_pipeline_inputs(
    tool_input: dict,
    state: RunCheckpoint,
    metadata: dict,
) -> None:
    if "run_id" not in tool_input:
        run_id = metadata.get("research_run_id") or metadata.get("run_id")
        if run_id:
            tool_input["run_id"] = str(run_id)
        else:
            for result in reversed(list(state.invocation_batch.results.values())):
                if not isinstance(result, dict):
                    continue
                run_id = result.get("run_id")
                if not run_id and isinstance(result.get("run"), dict):
                    run_id = result["run"].get("id")
                if run_id:
                    tool_input["run_id"] = str(run_id)
                    break
    if "max_items" not in tool_input:
        for result in reversed(list(state.invocation_batch.results.values())):
            if isinstance(result, dict) and result.get("max_items"):
                tool_input["max_items"] = int(result["max_items"])
                break


def _apply_tool_result_to_state(step: "ExecutableInvocation", result_data: object, state: RunCheckpoint) -> None:
    if step.tool_name in {"research_synthesize_digest", "research_verify_digest"} and isinstance(result_data, dict):
        answer = str(result_data.get("answer") or "").strip()
        if answer:
            state.answer = answer
        return
    if step.tool_name != "capture_text" or not isinstance(result_data, dict):
        return
    title = str(result_data.get("title") or "").strip()
    if title and not state.answer:
        state.answer = f"已收进知识库：{title}"


def _inject_capture_text_from_tool_result(
    source_step_id: str,
    text: str,
    user_id: str,
    source_type: str,
    steps: list,
) -> None:
    by_id = {s.step_id: s for s in steps}

    def depends_on_source(step) -> bool:
        pending = list(step.depends_on)
        visited: set[str] = set()
        while pending:
            step_id = pending.pop()
            if step_id == source_step_id:
                return True
            if step_id in visited:
                continue
            visited.add(step_id)
            parent = by_id.get(step_id)
            if parent is not None:
                pending.extend(parent.depends_on)
        return False

    for s in steps:
        if s.status != "planned":
            continue
        if (
            depends_on_source(s)
            and s.action_type == "tool_call"
            and s.tool_name == "capture_text"
        ):
            if not s.tool_input:
                s.tool_input = {}
            s.tool_input["text"] = text
            s.tool_input["user_id"] = user_id
            s.tool_input["source_type"] = source_type

# ---------------------------------------------------------------------------
# Step dispatch
# ---------------------------------------------------------------------------

def _dispatch_step(
    step: "ExecutableInvocation",
    sd: ExecutableInvocation,
    state: RunCheckpoint,
    deps: StepExecutionContext,
) -> None:
    """Execute a single step by action_type. Raises on failure.

    The graph-native executor operates on ``RunCheckpoint`` so every step
    update can be checkpointed.
    """
    results: dict = state.invocation_batch.results

    if step.action_type == "retrieve":
        result_data = _execute_retrieve_step(step, state, deps)
        results[step.step_id] = result_data
        _apply_declared_result_to_state(step, result_data, state)

    elif step.action_type == "tool_call":
        raise RuntimeError("tool_call must be executed by the main graph ToolGateway")

    elif step.action_type == "resolve":
        result_data = _execute_resolve_step(step, state, deps)
        results[step.step_id] = result_data
        _apply_declared_result_to_state(step, result_data, state)

    elif step.action_type == "commit":
        _execute_commit_step(step, sd, state, deps)

    elif step.action_type == "compose":
        answer = _execute_compose_step(step, state, deps)
        state.answer = answer
        results[step.step_id] = {"answer": answer, "draft": True}
        if answer:
            state.add_event("draft_ready", {
                "step_id": step.step_id,
                "draft_text": answer,
            })

    elif step.action_type == "verify":
        _execute_verify_step(step, state, deps)

    elif step.action_type == "repair":
        _execute_repair_step(step, state, deps)

    else:
        raise ValueError(f"未知的 action_type: {step.action_type}")


def _apply_declared_result_to_state(
    step: "ExecutableInvocation",
    result_data: object,
    state: RunCheckpoint,
) -> None:
    """Project a step result through its declared output contract."""
    if step.output_contract not in {"Answer", "Response"} or not isinstance(result_data, dict):
        return
    answer = str(result_data.get("answer") or "").strip()
    if answer:
        state.answer = answer


def _execute_commit_step(
    step,
    sd: ExecutableInvocation,
    state: RunCheckpoint,
    deps: StepExecutionContext,
) -> None:
    """Convert a read-only exploration proposal into a confirmed gateway action."""
    proposed: dict | None = None
    for result in reversed(list(state.invocation_batch.results.values())):
        if not isinstance(result, dict):
            continue
        candidate = result.get("proposed_commit")
        if isinstance(candidate, dict):
            proposed = candidate
            break
    if proposed is None:
        state.invocation_batch.results[step.step_id] = {
            "committed": False,
            "reason": "探索阶段未提出可执行的状态变更。",
        }
        return

    tool_name = str(proposed.get("tool_name") or "").strip()
    tool_input = proposed.get("tool_input")
    if not isinstance(tool_input, dict):
        raise ValueError("Proposed commit tool_input must be an object.")

    resolved_spec = _resolved_spec_for_step(state, step)
    if resolved_spec is None:
        raise PermissionError("Commit action has no governed capability scope.")
    if not tool_name or tool_name not in step.allowed_tools:
        raise PermissionError("Capability resolution did not admit the proposed commit tool.")

    sd.tool_name = tool_name
    sd.tool_input = dict(tool_input)
    step.tool_name = tool_name
    step.tool_input = dict(tool_input)

    state.pending_confirmation = InteractionRequest(
        kind="confirmation_required",
        step_id=step.step_id,
        action_type="commit",
        title="确认状态变更",
        summary=f"将执行 {tool_name}",
        description=step.description,
    )
    state.invocation_batch.results[step.step_id] = {
        "committed": False,
        "proposed_tool": tool_name,
        "pending_confirmation": True,
    }


def _execute_agent_call_step(
    step: "ExecutableInvocation",
    sd: ExecutableInvocation,
    state: RunCheckpoint,
    deps: StepExecutionContext,
) -> bool:
    """Submit or poll one child run; return whether it reached completion."""
    metadata = state.entry_input.metadata if state.entry_input is not None else {}
    task_input = step.task_input or state.entry_text or step.description
    task_payload: dict[str, object] = {"topic": task_input}
    subtask = step.subtask
    if subtask is not None:
        task_payload["subtask_contract"] = subtask.model_dump(mode="json")
        task_payload["context_projection_ids"] = list(subtask.context_projection_ids)
        task_payload["context_projection"] = [
            item.model_dump(mode="json")
            for item in state.context_inventory.selected(category="evidence")
        ]
    for key in ("report_type", "report_source", "tone"):
        if metadata.get(key):
            task_payload[key] = str(metadata[key])
    max_search_results = metadata.get("max_search_results")
    if max_search_results:
        try:
            task_payload["max_search_results"] = int(max_search_results)
        except (TypeError, ValueError):
            pass
    task = AgentTask(
        task_text=task_input,
        task_type="research",
        input=task_payload,
        metadata={
            "procedure_id": step.procedure_id,
            "step_id": step.step_id,
            "subtask_id": subtask.subtask_id if subtask is not None else "",
            "expected_artifact_contract": (
                subtask.expected_artifact_contract if subtask is not None else ""
            ),
        },
    )
    context = AgentGatewayContext(
        user_id=state.user_id,
        session_id=state.session_id,
        run_id=state.run_id,
        thread_id=state.thread_id,
        task_id=state.task_contract.task_id if state.task_contract else None,
        goal_id=step.goal_id,
        action_id=step.step_id,
        source_platform=(
            state.entry_input.source_platform
            if state.entry_input is not None
            else ""
        ),
    )
    previous = state.invocation_batch.results.get(step.step_id)
    saved = previous if isinstance(previous, dict) else {}
    agent_run_id = str(saved.get("agent_run_id") or "")
    if agent_run_id:
        run = deps.agent_gateway.poll(agent_run_id, context)
    else:
        run = deps.agent_gateway.submit(step.agent_id or "", task, context)
        state.add_event("agent_run_submitted", {
            "step_id": step.step_id,
            "agent_id": step.agent_id,
            "agent_run_id": run.definition.agent_run_id,
            "task_type": task.task_type,
            "subtask_id": subtask.subtask_id if subtask is not None else "",
        })

    seen_event_ids = {str(item) for item in saved.get("seen_event_ids", [])}
    for event in run.events:
        if event.event_id in seen_event_ids:
            continue
        seen_event_ids.add(event.event_id)
        state.add_event("agent_run_event", {
            "step_id": step.step_id,
            "agent_id": run.definition.agent_id,
            "agent_run_id": run.definition.agent_run_id,
            "agent_event_type": event.type,
            "payload": event.payload,
        })

    projection = run.projection
    artifacts = run.artifact_index.artifacts
    if projection.status in {"created", "queued", "running", "waiting", "blocked_approval"}:
        state.invocation_batch.results[step.step_id] = {
            "provider": run.definition.agent_id,
            "agent_run_id": run.definition.agent_run_id,
            "external_task_id": projection.external_task_id,
            "status": projection.status,
            "seen_event_ids": sorted(seen_event_ids),
        }
        state.add_event("agent_run_waiting", {
            "step_id": step.step_id,
            "agent_id": run.definition.agent_id,
            "agent_run_id": run.definition.agent_run_id,
            "status": projection.status,
        })
        return False
    if projection.status in {"cancel_requested", "cancelling", "cancelled", "failed", "timed_out"}:
        raise RuntimeError(
            projection.error
            or f"child agent run {run.definition.agent_run_id} ended with {projection.status}"
        )

    output_text = str(
        projection.result.get("report")
        or projection.result.get("answer")
        or projection.result.get("output")
        or next((artifact.content for artifact in artifacts if artifact.content), "")
    )
    for artifact in artifacts:
        _persist_step_artifact(
            state,
            sd,
            deps,
            phase=f"agent_artifact_{artifact.artifact_id}",
            payload={
                "agent_run_id": artifact.agent_run_id,
                "artifact_id": artifact.artifact_id,
                "kind": artifact.kind,
                "content": artifact.content,
                "payload": artifact.payload,
                "producer_verification_status": artifact.producer_verification_status,
            },
        )
        _admit_untrusted_observation(
            state,
            ref_id=f"agent:{artifact.artifact_id}",
            provenance=run.definition.agent_id,
            summary=str(artifact.content)[:2000],
            payload={
                "agent_run_id": run.definition.agent_run_id,
                "producer_verification_status": artifact.producer_verification_status,
            },
        )
    state.add_event("agent_run_completed", {
        "step_id": step.step_id,
        "agent_id": run.definition.agent_id,
        "agent_run_id": run.definition.agent_run_id,
        "status": projection.status,
        "external_task_id": projection.external_task_id,
        "artifact_count": len(artifacts),
        "artifact_producer_verification_statuses": [
            artifact.producer_verification_status
            for artifact in artifacts
        ],
    })
    state.invocation_batch.results[step.step_id] = {
        "provider": run.definition.agent_id,
        "agent_run_id": run.definition.agent_run_id,
        "external_task_id": projection.external_task_id,
        "status": projection.status,
        "report": output_text,
        "answer": output_text,
        "artifacts": [
            {
                "artifact_id": artifact.artifact_id,
                "kind": artifact.kind,
                "content": artifact.content,
                "producer_verification_status": artifact.producer_verification_status,
            }
            for artifact in artifacts
        ],
        "metadata": dict(projection.result.get("metadata") or {}),
        "seen_event_ids": sorted(seen_event_ids),
    }
    return True


def _resolved_spec_for_step(state: RunCheckpoint, step) -> ResolvedActionSpec | None:
    exact = next(
        (item for item in state.resolved_action_specs if item.action_id == step.step_id),
        None,
    )
    if exact is not None:
        return exact
    return next(
        (item for item in state.resolved_action_specs if item.goal_id == step.goal_id),
        None,
    )


def _execute_retrieve_step(step, state: RunCheckpoint, deps: StepExecutionContext) -> object:
    question = step.tool_input.get("question") if step.tool_input else None
    question = str(question or step.task_input or state.entry_text or step.description or "")

    if _step_requires_resource(step, domain="conversation", resource_type="thread", operation="read"):
        return {
            "answer": _summarize_thread(state, deps),
            "retrieval_kind": "thread_summary",
        }

    # For the ask flow, the retrieve step runs query understanding +
    # multi-source recall + context assembly — the ~18s pass — and stashes the
    # run-scoped AskRunContext for the downstream compose/verify steps. The
    # running "retrieve" step honestly reflects that latency to the user.
    if _step_requires_resource(
        step,
        domain="knowledge",
        resource_type="note",
        operation="search",
    ):
        from personal_agent.orchestration.orchestration_nodes._entry import _entry_conversation_messages

        conversation = _entry_conversation_messages(
            state,
            exclude_latest=True,
            deps=deps.conversation,
        )
        ask_service = deps.ask_service_factory()
        ctx = ask_service.build_run_context(
            question,
            state.user_id,
            state.session_id,
            conversation_messages=conversation,
        )
        ask_service.run_retrieval_stage(ctx)
        deps.ask_run_context_store.put(state.run_id, ctx)
        from personal_agent.kernel.contracts.agentic import ContextItem

        evidence_items = tuple(
            ContextItem(
                item_id=str(citation.evidence_id or citation.note_id or index),
                category="evidence",
                kind="retrieved_evidence",
                provenance=str(citation.source_type or "knowledge"),
                trust="evidence",
                summary=str(citation.snippet or "")[:1000],
                admission="admitted",
            )
            for index, citation in enumerate(ctx.selected_citations or [], 1)
        )
        state.context_inventory = state.context_inventory.with_items(*evidence_items)
        state.add_event("context_admitted", {
            "step_id": step.step_id,
            "trust_tier": "evidence",
            "count": len(evidence_items),
            "admitted_as_instruction": False,
        })
        return {
            "answer": "",
            "evidence_count": len(ctx.context_pack.evidence if ctx.context_pack else []),
            "citation_count": len(ctx.selected_citations or []),
            "match_count": len(ctx.selected_matches or []),
            "ask_staged": True,
        }

    result = deps.graph_store.ask(question, state.user_id)
    if result.enabled and result.answer:
        return {
            "answer": result.answer,
            "entity_names": result.entity_names,
            "relation_facts": result.relation_facts,
            "related_episode_uuids": result.related_episode_uuids,
        }
    return {"answer": "", "entity_names": [], "relation_facts": [], "hint": "graph disabled or empty"}


def _execute_resolve_step(step, state: RunCheckpoint, deps: StepExecutionContext) -> object:
    if step.llm_decision_node != "delete_target_resolve":
        raise ValueError(f"unsupported deterministic decision node: {step.llm_decision_node or 'missing'}")
    user_id = state.user_id
    original_query = step.task_input or state.entry_text or ""

    candidates: list[dict] = []

    # 1. Graph episode UUID mapping
    for sid, data in state.invocation_batch.results.items():
        if not isinstance(data, dict):
            continue
        episode_uuids = data.get("related_episode_uuids")
        if isinstance(episode_uuids, list) and episode_uuids:
            str_uuids = [str(u) for u in episode_uuids if u]
            if str_uuids:
                try:
                    matched = deps.memory.find_by_graph_episodes(user_id, str_uuids)
                    for note in matched:
                        candidates.append({
                            "note_id": note.id, "title": note.body.title,
                            "summary": note.body.summary, "source": "graph_episode",
                        })
                except Exception:
                    logger.exception("Episode UUID lookup failed in resolve")

    # 2. Let the LLM select a local candidate when graph mapping is unavailable.
    if not candidates and original_query:
        candidates = _select_local_delete_candidate_with_llm(
            original_query, user_id, deps,
        )

    if not candidates:
        state.answer = "未找到可删除的知识笔记，请提供更具体的标题或内容描述。"
        raise RuntimeError(state.answer)

    best = candidates[0]
    return {
        "note_id": best["note_id"],
        "title": best.get("title"),
        "summary": best.get("summary"),
        "source": best.get("source"),
        "candidates": candidates,
    }


def _select_local_delete_candidate_with_llm(
    delete_request: str, user_id: str, deps: StepExecutionContext,
) -> list[dict]:
    try:
        notes = deps.memory.list_notes(user_id, include_chunks=False)
    except Exception:
        logger.exception("Local note listing failed in resolve")
        return []
    if not notes:
        return []

    selectable_notes = list(reversed(notes))[:100]
    candidate_by_id = {
        note.id: {
            "note_id": note.id,
            "title": note.body.title,
            "summary": note.body.summary,
            "source": "llm_candidate_selection",
        }
        for note in selectable_notes
    }
    prompt_candidates = [
        {
            "note_id": note.id,
            "title": note.body.title[:200],
            "summary": (note.body.summary or "")[:300],
        }
        for note in selectable_notes
    ]
    prompt = render_prompt(
        "delete_candidate_resolve.user",
        delete_request=delete_request,
        prompt_candidates=json.dumps(prompt_candidates, ensure_ascii=False),
    )
    raw = _helpers._structured_llm_respond(
        "delete_candidate_resolve",
        prompt,
        deps,
        _DELETE_CANDIDATE_SCHEMA,
    )
    parsed = _helpers._react_parse_response(raw) if raw else None
    note_id = parsed.get("note_id") if isinstance(parsed, dict) else None
    if note_id is None and isinstance(parsed, dict) and isinstance(parsed.get("result"), dict):
        note_id = parsed["result"].get("note_id")
    if isinstance(note_id, str) and note_id in candidate_by_id:
        return [candidate_by_id[note_id]]
    return []


def _execute_compose_step(step, state: RunCheckpoint, deps: StepExecutionContext) -> str:
    context_parts: list[str] = []
    for sid, data in state.invocation_batch.results.items():
        if isinstance(data, dict):
            if data.get("text"):
                context_parts.append(str(data["text"]))
            if data.get("answer"):
                context_parts.append(str(data["answer"]))
            if data.get("entity_names"):
                context_parts.append("实体: " + ", ".join(str(n) for n in data["entity_names"] if n))

    context = "\n".join(context_parts) if context_parts else "暂无检索结果。"

    thread_summary = next((
        str(data.get("answer") or "")
        for data in reversed(list(state.invocation_batch.results.values()))
        if isinstance(data, dict) and data.get("retrieval_kind") == "thread_summary"
    ), "")
    if thread_summary:
        return thread_summary

    if _step_requires_resource(step, domain="conversation", resource_type="thread"):
        prior = next((
            item.summary
            for item in reversed(state.latest_observations)
            if item.goal_id == step.goal_id and item.kind == "action_result" and item.summary
        ), "")
        if prior:
            return prior

    if step.tool_input and step.tool_input.get("question"):
        question = str(step.tool_input["question"])
    else:
        question = step.task_input or step.description or "根据已有信息生成回答"

    if step.llm_decision_node == "solidify_draft":
        dialogue = _helpers._format_solidify_candidate_context(state.messages)
        if not dialogue:
            # No prior conversation to distill — solidify is only meaningful over
            # existing dialogue. Don't fall back to the bare request (that would
            # fabricate a note from the instruction itself). Fail fast with an
            # actionable message; the run still reaches a terminal event.
            raise RuntimeError(
                "没有可固化的历史对话内容。固化需要先有对话结论，"
                "请先提问或记录内容，再要求固化。"
            )
        solidify_prompt = render_prompt(
            "solidify_draft.user",
            entry_text=step.task_input or state.entry_text,
            dialogue=dialogue,
        )
        try:
            raw_answer = _helpers._structured_llm_respond(
                "solidify_draft",
                solidify_prompt,
                deps,
                _SOLIDIFY_DRAFT_SCHEMA,
                max_tokens=900,
            )
            parsed_answer = _helpers._react_parse_response(raw_answer) if raw_answer else None
            if isinstance(parsed_answer, dict):
                answer = _helpers._solidify_note_text(raw_answer)
                if not answer:
                    title = str(parsed_answer.get("title") or "").strip()
                    body = str(parsed_answer.get("content") or "").strip()
                    answer = f"{title}\n\n{body}" if title and body else body or title
            else:
                answer = None
        except Exception:
            logger.exception("Solidify compose step %s failed", step.step_id)
            answer = None
        if not answer:
            raise RuntimeError("模型未生成符合本次固化范围的知识草稿，未写入知识库。")
        return answer

    # ask flow: the retrieve step assembled the ContextPack onto the run-scoped
    # AskRunContext. Compose runs pure generation from it, then backfills
    # citations/matches onto the state. No second retrieval.
    workspace_payload = _latest_workspace_ask_result(state)
    if workspace_payload is not None:
        state.citations = _workspace_citations_from_payload(workspace_payload)
        state.matches = _workspace_matches_from_payload(workspace_payload)
        return str(workspace_payload.get("answer") or "证据不足，无法基于当前知识库回答。")

    ctx = deps.ask_run_context_store.get(state.run_id)
    if ctx is not None:
        task_evidence = (
            list(state.context_inventory.selected(category="evidence"))
            if state.context_inventory is not None else []
        )
        mutation_evidence = [item for item in task_evidence if item.kind == "mutation_receipt"]
        if mutation_evidence:
            from personal_agent.kernel.models import Citation

            state.citations = [
                Citation(
                    note_id=str(item.payload.get("note_id") or item.item_id),
                    title=str(item.payload.get("title") or "当前任务知识"),
                    snippet=item.summary,
                    source_type="task_artifact",
                    evidence_id=item.item_id,
                )
                for item in mutation_evidence
            ]
            state.matches = [
                {
                    "id": str(item.payload.get("note_id") or item.item_id),
                    "title": str(item.payload.get("title") or "当前任务知识"),
                    "summary": item.summary,
                }
                for item in mutation_evidence
            ]
            evidence_text = "\n".join(item.summary for item in mutation_evidence if item.summary)
            return f"根据当前任务刚写入的知识：{evidence_text}"
        ask_service = deps.ask_service_factory()
        ask_service.run_generation_stage(ctx)
        deps.ask_run_context_store.put(state.run_id, ctx)
        state.citations = list(ctx.selected_citations or [])
        state.matches = [
            {"id": m.id, "title": m.body.title, "summary": m.body.summary}
            for m in (ctx.selected_matches or [])
        ]
        return ctx.answer

    try:
        ask_result = deps.execute_ask(
            question,
            state.user_id,
            state.session_id,
        )
        state.citations = list(ask_result.citations or [])
        state.matches = [
            {"id": m.id, "title": m.body.title, "summary": m.body.summary}
            for m in (ask_result.matches or [])
        ]
        return ask_result.answer
    except Exception:
        logger.exception("Compose step %s failed", step.step_id)
        return f"根据已有信息：{context[:500]}"


def _workspace_ask_step_result(answer) -> dict[str, object]:
    payload = answer.model_dump(mode="json")
    return {
        "answer": answer.answer,
        "workspace_ask": True,
        "workspace_answer": payload,
        "grounding_status": answer.grounding_status,
        "evidence_count": len(answer.citations),
        "citation_count": len(answer.citations),
        "claim_ids": list(answer.selected_claim_ids),
        "conflicted_claim_ids": list(answer.conflicted_claim_ids),
        "evidence_span_ids": [
            citation.evidence_span_id for citation in answer.citations
        ],
        "evidence_block_ids": [
            citation.evidence_block_id for citation in answer.citations
        ],
        "artifact_ids": [
            citation.artifact_id for citation in answer.citations
        ],
    }


def _latest_workspace_ask_result(state: RunCheckpoint) -> dict[str, object] | None:
    for data in reversed(list(state.invocation_batch.results.values())):
        if not isinstance(data, dict) or not data.get("workspace_ask"):
            continue
        payload = data.get("workspace_answer")
        if isinstance(payload, dict):
            return payload
        return data
    return None


def _workspace_citations_from_payload(payload: dict[str, object]) -> list[Citation]:
    citations: list[Citation] = []
    for index, raw in enumerate(payload.get("citations") or [], 1):
        if not isinstance(raw, dict):
            continue
        citations.append(Citation(
            note_id=str(raw.get("artifact_id") or ""),
            title=f"Workspace evidence {index}",
            snippet=str(raw.get("quote") or ""),
            source_type="workspace",
            evidence_id=str(raw.get("evidence_span_id") or ""),
            source_ref=str(raw.get("artifact_id") or ""),
            source_span=str(raw.get("locator") or ""),
            element_ids=[str(item) for item in (raw.get("claim_ids") or [])],
        ))
    return citations


def _workspace_matches_from_payload(payload: dict[str, object]) -> list[dict[str, object]]:
    claim_ids = [str(item) for item in (payload.get("selected_claim_ids") or [])]
    summaries = [str(item) for item in (payload.get("claim_summaries") or [])]
    matches: list[dict[str, object]] = []
    for index, claim_id in enumerate(claim_ids):
        summary = summaries[index] if index < len(summaries) else claim_id
        matches.append({
            "id": claim_id,
            "title": summary[:48],
            "summary": summary,
            "source": "workspace_claim",
        })
    return matches


def _summarize_thread(state: RunCheckpoint, deps: StepExecutionContext) -> str:
    """Load and summarize a conversation resource admitted by the task contract."""
    entry_input = state.entry_input
    if entry_input is None:
        return "未收到可总结的内容。"

    messages: list[dict[str, str]] = []
    thread_messages_raw = entry_input.metadata.get("thread_messages", "")
    if thread_messages_raw:
        try:
            parsed_messages = json.loads(thread_messages_raw)
            if isinstance(parsed_messages, list):
                messages = [item for item in parsed_messages if isinstance(item, dict)]
        except json.JSONDecodeError:
            logger.warning(
                "Invalid preloaded thread messages for session=%s",
                entry_input.session_id,
            )

    if not messages:
        try:
            messages = deps.summary.load_thread_messages(entry_input, 20)
        except Exception:
            logger.exception(
                "Unable to load thread messages for summarize workflow session=%s",
                entry_input.session_id,
            )

    if not messages:
        messages = _helpers._dialogue_prompt_messages(
            state.messages,
            exclude_latest=True,
        )

    if messages:
        messages_text = "\n".join(
            f"[{item.get('role', 'unknown')}]: {item.get('content', '')}"
            for item in messages
        )
        return deps.summary.summarize_chat(
            messages_text,
            entry_input.user_id or "default",
        )

    if entry_input.metadata.get("chat_id", ""):
        return (
            "已识别为群聊总结诉求。当前暂时无法获取会话消息，请稍后重试，"
            "或直接粘贴需要总结的聊天内容。"
        )
    return "已识别为总结诉求。请直接发送需要总结的文本内容，或在群聊中使用此功能。"


def _step_requires_resource(
    step,
    *,
    domain: str,
    resource_type: str,
    operation: str | None = None,
) -> bool:
    return any(
        domain in set(requirement.semantic_domains)
        and resource_type in set(requirement.resource_types)
        and (operation is None or operation in set(requirement.operations))
        for requirement in step.capability_requirements
    )


def _execute_verify_step(step, state: RunCheckpoint, deps: StepExecutionContext) -> None:
    ctx = deps.ask_run_context_store.get(state.run_id)
    if ctx is not None:
        try:
            ask_service = deps.ask_service_factory()
            ask_service.run_verification_stage(ctx)
            deps.ask_run_context_store.put(state.run_id, ctx)
            state.answer = ctx.answer
            state.citations = list(ctx.selected_citations or [])
            state.matches = [
                {"id": m.id, "title": m.body.title, "summary": m.body.summary}
                for m in (ctx.selected_matches or [])
            ]
            verification = ctx.verification
            state.invocation_batch.results[step.step_id] = {
                "verified": bool(
                    verification is not None
                    and getattr(verification, "ok", False)
                    and getattr(verification, "sufficient", False)
                ),
                "evidence_score": (
                    float(getattr(verification, "evidence_score", 0.0))
                    if verification is not None else 0.0
                ),
                "citation_count": len(ctx.selected_citations or []),
                "match_count": len(ctx.selected_matches or []),
                "repair": ctx.repair_payload(),
            }
        except Exception:
            logger.exception("Ask verify stage %s error", step.step_id)
        return

    if not state.answer:
        return
    try:
        verifier = deps.verifier
        if verifier:
            verifier.verify(
                question=step.task_input or state.entry_text or "",
                answer=state.answer,
                citations=state.citations,
                matches=[],
                run_id=state.run_id,
                thread_id=state.thread_id,
                user_id=state.user_id,
                step_id=step.step_id,
            )
    except Exception:
        logger.exception("Verify step %s error", step.step_id)


def _execute_repair_step(step, state: RunCheckpoint, deps: StepExecutionContext) -> None:
    ctx = deps.ask_run_context_store.get(state.run_id)
    if ctx is None:
        return
    try:
        ask_service = deps.ask_service_factory()
        ask_service.run_repair_stage(ctx)
        deps.ask_run_context_store.put(state.run_id, ctx)
        state.answer = ctx.answer
        state.citations = list(ctx.selected_citations or [])
        state.matches = [
            {"id": m.id, "title": m.body.title, "summary": m.body.summary}
            for m in (ctx.selected_matches or [])
        ]
        verification = ctx.verification
        state.invocation_batch.results[step.step_id] = {
            "repaired": bool(ctx.repair.events),
            "verified": bool(
                verification is not None
                and getattr(verification, "ok", False)
                and getattr(verification, "sufficient", False)
            ),
            "evidence_score": (
                float(getattr(verification, "evidence_score", 0.0))
                if verification is not None else 0.0
            ),
            "citation_count": len(ctx.selected_citations or []),
            "match_count": len(ctx.selected_matches or []),
            "repair": ctx.repair_payload(),
        }
    except Exception:
        logger.exception("Ask repair stage %s error", step.step_id)


# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------

def _should_execute_step(state: RunCheckpoint) -> str:
    """Check if there are more steps to execute."""
    if state.invocation_batch.aborted:
        return "finalize_steps"
    if (
        state.invocation_batch.current_step_index < len(state.invocation_batch.invocations)
        and state.invocation_batch.invocations[state.invocation_batch.current_step_index].status == "running"
    ):
        return "execute_step"
    for sd in state.invocation_batch.invocations:
        if sd.status in ("planned",):
            return "execute_step"
    return "finalize_steps"


def _after_invocation_batch(state: RunCheckpoint) -> str:
    """Determine whether step succeeded, failed, awaits confirmation, or needs ReAct."""
    if state.invocation_batch.current_step_index < len(state.invocation_batch.invocations):
        sd = state.invocation_batch.invocations[state.invocation_batch.current_step_index]
        if sd.status == "awaiting_confirmation":
            return "confirm_step"
        if sd.status == "failed":
            return "handle_failure"
        if sd.execution_mode == "react" and sd.status == "running":
            return "react_step"
        if sd.action_type == "tool_call" and sd.status == "running":
            return "tool_node"
    return "handle_success"


def _after_step_failure(state: RunCheckpoint) -> str:
    """After handling failure: continue or abort to finalize."""
    if state.invocation_batch.aborted:
        return "finalize_steps"
    return "continue_loop"


def _after_confirm_step(state: RunCheckpoint) -> str:
    """After confirmation: route to success or failure handler."""
    if state.confirmation_decision == "confirmed":
        return "tool_node"
    return "handle_failure"


def _after_step_success(state: RunCheckpoint) -> str:
    """After handling success: always continue to next step."""
    return "continue_loop"
