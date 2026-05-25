"""Entry orchestration graph — unified LangGraph shell for the entry pipeline.

This graph wraps routing, planning, fixed non-planning branches, and
plan-step execution inside a single LangGraph StateGraph so that every entry
run benefits from checkpoint / interrupt / resume capabilities.

Phase 1
-------
* ``build_entry_orchestration_graph()`` produces a compiled graph with a
  ``MemorySaver``.
* Nodes reuse existing ``AgentRuntime`` methods internally.
* ``AgentRuntime.execute_entry()`` routes through this graph by default.

Phase 2 (this revision)
-----------------------
* Plan-driven paths (delete_knowledge, solidify_conversation) go through a
  step-level loop (prepare → select → execute → handle → loop) so each
  plan step transition writes a checkpoint.
* Idempotency: each tool_call step checks ``step_results`` before executing
  to avoid repeating side effects on resume.
* Revised steps from Replanner are validated through PlanValidator.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..core.models import EntryInput
from .orchestration_models import (
    AgentGraphState,
    PlanStepState,
    _new_run_id,
    _new_thread_id,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..capture import CaptureService
    from ..core.config import Settings
    from ..graphiti.store import GraphitiStore
    from ..memory import MemoryFacade
    from ..storage.memory_store import LocalMemoryStore
    from ..tools import ToolRegistry
    from .plan_validator import PlanValidator
    from .planner import PlanStep
    from .replanner import Replanner
    from .router import DefaultIntentRouter
    from .runtime_results import AskResult, CaptureResult
    from .verifier import AnswerVerifier


@dataclass(slots=True)
class OrchestrationDeps:
    """Explicit dependencies used by the entry orchestration graph."""

    settings: "Settings"
    memory: "MemoryFacade"
    intent_router: "DefaultIntentRouter"
    planner: object
    plan_validator: "PlanValidator"
    replanner: "Replanner | None"
    verifier: "AnswerVerifier | None"
    tool_registry: "ToolRegistry"
    graph_store: "GraphitiStore"
    store: "LocalMemoryStore"
    execute_ask: Callable[..., "AskResult"]
    execute_capture: Callable[..., "CaptureResult"] | None = None
    capture_service: "CaptureService | None" = None
    summarize_thread: Callable[[str, str], str] | None = None

    @classmethod
    def from_runtime(cls, runtime) -> "OrchestrationDeps":
        return cls(
            settings=runtime.settings,
            memory=runtime.memory,
            intent_router=runtime.intent_router,
            planner=runtime.planner,
            plan_validator=runtime.plan_validator,
            replanner=getattr(runtime, "_replanner", None),
            verifier=getattr(runtime, "_verifier", None),
            tool_registry=runtime.tool_registry,
            graph_store=runtime.graph_store,
            store=runtime.store,
            execute_ask=runtime.execute_ask,
            execute_capture=runtime.execute_capture,
            capture_service=runtime.capture_service,
            summarize_thread=runtime._summarize_thread,
        )

# ---------------------------------------------------------------------------
# Constants (mirrored from plan_executor for replay-safe retry)
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 2.0

# ReAct constants (mirrored from react_runner.py)
_REACT_MAX_ITERATIONS_CAP = 5
_REACT_BLOCKED_TOOL_PREFIXES = ("delete_", "capture_")
_REACT_DEFAULT_ALLOWED_TOOLS = ("graph_search", "web_search")

_REACT_SYSTEM_PROMPT = (
    "你是一个在受控环境中执行任务步骤的推理助手。"
    "每一轮你需要输出 JSON：\n"
    '- 仍在推理：{"thought":"...","tool":"工具名","input":{...}}\n'
    '- 已完成：{"thought":"...","done":true,"result":{...}}\n\n'
    "tool 必须在可用工具列表中。result 应包含步骤产出的结构化数据。\n"
    "不要输出 JSON 以外的内容。"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _topological_sort_steps(steps: list) -> list:
    """Sort plan steps so dependencies come before dependents."""
    if len(steps) <= 1:
        return list(steps)
    step_ids = {s.step_id for s in steps if s.step_id}
    indeg: dict[int, int] = {}
    adj: dict[int, list[int]] = {}
    for i, s in enumerate(steps):
        indeg[i] = 0
        adj[i] = []
        for dep_id in s.depends_on:
            if dep_id in step_ids:
                indeg[i] = indeg.get(i, 0) + 1
                for j, other in enumerate(steps):
                    if other.step_id == dep_id:
                        adj.setdefault(j, []).append(i)
                        break
    q: deque[int] = deque(i for i, d in indeg.items() if d == 0)
    result: list = []
    while q:
        i = q.popleft()
        result.append(steps[i])
        for ni in adj.get(i, []):
            indeg[ni] -= 1
            if indeg[ni] == 0:
                q.append(ni)
    return result


def _inject_note_id_into_steps(resolve_step_id: str, note_id: str, plan_steps: list) -> None:
    for s in plan_steps:
        if s.status != "planned":
            continue
        if (resolve_step_id in s.depends_on
                and s.action_type == "tool_call"
                and s.tool_name == "delete_note"):
            if not s.tool_input:
                s.tool_input = {}
            s.tool_input["note_id"] = note_id


def _inject_draft_text_into_steps(
    compose_step_id: str, text: str, user_id: str, plan_steps: list,
) -> None:
    by_id = {s.step_id: s for s in plan_steps}

    def depends_on_compose(step) -> bool:
        pending = list(step.depends_on)
        visited: set[str] = set()
        while pending:
            step_id = pending.pop()
            if step_id == compose_step_id:
                return True
            if step_id in visited:
                continue
            visited.add(step_id)
            parent = by_id.get(step_id)
            if parent is not None:
                pending.extend(parent.depends_on)
        return False

    for s in plan_steps:
        if s.status != "planned":
            continue
        if (depends_on_compose(s)
                and s.action_type == "tool_call"
                and s.tool_name == "capture_text"):
            if not s.tool_input:
                s.tool_input = {}
            s.tool_input["text"] = text
            s.tool_input["user_id"] = user_id


def _skip_step_dependents(failed_step_id: str, plan_steps: list) -> None:
    """Recursively mark dependents of a failed step as skipped."""
    for s in plan_steps:
        if s.status != "planned":
            continue
        if failed_step_id in s.depends_on:
            s.status = "skipped"
            _skip_step_dependents(s.step_id, plan_steps)


def _default_plan_answer(steps: list) -> str:
    completed = sum(1 for s in steps if s.status == "completed")
    failed = sum(1 for s in steps if s.status == "failed")
    skipped = sum(1 for s in steps if s.status == "skipped")
    return f"计划执行完成：{completed} 步成功" + (
        f"，{failed} 步失败" if failed else ""
    ) + (
        f"，{skipped} 步跳过" if skipped else ""
    ) + "。"


# ---------------------------------------------------------------------------
# ReAct helper functions (ported from ReActStepRunner for graph use)
# ---------------------------------------------------------------------------


def _resolve_allowed_tools_for_step(step: "PlanStep", deps: OrchestrationDeps) -> set[str]:
    allowed = set(step.allowed_tools) if step.allowed_tools else set(_REACT_DEFAULT_ALLOWED_TOOLS)
    registered = {t.name for t in deps.tool_registry.list_tools()}
    return allowed & registered


def _is_react_tool_blocked(tool_name: str, deps: OrchestrationDeps) -> bool:
    spec = None
    for t in deps.tool_registry.list_tools():
        if t.name == tool_name:
            spec = t
            break
    if spec is None:
        return True
    if spec.risk_level == "high" or spec.requires_confirmation or spec.writes_longterm:
        return True
    if any(tool_name.startswith(p) for p in _REACT_BLOCKED_TOOL_PREFIXES):
        return True
    return False


def _build_react_context(step: "PlanStep", step_results: dict) -> str:
    import json as _json

    parts: list[str] = []
    if step.tool_input:
        parts.append(f"步骤输入：{_json.dumps(step.tool_input, ensure_ascii=False)}")
    for sid, data in step_results.items():
        if isinstance(data, dict):
            summary = data.get("answer") or data.get("hint") or _json.dumps(data, ensure_ascii=False)[:200]
            parts.append(f"[{sid}] {summary}")
    return "\n".join(parts) if parts else "无"


def _format_react_tools(allowed: set[str], deps: OrchestrationDeps) -> str:
    lines: list[str] = []
    for spec in deps.tool_registry.list_tools():
        if spec.name in allowed:
            lines.append(f"- {spec.name}: {spec.description}")
            if spec.input_schema:
                props = spec.input_schema.get("properties", {})
                required = spec.input_schema.get("required", [])
                for pname, pdef in props.items():
                    req_mark = " (必填)" if pname in required else ""
                    desc = pdef.get("description", pdef.get("type", ""))
                    lines.append(f"    {pname}{req_mark}: {desc}")
    return "\n".join(lines) if lines else "无可用工具"


def _summarize_react_tool_result(data: object) -> str:
    import json as _json

    if data is None:
        return "（无返回数据）"
    if isinstance(data, dict):
        answer = data.get("answer")
        if answer:
            return str(answer)[:300]
        return _json.dumps(data, ensure_ascii=False)[:300]
    return str(data)[:300]


def _react_llm_respond(user_prompt: str, deps: OrchestrationDeps) -> str | None:
    from openai import OpenAI

    settings = deps.settings
    if not (settings.openai_api_key and settings.openai_base_url):
        return None
    try:
        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
        response = client.chat.completions.create(
            model=settings.openai_small_model,
            messages=[
                {"role": "system", "content": _REACT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        return (response.choices[0].message.content or "").strip() or None
    except Exception:
        logger.exception("ReAct LLM call failed")
        return None


def _react_parse_response(raw: str) -> dict | None:
    import json as _json

    try:
        return _json.loads(raw)
    except (_json.JSONDecodeError, TypeError):
        return None


def _solidify_note_text(raw: str) -> str:
    """Extract note content from a structured LLM solidification response."""
    parsed = _react_parse_response(raw)
    if not isinstance(parsed, dict):
        return ""
    result = parsed.get("result")
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, dict):
        title = str(result.get("标题") or result.get("title") or "").strip()
        body = str(
            result.get("正文") or result.get("content") or result.get("text") or ""
        ).strip()
        if title and body:
            return f"{title}\n\n{body}"
        return body or title
    answer = parsed.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer.strip()
    return ""


def _clarification_payload_parts(message: str, summary: str) -> dict:
    return {
        "message": message,
        "summary": summary,
        "options": [
            {
                "id": "capture",
                "label": "记录内容",
                "prompt": "请补充要写入知识库的具体内容。",
            },
            {
                "id": "ask",
                "label": "提出问题",
                "prompt": "请补充你想查询或追问的问题。",
            },
            {
                "id": "summarize",
                "label": "总结内容",
                "prompt": "请补充要总结的文本、会话或范围。",
            },
            {
                "id": "action",
                "label": "执行操作",
                "prompt": "请补充要执行的操作和对象，例如要删除哪条笔记。",
            },
        ],
    }


def _resume_value_get(value: object, key: str, default: object = None) -> object:
    if isinstance(value, dict):
        return value.get(key, default)
    return default


def _merge_clarification_text(original: str, supplemental: str, option_id: str) -> str:
    prefix_map = {
        "capture": "记一下：",
        "ask": "请问：",
        "summarize": "总结：",
        "action": "",
    }
    prefix = prefix_map.get(option_id, "")
    if prefix and not supplemental.startswith(prefix):
        return f"{prefix}{supplemental}"
    if original.strip() and original.strip() not in {"帮我", "帮我看看", "看看", "处理一下", "继续"}:
        return f"{original.strip()} {supplemental}".strip()
    return supplemental


def _dialogue_history(messages: list[BaseMessage], *, exclude_latest: bool = False) -> list[BaseMessage]:
    """Return recent user-visible dialogue messages for prompt context."""
    history = messages[:-1] if exclude_latest and messages else messages
    return [message for message in history[-12:] if message.type in {"human", "ai"}]


def _dialogue_prompt_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    return [
        {
            "role": "assistant" if message.type == "ai" else "user",
            "content": str(message.content),
        }
        for message in _dialogue_history(messages)
    ]


def _format_dialogue_context(messages: list[BaseMessage], *, exclude_latest: bool = False) -> str:
    lines: list[str] = []
    for message in _dialogue_history(messages, exclude_latest=exclude_latest):
        label = "用户" if message.type == "human" else "助手"
        lines.append(f"{label}: {message.content}")
    return "\n".join(lines)


def _format_solidify_candidate_context(messages: list[BaseMessage]) -> str:
    """Render candidate dialogue turns for model-driven solidification."""
    history = _dialogue_history(messages, exclude_latest=True)
    if not history:
        return ""
    turns: list[list[BaseMessage]] = []
    for message in history:
        if message.type == "human" or not turns:
            turns.append([message])
        else:
            turns[-1].append(message)

    lines: list[str] = []
    for index, turn in enumerate(turns, start=1):
        for message in turn:
            label = "用户" if message.type == "human" else "助手"
            lines.append(f"[turn-{index}] {label}: {message.content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 1 nodes
# ---------------------------------------------------------------------------


def _node_normalize_entry(state: AgentGraphState) -> dict:
    if state.run_id is None or state.run_id == "":
        state.run_id = _new_run_id()

    entry = state.entry_input
    user_id = entry.user_id if entry else state.user_id
    session_id = entry.session_id if entry else state.session_id
    text = entry.text if entry else state.entry_text

    thread_id = _new_thread_id(user_id, session_id)

    state.user_id = user_id
    state.session_id = session_id
    state.thread_id = thread_id
    state.entry_text = text
    state.router_decision = None
    state.plan_steps = []
    state.current_step_index = 0
    state.step_results = {}
    state.plan_aborted = False
    state.plan_retry_counts = {}
    state.react_iterations = []
    state.react_step_id = ""
    state.react_iteration_index = 0
    state.react_max_iterations = 3
    state.react_allowed_tools = []
    state.react_user_prompt = ""
    state.react_done = False
    state.react_result = {}
    state.tool_results = []
    state.execution_trace = []
    state.evidence_summary = []
    state.citations = []
    state.matches = []
    state.pending_confirmation = None
    state.confirmation_decision = None
    state.draft = None
    state.answer = None
    state.answer_completed = False
    state.events = []
    state.errors = []
    state.replan_history = []
    state.created_at = datetime.utcnow()
    state.updated_at = state.created_at

    state.add_event("entry_started", {"text_preview": text[:120] if text else ""})
    logger.info("normalize_entry run_id=%s thread_id=%s", state.run_id, thread_id)
    return {
        "user_id": user_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "entry_text": text,
        "messages": [HumanMessage(content=text, id=f"{state.run_id}:user")],
        "router_decision": None,
        "plan_steps": [],
        "current_step_index": 0,
        "step_results": {},
        "plan_aborted": False,
        "plan_retry_counts": {},
        "react_iterations": [],
        "react_step_id": "",
        "react_iteration_index": 0,
        "react_max_iterations": 3,
        "react_allowed_tools": [],
        "react_user_prompt": "",
        "react_done": False,
        "react_result": {},
        "tool_results": [],
        "execution_trace": [],
        "evidence_summary": [],
        "citations": [],
        "matches": [],
        "pending_confirmation": None,
        "confirmation_decision": None,
        "draft": None,
        "answer": None,
        "answer_completed": False,
        "events": state.events,
        "errors": [],
        "replan_history": [],
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }


def _node_prepare_clarify(state: AgentGraphState) -> dict:
    """Materialize a router-requested clarification before interrupting.

    ``route_intent`` has already determined that information is missing. This
    node writes the payload first so the checkpoint records exactly what the
    UI should present before ``interrupt()`` pauses execution.
    """
    decision = state.router_decision
    if decision is None or not decision.requires_clarification:
        return {}

    issue = _clarification_payload_parts(
        decision.clarification_prompt
        or "请补充你想记录、查询、总结或执行的具体内容。",
        decision.user_visible_message or "入口信息不足，需要用户补充。",
    )
    payload = {
        "kind": "clarification_required",
        "action_type": "clarify_entry",
        "step_id": "clarify_entry",
        "title": "需要补充信息",
        "message": issue["message"],
        "summary": issue["summary"],
        "original_text": state.entry_text,
        "missing_information": decision.missing_information,
        "options": issue["options"],
    }
    state.add_event("clarification_required", payload)
    return {"pending_confirmation": payload, "events": state.events}


def _node_interrupt_clarify(state: AgentGraphState) -> dict:
    """Pause the graph for human clarification and process the resume value.

    Expects ``state.pending_confirmation`` to be populated by the upstream
    ``_node_prepare_clarify`` node (and therefore present in the checkpoint).
    """
    payload = state.pending_confirmation
    if payload is None:
        return {}

    resume_value = interrupt(payload)
    decision = str(_resume_value_get(resume_value, "decision", "clarify")).lower()
    if decision in ("reject", "cancel"):
        state.answer = "已取消。你可以重新发送更完整的内容。"
        state.answer_completed = True
        state.execution_trace = ["用户取消补充信息，流程结束"]
        state.add_event("clarification_resumed", {"decision": "cancelled"})
        return {
            "pending_confirmation": None,
            "answer": state.answer,
            "answer_completed": True,
            "execution_trace": state.execution_trace,
            "events": state.events,
        }

    supplemental = str(_resume_value_get(resume_value, "text", "")).strip()
    option_id = str(_resume_value_get(resume_value, "option_id", "")).strip()
    if not supplemental:
        state.answer = "还需要补充具体内容后才能继续。请重新发起请求，并说明要记录、查询、总结或执行什么。"
        state.answer_completed = True
        state.execution_trace = ["补充信息为空，流程结束"]
        state.add_event("clarification_resumed", {"decision": "empty"})
        return {
            "pending_confirmation": None,
            "answer": state.answer,
            "answer_completed": True,
            "execution_trace": state.execution_trace,
            "events": state.events,
        }

    clarified_text = _merge_clarification_text(state.entry_text, supplemental, option_id)
    state.entry_text = clarified_text
    if state.entry_input is not None:
        state.entry_input = state.entry_input.model_copy(update={"text": clarified_text})
    else:
        state.entry_input = EntryInput(
            text=clarified_text,
            user_id=state.user_id,
            session_id=state.session_id,
        )
    state.add_event("clarification_resumed", {
        "decision": "clarified",
        "option_id": option_id,
        "text_preview": clarified_text[:120],
    })
    state.router_decision = None
    return {
        "entry_text": clarified_text,
        "entry_input": state.entry_input,
        "messages": [HumanMessage(content=supplemental, id=f"{state.run_id}:clarification")],
        "pending_confirmation": None,
        "router_decision": None,
        "events": state.events,
    }


def _after_prepare_clarify(state: AgentGraphState) -> str:
    """Route to interrupt after its payload has been checkpointed."""
    if state.pending_confirmation is not None:
        return "interrupt_clarify_entry"
    return "route_intent"


def _after_interrupt_clarify(state: AgentGraphState) -> str:
    """After interrupt, go to finalize if cancelled/empty, else continue to route_intent."""
    if state.answer_completed:
        return "finalize_entry_result"
    return "route_intent"


# ============================================================================
# Phase 6: route_intent → should_plan → plan_task → validate_plan (split from
# the former composite route_and_plan node)
# ============================================================================


def _node_route_intent(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Session binding + intent classification (no planning yet).

    Checkpoint boundary: after this node the intent is known and can be
    inspected / resumed without re-running classification.
    """
    from ..core.logging_utils import log_event as _log_event

    if state.entry_input is None:
        state.entry_input = EntryInput(
            text=state.entry_text,
            user_id=state.user_id,
            session_id=state.session_id,
        )

    deps.memory.bind_session(state.user_id, state.session_id)
    deps.memory.refresh_conversation_summary(state.user_id, state.session_id)
    conversation_context = _format_dialogue_context(state.messages, exclude_latest=True)
    decision = deps.intent_router.classify(
        state.entry_input,
        conversation_context=conversation_context,
    )
    deps.memory.working.set_goal(
        f"入口任务[{decision.route}]: {state.entry_input.text[:60]}"
    )

    state.router_decision = decision
    state.plan_steps = []
    state.execution_trace = []

    state.add_event("intent_classified", {
        "intent": decision.route,
        "reason": decision.user_visible_message,
        "confidence": decision.confidence,
        "risk_level": decision.risk_level,
        "requires_planning": decision.requires_planning,
        "requires_clarification": decision.requires_clarification,
    })

    _log_event(
        logger,
        logging.INFO,
        "entry.route.decision",
        user_id=state.user_id,
        session_id=state.session_id,
        route=decision.route,
        requires_planning=decision.requires_planning,
        requires_clarification=decision.requires_clarification,
        reason=decision.user_visible_message,
    )

    logger.info(
        "route_intent run_id=%s intent=%s requires_planning=%s requires_clarification=%s",
        state.run_id, decision.route, decision.requires_planning, decision.requires_clarification,
    )

    return {
        "router_decision": state.router_decision,
        "plan_steps": [],
        "execution_trace": [],
        "events": state.events,
    }


