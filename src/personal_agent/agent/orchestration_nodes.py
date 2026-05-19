"""Entry orchestration graph — unified LangGraph shell for the entry pipeline.

This graph wraps the existing router / planner / PlanExecutor / entry graph
branches inside a single LangGraph StateGraph so that every entry run
benefits from checkpoint / interrupt / resume capabilities.

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
from typing import TYPE_CHECKING

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..core.models import EntryInput
from .orchestration_models import (
    AgentGraphState,
    _new_run_id,
    _new_thread_id,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .planner import PlanStep

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

def _plan_step_from_dict(sd: dict) -> "PlanStep":
    from .planner import PlanStep
    return PlanStep(
        step_id=str(sd.get("step_id", "")),
        action_type=str(sd.get("action_type", "")),
        description=str(sd.get("description", "")),
        tool_name=str(sd["tool_name"]) if sd.get("tool_name") else None,
        tool_input=dict(sd.get("tool_input") or {}),
        depends_on=list(sd.get("depends_on", [])),
        expected_output=str(sd.get("expected_output", "")),
        success_criteria=str(sd.get("success_criteria", "")),
        risk_level=str(sd.get("risk_level", "low")),
        requires_confirmation=bool(sd.get("requires_confirmation", False)),
        on_failure=str(sd.get("on_failure", "skip")),
        status=str(sd.get("status", "planned")),
        retry_count=int(sd.get("retry_count", 0)),
        execution_mode=str(sd.get("execution_mode", "deterministic")),
        allowed_tools=list(sd.get("allowed_tools", [])),
        max_iterations=int(sd.get("max_iterations", 3)),
    )


def _plan_step_to_dict(s: "PlanStep") -> dict:
    return {
        "step_id": s.step_id,
        "action_type": s.action_type,
        "description": s.description,
        "tool_name": s.tool_name,
        "tool_input": s.tool_input,
        "depends_on": s.depends_on,
        "expected_output": s.expected_output,
        "success_criteria": s.success_criteria,
        "risk_level": s.risk_level,
        "requires_confirmation": s.requires_confirmation,
        "on_failure": s.on_failure,
        "status": s.status,
        "retry_count": s.retry_count,
        "execution_mode": s.execution_mode,
        "allowed_tools": s.allowed_tools,
        "max_iterations": s.max_iterations,
    }


def _topological_sort_steps(steps: list) -> list:
    """Sort plan step dicts so dependencies come before dependents."""
    if len(steps) <= 1:
        return list(steps)
    step_ids = {s["step_id"] for s in steps if s.get("step_id")}
    indeg: dict[int, int] = {}
    adj: dict[int, list[int]] = {}
    for i, s in enumerate(steps):
        indeg[i] = 0
        adj[i] = []
        for dep_id in s.get("depends_on", []):
            if dep_id in step_ids:
                indeg[i] = indeg.get(i, 0) + 1
                for j, other in enumerate(steps):
                    if other.get("step_id") == dep_id:
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


def _inject_note_id_into_steps(resolve_step_id: str, note_id: str, plan_steps: list[dict]) -> None:
    for s in plan_steps:
        if s.get("status") != "planned":
            continue
        if (resolve_step_id in s.get("depends_on", [])
                and s.get("action_type") == "tool_call"
                and s.get("tool_name") == "delete_note"):
            if not s.get("tool_input"):
                s["tool_input"] = {}
            s["tool_input"]["note_id"] = note_id


def _inject_draft_text_into_steps(compose_step_id: str, text: str, plan_steps: list[dict]) -> None:
    for s in plan_steps:
        if s.get("status") != "planned":
            continue
        if (compose_step_id in s.get("depends_on", [])
                and s.get("action_type") == "tool_call"
                and s.get("tool_name") == "capture_text"):
            if not s.get("tool_input"):
                s["tool_input"] = {}
            s["tool_input"]["text"] = text


def _skip_step_dependents(failed_step_id: str, plan_steps: list[dict]) -> None:
    """Recursively mark dependents of a failed step as skipped."""
    for s in plan_steps:
        if s.get("status") != "planned":
            continue
        if failed_step_id in s.get("depends_on", []):
            s["status"] = "skipped"
            _skip_step_dependents(s["step_id"], plan_steps)


def _default_plan_answer(steps: list[dict]) -> str:
    completed = sum(1 for s in steps if s.get("status") == "completed")
    failed = sum(1 for s in steps if s.get("status") == "failed")
    skipped = sum(1 for s in steps if s.get("status") == "skipped")
    return f"计划执行完成：{completed} 步成功" + (
        f"，{failed} 步失败" if failed else ""
    ) + (
        f"，{skipped} 步跳过" if skipped else ""
    ) + "。"


# ---------------------------------------------------------------------------
# ReAct helper functions (ported from ReActStepRunner for graph use)
# ---------------------------------------------------------------------------


def _resolve_allowed_tools_for_step(step: "PlanStep", runtime) -> set[str]:
    allowed = set(step.allowed_tools) if step.allowed_tools else set(_REACT_DEFAULT_ALLOWED_TOOLS)
    registered = {t.name for t in runtime._tool_registry.list_tools()}
    return allowed & registered


def _is_react_tool_blocked(tool_name: str, runtime) -> bool:
    spec = None
    for t in runtime._tool_registry.list_tools():
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


def _format_react_tools(allowed: set[str], runtime) -> str:
    lines: list[str] = []
    for spec in runtime._tool_registry.list_tools():
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


def _react_llm_respond(user_prompt: str, runtime) -> str | None:
    from openai import OpenAI

    settings = runtime.settings
    if not (settings.openai_api_key and settings.openai_base_url):
        return None
    try:
        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
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

    thread_id = _new_thread_id(user_id, session_id, state.run_id)

    state.user_id = user_id
    state.session_id = session_id
    state.thread_id = thread_id
    state.entry_text = text
    state.created_at = state.created_at or state.updated_at

    state.add_event("entry_started", {"text_preview": text[:120] if text else ""})
    logger.info("normalize_entry run_id=%s thread_id=%s", state.run_id, thread_id)
    return {"user_id": user_id, "session_id": session_id, "thread_id": thread_id, "entry_text": text}


# ============================================================================
# Phase 6: route_intent → should_plan → plan_task → validate_plan (split from
# the former composite route_and_plan node)
# ============================================================================


def _node_route_intent(state: AgentGraphState, *, runtime) -> dict:
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

    runtime.memory.bind_session(state.user_id, state.session_id)
    runtime.memory.refresh_conversation_summary(state.user_id, state.session_id)
    decision = runtime._intent_router.classify(state.entry_input)
    runtime.memory.working.set_goal(
        f"入口任务[{decision.route}]: {state.entry_input.text[:60]}"
    )

    state.intent = decision.route
    state.intent_reason = decision.user_visible_message
    state.requires_planning = decision.requires_planning
    state.router_decision = {
        "route": decision.route,
        "confidence": decision.confidence,
        "risk_level": decision.risk_level,
        "requires_tools": decision.requires_tools,
        "requires_retrieval": decision.requires_retrieval,
        "requires_planning": decision.requires_planning,
        "requires_confirmation": decision.requires_confirmation,
        "candidate_tools": decision.candidate_tools,
        "missing_information": decision.missing_information,
        "user_visible_message": decision.user_visible_message,
    }
    state.plan_steps = []
    state.execution_trace = []

    state.add_event("intent_classified", {
        "intent": decision.route,
        "reason": decision.user_visible_message,
        "confidence": decision.confidence,
        "risk_level": decision.risk_level,
        "requires_planning": decision.requires_planning,
    })

    _log_event(
        logger,
        logging.INFO,
        "entry.route.decision",
        user_id=state.user_id,
        session_id=state.session_id,
        route=decision.route,
        requires_planning=decision.requires_planning,
        reason=decision.user_visible_message,
    )

    logger.info(
        "route_intent run_id=%s intent=%s requires_planning=%s",
        state.run_id, decision.route, decision.requires_planning,
    )

    return {
        "intent": decision.route,
        "intent_reason": decision.user_visible_message,
        "requires_planning": decision.requires_planning,
        "router_decision": state.router_decision,
        "plan_steps": [],
        "execution_trace": [],
    }


def _should_plan(state: AgentGraphState) -> str:
    """Conditional edge: decide whether to enter the planning branch."""
    if state.requires_planning:
        return "plan_task"
    return "execute_current_runtime_path"


def _node_plan_task(state: AgentGraphState, *, runtime) -> dict:
    """Generate structured plan steps via the task planner.

    Checkpoint boundary: after this node the plan steps exist and can be
    inspected before validation.
    """
    route = str(state.router_decision.get("route", state.intent))
    entry_text = state.entry_text or (state.entry_input.text if state.entry_input else "")
    steps = runtime._planner.plan(route, entry_text)
    plan_dicts = [_plan_step_to_dict(s) for s in steps]

    state.plan_steps = plan_dicts
    state.add_event("plan_created", {"plan_steps": plan_dicts})

    logger.info(
        "plan_task run_id=%s route=%s steps=%d",
        state.run_id, route, len(plan_dicts),
    )
    return {"plan_steps": plan_dicts}


def _node_validate_plan(state: AgentGraphState, *, runtime) -> dict:
    """Validate plan steps and handle blocking / fallback / reversion.

    Checkpoint boundary: after this node the plan is either confirmed valid
    or the intent has been reverted to a non-planning fallback (unknown).

    If validation completely fails (blocking after retry), the intent is
    reverted to ``unknown`` and ``requires_planning`` is set to ``False`` so
    the routing layer sends the entry to the legacy graph path.
    """
    from .router import RouterDecision

    rd = state.router_decision
    decision = RouterDecision(
        route=str(rd.get("route", state.intent)),
        confidence=float(rd.get("confidence", 0.5)),
        requires_tools=bool(rd.get("requires_tools", False)),
        requires_retrieval=bool(rd.get("requires_retrieval", False)),
        requires_planning=bool(rd.get("requires_planning", False)),
        risk_level=str(rd.get("risk_level", "low")),
        requires_confirmation=bool(rd.get("requires_confirmation", False)),
        missing_information=list(rd.get("missing_information", [])),
        candidate_tools=list(rd.get("candidate_tools", [])),
        user_visible_message=str(rd.get("user_visible_message", "")),
    )

    steps = [_plan_step_from_dict(sd) for sd in (state.plan_steps or [])]
    validation = runtime._plan_validator.validate(steps, decision)

    if validation.blocking:
        logger.warning(
            "Plan validation blocked: %d issues, %d warnings. Issues: %s",
            len(validation.issues), len(validation.warnings), validation.issues,
        )
        if validation.corrected_steps:
            validated_steps = validation.corrected_steps
        else:
            validated_steps = runtime._planner.fallback_plan(decision.route)
            revalidation = runtime._plan_validator.validate(validated_steps, decision)
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
                validated_steps = runtime._planner.fallback_plan("unknown")
                # Revert intent so the routing layer skips plan execution
                state.intent = "unknown"
                state.requires_planning = False
                state.router_decision["route"] = "unknown"
                state.router_decision["requires_planning"] = False
                state.router_decision["risk_level"] = "low"
                state.router_decision["user_visible_message"] = decision.user_visible_message
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

    plan_dicts = [_plan_step_to_dict(s) for s in validated_steps]
    state.plan_steps = plan_dicts

    logger.info(
        "validate_plan run_id=%s steps=%d blocked=%s requires_planning=%s",
        state.run_id, len(plan_dicts), validation.blocking, state.requires_planning,
    )
    return {"plan_steps": plan_dicts}


def _after_validate_plan(state: AgentGraphState) -> str:
    """After validation: enter plan execution or fall back to legacy branch."""
    if state.requires_planning and state.plan_steps:
        return "prepare_plan_execution"
    return "execute_current_runtime_path"


def _node_execute_current_runtime_path(state: AgentGraphState, *, runtime) -> dict:
    """Execute capture/ask/summarize/direct_answer — non-planning intents."""
    from .router import RouterDecision

    if state.entry_input is None:
        state.entry_input = EntryInput(
            text=state.entry_text,
            user_id=state.user_id,
            session_id=state.session_id,
        )

    rd = state.router_decision
    decision = RouterDecision(
        route=rd.get("route", state.intent),
        confidence=float(rd.get("confidence", 0.5)),
        requires_tools=bool(rd.get("requires_tools", False)),
        requires_retrieval=bool(rd.get("requires_retrieval", False)),
        requires_planning=bool(rd.get("requires_planning", False)),
        risk_level=rd.get("risk_level", "low"),
        requires_confirmation=bool(rd.get("requires_confirmation", False)),
        missing_information=list(rd.get("missing_information", [])),
        candidate_tools=list(rd.get("candidate_tools", [])),
        user_visible_message=str(rd.get("user_visible_message", "")),
    )

    validated_steps = [_plan_step_from_dict(sd) for sd in state.plan_steps]

    result = runtime._execute_entry_body(
        entry_input=state.entry_input,
        decision=decision,
        validated_steps=validated_steps,
        normalized_user=state.user_id,
        normalized_session=state.session_id,
    )

    state.answer = result.reply_text
    state.answer_completed = True
    state.execution_trace = result.execution_trace or state.execution_trace
    state.plan_steps = result.plan_steps or state.plan_steps

    if result.ask_result:
        state.citations = result.ask_result.citations or []
        state.evidence_summary = result.ask_result.evidence or []
        state.matches = [
            {"id": m.id, "title": m.title, "summary": m.summary}
            for m in (result.ask_result.matches or [])
        ]

    state.add_event("answer_completed", {"answer": state.answer})
    logger.info(
        "execute_current_runtime_path run_id=%s intent=%s answer_len=%d",
        state.run_id, state.intent, len(state.answer or ""),
    )
    return {
        "answer": state.answer,
        "answer_completed": True,
        "execution_trace": state.execution_trace,
    }


def _node_finalize_entry_result(state: AgentGraphState) -> dict:
    if state.errors:
        state.add_event("run_failed", {"errors": state.errors})
    else:
        state.add_event("run_completed", {
            "answer": state.answer,
            "intent": state.intent,
        })
    logger.info(
        "finalize_entry_result run_id=%s intent=%s errors=%d",
        state.run_id, state.intent, len(state.errors),
    )
    return {}


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
    }


def _node_select_next_step(state: AgentGraphState) -> dict:
    """Find the next unexecuted step and set current_step_index.

    Skips steps with status 'skipped' or 'completed'.
    Returns with updated current_step_index or leaves it unchanged
    when no more steps remain (checked by the conditional edge).
    """
    for i, sd in enumerate(state.plan_steps):
        if sd.get("status") in ("planned",):
            state.current_step_index = i
            sd["status"] = "running"
            state.add_event("step_started", {
                "step_id": sd.get("step_id"),
                "action_type": sd.get("action_type"),
                "description": sd.get("description"),
            })
            logger.info(
                "select_next_step run_id=%s step=%s index=%d",
                state.run_id, sd.get("step_id"), i,
            )
            return {"current_step_index": i, "plan_steps": state.plan_steps}

    # No more steps
    logger.info("select_next_step run_id=%s: no more steps", state.run_id)
    return {}


def _node_execute_plan_step(state: AgentGraphState, *, runtime) -> dict:
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
    step = _plan_step_from_dict(sd)

    # Idempotency: skip side-effect steps that already ran
    if step.action_type == "tool_call" and step.tool_name:
        idem_key = step.step_id
        if idem_key in state.step_results:
            logger.info(
                "Skipping already-executed tool_call step %s (idempotent)",
                step.step_id,
            )
            sd["status"] = "completed"
            state.add_event("step_completed", {
                "step_id": step.step_id,
                "result_summary": "跳过（已执行）",
            })
            return {"plan_steps": state.plan_steps}

    # ---- ReAct branch: seed state and let subgraph handle execution ----
    if getattr(step, "execution_mode", "deterministic") == "react":
        state.react_step_id = step.step_id
        state.react_max_iterations = min(step.max_iterations, _REACT_MAX_ITERATIONS_CAP)
        state.react_allowed_tools = list(_resolve_allowed_tools_for_step(step, runtime))
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
        }

    try:
        _dispatch_plan_step(step, sd, state, runtime)
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        logger.warning("Plan step %s failed: %s", step.step_id, err_msg)
        sd["status"] = "failed"
        sd["retry_count"] = sd.get("retry_count", 0) + 1
        state.plan_retry_counts[step.step_id] = sd["retry_count"]
        state.errors.append(f"[{step.step_id}] {err_msg}")
        state.add_event("step_failed", {
            "step_id": step.step_id,
            "error": err_msg,
            "on_failure": step.on_failure,
            "retry_count": sd["retry_count"],
        })
        return {
            "plan_steps": state.plan_steps,
            "errors": state.errors,
            "plan_retry_counts": state.plan_retry_counts,
        }

    # If the step triggered a confirmation request, don't mark completed yet
    if state.pending_confirmation is not None:
        sd["status"] = "awaiting_confirmation"
        state.add_event("confirmation_required", state.pending_confirmation)
        logger.info("Step %s awaiting confirmation", step.step_id)
        return {"plan_steps": state.plan_steps}

    # Normal success — no confirmation needed
    sd["status"] = "completed"
    state.add_event("step_completed", {
        "step_id": step.step_id,
        "result_summary": _summarize_result(state.step_results.get(step.step_id)),
    })
    return {"plan_steps": state.plan_steps}


def _node_handle_step_success(state: AgentGraphState) -> dict:
    """Post-success: inject dependencies, mark drafts solidified."""
    if state.current_step_index >= len(state.plan_steps):
        return {}

    sd = state.plan_steps[state.current_step_index]
    step = _plan_step_from_dict(sd)

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
                step.step_id, str(result_data["answer"]), state.plan_steps,
            )

    logger.info(
        "handle_step_success run_id=%s step=%s",
        state.run_id, step.step_id,
    )
    return {"plan_steps": state.plan_steps}


def _node_handle_step_failure(state: AgentGraphState, *, runtime) -> dict:
    """Handle a failed step: retry, replan, skip, or abort."""
    if state.current_step_index >= len(state.plan_steps):
        return {}

    sd = state.plan_steps[state.current_step_index]
    step = _plan_step_from_dict(sd)
    on_failure = sd.get("on_failure", "skip")
    retry_count = sd.get("retry_count", 0)

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
        sd["status"] = "planned"  # Reset so select_next_step picks it up again
        return {"plan_steps": state.plan_steps}

    # Retries exhausted — try replanning
    if on_failure == "retry" and retry_count >= _MAX_RETRIES:
        replanner = getattr(runtime, "_replanner", None)
        if replanner is not None:
            state.add_event("replan_attempted", {
                "step_id": step.step_id,
                "reason": "重试耗尽，尝试重新规划",
            })
            try:
                intent = state.intent or "unknown"
                err_msg = state.errors[-1] if state.errors else "未知错误"
                # Reconstruct plan step objects for replanner
                step_objs = [_plan_step_from_dict(s) for s in state.plan_steps]
                revised = replanner.replan(
                    step_objs, step, err_msg, state.step_results, intent,
                )
                if revised:
                    # Validate revised steps
                    plan_validator = getattr(runtime, "_plan_validator", None)
                    if plan_validator is not None:
                        from .router import RouterDecision
                        rd = state.router_decision
                        decision = RouterDecision(
                            route=rd.get("route", state.intent),
                            risk_level=rd.get("risk_level", "low"),
                        )
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
                            sd["status"] = "failed"
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
                    sd["status"] = "skipped"

                    # Append revised steps
                    for r in revised:
                        state.plan_steps.append(_plan_step_to_dict(r))
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
    sd["status"] = "failed"

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


def _node_confirm_step(state: AgentGraphState, *, runtime) -> dict:
    """Pause the graph for human confirmation via ``interrupt()``.

    First invocation: ``interrupt()`` pauses the graph and returns an
    ``__interrupt__`` payload from ``graph.invoke()``. On resume (re-entered
    via ``Command(resume=...)``), ``interrupt()`` returns the user's decision
    dict and the node processes the confirm / reject action.
    """
    if state.current_step_index >= len(state.plan_steps):
        return {}

    sd = state.plan_steps[state.current_step_index]
    step = _plan_step_from_dict(sd)
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

        result = runtime._tool_registry.execute(step.tool_name, **tool_input)
        if result is not None and hasattr(result, "ok") and not result.ok:
            err_msg = result.error or f"确认后工具 {step.tool_name} 执行失败"
            sd["status"] = "failed"
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
        sd["status"] = "completed"
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
    sd["status"] = "skipped"
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
    }


# ---------------------------------------------------------------------------
# Step dispatch (reuses PlanExecutor logic)
# ---------------------------------------------------------------------------

def _dispatch_plan_step(
    step: "PlanStep",
    sd: dict,
    state: AgentGraphState,
    runtime,
) -> None:
    """Execute a single step by action_type. Raises on failure.

    This mirrors ``PlanExecutor._dispatch_step`` but operates on
    ``AgentGraphState`` instead of ``AgentState``.
    """
    step_results: dict = state.step_results

    if step.action_type == "retrieve":
        result_data = _execute_retrieve_step(step, state, runtime)
        step_results[step.step_id] = result_data

    elif step.action_type == "tool_call":
        result_data = _execute_tool_call_step(step, runtime)
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
        result_data = _execute_resolve_step(step, state, runtime)
        step_results[step.step_id] = result_data

    elif step.action_type == "compose":
        answer = _execute_compose_step(step, state, runtime)
        state.answer = answer
        step_results[step.step_id] = {"answer": answer, "draft": True}
        if answer:
            state.add_event("draft_ready", {
                "step_id": step.step_id,
                "draft_text": answer,
            })

    elif step.action_type == "verify":
        _execute_verify_step(step, state, runtime)

    else:
        raise ValueError(f"未知的 action_type: {step.action_type}")


def _execute_retrieve_step(step, state: AgentGraphState, runtime) -> object:
    question = step.tool_input.get("question") if step.tool_input else step.description
    result = runtime.graph_store.ask(str(question), state.user_id)
    if result.enabled and result.answer:
        return {
            "answer": result.answer,
            "entity_names": result.entity_names,
            "relation_facts": result.relation_facts,
            "related_episode_uuids": result.related_episode_uuids,
        }
    return {"answer": "", "entity_names": [], "relation_facts": [], "hint": "graph disabled or empty"}


def _execute_tool_call_step(step, runtime) -> object:
    if not step.tool_name:
        raise ValueError("tool_call step missing tool_name")
    result = runtime._tool_registry.execute(
        step.tool_name, **(step.tool_input or {})
    )
    if result is not None and hasattr(result, "ok") and not result.ok:
        raise RuntimeError(result.error or f"Tool {step.tool_name} returned failure")
    return result.data if hasattr(result, "data") and result.data is not None else {"ok": True}


def _execute_resolve_step(step, state: AgentGraphState, runtime) -> object:
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
                    matched = runtime.store.find_notes_by_graph_episode_uuids(user_id, str_uuids)
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
            similar = runtime.store.find_similar_notes(user_id, original_query, limit=5)
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
            all_notes = runtime.store.list_notes(user_id)
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


def _execute_compose_step(step, state: AgentGraphState, runtime) -> str:
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

    try:
        ask_result = runtime.execute_ask(question, state.user_id)
        answer = ask_result.answer
    except Exception:
        logger.exception("Compose step %s failed", step.step_id)
        answer = f"根据已有信息：{context[:500]}"

    # Save solidify drafts
    if state.intent == "solidify_conversation" and answer:
        try:
            memory = getattr(runtime, "memory", None)
            if memory:
                draft_id = memory.save_draft(state.user_id, answer, source_context=context[:500])
                if draft_id and step.step_id in state.step_results:
                    state.step_results[step.step_id]["draft_id"] = draft_id
        except Exception:
            logger.exception("Failed to save solidify draft")

    return answer


def _execute_verify_step(step, state: AgentGraphState, runtime) -> None:
    if not state.answer:
        return
    try:
        verifier = getattr(runtime, "_verifier", None)
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

def _route_after_plan(state: AgentGraphState) -> str:
    """After route_and_plan: choose plan execution loop or legacy branch."""
    if state.requires_planning and state.plan_steps:
        return "prepare_plan_execution"
    return "execute_current_runtime_path"


def _should_execute_step(state: AgentGraphState) -> str:
    """Check if there are more steps to execute."""
    if state.plan_aborted:
        return "finalize_plan"
    for sd in state.plan_steps:
        if sd.get("status") in ("planned",):
            return "execute_step"
    return "finalize_plan"


def _after_step_execution(state: AgentGraphState) -> str:
    """Determine whether step succeeded, failed, awaits confirmation, or needs ReAct."""
    if state.current_step_index < len(state.plan_steps):
        sd = state.plan_steps[state.current_step_index]
        if sd.get("status") == "awaiting_confirmation":
            return "confirm_step"
        if sd.get("status") == "failed":
            return "handle_failure"
        if sd.get("execution_mode") == "react" and sd.get("status") == "running":
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


def _node_react_init(state: AgentGraphState, *, runtime) -> dict:
    """Seed ReAct iteration state from the current plan step.

    Reads the step at ``current_step_index``, resolves allowed tools, and
    builds the initial LLM prompt.  The step status stays ``"running"`` —
    the subgraph loop will mark it ``"completed"`` on finish.
    """
    if state.current_step_index >= len(state.plan_steps):
        state.react_done = True
        return {"react_done": True}

    sd = state.plan_steps[state.current_step_index]
    step = _plan_step_from_dict(sd)

    state.react_step_id = step.step_id
    state.react_max_iterations = min(step.max_iterations, _REACT_MAX_ITERATIONS_CAP)
    state.react_allowed_tools = list(_resolve_allowed_tools_for_step(step, runtime))
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


def _node_react_iterate(state: AgentGraphState, *, runtime) -> dict:
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
        sd = state.plan_steps[state.current_step_index] if state.current_step_index < len(state.plan_steps) else {}
        step = _plan_step_from_dict(sd)
        context_block = _build_react_context(step, state.step_results)
        tools_block = _format_react_tools(allowed, runtime)
        state.react_user_prompt = (
            f"## 步骤描述\n{step.description}\n\n"
            f"## 已有上下文\n{context_block}\n\n"
            f"## 可用工具\n{tools_block}\n\n"
            f"请开始推理（最多 {max_iter} 轮）。"
        )

    # ---- Call LLM ----
    raw = _react_llm_respond(state.react_user_prompt, runtime)
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
    elif _is_react_tool_blocked(tool_name, runtime):
        observation = f"错误：工具 '{tool_name}' 是高风险/写操作工具，不允许在 ReAct 中调用。"
    else:
        tool_result = runtime._tool_registry.execute(tool_name, **tool_input)
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
        if sd.get("step_id") == step_id:
            sd["status"] = "completed"

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


def _build_react_subgraph(runtime):
    """Build and compile the ReAct inner-loop subgraph.

    The subgraph uses ``AgentGraphState`` and checkpoints at every
    iteration boundary (react_iterate self-loop).
    """
    builder = StateGraph(AgentGraphState)

    builder.add_node(
        "react_init",
        lambda state: _node_react_init(state, runtime=runtime),
    )
    builder.add_node(
        "react_iterate",
        lambda state: _node_react_iterate(state, runtime=runtime),
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

