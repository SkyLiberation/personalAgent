"""Entry processing nodes: normalize, clarify, route, project, branch, finalize."""

from __future__ import annotations

import logging
from copy import deepcopy

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from ...core.models import EntryInput, local_now
from ..orchestration_models import (
    AgentGraphState,
    StepRunState,
    StepExecutionState,
    ReactSubState,
    ToolTrackingSubState,
    _new_run_id,
    _new_thread_id,
)
from ..orchestration_contexts import DirectAnswerContext, PlanningContext, RoutingContext
from ._helpers import (
    _clarification_payload_parts,
    _dialogue_prompt_messages,
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
    state.execution_plan = None
    state.workflow_id = ""
    state.workflow_version = ""
    state.react = ReactSubState()
    state.step_execution = StepExecutionState()
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
        "execution_plan": None,
        "workflow_id": "",
        "workflow_version": "",
        "react": state.react,
        "step_execution": state.step_execution,
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
        "入口信息不足，需要用户补充。",
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
# Phase 6: route_intent -> should_project_steps -> project_workflow_steps -> validate_projected_steps (split from
# the former composite route_and_plan node)
# ============================================================================


def _node_route_intent(state: AgentGraphState, *, deps: RoutingContext) -> dict:
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
    conversation_messages = _entry_conversation_messages(state, exclude_latest=True, deps=deps)
    decision = deps.intent_router.classify(
        state.entry_input,
        conversation_messages=conversation_messages,
    )

    state.router_decision = decision
    state.execution_plan = None
    state.step_execution.steps = []
    state.execution_trace = []

    state.add_event("intent_classified", {
        "intents": [goal.intent for goal in decision.goals],
        "goals": [goal.model_dump(mode="json") for goal in decision.goals],
        "reason": _router_reason(decision),
        "requires_clarification": decision.requires_clarification,
    })

    _log_event(
        logger,
        logging.INFO,
        "entry.route.decision",
        user_id=state.user_id,
        session_id=state.session_id,
        intents=[goal.intent for goal in decision.goals],
        requires_clarification=decision.requires_clarification,
        reason=_router_reason(decision),
    )

    logger.info(
        "route_intent run_id=%s intents=%s requires_clarification=%s",
        state.run_id, [goal.intent for goal in decision.goals], decision.requires_clarification,
    )

    return {
        "router_decision": state.router_decision,
        "execution_plan": None,
        "step_execution": state.step_execution,
        "execution_trace": [],
        "events": state.events,
    }


def _node_project_workflow_steps(state: AgentGraphState, *, deps: PlanningContext) -> dict:
    """Project structured execution steps from the selected workflow.

    Checkpoint boundary: after this node the projected steps exist and can be
    inspected before validation.
    """
    entry_text = state.entry_text or (state.entry_input.text if state.entry_input else "")
    if state.router_decision is None:
        return {}
    plan, steps = deps.workflow_planner.plan(
        state.router_decision,
        entry_text=entry_text,
        routing_key=f"{state.user_id}:{state.session_id}",
    )
    state.execution_plan = plan
    step_states = [StepRunState.from_execution_step(s) for s in steps]

    state.step_execution.steps = step_states
    if len(plan.tasks) == 1 and step_states:
        state.workflow_id = step_states[0].workflow_id
        state.workflow_version = step_states[0].workflow_version
    else:
        state.workflow_id = "multi_intent_plan"
        state.workflow_version = "v1"
    state.add_event("steps_projected", {
        "workflow_id": state.workflow_id,
        "workflow_version": state.workflow_version,
        "tasks": [task.model_dump(mode="json") for task in plan.tasks],
        "steps": [pss.model_dump(mode="json") for pss in step_states],
    })

    logger.info(
        "project_workflow_steps run_id=%s tasks=%d steps=%d",
        state.run_id, len(plan.tasks), len(step_states),
    )
    return {
        "workflow_id": state.workflow_id,
        "workflow_version": state.workflow_version,
        "execution_plan": state.execution_plan,
        "step_execution": state.step_execution,
        "events": state.events,
    }


def _node_validate_projected_steps(state: AgentGraphState, *, deps: PlanningContext) -> dict:
    """Validate compiled workflow tasks before execution."""
    steps = [sd.to_execution_step() for sd in (state.step_execution.steps or [])]
    validated_steps = list(steps)
    issues: list[str] = []
    warnings: list[str] = []
    for task in (state.execution_plan.tasks if state.execution_plan else []):
        task_id = task.task_id
        task_steps = [deepcopy(step) for step in validated_steps if step.task_id == task_id]
        task_step_ids = {step.step_id for step in task_steps}
        for step in task_steps:
            step.depends_on = [
                dependency for dependency in step.depends_on
                if dependency in task_step_ids
            ]
        validation = deps.step_projection_validator.validate(task_steps, task.intent)
        issues.extend(f"[{task_id}] {issue}" for issue in validation.issues)
        warnings.extend(f"[{task_id}] {warning}" for warning in validation.warnings)
    if issues:
        state.errors.extend(issues)
        state.add_event("steps_validated", {
            "outcome": "blocked",
            "issues": issues,
            "warnings": warnings,
        })
        state.step_execution.aborted = True
    else:
        state.add_event("steps_validated", {
            "outcome": "valid",
            "warnings": warnings,
        })

    step_states = [StepRunState.from_execution_step(s) for s in validated_steps]
    state.step_execution.steps = step_states

    logger.info(
        "validate_projected_steps run_id=%s steps=%d blocked=%s executable=%s",
        state.run_id, len(step_states), bool(issues), not bool(issues),
    )
    return {
        "step_execution": state.step_execution,
        "router_decision": state.router_decision,
        "events": state.events,
    }


def _after_validate_projected_steps(state: AgentGraphState) -> str:
    """After validation: enter step execution or ask the user to clarify."""
    if (
        state.router_decision
        and state.router_decision.goals
        and state.step_execution.steps
        and not state.step_execution.aborted
    ):
        return "prepare_step_execution"
    return "direct_answer_branch"


def _node_direct_answer_branch(state: AgentGraphState, *, deps: DirectAnswerContext) -> dict:
    """Execute direct answer or classification-driven clarification."""
    entry_input = state.entry_input
    if entry_input is None or not entry_input.text.strip():
        state.answer = "你好，有什么可以帮你的？"
        return {"answer": state.answer}

    logger.debug("Executing direct_answer branch user=%s", state.user_id)

    if not state.router_decision or state.router_decision.primary_intent == "unknown":
        state.answer = _build_clarification_answer(state)
        route = state.router_decision.primary_intent if state.router_decision else "unknown"
        state.execution_trace = _execution_trace_for_intent(route)
        return {"answer": state.answer, "execution_trace": state.execution_trace}

    if (
        deps.settings.openai.api_key
        and deps.settings.openai.base_url
        and deps.settings.openai.small_model
    ):
        from ...core.llm_trace import traced_chat_completion
        from ...core.prompts import get_prompt

        try:
            dialogue_messages = _entry_conversation_messages(
                state,
                exclude_latest=False,
                deps=deps,
            )
            if not dialogue_messages:
                dialogue_messages = [{"role": "user", "content": entry_input.text}]
            direct_prompt = get_prompt("direct_answer.system")
            result = traced_chat_completion(
                deps.settings.openai,
                prompt_name="direct_answer",
                prompt_version=direct_prompt.version,
                messages=[
                    {"role": "system", "content": direct_prompt.template},
                    *dialogue_messages,
                ],
                model=deps.settings.openai.small_model,
                max_tokens=300,
                metadata={"component": "orchestration", "intents": [goal.intent for goal in state.router_decision.goals]},
                upload_inputs_outputs=deps.settings.langsmith.upload_inputs,
            )
            generated = result.content.strip()
            if generated:
                state.answer = generated
                route = state.router_decision.primary_intent if state.router_decision else "unknown"
                state.execution_trace = _execution_trace_for_intent(route)
                return {"answer": state.answer, "execution_trace": state.execution_trace}
        except Exception:
            logger.exception("Direct answer LLM call failed")

    state.answer = "回答模型当前不可用，请检查 LLM 配置或稍后重试。"
    route = state.router_decision.primary_intent if state.router_decision else "unknown"
    state.execution_trace = _execution_trace_for_intent(route)
    return {"answer": state.answer, "execution_trace": state.execution_trace}


def _entry_conversation_messages(
    state: AgentGraphState,
    *,
    exclude_latest: bool = True,
    deps: "RoutingContext | DirectAnswerContext | None" = None,
) -> list[dict[str, str]]:
    """Return structured thread dialogue from checkpoint messages.

    When ``deps`` is provided, applies the unified short-term策略 (token 预算 +
    单条截断 + 溢出滚动摘要)；否则回退到默认窗口（无摘要）。
    """
    from ...core.config import ShortTermMemoryConfig
    from ..short_term_context import build_dialogue_context_result

    if deps is None:
        return _dialogue_prompt_messages(state.messages, exclude_latest=exclude_latest)

    cfg = getattr(deps.settings, "short_term", None) or ShortTermMemoryConfig()
    summarizer = None
    if deps.compress_context is not None:
        user_id = state.user_id or "default"

        def summarizer(text: str) -> str:
            return deps.compress_context(text, user_id)

    result = build_dialogue_context_result(
        state.messages,
        cfg,
        exclude_latest=exclude_latest,
        prior_summary=state.thread_summary,
        summarizer=summarizer,
    )
    if result.summary_updated:
        state.thread_summary = result.thread_summary
    return result.messages


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
    if decision.error == "router_unavailable":
        return _router_reason(decision)
    if missing:
        details = "、".join(missing[:3])
        return f"我还需要你补充：{details}。你可以说明这是要记录、查询、总结，还是要执行某个操作。"
    return "我暂时没判断出你的意图。你可以说明这是要记录、查询、总结，还是要执行某个操作。"


def _router_reason(decision) -> str:
    from ..router import describe_router_decision

    return describe_router_decision(decision)


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


def _node_finalize_entry_result(state: AgentGraphState) -> dict:
    if state.errors:
        state.add_event("run_failed", {"errors": state.errors})
    else:
        state.answer_completed = True
        if not any(event.type == "answer_completed" for event in state.events):
            state.add_event("answer_completed", {"answer": state.answer})
        state.add_event("run_completed", {
            "answer": state.answer,
            "intents": [goal.intent for goal in state.router_decision.goals] if state.router_decision else [],
        })
        logger.info(
            "finalize_entry_result relies on checkpoint messages run_id=%s intent=%s answer_len=%d",
            state.run_id,
            state.router_decision.primary_intent if state.router_decision else "unknown",
            len(state.answer or ""),
        )
    logger.info(
        "finalize_entry_result run_id=%s intent=%s errors=%d",
        state.run_id, state.router_decision.primary_intent if state.router_decision else "unknown", len(state.errors),
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