def _node_plan_task(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Generate structured plan steps via the task planner.

    Checkpoint boundary: after this node the plan steps exist and can be
    inspected before validation.
    """
    route = state.router_decision.route if state.router_decision else "unknown"
    entry_text = state.entry_text or (state.entry_input.text if state.entry_input else "")
    steps = deps.planner.plan(route, entry_text)
    plan_states = [PlanStepState.from_plan_step(s) for s in steps]

    state.plan_steps = plan_states
    state.add_event("plan_created", {"plan_steps": [pss.model_dump(mode="json") for pss in plan_states]})

    logger.info(
        "plan_task run_id=%s route=%s steps=%d",
        state.run_id, route, len(plan_states),
    )
    return {"plan_steps": plan_states, "events": state.events}


def _node_validate_plan(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Validate plan steps and handle blocking / fallback / reversion.

    Checkpoint boundary: after this node the plan is either confirmed valid
    or the intent has been reverted to a clarification fallback (unknown).

    If validation completely fails (blocking after retry), the intent is
    reverted to ``unknown`` and ``requires_planning`` is set to ``False`` so
    the routing layer sends the entry to the clarification/direct-answer path.
    """
    from .router import RouterDecision

    decision = state.router_decision or RouterDecision(route="unknown")

    steps = [sd.to_plan_step() for sd in (state.plan_steps or [])]
    validation = deps.plan_validator.validate(steps, decision)

    if validation.blocking:
        logger.warning(
            "Plan validation blocked: %d issues, %d warnings. Issues: %s",
            len(validation.issues), len(validation.warnings), validation.issues,
        )
        if validation.corrected_steps:
            validated_steps = validation.corrected_steps
        else:
            validated_steps = deps.planner.fallback_plan(decision.route)
            revalidation = deps.plan_validator.validate(validated_steps, decision)
            if revalidation.blocking:
                logger.error(
                    "Heuristic plan also blocked: %s. Reverting to unknown.",
                    revalidation.issues,
                )
                decision = RouterDecision(
                    route="unknown",
                    confidence=0.1,
                    risk_level="low",
                    user_visible_message=f"计划校验失败: {'; '.join(revalidation.issues[:3])}",
                )
                validated_steps = deps.planner.fallback_plan("unknown")
                # Revert intent so the routing layer skips plan execution
                state.router_decision = decision
                state.add_event("plan_validated", {
                    "outcome": "reverted_to_unknown",
                    "issues": validation.issues,
                })
    else:
        validated_steps = validation.corrected_steps or steps
        if not validation.ok:
            logger.warning(
                "Plan validation found %d non-blocking issues: %s",
                len(validation.issues), validation.warnings,
            )

    plan_states = [PlanStepState.from_plan_step(s) for s in validated_steps]
    state.plan_steps = plan_states

    logger.info(
        "validate_plan run_id=%s steps=%d blocked=%s requires_planning=%s",
        state.run_id, len(plan_states), validation.blocking, state.router_decision.requires_planning if state.router_decision else False,
    )
    return {
        "plan_steps": plan_states,
        "router_decision": state.router_decision,
        "events": state.events,
    }


def _after_validate_plan(state: AgentGraphState) -> str:
    """After validation: enter plan execution or ask the user to clarify."""
    if (state.router_decision and state.router_decision.requires_planning) and state.plan_steps:
        return "prepare_plan_execution"
    return "direct_answer_branch"


def _node_capture_branch(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Execute capture branch for capture_text / capture_link / capture_file intents.

    Uses the already-classified intent from ``state.router_decision`` — no duplicate routing.
    """
    entry_input = state.entry_input
    if entry_input is None:
        state.answer = "未收到可采集内容。"
        state.execution_trace = _execution_trace_for_intent(state.router_decision.route if state.router_decision else "unknown")
        return {"answer": state.answer, "execution_trace": state.execution_trace}

    intent = state.router_decision.route if state.router_decision else "unknown"
    logger.debug("Executing capture branch intent=%s user=%s", intent, state.user_id)

    if intent == "capture_file":
        file_path = entry_input.metadata.get("file_path", "")
        if file_path:
            from pathlib import Path

            path = Path(file_path)
            if path.exists() and deps.capture_service is not None:
                original_filename = entry_input.metadata.get("original_filename", path.name)
                file_bytes = path.read_bytes()
                capture_text = deps.capture_service.capture_text_from_upload(
                    filename=original_filename,
                    content_type=None,
                    file_bytes=file_bytes,
                    source_type="file",
                )
                result = deps.execute_capture(
                    text=capture_text,
                    source_type="file",
                    user_id=entry_input.user_id,
                    source_ref=entry_input.source_ref or file_path,
                )
                state.answer = f"已收进知识库：{result.note.title}"
                state.execution_trace = _execution_trace_for_intent(intent)
                return {"answer": state.answer, "execution_trace": state.execution_trace}
        state.answer = "文件消息已识别，但文件内容暂未获取到。请通过 Web 端上传文件，或稍后重试。"
        state.execution_trace = _execution_trace_for_intent(intent)
        return {"answer": state.answer, "execution_trace": state.execution_trace}

    capture_text = entry_input.text
    source_type = "text"
    source_ref = entry_input.source_ref
    if intent == "capture_link":
        source_type = "link"
        url = entry_input.metadata.get("url") or _first_url(entry_input.text)
        if not url:
            state.answer = "识别成了链接采集，但消息里没有找到可用链接。"
            state.execution_trace = _execution_trace_for_intent(intent)
            return {"answer": state.answer, "execution_trace": state.execution_trace}
        source_ref = url
        if deps.capture_service is None:
            state.answer = "当前没有可用的采集服务，暂时无法抓取链接正文。"
            state.execution_trace = _execution_trace_for_intent(intent)
            return {"answer": state.answer, "execution_trace": state.execution_trace}
        capture_text = deps.capture_service.capture_text_from_url(url)

    result = deps.execute_capture(
        text=capture_text,
        source_type=source_type,
        user_id=entry_input.user_id,
        source_ref=source_ref,
    )
    state.answer = f"已收进知识库：{result.note.title}"
    state.execution_trace = _execution_trace_for_intent(intent)
    return {"answer": state.answer, "execution_trace": state.execution_trace}


def _node_ask_branch(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Execute ask branch — already classified, no duplicate routing."""
    entry_input = state.entry_input
    if entry_input is None or not entry_input.text.strip():
        state.answer = "未收到可提问内容。"
        return {"answer": state.answer}

    logger.debug("Executing ask branch user=%s question=%s", state.user_id, entry_input.text[:80])
    conversation_context = _format_dialogue_context(state.messages, exclude_latest=True)
    result = deps.execute_ask(
        entry_input.text,
        entry_input.user_id,
        entry_input.session_id,
        conversation_context=conversation_context,
    )
    state.answer = result.answer
    state.citations = result.citations
    state.execution_trace = _execution_trace_for_intent(state.router_decision.route if state.router_decision else "unknown")
    state.matches = [
        {"id": m.id, "title": m.title, "summary": m.summary}
        for m in (result.matches or [])
    ]
    return {
        "answer": state.answer,
        "citations": state.citations,
        "matches": state.matches,
        "execution_trace": state.execution_trace,
    }


def _node_summarize_branch(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Execute summarize_thread branch — already classified, no duplicate routing."""
    entry_input = state.entry_input
    if entry_input is None:
        state.answer = "未收到可总结的内容。"
        return {"answer": state.answer}

    logger.debug("Executing summarize branch user=%s", state.user_id)

    import json as _json

    thread_messages_raw = entry_input.metadata.get("thread_messages", "")
    if thread_messages_raw and deps.summarize_thread is not None:
        try:
            messages = _json.loads(thread_messages_raw)
            if isinstance(messages, list) and messages:
                messages_text = "\n".join(
                    f"[{m.get('role', 'unknown')}]: {m.get('content', '')}"
                    for m in messages
                )
                summary = deps.summarize_thread(messages_text, entry_input.user_id or "default")
                state.answer = summary
                state.execution_trace = _execution_trace_for_intent(state.router_decision.route if state.router_decision else "unknown")
                return {"answer": state.answer, "execution_trace": state.execution_trace}
        except (_json.JSONDecodeError, Exception):
            pass

    chat_id = entry_input.metadata.get("chat_id", "")
    if chat_id:
        state.answer = (
            "已识别为群聊总结诉求。当前暂时无法获取会话消息，请稍后重试，"
            "或直接粘贴需要总结的聊天内容。"
        )
    else:
        state.answer = "已识别为总结诉求。请直接发送需要总结的文本内容，或在群聊中使用此功能。"
    state.execution_trace = _execution_trace_for_intent(state.router_decision.route if state.router_decision else "unknown")
    return {"answer": state.answer, "execution_trace": state.execution_trace}


def _node_direct_answer_branch(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Execute direct answer or classification-driven clarification."""
    entry_input = state.entry_input
    if entry_input is None or not entry_input.text.strip():
        state.answer = "你好，有什么可以帮你的？"
        return {"answer": state.answer}

    logger.debug("Executing direct_answer branch user=%s", state.user_id)

    if not state.router_decision or state.router_decision.route == "unknown":
        state.answer = _build_clarification_answer(state)
        route = state.router_decision.route if state.router_decision else "unknown"
        state.execution_trace = _execution_trace_for_intent(route)
        return {"answer": state.answer, "execution_trace": state.execution_trace}

    if (
        deps.settings.openai_api_key
        and deps.settings.openai_base_url
        and deps.settings.openai_small_model
    ):
        from openai import OpenAI

        try:
            client = OpenAI(
                api_key=deps.settings.openai_api_key,
                base_url=deps.settings.openai_base_url,
                timeout=deps.settings.openai_timeout_seconds,
                max_retries=deps.settings.openai_max_retries,
            )
            dialogue_messages = _dialogue_prompt_messages(state.messages)
            if not dialogue_messages:
                dialogue_messages = [{"role": "user", "content": entry_input.text}]
            response = client.chat.completions.create(
                model=deps.settings.openai_small_model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个友好、简洁的个人知识库助手。直接回答用户，不需要检索知识库。保持简短。",
                    },
                    *dialogue_messages,
                ],
                max_tokens=300,
            )
            generated = (response.choices[0].message.content or "").strip()
            if generated:
                state.answer = generated
                route = state.router_decision.route if state.router_decision else "unknown"
                state.execution_trace = _execution_trace_for_intent(route)
                return {"answer": state.answer, "execution_trace": state.execution_trace}
        except Exception:
            logger.exception("Direct answer LLM call failed")

    state.answer = _simple_direct_answer(entry_input.text)
    route = state.router_decision.route if state.router_decision else "unknown"
    state.execution_trace = _execution_trace_for_intent(route)
    return {"answer": state.answer, "execution_trace": state.execution_trace}


# ---------------------------------------------------------------------------
# Helpers ported from entry_nodes.py
# ---------------------------------------------------------------------------


def _first_url(text: str) -> str | None:
    import re

    match = re.search(r"https?://\S+", text)
    if match is None:
        return None
    return match.group(0).rstrip(".,);]}>\"'")


def _simple_direct_answer(text: str) -> str:
    """Generate a simple reply without LLM, for when LLM is unavailable."""
    lower = text.strip().lower()
    greetings = {"你好", "hello", "hi", "嗨", "hey", "晚上好", "早上好", "下午好"}
    thanks = {"谢谢", "感谢", "thanks", "thank"}
    goodbye = {"再见", "bye", "拜拜", "晚安"}
    if any(g in lower for g in greetings):
        return "你好！有什么可以帮你的？"
    if any(g in lower for g in thanks):
        return "不客气，还有其他需要吗？"
    if any(g in lower for g in goodbye):
        return "再见，祝你好运！"
    return "我暂时无法生成这个问题的直接回答，请稍后重试。"


_EXECUTION_TRACE_MAP: dict[str, list[str]] = {
    "ask": [
        "在知识库和图谱中检索相关内容",
        "整合检索到的证据，生成自然语言回答",
        "校验回答的事实依据和引用完整性",
        "若证据不足，通过网络搜索补充外部信息",
    ],
    "capture_text": [
        "采集内容并写入知识库",
        "整理采集结果，生成标题和摘要",
        "校验笔记完整性和格式",
    ],
    "capture_link": [
        "抓取链接内容",
        "采集内容并写入知识库",
        "整理采集结果",
    ],
    "capture_file": [
        "解析上传文件",
        "采集内容并写入知识库",
        "整理采集结果",
    ],
    "summarize_thread": [
        "获取群聊消息记录",
        "按主题分点总结讨论要点和结论",
    ],
    "direct_answer": [
        "直接生成简短回复",
    ],
}


def _execution_trace_for_intent(intent: str) -> list[str]:
    return _EXECUTION_TRACE_MAP.get(intent, ["生成通用回复"])


def _build_clarification_answer(state: AgentGraphState) -> str:
    """Build a clarification prompt from the classify result."""
    rd = state.router_decision
    if rd is None:
        return "我暂时没判断出你的意图。你可以说明这是要记录、查询、总结，还是要执行某个操作。"
    missing = [
        str(item).strip()
        for item in rd.missing_information
        if str(item).strip()
    ]
    reason = (rd.user_visible_message or "").strip()

    if missing:
        details = "、".join(missing[:3])
        return f"我还需要你补充：{details}。你可以说明这是要记录、查询、总结，还是要执行某个操作。"

    if reason and "计划校验失败" in reason:
        return f"{reason}。请补充更明确的目标或操作范围后我再继续。"

    return "我暂时没判断出你的意图。你可以说明这是要记录、查询、总结，还是要执行某个操作。"


def _execution_trace_for_intent(intent: str) -> list[str]:
    """Return a lightweight trace for non-planning branches."""
    trace_map = {
        "ask": [
            "在知识库和图谱中检索相关内容",
            "整合检索到的证据，生成自然语言回答",
            "校验回答的事实依据和引用完整性",
            "若证据不足，通过网络搜索补充外部信息",
        ],
        "capture_text": [
            "采集内容并写入知识库",
            "整理采集结果，生成标题和摘要",
            "校验笔记完整性和格式",
        ],
        "capture_link": [
            "抓取链接内容",
            "采集内容并写入知识库",
            "整理采集结果",
        ],
        "capture_file": [
            "解析上传文件",
            "采集内容并写入知识库",
            "整理采集结果",
        ],
        "summarize_thread": [
            "获取群聊消息记录",
            "按主题分点总结讨论要点和结论",
        ],
        "direct_answer": [
            "直接生成简短回复",
        ],
        "unknown": [
            "根据意图识别结果请求用户补充信息",
        ],
    }
    return trace_map.get(intent, ["生成通用回复"])


def _node_finalize_entry_result(state: AgentGraphState) -> dict:
    if state.errors:
        state.add_event("run_failed", {"errors": state.errors})
    else:
        state.answer_completed = True
        if not any(event.type == "answer_completed" for event in state.events):
            state.add_event("answer_completed", {"answer": state.answer})
        state.add_event("run_completed", {
            "answer": state.answer,
            "intent": state.router_decision.route if state.router_decision else "unknown",
        })
    logger.info(
        "finalize_entry_result run_id=%s intent=%s errors=%d",
        state.run_id, state.router_decision.route if state.router_decision else "unknown", len(state.errors),
    )
    result = {
        "answer_completed": state.answer_completed,
        "events": state.events,
        "updated_at": state.updated_at,
    }
    if not state.errors and state.answer:
        result["messages"] = [
            AIMessage(content=state.answer, id=f"{state.run_id}:assistant")
        ]
    return result


# ===================================================================
# Phase 2: plan execution loop nodes (step-level checkpointing)
# ===================================================================


def _node_prepare_plan_execution(state: AgentGraphState) -> dict:
    """Sort plan steps and initialise execution state."""
    if not state.plan_steps:
        logger.info("prepare_plan_execution: no steps to execute")
        state.plan_aborted = True
        return {"plan_aborted": True}

    # Topologically sort steps
    sorted_steps = _topological_sort_steps(state.plan_steps)
    state.plan_steps = sorted_steps
    state.current_step_index = 0
    state.plan_aborted = False
    state.step_results = state.step_results or {}
    state.plan_retry_counts = state.plan_retry_counts or {}

    state.add_event("step_started", {
        "step_id": "__plan__",
        "description": f"开始执行 {len(sorted_steps)} 步计划",
    })
    logger.info(
        "prepare_plan_execution run_id=%s steps=%d",
        state.run_id, len(sorted_steps),
    )
    return {
        "plan_steps": sorted_steps,
        "current_step_index": 0,
        "plan_aborted": False,
        "step_results": state.step_results,
        "plan_retry_counts": state.plan_retry_counts,
        "events": state.events,
    }


def _node_select_next_step(state: AgentGraphState) -> dict:
    """Find the next unexecuted step and set current_step_index.

    Skips steps with status 'skipped' or 'completed'.
    Returns with updated current_step_index or leaves it unchanged
    when no more steps remain (checked by the conditional edge).
    """
    for i, sd in enumerate(state.plan_steps):
        if sd.status in ("planned",):
            state.current_step_index = i
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
                "current_step_index": i,
                "plan_steps": state.plan_steps,
                "events": state.events,
            }

    # No more steps
    logger.info("select_next_step run_id=%s: no more steps", state.run_id)
    return {}


