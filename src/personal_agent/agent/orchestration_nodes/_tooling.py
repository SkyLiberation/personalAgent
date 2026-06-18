from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, ToolMessage

from ..orchestration_models import AgentGraphState, ToolTrackingSubState
from ._deps import OrchestrationDeps
from . import _helpers

logger = logging.getLogger(__name__)


def _tool_result_event_payload(
    state: AgentGraphState,
    *,
    deps: OrchestrationDeps | None,
    context: str,
    step_id: str,
    tool_call_id: str | None,
    artifact: dict,
) -> dict:
    payload = {
        "context": "step_execution",
        "step_id": step_id,
        "tool_call_id": tool_call_id,
        "ok": bool(artifact.get("ok")),
        "result_summary": _helpers._summarize_result(artifact.get("data")),
        "tool_name": state.tool_tracking.pending_tool_name,
        "input": state.tool_tracking.pending_tool_input,
        "output": artifact,
        "artifact_ok": artifact.get("ok"),
        "error": artifact.get("error"),
        "evidence": artifact.get("evidence", []),
    }
    payload["context"] = context
    data = artifact.get("data")
    if isinstance(data, dict):
        for key in ("note_id", "title", "summary", "content_preview", "url", "filename", "source_type"):
            if key in data:
                payload[key] = data[key]
    spec = _lookup_tool_spec(deps, state.tool_tracking.pending_tool_name)
    if spec is not None:
        from ...tools import tool_invocation_event
        payload["invocation"] = tool_invocation_event(
            spec,
            tool_call_id=tool_call_id or "",
            input=state.tool_tracking.pending_tool_input,
            output=artifact,
            execution_mode="react" if context == "react" else "deterministic",
            step_id=step_id,
            thread_id=state.thread_id,
            user_id=state.user_id,
        ).model_dump(mode="json")
    return payload


def _lookup_tool_spec(deps: OrchestrationDeps | None, tool_name: str):
    if deps is None or not tool_name:
        return None
    return deps.tool_executor.get(tool_name)


def _log_tool_invocation_event(
    state: AgentGraphState,
    deps: OrchestrationDeps,
    artifact: dict,
    *,
    execution_mode: str,
) -> None:
    spec = _lookup_tool_spec(deps, state.tool_tracking.pending_tool_name)
    if spec is None:
        return
    from ...tools import tool_invocation_event
    logger.info(
        "Graph tool invocation completed",
        extra={"tool_invocation": tool_invocation_event(
            spec,
            tool_call_id=state.tool_tracking.pending_call_id,
            input=state.tool_tracking.pending_tool_input,
            output=artifact,
            execution_mode=execution_mode,
            step_id=state.tool_tracking.pending_step_id,
            thread_id=state.thread_id,
            user_id=state.user_id,
        ).model_dump(mode="json")},
    )


def _begin_tool_call(
    state: AgentGraphState,
    *,
    context: str,
    tool_name: str,
    tool_input: dict | None,
    step_id: str,
    suffix: str,
    iteration: int | None = None,
) -> AIMessage:
    call_id = f"{state.run_id}:{suffix}:{len(state.tool_results)}"
    normalized_input = dict(tool_input or {})
    if context == "step_execution" and tool_name == "graph_search" and "user_id" not in normalized_input:
        normalized_input["user_id"] = state.user_id
    state.tool_tracking = ToolTrackingSubState(
        active_context=context,
        pending_step_id=step_id,
        pending_call_id=call_id,
        pending_tool_name=tool_name,
        pending_tool_input=normalized_input,
        pending_react_iteration=iteration,
    )
    state.add_event("tool_called", {
        "context": context,
        "step_id": step_id,
        "tool_name": tool_name,
        "tool_call_id": call_id,
        "iteration": iteration,
    })
    return AIMessage(
        content="",
        tool_calls=[{
            "name": tool_name,
            "args": normalized_input,
            "id": call_id,
            "type": "tool_call",
        }],
    )


def _latest_tool_artifact(state: AgentGraphState) -> dict:
    expected_call_id = state.tool_tracking.pending_call_id
    if not expected_call_id:
        return {"ok": False, "data": None, "error": "缺少待处理工具调用标识。", "evidence": []}
    message = next(
        (
            item for item in reversed(state.tool_messages)
            if isinstance(item, ToolMessage) and item.tool_call_id == expected_call_id
        ),
        None,
    )
    if message is None:
        return {"ok": False, "data": None, "error": "工具节点未返回匹配当前调用的结果。", "evidence": []}
    artifact = getattr(message, "artifact", None)
    if isinstance(artifact, dict) and "ok" in artifact:
        return artifact
    return {
        "ok": False,
        "data": None,
        "error": str(getattr(message, "content", "工具执行失败。")),
        "evidence": [],
    }


def _clear_pending_tool_call(state: AgentGraphState) -> None:
    state.tool_tracking = ToolTrackingSubState()


def _pending_tool_updates(state: AgentGraphState) -> dict:
    return {"tool_tracking": state.tool_tracking}
