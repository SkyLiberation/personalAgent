from __future__ import annotations

import logging
from typing import Any

from ..core.models import EntryInput, MemoryEpisode, MemoryItem, local_now
from .runtime_results import EntryResult

logger = logging.getLogger(__name__)


def record_entry_episode(memory, result: EntryResult, entry_input: EntryInput | None = None) -> MemoryEpisode | None:
    """Persist one deterministic episodic memory for a completed/interrupted entry run."""
    if not result.run_id:
        return None
    episode = build_entry_episode(result, entry_input)
    try:
        memory.add_episode(episode, user_id=episode.user_id)
        reflection = build_reflection_candidate(result, episode)
        if reflection is not None:
            memory.add_memory_item(reflection, user_id=reflection.user_id)
    except Exception:
        logger.exception("Failed to record memory episode run_id=%s", result.run_id)
        return None
    return episode


def build_entry_episode(result: EntryResult, entry_input: EntryInput | None = None) -> MemoryEpisode:
    events = [_coerce_event(event) for event in result.events]
    user_id = entry_input.user_id if entry_input is not None else _event_user_id(events)
    session_id = entry_input.session_id if entry_input is not None else _event_session_id(events)
    entry_text = entry_input.text if entry_input is not None else _entry_text_from_events(events)
    outcome = _episode_outcome(result)
    intent = result.intent or "unknown"
    now = local_now()

    decisions = _decisions_from_events(events)
    open_items = _open_items(result)
    event_refs = [str(event.get("event_id", "")) for event in events if event.get("event_id")]
    tool_refs = _tool_refs_from_events(events)
    note_refs = _note_refs_from_result(result, events)

    return MemoryEpisode(
        id=f"episode:{result.run_id}",
        user_id=user_id or "default",
        session_id=session_id or "default",
        thread_id=result.thread_id or "",
        run_id=result.run_id or "",
        workflow=intent,
        title=_episode_title(intent, entry_text, outcome),
        summary=_episode_summary(result, entry_text, tool_refs, note_refs),
        outcome=outcome,
        entry_text=entry_text,
        decisions=decisions,
        open_items=open_items,
        event_refs=event_refs,
        tool_refs=tool_refs,
        note_refs=note_refs,
        metadata={
            "reason": result.reason,
            "plan_step_count": len(result.plan_steps),
            "execution_trace": result.execution_trace,
        },
        created_at=now,
        updated_at=now,
    )


def build_reflection_candidate(result: EntryResult, episode: MemoryEpisode) -> MemoryItem | None:
    """Build a deterministic reflection candidate for failed or blocked runs."""
    if episode.outcome not in {"failed", "cancelled"} and not result.errors:
        return None
    title = f"反思候选: {episode.workflow} {episode.outcome}"
    error_lines = _errors_from_result(result)
    trace = "；".join(str(item) for item in result.execution_trace[:5])
    content_parts = [
        f"workflow={episode.workflow}",
        f"outcome={episode.outcome}",
        f"entry={_clip(episode.entry_text, 180)}",
    ]
    if error_lines:
        content_parts.append("errors=" + "；".join(_clip(item, 160) for item in error_lines[:5]))
    if trace:
        content_parts.append(f"trace={_clip(trace, 260)}")
    if episode.open_items:
        content_parts.append("open_items=" + "；".join(episode.open_items[:3]))
    return MemoryItem(
        id=f"reflection:{episode.run_id}",
        memory_type="reflection",
        user_id=episode.user_id,
        session_id=episode.session_id,
        thread_id=episode.thread_id,
        title=title,
        content="\n".join(content_parts),
        status="candidate",
        confidence=0.5,
        source_episode_ids=[episode.id],
        source_run_ids=[episode.run_id],
        evidence_refs=[*episode.event_refs[:8], *episode.note_refs[:8]],
        applies_to=[episode.workflow],
        metadata={
            "outcome": episode.outcome,
            "reason": result.reason,
            "error_count": len(error_lines),
            "generated_by": "deterministic_entry_episode",
        },
        created_at=episode.updated_at,
        updated_at=episode.updated_at,
    )


def _errors_from_result(result: EntryResult) -> list[str]:
    raw_errors = getattr(result, "errors", None) or []
    errors = [str(error) for error in raw_errors if error]
    for event in result.events:
        event_data = _coerce_event(event)
        if event_data.get("type") not in {"step_failed", "run_failed"}:
            continue
        payload = event_data.get("payload")
        if isinstance(payload, dict):
            for key in ("error", "failure_reason", "message"):
                value = payload.get(key)
                if value:
                    errors.append(str(value))
    if not errors and result.reason:
        errors.append(str(result.reason))
    return _unique(errors)