def _node_execute_plan_step(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Dispatch a single plan step.  Raises on failure; retry/replan handled
    by the handle_step_result node.

    Idempotency: if a tool_call step already has a result in step_results,
    skip execution.

    ReAct steps are *not* dispatched here — the state is seeded and the
    ``_after_step_execution`` conditional edge routes to the ``react_step``
    subgraph.
    """
    if state.current_step_index >= len(state.plan_steps):
        return {}

    sd = state.plan_steps[state.current_step_index]
    step = sd.to_plan_step()

    # Idempotency: skip side-effect steps that already ran
    if step.action_type == "tool_call" and step.tool_name:
        idem_key = step.step_id
        if idem_key in state.step_results:
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
                "plan_steps": state.plan_steps,
                "step_results": state.step_results,
                "events": state.events,
            }

    # ---- ReAct branch: seed state and let subgraph handle execution ----
    if getattr(step, "execution_mode", "deterministic") == "react":
        state.react_step_id = step.step_id
        state.react_max_iterations = min(step.max_iterations, _REACT_MAX_ITERATIONS_CAP)
        state.react_allowed_tools = list(_resolve_allowed_tools_for_step(step, deps))
        state.react_iteration_index = 0
        state.react_done = False
        state.react_result = {}
        state.react_user_prompt = ""
        state.react_iterations = []
        logger.info(
            "Seeded ReAct state for step %s (max_iter=%d, tools=%s)",
            step.step_id, state.react_max_iterations, state.react_allowed_tools,
        )
        # Status stays "running" — _after_step_execution routes to react_step subgraph
        return {
            "plan_steps": state.plan_steps,
            "react_step_id": state.react_step_id,
            "react_max_iterations": state.react_max_iterations,
            "react_allowed_tools": state.react_allowed_tools,
            "react_iteration_index": 0,
            "react_done": False,
            "react_result": {},
            "react_user_prompt": "",
            "react_iterations": [],
            "events": state.events,
        }

    try:
        _dispatch_plan_step(step, sd, state, deps)
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        logger.warning("Plan step %s failed: %s", step.step_id, err_msg)
        sd.status = "failed"
        sd.retry_count = sd.retry_count + 1
        state.plan_retry_counts[step.step_id] = sd.retry_count
        state.errors.append(f"[{step.step_id}] {err_msg}")
        state.add_event("step_failed", {
            "step_id": step.step_id,
            "error": err_msg,
            "on_failure": step.on_failure,
            "retry_count": sd.retry_count,
        })
        return {
            "plan_steps": state.plan_steps,
            "step_results": state.step_results,
            "errors": state.errors,
            "plan_retry_counts": state.plan_retry_counts,
            "events": state.events,
        }

    # If the step triggered a confirmation request, don't mark completed yet
    if state.pending_confirmation is not None:
        sd.status = "awaiting_confirmation"
        state.add_event("confirmation_required", state.pending_confirmation)
        logger.info("Step %s awaiting confirmation", step.step_id)
        return {
            "plan_steps": state.plan_steps,
            "step_results": state.step_results,
            "answer": state.answer,
            "pending_confirmation": state.pending_confirmation,
            "events": state.events,
        }

    # Normal success — no confirmation needed
    sd.status = "completed"
    state.add_event("step_completed", {
        "step_id": step.step_id,
        "result_summary": _summarize_result(state.step_results.get(step.step_id)),
    })
    return {
        "plan_steps": state.plan_steps,
        "step_results": state.step_results,
        "answer": state.answer,
        "events": state.events,
    }


def _node_handle_step_success(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Post-success: inject dependencies, mark drafts solidified."""
    if state.current_step_index >= len(state.plan_steps):
        return {}

    sd = state.plan_steps[state.current_step_index]
    step = sd.to_plan_step()

    # Inject resolved note_id into dependent tool_call steps
    if step.action_type == "resolve":
        result_data = state.step_results.get(step.step_id)
        if isinstance(result_data, dict) and result_data.get("note_id"):
            _inject_note_id_into_steps(
                step.step_id, str(result_data["note_id"]), state.plan_steps,
            )

    # Inject compose draft text into dependent capture_text steps
    if step.action_type == "compose":
        result_data = state.step_results.get(step.step_id)
        if isinstance(result_data, dict) and result_data.get("answer"):
            _inject_draft_text_into_steps(
                step.step_id, str(result_data["answer"]), state.user_id, state.plan_steps,
            )

    if step.action_type == "tool_call" and step.tool_name == "capture_text":
        _mark_upstream_drafts_solidified(step, state, deps)

    logger.info(
        "handle_step_success run_id=%s step=%s",
        state.run_id, step.step_id,
    )
    return {"plan_steps": state.plan_steps, "events": state.events}


def _node_handle_step_failure(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Handle a failed step: retry, replan, skip, or abort."""
    if state.current_step_index >= len(state.plan_steps):
        return {}

    sd = state.plan_steps[state.current_step_index]
    step = sd.to_plan_step()
    on_failure = sd.on_failure
    retry_count = sd.retry_count

    # Retry logic
    if on_failure == "retry" and retry_count < _MAX_RETRIES:
        logger.info(
            "Retrying step %s (attempt %d/%d)",
            step.step_id, retry_count + 1, _MAX_RETRIES,
        )
        state.add_event("replan_attempted", {
            "step_id": step.step_id,
            "attempt": retry_count + 1,
            "max_retries": _MAX_RETRIES,
        })
        time.sleep(_RETRY_DELAY_SECONDS)
        sd.status = "planned"  # Reset so select_next_step picks it up again
        return {"plan_steps": state.plan_steps}

    # Retries exhausted — try replanning
    if on_failure == "retry" and retry_count >= _MAX_RETRIES:
        replanner = deps.replanner
        if replanner is not None:
            state.add_event("replan_attempted", {
                "step_id": step.step_id,
                "reason": "重试耗尽，尝试重新规划",
            })
            try:
                intent = state.router_decision.route if state.router_decision else "unknown"
                err_msg = state.errors[-1] if state.errors else "未知错误"
                # Reconstruct plan step objects for replanner
                step_objs = [s.to_plan_step() for s in state.plan_steps]
                revised = replanner.replan(
                    step_objs, step, err_msg, state.step_results, intent,
                )
                if revised:
                    # Validate revised steps
                    plan_validator = deps.plan_validator
                    if plan_validator is not None:
                        from .router import RouterDecision
                        decision = state.router_decision or RouterDecision(route="unknown")
                        validation = plan_validator.validate(revised, decision)
                        if validation.blocking:
                            logger.warning(
                                "Replan validation blocked for step %s: %s",
                                step.step_id, validation.issues,
                            )
                            state.add_event("replan_completed", {
                                "step_id": step.step_id,
                                "result": "blocked",
                                "issues": validation.issues,
                            })
                            sd.status = "failed"
                            state.plan_aborted = True
                            state.answer = state.answer or f"计划执行失败: {'; '.join(validation.issues[:3])}"
                            return {
                                "plan_steps": state.plan_steps,
                                "plan_aborted": True,
                                "answer": state.answer,
                            }
                        if validation.corrected_steps:
                            revised = validation.corrected_steps

                    # Mark failed step as skipped, skip its dependents
                    _skip_step_dependents(step.step_id, state.plan_steps)
                    sd.status = "skipped"

                    # Append revised steps
                    for r in revised:
                        state.plan_steps.append(PlanStepState.from_plan_step(r))
                    state.plan_steps = _topological_sort_steps(state.plan_steps)

                    state.add_event("replan_completed", {
                        "step_id": step.step_id,
                        "revised_step_count": len(revised),
                    })
                    logger.info(
                        "Replanned step %s: %d revised steps added",
                        step.step_id, len(revised),
                    )
                    return {"plan_steps": state.plan_steps}
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
        state.plan_aborted = True
        state.answer = state.answer or f"执行中断于步骤 {step.step_id}。"
        return {"plan_steps": state.plan_steps, "plan_aborted": True, "answer": state.answer}

    if on_failure in ("skip", "retry"):
        _skip_step_dependents(step.step_id, state.plan_steps)

    logger.info(
        "handle_step_failure run_id=%s step=%s on_failure=%s",
        state.run_id, step.step_id, on_failure,
    )
    return {"plan_steps": state.plan_steps}


def _node_confirm_step(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Pause the graph for human confirmation via ``interrupt()``.

    First invocation: ``interrupt()`` pauses the graph and returns an
    ``__interrupt__`` payload from ``graph.invoke()``. On resume (re-entered
    via ``Command(resume=...)``), ``interrupt()`` returns the user's decision
    dict and the node processes the confirm / reject action.
    """
    if state.current_step_index >= len(state.plan_steps):
        return {}

    sd = state.plan_steps[state.current_step_index]
    step = sd.to_plan_step()
    pending = state.pending_confirmation or {}

    # ---- Build the interrupt payload (presented to the caller) ----
    confirm_payload = {
        "step_id": step.step_id,
        "action_type": pending.get("action_type", step.action_type),
        "action_id": pending.get("action_id"),
        "token": pending.get("token"),
        "note_id": pending.get("note_id"),
        "title": pending.get("title", ""),
        "summary": pending.get("summary", ""),
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
        # Re-execute the tool with confirmed=True parameters
        tool_input = dict(step.tool_input or {})
        tool_input["confirmed"] = True
        tool_input["action_id"] = pending.get("action_id", "")
        tool_input["token"] = pending.get("token", "")

        result = deps.tool_registry.execute(step.tool_name, **tool_input)
        if result is not None and hasattr(result, "ok") and not result.ok:
            err_msg = result.error or f"确认后工具 {step.tool_name} 执行失败"
            sd.status = "failed"
            state.pending_confirmation = None
            state.confirmation_decision = "rejected"
            state.errors.append(f"[{step.step_id}] {err_msg}")
            state.add_event("step_failed", {
                "step_id": step.step_id,
                "error": err_msg,
            })
            logger.warning("Confirmed step %s failed: %s", step.step_id, err_msg)
            return {
                "plan_steps": state.plan_steps,
                "errors": state.errors,
                "confirmation_decision": "rejected",
            }

        result_data = (
            result.data
            if hasattr(result, "data") and result.data is not None
            else {"ok": True, "confirmed": True, "note_id": pending.get("note_id")}
        )
        state.step_results[step.step_id] = result_data
        sd.status = "completed"
        state.confirmation_decision = "confirmed"
        state.pending_confirmation = None

        state.add_event("confirmation_resumed", {
            "step_id": step.step_id,
            "decision": "confirmed",
        })
        state.add_event("step_completed", {
            "step_id": step.step_id,
            "result_summary": _summarize_result(result_data),
        })
        logger.info("Step %s confirmed and executed", step.step_id)
        return {
            "plan_steps": state.plan_steps,
            "confirmation_decision": "confirmed",
        }

    # Reject (or unknown decision)
    sd.status = "skipped"
    _skip_step_dependents(step.step_id, state.plan_steps)
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
        "plan_steps": state.plan_steps,
        "confirmation_decision": "rejected",
    }


def _node_finalize_plan_execution(state: AgentGraphState) -> dict:
    """Compose default answer if none was set, mark execution complete."""
    if not state.answer:
        state.answer = _default_plan_answer(state.plan_steps)

    state.answer_completed = True

    # Phase 5: derive execution_trace from structured events
    from .orchestration_models import execution_trace_from_events
    state.execution_trace = execution_trace_from_events(state.events)

    state.add_event("answer_completed", {"answer": state.answer})
    logger.info(
        "finalize_plan_execution run_id=%s answer_len=%d trace_items=%d",
        state.run_id, len(state.answer or ""), len(state.execution_trace),
    )
    return {
        "answer": state.answer,
        "answer_completed": True,
        "execution_trace": state.execution_trace,
        "events": state.events,
        "updated_at": state.updated_at,
    }


# ---------------------------------------------------------------------------
# Step dispatch (reuses PlanExecutor logic)
# ---------------------------------------------------------------------------

def _dispatch_plan_step(
    step: "PlanStep",
    sd: PlanStepState,
    state: AgentGraphState,
    deps: OrchestrationDeps,
) -> None:
    """Execute a single step by action_type. Raises on failure.

    This mirrors ``PlanExecutor._dispatch_step`` but operates on
    ``AgentGraphState`` instead of ``AgentState``.
    """
    step_results: dict = state.step_results

    if step.action_type == "retrieve":
        result_data = _execute_retrieve_step(step, state, deps)
        step_results[step.step_id] = result_data

    elif step.action_type == "tool_call":
        result_data = _execute_tool_call_step(step, deps)
        step_results[step.step_id] = result_data
        if isinstance(result_data, dict) and result_data.get("pending_confirmation"):
            state.pending_confirmation = {
                "step_id": step.step_id,
                "action_id": result_data.get("action_id"),
                "token": result_data.get("token"),
                "action_type": "delete_note",
                "note_id": result_data.get("note_id"),
                "title": result_data.get("title"),
                "summary": result_data.get("summary"),
            }

    elif step.action_type == "resolve":
        result_data = _execute_resolve_step(step, state, deps)
        step_results[step.step_id] = result_data

    elif step.action_type == "compose":
        answer = _execute_compose_step(step, state, deps)
        state.answer = answer
        step_results[step.step_id] = {"answer": answer, "draft": True}
        if state.router_decision and state.router_decision.route == "solidify_conversation" and answer:
            try:
                draft_id = deps.memory.save_draft(
                    state.user_id, answer, source_context=state.entry_text[:500],
                )
                if draft_id:
                    step_results[step.step_id]["draft_id"] = draft_id
            except Exception:
                logger.exception("Failed to save solidify draft")
        if answer:
            state.add_event("draft_ready", {
                "step_id": step.step_id,
                "draft_text": answer,
            })

    elif step.action_type == "verify":
        _execute_verify_step(step, state, deps)

    else:
        raise ValueError(f"未知的 action_type: {step.action_type}")


def _execute_retrieve_step(step, state: AgentGraphState, deps: OrchestrationDeps) -> object:
    question = step.tool_input.get("question") if step.tool_input else step.description
    result = deps.graph_store.ask(str(question), state.user_id)
    if result.enabled and result.answer:
        return {
            "answer": result.answer,
            "entity_names": result.entity_names,
            "relation_facts": result.relation_facts,
            "related_episode_uuids": result.related_episode_uuids,
        }
    return {"answer": "", "entity_names": [], "relation_facts": [], "hint": "graph disabled or empty"}


def _execute_tool_call_step(step, deps: OrchestrationDeps) -> object:
    if not step.tool_name:
        raise ValueError("tool_call step missing tool_name")
    result = deps.tool_registry.execute(
        step.tool_name, **(step.tool_input or {})
    )
    if result is not None and hasattr(result, "ok") and not result.ok:
        raise RuntimeError(result.error or f"Tool {step.tool_name} returned failure")
    return result.data if hasattr(result, "data") and result.data is not None else {"ok": True}


def _execute_resolve_step(step, state: AgentGraphState, deps: OrchestrationDeps) -> object:
    user_id = state.user_id
    original_query = state.entry_text or ""

    candidates: list[dict] = []

    # 1. Graph episode UUID mapping
    for sid, data in state.step_results.items():
        if not isinstance(data, dict):
            continue
        episode_uuids = data.get("related_episode_uuids")
        if isinstance(episode_uuids, list) and episode_uuids:
            str_uuids = [str(u) for u in episode_uuids if u]
            if str_uuids:
                try:
                    matched = deps.store.find_notes_by_graph_episode_uuids(user_id, str_uuids)
                    for note in matched:
                        candidates.append({
                            "note_id": note.id, "title": note.title,
                            "summary": note.summary, "source": "graph_episode",
                        })
                except Exception:
                    logger.exception("Episode UUID lookup failed in resolve")

    # 2. Local similarity
    if not candidates and original_query:
        try:
            similar = deps.store.find_similar_notes(user_id, original_query, limit=5)
            for note in similar:
                candidates.append({
                    "note_id": note.id, "title": note.title,
                    "summary": note.summary, "source": "text_similarity",
                })
        except Exception:
            logger.exception("Similarity search failed in resolve")

    # 3. Keyword match
    if not candidates:
        try:
            all_notes = deps.store.list_notes(user_id)
            ql = original_query.lower()
            for note in all_notes:
                if ql and (ql in note.title.lower() or ql in (note.content or "").lower()):
                    candidates.append({
                        "note_id": note.id, "title": note.title,
                        "summary": note.summary, "source": "keyword_match",
                    })
            candidates = candidates[:5]
        except Exception:
            logger.exception("Keyword fallback failed in resolve")

    if not candidates:
        return {"note_id": None, "candidates": [], "error": "未找到匹配的笔记。"}

    best = candidates[0]
    return {
        "note_id": best["note_id"],
        "title": best.get("title"),
        "summary": best.get("summary"),
        "source": best.get("source"),
        "candidates": candidates,
    }


def _execute_compose_step(step, state: AgentGraphState, deps: OrchestrationDeps) -> str:
    context_parts: list[str] = []
    for sid, data in state.step_results.items():
        if isinstance(data, dict):
            if data.get("answer"):
                context_parts.append(str(data["answer"]))
            if data.get("entity_names"):
                context_parts.append("实体: " + ", ".join(str(n) for n in data["entity_names"] if n))

    context = "\n".join(context_parts) if context_parts else "暂无检索结果。"

    if step.tool_input and step.tool_input.get("question"):
        question = str(step.tool_input["question"])
    else:
        question = step.description or "根据已有信息生成回答"

    if state.router_decision and state.router_decision.route == "solidify_conversation":
        dialogue = _format_solidify_candidate_context(state.messages) or context
        solidify_prompt = (
            "你负责决定哪些会话事实属于用户本次指定的固化范围，并将它们整理为一条可独立入库的中文知识笔记。"
            "候选会话可能同时包含多个无关主题，必须根据当前保存请求进行语义选择；"
            "不要仅因为某段出现在上下文中就写入笔记，也不要写入操作指令本身。"
            "如果候选会话中没有足以支撑本次请求的知识，请将正文留空。\n\n"
            "请输出 JSON："
            '{"thought":"范围判断理由","done":true,"result":{"selected_turn_ids":["turn-N"],'
            '"title":"知识标题","content":"仅包含被选择知识的正文"}}。\n\n'
            f"当前保存请求：{state.entry_text}\n\n候选会话：\n{dialogue}"
        )
        try:
            raw_answer = _react_llm_respond(solidify_prompt, deps)
            answer = _solidify_note_text(raw_answer) if raw_answer else None
        except Exception:
            logger.exception("Solidify compose step %s failed", step.step_id)
            answer = None
        if not answer:
            raise RuntimeError("模型未生成符合本次固化范围的知识草稿，未写入知识库。")
        return answer

    try:
        ask_result = deps.execute_ask(question, state.user_id)
        return ask_result.answer
    except Exception:
        logger.exception("Compose step %s failed", step.step_id)
        return f"根据已有信息：{context[:500]}"


def _mark_upstream_drafts_solidified(step, state: AgentGraphState, deps: OrchestrationDeps) -> None:
    by_id = {candidate.step_id: candidate for candidate in state.plan_steps}
    pending = list(step.depends_on)
    visited: set[str] = set()
    while pending:
        step_id = pending.pop()
        if step_id in visited:
            continue
        visited.add(step_id)
        result = state.step_results.get(step_id)
        if isinstance(result, dict):
            draft_id = result.get("draft_id")
            if draft_id:
                deps.memory.mark_draft_solidified(state.user_id, str(draft_id))
            for conclusion_id in result.get("conclusion_ids", []):
                deps.memory.mark_conclusion_solidified(state.user_id, str(conclusion_id))
        parent = by_id.get(step_id)
        if parent is not None:
            pending.extend(parent.depends_on)


def _execute_verify_step(step, state: AgentGraphState, deps: OrchestrationDeps) -> None:
    if not state.answer:
        return
    try:
        verifier = deps.verifier
        if verifier:
            verifier.verify(
                question=state.entry_text or "",
                answer=state.answer,
                citations=state.citations,
                matches=[],
            )
    except Exception:
        logger.exception("Verify step %s error", step.step_id)


# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------

def _should_execute_step(state: AgentGraphState) -> str:
    """Check if there are more steps to execute."""
    if state.plan_aborted:
        return "finalize_plan"
    if (
        state.current_step_index < len(state.plan_steps)
        and state.plan_steps[state.current_step_index].status == "running"
    ):
        return "execute_step"
    for sd in state.plan_steps:
        if sd.status in ("planned",):
            return "execute_step"
    return "finalize_plan"


def _after_step_execution(state: AgentGraphState) -> str:
    """Determine whether step succeeded, failed, awaits confirmation, or needs ReAct."""
    if state.current_step_index < len(state.plan_steps):
        sd = state.plan_steps[state.current_step_index]
        if sd.status == "awaiting_confirmation":
            return "confirm_step"
        if sd.status == "failed":
            return "handle_failure"
        if sd.execution_mode == "react" and sd.status == "running":
            return "react_step"
    return "handle_success"


def _after_step_failure(state: AgentGraphState) -> str:
    """After handling failure: continue or abort to finalize."""
    if state.plan_aborted:
        return "finalize_plan"
    return "continue_loop"


def _after_confirm_step(state: AgentGraphState) -> str:
    """After confirmation: route to success or failure handler."""
    if state.confirmation_decision == "confirmed":
        return "handle_success"
    return "handle_failure"


def _after_step_success(state: AgentGraphState) -> str:
    """After handling success: always continue to next step."""
    return "continue_loop"


def _summarize_result(data: object) -> str:
    if data is None:
        return "无结果"
    if isinstance(data, dict):
        answer = data.get("answer", "")
        if answer:
            return str(answer)[:100]
        return "已获取结果"
    if isinstance(data, str):
        return data[:100]
    return str(data)[:100]


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
        context_block = _build_react_context(step, state.step_results)
        tools_block = _format_react_tools(allowed, deps)
        state.react_user_prompt = (
            f"## 步骤描述\n{step.description}\n\n"
            f"## 已有上下文\n{context_block}\n\n"
            f"## 可用工具\n{tools_block}\n\n"
            f"请开始推理（最多 {max_iter} 轮）。"
        )

    # ---- Call LLM ----
    raw = _react_llm_respond(state.react_user_prompt, deps)
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

    parsed = _react_parse_response(raw)
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
            observation = _summarize_react_tool_result(tool_result.data if hasattr(tool_result, "data") else None)
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
        "result_summary": _summarize_result(result_to_persist),
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


