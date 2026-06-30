"""execution step execution loop nodes, step dispatchers, and conditional edge functions."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import time

from langgraph.types import interrupt

from personal_agent.kernel.prompts import render_prompt
from personal_agent.orchestration.orchestration_models import (
    AgentGraphState,
    StepRunState,
    StepExecutionState,
    ReactSubState,
)
from personal_agent.orchestration.orchestration_contexts import StepExecutionContext
from personal_agent.orchestration.orchestration_nodes._graph_helpers import (
    _RETRY_DELAY_SECONDS,
    _REACT_MAX_ITERATIONS_CAP,
    _default_step_answer,
    _inject_draft_text_into_steps,
    _inject_note_id_into_steps,
    _resolve_allowed_tools_for_step,
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

if TYPE_CHECKING:
    from personal_agent.orchestration.orchestration_nodes._graph_helpers import ExecutionStep

logger = logging.getLogger(__name__)


def _retrieve_reflections(
    state: AgentGraphState,
    deps: StepExecutionContext,
    intent: str,
    error: str,
):
    """Fetch same-intent past-failure reflections to inject into replanning.

    Returns a list of MemoryItem (or None) and records the applied ids on the
    state for post-run promotion. Gated by the reflection_replay config flag.
    """
    cfg = deps.settings.reflection_replay
    if not cfg.enabled:
        return None
    try:
        items = deps.memory.search_memory_items(
            state.user_id,
            f"{intent} {error}",
            memory_type="reflection",
            status=["candidate", "confirmed"],
            limit=cfg.max_items,
        )
    except Exception:
        logger.exception("Reflection retrieval for replan failed")
        return None
    items = [it for it in items if it.confidence >= cfg.min_confidence]
    if not items:
        return None
    for it in items:
        if it.id not in state.applied_reflection_ids:
            state.applied_reflection_ids.append(it.id)
    return items

# Staged ask execution. The ask flow is split across retrieve→compose→verify
# step nodes that now do real, bounded work: retrieve runs query understanding +
# multi-source recall + context assembly (the ~18s pass), compose generates from
# the assembled ContextPack, verify runs verification + web fallback + annotate.
# The run-scoped AskRunContext threads the large payload (evidence/context_pack)
# between ask steps via deps.ask_run_context_store. The store persists a durable
# artifact payload, so only summary counts go into AgentGraphState and compose /
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


def _node_prepare_step_execution(state: AgentGraphState) -> dict:
    """Sort execution steps and initialise execution state."""
    if not state.step_execution.steps:
        logger.info("prepare_step_execution: no steps to execute")
        state.step_execution.aborted = True
        return {"step_execution": state.step_execution}

    # Topologically sort steps
    sorted_steps = _topological_sort_steps(state.step_execution.steps)
    state.step_execution = StepExecutionState(
        steps=sorted_steps,
        current_step_index=0,
        results=state.step_execution.results or {},
        aborted=False,
        retry_counts=state.step_execution.retry_counts or {},
    )

    state.add_event("step_started", {
        "step_id": "__steps__",
        "description": f"开始执行 {len(sorted_steps)} 个步骤",
    })
    logger.info(
        "prepare_step_execution run_id=%s steps=%d",
        state.run_id, len(sorted_steps),
    )
    return {
        "step_execution": state.step_execution,
        "events": state.events,
    }


def _node_select_next_step(state: AgentGraphState) -> dict:
    """Find the next unexecuted step and set current_step_index.

    Skips steps with status 'skipped' or 'completed'.
    Returns with updated current_step_index or leaves it unchanged
    when no more steps remain (checked by the conditional edge).
    """
    for i, sd in enumerate(state.step_execution.steps):
        if sd.status in ("planned",):
            state.step_execution.current_step_index = i
            sd.status = "running"
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
                "step_execution": state.step_execution,
                "events": state.events,
            }

    # No more steps
    logger.info("select_next_step run_id=%s: no more steps", state.run_id)
    return {}


def _node_execute_step(state: AgentGraphState, *, deps: StepExecutionContext) -> dict:
    """Dispatch a single execution step.  Raises on failure; retry/replan handled
    by the handle_step_result node.

    Idempotency: if a tool_call step already has a result in results,
    skip execution.

    ReAct steps are *not* dispatched here: the state is seeded and the
    StepExecutionGraph routes into ReactGraph. Tool calls are prepared as LangChain
    messages so the appropriate subgraph ``ToolGateway`` performs execution.
    """
    if state.step_execution.current_step_index >= len(state.step_execution.steps):
        return {}

    sd = state.step_execution.steps[state.step_execution.current_step_index]
    step = sd.to_execution_step()
    _prepare_entry_tool_input(sd, step, state)
    _persist_step_artifact(
        state,
        sd,
        deps,
        phase="input",
        payload={
            "workflow_id": step.workflow_id,
            "workflow_version": step.workflow_version,
            "step_id": step.step_id,
            "action_type": step.action_type,
            "tool_name": step.tool_name,
            "tool_input": step.tool_input,
            "task_id": step.task_id,
            "task_intent": step.task_intent,
            "task_input": step.task_input,
        },
    )

    # Idempotency: skip side-effect steps that already ran
    if step.action_type == "tool_call" and step.tool_name:
        idem_key = step.step_id
        if idem_key in state.step_execution.results:
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
                "step_execution": state.step_execution,
                "events": state.events,
            }

    # ---- ReAct branch: seed state and let ReactGraph handle execution ----
    if getattr(step, "execution_mode", "deterministic") == "react":
        state.react = ReactSubState(
            step_id=step.step_id,
            max_iterations=min(step.max_iterations, _REACT_MAX_ITERATIONS_CAP),
            allowed_tools=list(_resolve_allowed_tools_for_step(step, deps)),
            status="running",
        )
        logger.info(
            "Seeded ReAct state for step %s (max_iter=%d, tools=%s)",
            step.step_id, state.react.max_iterations, state.react.allowed_tools,
        )
        return {
            "step_execution": state.step_execution,
            "react": state.react,
            "events": state.events,
        }

    if step.action_type == "tool_call":
        if not step.tool_name:
            return _fail_current_step(
                state,
                step,
                ValueError("tool_call step missing tool_name"),
                deps=deps,
            )
        return {
            "tool_messages": [_begin_tool_call(
                state,
                context="step_execution",
                tool_name=step.tool_name,
                tool_input=step.tool_input,
                step_id=step.step_id,
                suffix=step.step_id,
            )],
            "tool_tracking": state.tool_tracking,
            "step_execution": state.step_execution,
            "events": state.events,
        }

    try:
        _dispatch_step(step, sd, state, deps)
    except Exception as exc:
        return _fail_current_step(state, step, exc, deps=deps)

    return _complete_current_step(state, step, deps=deps)


def _node_consume_step_tool_result(state: AgentGraphState, *, deps: StepExecutionContext | None = None) -> dict:
    """Consume the latest ToolGateway artifact for a deterministic execution step."""
    if state.step_execution.current_step_index >= len(state.step_execution.steps):
        _clear_pending_tool_call(state)
        return _pending_tool_updates(state)
    sd = state.step_execution.steps[state.step_execution.current_step_index]
    step = sd.to_execution_step()
    if state.tool_tracking.active_context != "step_execution" or state.tool_tracking.pending_step_id != step.step_id:
        _clear_pending_tool_call(state)
        return _fail_current_step(
            state,
            step,
            RuntimeError("工具返回上下文与当前计划步骤不匹配。"),
            deps=deps,
        )
    artifact = _latest_tool_artifact(state)
    tool_call_id = state.tool_tracking.pending_call_id
    state.tool_results.append(artifact)
    state.add_event("tool_result", _tool_result_event_payload(
        state,
        deps=deps,
        context="step_execution",
        step_id=step.step_id,
        tool_call_id=tool_call_id,
        artifact=artifact,
    ))
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
    state.step_execution.results[step.step_id] = result_data
    _apply_tool_result_to_state(step, result_data, state)
    if isinstance(result_data, dict) and result_data.get("pending_confirmation"):
        state.pending_confirmation = {
            "step_id": step.step_id,
            "action_type": "delete_note",
            "note_id": result_data.get("note_id"),
            "title": result_data.get("title"),
            "summary": result_data.get("summary"),
            "description": result_data.get("description"),
        }
    else:
        state.pending_confirmation = None
    return _complete_current_step(state, step, deps=deps)


def _fail_current_step(
    state: AgentGraphState,
    step: "ExecutionStep",
    exc: Exception,
    *,
    deps: StepExecutionContext | None = None,
) -> dict:
    sd = state.step_execution.steps[state.step_execution.current_step_index]
    err_msg = f"{type(exc).__name__}: {exc}"
    logger.warning("execution step %s failed: %s", step.step_id, err_msg)
    sd.status = "failed"
    sd.retry_count = sd.retry_count + 1
    sd.failure_reason = err_msg
    sd.recoverable = step.on_failure == "retry" and sd.retry_count < sd.max_retries
    state.step_execution.retry_counts[step.step_id] = sd.retry_count
    state.errors.append(f"[{step.step_id}] {err_msg}")
    state.add_event("step_failed", {
        "step_id": step.step_id,
        "error": err_msg,
        "on_failure": step.on_failure,
        "retry_count": sd.retry_count,
    })
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
        "step_execution": state.step_execution,
        "errors": state.errors,
        "events": state.events,
    }
    result.update(_pending_tool_updates(state))
    return result


def _complete_current_step(
    state: AgentGraphState,
    step: "ExecutionStep",
    *,
    deps: StepExecutionContext | None = None,
) -> dict:
    sd = state.step_execution.steps[state.step_execution.current_step_index]
    if state.pending_confirmation is not None:
        sd.status = "awaiting_confirmation"
        state.add_event("confirmation_required", state.pending_confirmation)
        logger.info("Step %s awaiting confirmation", step.step_id)
        result = {
            "step_execution": state.step_execution,
            "answer": state.answer,
            "pending_confirmation": state.pending_confirmation,
            "events": state.events,
        }
        result.update(_pending_tool_updates(state))
        return result

    sd.status = "completed"
    display_output = _step_display_output(step, state.step_execution.results.get(step.step_id))
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
                "result": state.step_execution.results.get(step.step_id),
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
        "result_summary": _helpers._summarize_result(state.step_execution.results.get(step.step_id)),
    }
    completion_payload.update(display_output)
    state.add_event("step_completed", completion_payload)
    result = {
        "step_execution": state.step_execution,
        "answer": state.answer,
        "pending_confirmation": state.pending_confirmation,
        "events": state.events,
    }
    result.update(_pending_tool_updates(state))
    return result


def _persist_step_artifact(
    state: AgentGraphState,
    sd: StepRunState,
    deps: StepExecutionContext,
    *,
    phase: str,
    payload: dict,
) -> None:
    artifact_id = f"step:{state.run_id}:{sd.step_id}:{phase}"
    try:
        deps.workflow_artifact_store.put_artifact(
            artifact_id=artifact_id,
            run_id=state.run_id,
            kind=f"step_{phase}",
            payload=payload,
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


def _step_display_output(step, result_data: object) -> dict[str, str]:
    if not isinstance(result_data, dict):
        return {}
    if step.action_type == "compose" and result_data.get("answer"):
        return {
            "output_label": "生成草稿",
            "output_preview": str(result_data["answer"])[:800],
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


def _node_handle_step_success(state: AgentGraphState, *, deps: StepExecutionContext) -> dict:
    """Post-success: inject dependency outputs into downstream planned steps."""
    if state.step_execution.current_step_index >= len(state.step_execution.steps):
        return {}

    sd = state.step_execution.steps[state.step_execution.current_step_index]
    step = sd.to_execution_step()

    # Inject resolved note_id into dependent tool_call steps
    if step.action_type == "resolve":
        result_data = state.step_execution.results.get(step.step_id)
        if isinstance(result_data, dict) and result_data.get("note_id"):
            _inject_note_id_into_steps(
                step.step_id, str(result_data["note_id"]), state.user_id, state.step_execution.steps,
            )

    # Inject compose draft text into dependent capture_text steps
    if step.action_type == "compose":
        result_data = state.step_execution.results.get(step.step_id)
        if isinstance(result_data, dict) and result_data.get("answer"):
            _inject_draft_text_into_steps(
                step.step_id, str(result_data["answer"]), state.user_id, state.step_execution.steps,
            )

    # Inject fetched/extracted text into dependent capture_text steps.
    if step.action_type == "tool_call" and step.tool_name in {"capture_url", "capture_upload"}:
        result_data = state.step_execution.results.get(step.step_id)
        if isinstance(result_data, dict) and result_data.get("text"):
            source_type = "link" if step.tool_name == "capture_url" else str(result_data.get("source_type") or "file")
            _inject_capture_text_from_tool_result(
                step.step_id,
                str(result_data["text"]),
                state.user_id,
                source_type,
                state.step_execution.steps,
            )

    logger.info(
        "handle_step_success run_id=%s step=%s",
        state.run_id, step.step_id,
    )
    return {"step_execution": state.step_execution, "events": state.events}


def _node_handle_step_failure(state: AgentGraphState, *, deps: StepExecutionContext) -> dict:
    """Handle a failed step: retry, replan, skip, or abort."""
    if state.step_execution.current_step_index >= len(state.step_execution.steps):
        return {}

    sd = state.step_execution.steps[state.step_execution.current_step_index]
    step = sd.to_execution_step()
    on_failure = sd.on_failure
    retry_count = sd.retry_count
    max_retries = sd.max_retries

    # Retry logic
    if on_failure == "retry" and retry_count < max_retries:
        logger.info(
            "Retrying step %s (attempt %d/%d)",
            step.step_id, retry_count + 1, max_retries,
        )
        state.add_event("replan_attempted", {
            "step_id": step.step_id,
            "attempt": retry_count + 1,
            "max_retries": max_retries,
        })
        time.sleep(_RETRY_DELAY_SECONDS)
        sd.status = "planned"  # Reset so select_next_step picks it up again
        return {"step_execution": state.step_execution}

    # Retries exhausted — try replanning
    if on_failure == "retry" and retry_count >= max_retries:
        replanner = deps.replanner
        if replanner is not None:
            state.add_event("replan_attempted", {
                "step_id": step.step_id,
                "reason": "重试耗尽，尝试重新规划",
            })
            try:
                intent = step.task_intent
                err_msg = state.errors[-1] if state.errors else "未知错误"
                # Reconstruct execution step objects for replanner
                step_objs = [s.to_execution_step() for s in state.step_execution.steps]
                # Inject same-intent past-failure reflections (Reflexion loop)
                reflections = _retrieve_reflections(state, deps, intent, err_msg)
                revised = replanner.replan(
                    step_objs, step, err_msg, state.step_execution.results, intent,
                    reflections=reflections,
                )
                if revised:
                    # Validate revised steps
                    step_projection_validator = deps.step_projection_validator
                    if step_projection_validator is not None:
                        validation = step_projection_validator.validate(
                            revised,
                            step.task_intent,
                        )
                        if validation.blocking:
                            logger.warning(
                                "ReStep projection validation blocked for step %s: %s",
                                step.step_id, validation.issues,
                            )
                            state.add_event("replan_completed", {
                                "step_id": step.step_id,
                                "result": "blocked",
                                "issues": validation.issues,
                            })
                            sd.status = "failed"
                            state.step_execution.aborted = True
                            state.answer = state.answer or f"计划执行失败: {'; '.join(validation.issues[:3])}"
                            return {
                                "step_execution": state.step_execution,
                                "answer": state.answer,
                            }
                        if validation.corrected_steps:
                            revised = validation.corrected_steps

                    # Mark failed step as skipped, skip its dependents
                    _skip_step_dependents(step.step_id, state.step_execution.steps)
                    sd.status = "skipped"

                    # Append revised steps
                    for r in revised:
                        state.step_execution.steps.append(StepRunState.from_execution_step(r))
                    state.step_execution.steps = _topological_sort_steps(state.step_execution.steps)

                    state.add_event("replan_completed", {
                        "step_id": step.step_id,
                        "revised_step_count": len(revised),
                    })
                    logger.info(
                        "Replanned step %s: %d revised steps added",
                        step.step_id, len(revised),
                    )
                    return {"step_execution": state.step_execution}
                else:
                    state.add_event("replan_completed", {
                        "step_id": step.step_id,
                        "result": "no_alternative",
                    })
            except Exception as replan_exc:
                logger.exception("Replanner failed for step %s: %s", step.step_id, replan_exc)
                state.add_event("replan_completed", {
                    "step_id": step.step_id,
                    "result": "error",
                    "error": str(replan_exc),
                })

    # Handle final failure state
    sd.status = "failed"

    if on_failure == "abort":
        state.step_execution.aborted = True
        state.answer = state.answer or f"执行中断于步骤 {step.step_id}。"
        return {"step_execution": state.step_execution, "answer": state.answer}

    if on_failure in ("skip", "retry"):
        _skip_step_dependents(step.step_id, state.step_execution.steps)

    logger.info(
        "handle_step_failure run_id=%s step=%s on_failure=%s",
        state.run_id, step.step_id, on_failure,
    )
    return {"step_execution": state.step_execution}


def _node_confirm_step(state: AgentGraphState, *, deps: StepExecutionContext) -> dict:
    """Pause the graph for human confirmation via ``interrupt()``.

    First invocation: ``interrupt()`` pauses the graph and returns an
    ``__interrupt__`` payload from ``graph.invoke()``. On resume (re-entered
    via ``Command(resume=...)``), ``interrupt()`` returns the user's decision
    dict and the node processes the confirm / reject action.
    """
    if state.step_execution.current_step_index >= len(state.step_execution.steps):
        return {}

    sd = state.step_execution.steps[state.step_execution.current_step_index]
    step = sd.to_execution_step()
    pending = state.pending_confirmation or {}

    # ---- Build the interrupt payload (presented to the caller) ----
    confirm_payload = {
        "step_id": step.step_id,
        "action_type": pending.get("action_type", step.action_type),
        "note_id": pending.get("note_id"),
        "title": pending.get("title", ""),
        "summary": pending.get("summary", ""),
        "description": pending.get("description", ""),
        "message": (
            step.description
            or f"确认执行 {pending.get('action_type', step.action_type)} 操作？"
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
        state.confirmation_decision = "confirmed"
        state.add_event("confirmation_resumed", {
            "step_id": step.step_id,
            "decision": "confirmed",
        })
        logger.info("Step %s confirmed; dispatching through main ToolGateway", step.step_id)
        return {
            "tool_messages": [_begin_tool_call(
                state,
                context="step_execution",
                tool_name=step.tool_name or "",
                tool_input=tool_input,
                step_id=step.step_id,
                suffix=f"{step.step_id}:confirmed",
            )],
            "tool_tracking": state.tool_tracking,
            "step_execution": state.step_execution,
            "confirmation_decision": "confirmed",
            "events": state.events,
        }

    # Reject (or unknown decision)
    sd.status = "skipped"
    _skip_step_dependents(step.step_id, state.step_execution.steps)
    state.confirmation_decision = "rejected"
    state.pending_confirmation = None
    if not state.answer:
        state.answer = f"操作已取消：{step.description or pending.get('action_type', '')}"

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
        "step_execution": state.step_execution,
        "confirmation_decision": "rejected",
    }


def _node_finalize_step_execution(state: AgentGraphState, *, deps: StepExecutionContext | None = None) -> dict:
    """Compose default answer if none was set, mark execution complete."""
    if not state.answer:
        state.answer = _default_step_answer(state.step_execution.steps)

    state.answer_completed = True

    # Phase 5: derive execution_trace from structured events
    from personal_agent.orchestration.orchestration_models import execution_trace_from_events
    state.execution_trace = execution_trace_from_events(state.events)

    state.add_event("answer_completed", {"answer": state.answer})
    logger.info(
        "finalize_step_execution run_id=%s answer_len=%d trace_items=%d",
        state.run_id, len(state.answer or ""), len(state.execution_trace),
    )
    return {
        "answer": state.answer,
        "answer_completed": True,
        "execution_trace": state.execution_trace,
        "events": state.events,
        "updated_at": state.updated_at,
    }


def _prepare_entry_tool_input(sd: StepRunState, step: "ExecutionStep", state: AgentGraphState) -> None:
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
    route = step.task_intent

    if step.tool_name == "capture_text":
        tool_input.setdefault("user_id", state.user_id)
        if route == "capture_link":
            tool_input.setdefault("source_type", "link")
        elif route == "capture_file":
            tool_input.setdefault("source_type", "file")
        else:
            tool_input.setdefault("source_type", "text")
        if "text" not in tool_input and route == "capture_text":
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
    state: AgentGraphState,
    metadata: dict,
) -> None:
    if "run_id" not in tool_input:
        run_id = metadata.get("research_run_id") or metadata.get("run_id")
        if run_id:
            tool_input["run_id"] = str(run_id)
        else:
            for result in reversed(list(state.step_execution.results.values())):
                if not isinstance(result, dict):
                    continue
                run_id = result.get("run_id")
                if not run_id and isinstance(result.get("run"), dict):
                    run_id = result["run"].get("id")
                if run_id:
                    tool_input["run_id"] = str(run_id)
                    break
    if "max_items" not in tool_input:
        for result in reversed(list(state.step_execution.results.values())):
            if isinstance(result, dict) and result.get("max_items"):
                tool_input["max_items"] = int(result["max_items"])
                break


def _apply_tool_result_to_state(step: "ExecutionStep", result_data: object, state: AgentGraphState) -> None:
    if step.tool_name in {"research_synthesize_digest", "research_verify_digest"} and isinstance(result_data, dict):
        answer = str(result_data.get("answer") or "").strip()
        if answer:
            state.answer = answer
        return
    if step.tool_name != "capture_text" or not isinstance(result_data, dict):
        return
    route = step.task_intent
    if route not in {"capture_text", "capture_link", "capture_file"}:
        return
    title = str(result_data.get("title") or "").strip()
    if title:
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
    step: "ExecutionStep",
    sd: StepRunState,
    state: AgentGraphState,
    deps: StepExecutionContext,
) -> None:
    """Execute a single step by action_type. Raises on failure.

    The graph-native executor operates on ``AgentGraphState`` so every step
    update can be checkpointed.
    """
    results: dict = state.step_execution.results

    if step.action_type == "retrieve":
        result_data = _execute_retrieve_step(step, state, deps)
        results[step.step_id] = result_data

    elif step.action_type == "tool_call":
        raise RuntimeError("tool_call must be executed by the main graph ToolGateway")

    elif step.action_type == "resolve":
        result_data = _execute_resolve_step(step, state, deps)
        results[step.step_id] = result_data

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

    else:
        raise ValueError(f"未知的 action_type: {step.action_type}")


def _execute_retrieve_step(step, state: AgentGraphState, deps: StepExecutionContext) -> object:
    question = step.tool_input.get("question") if step.tool_input else None
    question = str(question or step.task_input or state.entry_text or step.description or "")

    # For the ask flow, the retrieve step runs query understanding +
    # multi-source recall + context assembly — the ~18s pass — and stashes the
    # run-scoped AskRunContext for the downstream compose/verify steps. The
    # running "retrieve" step honestly reflects that latency to the user.
    if step.task_intent == "ask":
        from personal_agent.orchestration.orchestration_nodes._entry import _entry_conversation_messages

        conversation = _entry_conversation_messages(
            state,
            exclude_latest=True,
            deps=deps.direct_answer,
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


def _execute_resolve_step(step, state: AgentGraphState, deps: StepExecutionContext) -> object:
    user_id = state.user_id
    original_query = step.task_input or state.entry_text or ""

    candidates: list[dict] = []

    # 1. Graph episode UUID mapping
    for sid, data in state.step_execution.results.items():
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


def _execute_compose_step(step, state: AgentGraphState, deps: StepExecutionContext) -> str:
    context_parts: list[str] = []
    for sid, data in state.step_execution.results.items():
        if isinstance(data, dict):
            if data.get("answer"):
                context_parts.append(str(data["answer"]))
            if data.get("entity_names"):
                context_parts.append("实体: " + ", ".join(str(n) for n in data["entity_names"] if n))

    context = "\n".join(context_parts) if context_parts else "暂无检索结果。"

    if step.tool_input and step.tool_input.get("question"):
        question = str(step.tool_input["question"])
    else:
        question = step.task_input or step.description or "根据已有信息生成回答"

    route = step.task_intent
    if route in {
        "review_digest",
        "consolidate_knowledge",
        "inspect_knowledge_gaps",
    }:
        for data in reversed(list(state.step_execution.results.values())):
            if not isinstance(data, dict):
                continue
            text = str(data.get("text") or "").strip()
            if text:
                return text
            if route == "consolidate_knowledge" and data.get("note_id"):
                title = str(data.get("title") or step.task_input or "主题综述")
                source_count = len(data.get("source_note_ids") or data.get("superseded") or [])
                return f"已将 {source_count} 条相关笔记整理为《{title}》。"
        raise RuntimeError("工作流未产生可呈现的结果。")

    if route == "summarize_thread":
        return _summarize_thread(state, deps)

    if route == "direct_answer":
        from personal_agent.orchestration.orchestration_nodes._entry import _node_direct_answer_branch

        original_entry = state.entry_input
        if original_entry is not None and step.task_input:
            state.entry_input = original_entry.model_copy(update={"text": step.task_input})
        try:
            _node_direct_answer_branch(state, deps=deps.direct_answer)
        finally:
            state.entry_input = original_entry
        return state.answer or ""

    if step.task_intent == "solidify_conversation":
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
    ctx = deps.ask_run_context_store.get(state.run_id)
    if ctx is not None:
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


def _summarize_thread(state: AgentGraphState, deps: StepExecutionContext) -> str:
    """Execute the summarize workflow's compose operation."""
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