def _coerce_event(event: object) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    return {"type": str(event)}


def _event_user_id(events: list[dict[str, Any]]) -> str:
    for event in events:
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("user_id"):
            return str(payload["user_id"])
    return "default"


def _event_session_id(events: list[dict[str, Any]]) -> str:
    for event in events:
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("session_id"):
            return str(payload["session_id"])
    return "default"


def _entry_text_from_events(events: list[dict[str, Any]]) -> str:
    for event in events:
        if event.get("type") != "entry_started":
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            return str(payload.get("text_preview") or "")
    return ""


def _episode_outcome(result: EntryResult) -> str:
    if result.run_status == "waiting_confirmation":
        return "waiting_confirmation"
    if result.run_status in {"completed", "failed", "cancelled"}:
        return result.run_status
    if result.pending_confirmation:
        return "waiting_confirmation"
    return "completed"


def _episode_title(intent: str, entry_text: str, outcome: str) -> str:
    labels = {
        "ask": "回答问题",
        "capture_text": "采集文本",
        "capture_link": "采集链接",
        "capture_file": "采集文件",
        "delete_knowledge": "删除知识",
        "solidify_conversation": "固化对话",
        "summarize_thread": "总结会话",
        "direct_answer": "直接回复",
        "unknown": "处理入口请求",
    }
    text = _clip(entry_text, 48)
    suffix = f": {text}" if text else ""
    status = "等待确认" if outcome == "waiting_confirmation" else "已完成"
    if outcome == "failed":
        status = "失败"
    elif outcome == "cancelled":
        status = "已取消"
    return f"{labels.get(intent, intent)}{suffix} ({status})"


def _episode_summary(
    result: EntryResult,
    entry_text: str,
    tool_refs: list[str],
    note_refs: list[str],
) -> str:
    parts = []
    if entry_text:
        parts.append(f"用户请求: {_clip(entry_text, 180)}")
    if result.reply_text:
        parts.append(f"结果: {_clip(result.reply_text, 320)}")
    if tool_refs:
        parts.append("使用工具: " + "、".join(tool_refs[:6]))
    if note_refs:
        parts.append("关联笔记: " + "、".join(note_refs[:6]))
    if result.execution_trace:
        parts.append("执行轨迹: " + "；".join(_clip(item, 80) for item in result.execution_trace[:5]))
    return "\n".join(parts) or _clip(result.reason, 320)


def _decisions_from_events(events: list[dict[str, Any]]) -> list[str]:
    decisions: list[str] = []
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        event_type = event.get("type")
        if event_type == "intent_classified":
            decisions.append(
                f"识别意图为 {payload.get('intent', 'unknown')}，风险 {payload.get('risk_level', 'low')}"
            )
        elif event_type in {"confirmation_resumed", "clarification_resumed"}:
            decisions.append(f"{event_type}: {payload.get('decision') or payload.get('text') or 'resumed'}")
        elif event_type == "replan_completed":
            decisions.append(f"重新规划: {payload.get('reason') or payload.get('message') or 'completed'}")
    return _unique(decisions)


def _open_items(result: EntryResult) -> list[str]:
    if not result.pending_confirmation:
        return []
    pending = result.pending_confirmation
    message = str(pending.get("message") or pending.get("description") or "等待用户确认")
    return [message]


def _tool_refs_from_events(events: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        tool_name = payload.get("tool_name")
        if tool_name:
            refs.append(str(tool_name))
    return _unique(refs)


def _note_refs_from_result(result: EntryResult, events: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    if result.capture_result is not None:
        refs.append(result.capture_result.note.id)
        refs.extend(note.id for note in result.capture_result.chunk_notes)
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        output = payload.get("output")
        if isinstance(output, dict):
            refs.extend(_note_ids_from_payload(output))
        refs.extend(_note_ids_from_payload(payload))
    return _unique(refs)


def _note_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("note_id", "parent_note_id", "deleted_note_id"):
        value = payload.get(key)
        if value:
            refs.append(str(value))
    data = payload.get("data")
    if isinstance(data, dict):
        refs.extend(_note_ids_from_payload(data))
    note = payload.get("note")
    if isinstance(note, dict) and note.get("id"):
        refs.append(str(note["id"]))
    return refs


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _clip(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."
