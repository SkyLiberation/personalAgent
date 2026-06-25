from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from personal_agent.orchestration.orchestration_models import AgentEvent, AgentRunStatus


class WorkflowExecutionProjection(BaseModel):
    """Event-sourced read model for one workflow run."""

    run_id: str
    thread_id: str = ""
    status: AgentRunStatus = AgentRunStatus.pending
    intent: str = "unknown"
    workflow_id: str = ""
    workflow_version: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    answer: str | None = None
    pending_confirmation: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    replay: dict[str, Any] | None = None
    event_count: int = 0


def project_workflow_events(
    run_id: str,
    events: list[AgentEvent],
) -> WorkflowExecutionProjection:
    """Fold the append-only event stream into a query-friendly run view."""
    projection = WorkflowExecutionProjection(run_id=run_id)
    steps_by_id: dict[str, dict[str, Any]] = {}
    step_order: list[str] = []

    for event in events:
        projection.thread_id = event.thread_id or projection.thread_id
        projection.event_count += 1
        payload = event.payload

        if event.type == "entry_started":
            projection.status = AgentRunStatus.running
        elif event.type == "intent_classified":
            projection.intent = str(payload.get("intent") or "unknown")
            projection.status = AgentRunStatus.running
        elif event.type == "steps_projected":
            projection.workflow_id = str(payload.get("workflow_id") or "")
            projection.workflow_version = str(payload.get("workflow_version") or "")
            for raw_step in payload.get("steps") or []:
                if not isinstance(raw_step, dict):
                    continue
                step = dict(raw_step)
                step_id = str(step.get("step_id") or "")
                if not step_id:
                    continue
                steps_by_id[step_id] = step
                if step_id not in step_order:
                    step_order.append(step_id)
        elif event.type == "step_started":
            step_id = str(payload.get("step_id") or "")
            if step_id and step_id != "__steps__":
                step = _ensure_step(steps_by_id, step_order, step_id)
                step.update(_display_fields(payload))
                step["status"] = "running"
        elif event.type == "artifact_written":
            step_id = str(payload.get("step_id") or "")
            kind = str(payload.get("kind") or "")
            if step_id:
                step = _ensure_step(steps_by_id, step_order, step_id)
                artifact_field = {
                    "step_input": "input_artifact_id",
                    "step_output": "output_artifact_id",
                    "step_error": "error_artifact_id",
                }.get(kind)
                if artifact_field:
                    step[artifact_field] = str(payload.get("artifact_id") or "")
        elif event.type == "step_completed":
            step_id = str(payload.get("step_id") or "")
            if step_id:
                step = _ensure_step(steps_by_id, step_order, step_id)
                step.update(_display_fields(payload))
                step["status"] = "completed"
                step["result_summary"] = payload.get("result_summary")
        elif event.type == "step_failed":
            step_id = str(payload.get("step_id") or "")
            error = str(payload.get("error") or "")
            if step_id:
                step = _ensure_step(steps_by_id, step_order, step_id)
                step["status"] = "failed"
                step["failure_reason"] = error
            if error:
                projection.errors.append(error)
            projection.status = AgentRunStatus.failed
        elif event.type in {"clarification_required", "confirmation_required"}:
            projection.pending_confirmation = dict(payload)
            projection.status = AgentRunStatus.waiting_confirmation
        elif event.type in {"clarification_resumed", "confirmation_resumed"}:
            projection.pending_confirmation = None
            projection.status = AgentRunStatus.running
        elif event.type == "answer_completed":
            projection.answer = payload.get("answer")
        elif event.type == "run_completed":
            projection.answer = payload.get("answer", projection.answer)
            projection.status = AgentRunStatus.completed
        elif event.type == "run_failed":
            projection.errors.extend(str(item) for item in payload.get("errors") or [])
            projection.status = AgentRunStatus.failed
        elif event.type in {"workflow_forked", "workflow_replayed"}:
            projection.replay = {"type": event.type, **dict(payload)}

    projection.steps = [steps_by_id[step_id] for step_id in step_order]
    return projection


def _ensure_step(
    steps_by_id: dict[str, dict[str, Any]],
    step_order: list[str],
    step_id: str,
) -> dict[str, Any]:
    if step_id not in steps_by_id:
        steps_by_id[step_id] = {"step_id": step_id, "status": "planned"}
        step_order.append(step_id)
    return steps_by_id[step_id]


def _display_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload[key]
        for key in ("description", "action_type", "output_label", "output_title", "output_preview")
        if key in payload
    }