def _execute_verify_step(step, state: AgentGraphState, deps: StepExecutionContext) -> None:
    # ask flow: run the real verification stage on the run-scoped context —
    # verify + retry + web fallback (re-assemble/re-compose/re-verify) + annotate.
    # The final answer and citations/matches are written back onto the state.
    if step.task_intent == "ask":
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


# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------

def _should_execute_step(state: AgentGraphState) -> str:
    """Check if there are more steps to execute."""
    if state.step_execution.aborted:
        return "finalize_steps"
    if (
        state.step_execution.current_step_index < len(state.step_execution.steps)
        and state.step_execution.steps[state.step_execution.current_step_index].status == "running"
    ):
        return "execute_step"
    for sd in state.step_execution.steps:
        if sd.status in ("planned",):
            return "execute_step"
    return "finalize_steps"


def _after_step_execution(state: AgentGraphState) -> str:
    """Determine whether step succeeded, failed, awaits confirmation, or needs ReAct."""
    if state.step_execution.current_step_index < len(state.step_execution.steps):
        sd = state.step_execution.steps[state.step_execution.current_step_index]
        if sd.status == "awaiting_confirmation":
            return "confirm_step"
        if sd.status == "failed":
            return "handle_failure"
        if sd.execution_mode == "react" and sd.status == "running":
            return "react_step"
        if sd.action_type == "tool_call" and sd.status == "running":
            return "tool_node"
    return "handle_success"


def _after_step_failure(state: AgentGraphState) -> str:
    """After handling failure: continue or abort to finalize."""
    if state.step_execution.aborted:
        return "finalize_steps"
    return "continue_loop"


def _after_confirm_step(state: AgentGraphState) -> str:
    """After confirmation: route to success or failure handler."""
    if state.confirmation_decision == "confirmed":
        return "tool_node"
    return "handle_failure"


def _after_step_success(state: AgentGraphState) -> str:
    """After handling success: always continue to next step."""
    return "continue_loop"
