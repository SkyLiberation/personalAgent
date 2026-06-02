"""Entry processing nodes: normalize, clarify, route, plan, branch, finalize."""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from ...core.models import EntryInput, local_now
from ..orchestration_models import (
    AgentGraphState,
    PlanStepState,
    PlanSubState,
    ReactSubState,
    ToolTrackingSubState,
    _new_run_id,
    _new_thread_id,
)
from ._deps import OrchestrationDeps
from ._helpers import (
    _clarification_payload_parts,
    _dialogue_prompt_messages,
    _first_url,
    _merge_clarification_text,
    _resume_value_get,
)

logger = logging.getLogger(__name__)

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
    state.react = ReactSubState()
    state.plan = PlanSubState()
    state.tool_tracking = ToolTrackingSubState()
    state.tool_results = []
    state.tool_messages = []
    state.execution_trace = []
    state.citations = []
    state.matches = []
    state.pending_confirmation = None
    state.confirmation_decision = None
    state.answer = None
    state.answer_completed = False
    state.events = []
    state.errors = []
    state.created_at = local_now()
    state.updated_at = state.created_at

    state.add_event("entry_started", {"text_preview": text[:120] if text else ""})
    logger.info("normalize_entry run_id=%s thread_id=%s", state.run_id, thread_id)
    return {
        "user_id": user_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "entry_text": text,
        "messages": [HumanMessage(content=text, id=f"{state.run_id}:user")],
        "tool_messages": [],
        "router_decision": None,
        "react": state.react,
        "plan": state.plan,
        "tool_tracking": state.tool_tracking,
        "tool_results": [],
        "execution_trace": [],
        "citations": [],
        "matches": [],
        "pending_confirmation": None,
        "confirmation_decision": None,
        "answer": None,
        "answer_completed": False,
        "events": state.events,
        "errors": [],
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
    from ...core.logging_utils import log_event as _log_event

    if state.entry_input is None:
        state.entry_input = EntryInput(
            text=state.entry_text,
            user_id=state.user_id,
            session_id=state.session_id,
        )

    deps.memory.bind_session(state.user_id, state.session_id)
    conversation_messages = _entry_conversation_messages(state, exclude_latest=True)
    decision = deps.intent_router.classify(
        state.entry_input,
        conversation_messages=conversation_messages,
    )

    state.router_decision = decision
    state.plan.steps = []
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
        "plan": state.plan,
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
    planning_messages = _entry_conversation_messages(state, exclude_latest=True)
    steps = deps.planner.plan(route, entry_text, conversation_messages=planning_messages)
    plan_states = [PlanStepState.from_plan_step(s) for s in steps]

    state.plan.steps = plan_states
    state.add_event("plan_created", {"plan_steps": [pss.model_dump(mode="json") for pss in plan_states]})

    logger.info(
        "plan_task run_id=%s route=%s steps=%d",
        state.run_id, route, len(plan_states),
    )
    return {"plan": state.plan, "events": state.events}


def _node_validate_plan(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Validate plan steps and handle blocking / fallback / reversion.

    Checkpoint boundary: after this node the plan is either confirmed valid
    or the intent has been reverted to a clarification fallback (unknown).

    If validation completely fails (blocking after retry), the intent is
    reverted to ``unknown`` and ``requires_planning`` is set to ``False`` so
    the routing layer sends the entry to the clarification/direct-answer path.
    """
    from ..router import RouterDecision

    decision = state.router_decision or RouterDecision(route="unknown")

    steps = [sd.to_plan_step() for sd in (state.plan.steps or [])]
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
    state.plan.steps = plan_states

    logger.info(
        "validate_plan run_id=%s steps=%d blocked=%s requires_planning=%s",
        state.run_id, len(plan_states), validation.blocking, state.router_decision.requires_planning if state.router_decision else False,
    )
    return {
        "plan": state.plan,
        "router_decision": state.router_decision,
        "events": state.events,
    }


def _after_validate_plan(state: AgentGraphState) -> str:
    """After validation: enter plan execution or ask the user to clarify."""
    if (state.router_decision and state.router_decision.requires_planning) and state.plan.steps:
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
                capture_metadata = {
                    **entry_input.metadata,
                    "original_filename": original_filename,
                    "captured_at": local_now().isoformat(),
                }
                result = deps.execute_capture(
                    text=capture_text,
                    source_type="file",
                    user_id=entry_input.user_id,
                    source_ref=entry_input.source_ref or file_path,
                    metadata=capture_metadata,
                )
                state.answer = f"已收进知识库：{result.note.title}"
                state.execution_trace = _execution_trace_for_intent(intent)
                state.add_event("tool_result", {
                    "tool_name": "capture_file",
                    "title": result.note.title,
                    "content_preview": result.note.content[:800],
                })
                return {
                    "answer": state.answer,
                    "execution_trace": state.execution_trace,
                    "tool_results": [{"capture_result": result.model_dump(mode="json")}],
                    "events": state.events,
                }
        state.answer = "文件消息已识别，但文件内容暂未获取到。请通过 Web 端上传文件，或稍后重试。"
        state.execution_trace = _execution_trace_for_intent(intent)
        return {"answer": state.answer, "execution_trace": state.execution_trace}

    capture_text = entry_input.text
    source_type = "text"
    source_ref = entry_input.source_ref
    capture_metadata = {**entry_input.metadata, "captured_at": local_now().isoformat()}
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
        capture_metadata["url"] = url

    result = deps.execute_capture(
        text=capture_text,
        source_type=source_type,
        user_id=entry_input.user_id,
        source_ref=source_ref,
        metadata=capture_metadata,
    )
    state.answer = f"已收进知识库：{result.note.title}"
    state.execution_trace = _execution_trace_for_intent(intent)
    state.add_event("tool_result", {
        "tool_name": "capture_text" if intent == "capture_text" else "capture_link",
        "title": result.note.title,
        "content_preview": result.note.content[:800],
    })
    return {
        "answer": state.answer,
        "execution_trace": state.execution_trace,
        "tool_results": [{"capture_result": result.model_dump(mode="json")}],
        "events": state.events,
    }


def _node_ask_branch(state: AgentGraphState, *, deps: OrchestrationDeps) -> dict:
    """Execute ask branch — already classified, no duplicate routing."""
    entry_input = state.entry_input
    if entry_input is None or not entry_input.text.strip():
        state.answer = "未收到可提问内容。"
        return {"answer": state.answer}

    logger.debug("Executing ask branch user=%s question=%s", state.user_id, entry_input.text[:80])
    conversation_messages = _entry_conversation_messages(state, exclude_latest=True)
    result = deps.execute_ask(
        entry_input.text,
        entry_input.user_id,
        entry_input.session_id,
        conversation_messages=conversation_messages,
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

    messages: list[dict[str, str]] = []
    thread_messages_raw = entry_input.metadata.get("thread_messages", "")
    if thread_messages_raw:
        try:
            parsed_messages = _json.loads(thread_messages_raw)
            if isinstance(parsed_messages, list):
                messages = [m for m in parsed_messages if isinstance(m, dict)]
        except _json.JSONDecodeError:
            logger.warning("Invalid preloaded thread messages for session=%s", entry_input.session_id)

    if not messages and deps.load_thread_messages is not None:
        try:
            messages = deps.load_thread_messages(entry_input, 20)
        except Exception:
            logger.exception(
                "Unable to load thread messages after summarize routing session=%s",
                entry_input.session_id,
            )

    if messages and deps.summarize_thread is not None:
        messages_text = "\n".join(
            f"[{m.get('role', 'unknown')}]: {m.get('content', '')}"
            for m in messages
        )
        summary = deps.summarize_thread(messages_text, entry_input.user_id or "default")
        state.answer = summary
        state.execution_trace = _execution_trace_for_intent(state.router_decision.route if state.router_decision else "unknown")
        return {"answer": state.answer, "execution_trace": state.execution_trace}

    dialogue_messages = _entry_conversation_messages(state, exclude_latest=True)
    if dialogue_messages and deps.summarize_thread is not None:
        messages_text = "\n".join(
            f"[{m.get('role', 'unknown')}]: {m.get('content', '')}"
            for m in dialogue_messages
        )
        summary = deps.summarize_thread(messages_text, entry_input.user_id or "default")
        state.answer = summary
        state.execution_trace = _execution_trace_for_intent(state.router_decision.route if state.router_decision else "unknown")
        return {"answer": state.answer, "execution_trace": state.execution_trace}

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
        deps.settings.openai.api_key
        and deps.settings.openai.base_url
        and deps.settings.openai.small_model
    ):
        from openai import OpenAI

        try:
            client = OpenAI(
                api_key=deps.settings.openai.api_key,
                base_url=deps.settings.openai.base_url,
                timeout=deps.settings.openai.timeout_seconds,
                max_retries=deps.settings.openai.max_retries,
            )
            dialogue_messages = _dialogue_prompt_messages(state.messages)
            if not dialogue_messages:
                dialogue_messages = [{"role": "user", "content": entry_input.text}]
            system_content = "你是一个友好、简洁的个人知识库助手。直接回答用户，不需要检索知识库。保持简短。"
            response = client.chat.completions.create(
                model=deps.settings.openai.small_model,
                messages=[
                    {"role": "system", "content": system_content},
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

    state.answer = "回答模型当前不可用，请检查 LLM 配置或稍后重试。"
    route = state.router_decision.route if state.router_decision else "unknown"
    state.execution_trace = _execution_trace_for_intent(route)
    return {"answer": state.answer, "execution_trace": state.execution_trace}


def _entry_conversation_messages(
    state: AgentGraphState, *, exclude_latest: bool = True
) -> list[dict[str, str]]:
    """Return structured thread dialogue from checkpoint messages."""
    return _dialogue_prompt_messages(state.messages, exclude_latest=exclude_latest)


# ---------------------------------------------------------------------------
# Entry response helpers
# ---------------------------------------------------------------------------

def _build_clarification_answer(state: AgentGraphState) -> str:
    """Build a clarification prompt from the classify result."""
    decision = state.router_decision
    if decision is None:
        return "我暂时没判断出你的意图。你可以说明这是要记录、查询、总结，还是要执行某个操作。"
    missing = [
        str(item).strip()
        for item in decision.missing_information
        if str(item).strip()
    ]
    reason = (decision.user_visible_message or "").strip()
    if reason.startswith("入口路由模型当前不可用"):
        return reason
    if missing:
        details = "、".join(missing[:3])
        return f"我还需要你补充：{details}。你可以说明这是要记录、查询、总结，还是要执行某个操作。"
    if reason and "计划校验失败" in reason:
        return f"{reason}。请补充更明确的目标或操作范围后我再继续。"
    return "我暂时没判断出你的意图。你可以说明这是要记录、查询、总结，还是要执行某个操作。"


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


def _node_finalize_entry_result(
    state: AgentGraphState, *, deps: OrchestrationDeps | None = None
) -> dict:
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
            "finalize_entry_result relies on checkpoint messages run_id=%s intent=%s answer_len=%d",
            state.run_id,
            state.router_decision.route if state.router_decision else "unknown",
            len(state.answer or ""),
        )
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
