from __future__ import annotations

import logging
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from personal_agent.kernel.logging_utils import log_event
from personal_agent.kernel.models import EntryInput, EntryIntent
from personal_agent.kernel.prompts import get_prompt, render_prompt
from personal_agent.infra.structured_model import StructuredModelClient, StructuredModelRequest

logger = logging.getLogger(__name__)
ConversationMessage = dict[str, str]


class GoalDraft(BaseModel):
    """Minimal transport contract emitted by the router LLM."""

    intent: EntryIntent
    input: str = Field(min_length=1)


class ClarificationDraft(BaseModel):
    missing_information: list[str] = Field(min_length=1)
    prompt: str = Field(min_length=1)


class RouterOutput(BaseModel):
    """Strict JSON-schema DTO; converted to domain goals after parsing."""

    outcome: Literal["ready", "clarify"]
    goals: list[GoalDraft]
    clarification: ClarificationDraft | None

    @model_validator(mode="after")
    def _validate_contract(self) -> "RouterOutput":
        if self.outcome == "ready":
            if not self.goals:
                raise ValueError("ready output requires at least one goal")
            if self.clarification is not None:
                raise ValueError("ready output cannot contain clarification")
        else:
            if self.clarification is None:
                raise ValueError("clarify output requires clarification")
            if self.goals:
                raise ValueError("clarify output cannot contain goals")

        return self


class Goal(BaseModel):
    """Validated domain goal consumed by WorkflowPlanner."""

    goal_id: str
    intent: EntryIntent
    input: str = ""


class RouterDecision(BaseModel):
    """Semantic decomposition. Workflow policy is deliberately absent."""

    goals: list[Goal] = Field(default_factory=list)
    requires_clarification: bool = False
    missing_information: list[str] = Field(default_factory=list)
    clarification_prompt: str = ""
    error: Literal["router_unavailable"] | None = None

    @property
    def primary_intent(self) -> EntryIntent:
        return self.goals[-1].intent if self.goals else "unknown"


class IntentRouter(Protocol):
    def classify(
        self,
        entry_input: EntryInput,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> RouterDecision: ...


def _single_goal_decision(
    intent: EntryIntent,
    *,
    input_text: str = "",
    requires_clarification: bool = False,
    missing_information: list[str] | None = None,
    clarification_prompt: str = "",
) -> RouterDecision:
    return RouterDecision(
        goals=[Goal(
            goal_id="goal_1",
            intent=intent,
            input=input_text,
        )],
        requires_clarification=requires_clarification,
        missing_information=missing_information or [],
        clarification_prompt=clarification_prompt,
    )


def _to_domain_decision(output: RouterOutput) -> RouterDecision:
    goals = [
        Goal(
            goal_id=f"goal_{index + 1}",
            intent=draft.intent,
            input=draft.input,
        )
        for index, draft in enumerate(output.goals)
    ]
    clarification = output.clarification
    return RouterDecision(
        goals=goals,
        requires_clarification=output.outcome == "clarify",
        missing_information=(
            clarification.missing_information if clarification else []
        ),
        clarification_prompt=clarification.prompt if clarification else "",
    )


def _router_unavailable_decision() -> RouterDecision:
    return RouterDecision(error="router_unavailable")


def describe_router_decision(decision: RouterDecision | None) -> str:
    """Generate presentation text outside the LLM transport contract."""
    if decision is None:
        return "未提供路由结果。"
    if decision.error == "router_unavailable":
        return "入口路由模型当前不可用，请检查 LLM 配置或稍后重试。"
    if decision.requires_clarification:
        return decision.clarification_prompt or "入口信息不足，需要用户补充。"
    intents = [goal.intent for goal in decision.goals]
    if not intents:
        return "没有识别到可执行目标。"
    return "已识别目标：" + " → ".join(intents)


class DefaultIntentRouter:
    """LLM semantic decomposition for entry requests."""

    def __init__(self, model_client: StructuredModelClient | None) -> None:
        self._model_client = model_client

    def classify(
        self,
        entry_input: EntryInput,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> RouterDecision:
        if entry_input.source_type == "file":
            decision = _single_goal_decision(
                "capture_file",
                input_text=entry_input.text,
            )
            self._log_decision(entry_input, decision, strategy="source_type")
            return decision

        deterministic = _deterministic_research_decision(entry_input.text)
        if deterministic is not None:
            self._log_decision(entry_input, deterministic, strategy="rule")
            return deterministic

        result = self._classify_with_llm(entry_input.text, conversation_messages or [])
        if result is not None:
            decision = _to_domain_decision(result)
            self._log_decision(
                entry_input,
                decision,
                strategy="empty" if not entry_input.text.strip() else "llm",
            )
            return decision

        decision = _router_unavailable_decision()
        self._log_decision(
            entry_input,
            decision,
            strategy="llm_unavailable" if self._llm_configured else "llm_unconfigured",
        )
        return decision

    def _classify_with_llm(
        self,
        text: str,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> RouterOutput | None:
        if not text.strip():
            return RouterOutput(
                outcome="clarify",
                goals=[],
                clarification=ClarificationDraft(
                    missing_information=["明确的目标、问题或操作对象"],
                    prompt="请补充你想记录、查询、总结或执行的具体内容。",
                ),
            )
        if not self._llm_configured:
            logger.warning("Router LLM not configured")
            return None

        prompt = get_prompt("router.classify.system")
        messages = [{"role": "system", "content": prompt.template}]
        for message in conversation_messages or []:
            role = message.get("role")
            content = str(message.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({
            "role": "user",
            "content": render_prompt("router.classify.user", text=text),
        })

        try:
            if self._model_client is None:
                logger.warning("Router LLM not configured")
                return None
            response = self._model_client.generate(StructuredModelRequest(
                operation="router",
                version=prompt.version,
                messages=messages,
                output_type=RouterOutput,
                temperature=0,
                max_tokens=3000,
            ))
            return response.value
        except Exception:
            logger.exception("Router LLM call failed")
            return None

    @property
    def _llm_configured(self) -> bool:
        return self._model_client is not None

    def _log_decision(
        self,
        entry_input: EntryInput,
        decision: RouterDecision,
        strategy: str,
    ) -> None:
        log_event(
            logger,
            logging.INFO,
            "router.decision",
            strategy=strategy,
            goals=[goal.intent for goal in decision.goals],
            goal_count=len(decision.goals),
            requires_clarification=decision.requires_clarification,
            missing_information=decision.missing_information,
            source_type=entry_input.source_type,
            source_platform=entry_input.source_platform,
            user_id=entry_input.user_id,
            session_id=entry_input.session_id,
            text_preview=entry_input.text[:120],
        )


def _deterministic_research_decision(text: str) -> RouterDecision | None:
    stripped = text.strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    if _looks_like_research_subscription(stripped, lowered):
        return None
    if not _looks_like_one_shot_research(stripped, lowered):
        return None
    return _single_goal_decision(
        "research_once",
        input_text=stripped,
    )


def _looks_like_research_subscription(text: str, lowered: str) -> bool:
    schedule_terms = ("每天", "每周", "工作日", "定时", "周期", "订阅", "跟踪")
    subject_terms = ("新闻", "资讯", "动态", "简报", "公告", "发布")
    return (
        any(term in text for term in schedule_terms)
        and any(term in text for term in subject_terms)
    ) or "subscription" in lowered


def _looks_like_one_shot_research(text: str, lowered: str) -> bool:
    research_verbs = (
        "调研",
        "研究一下",
        "研究最近",
        "查一下",
        "搜集最新",
        "收集最新",
        "关注",
    )
    research_cues = (
        "最新",
        "最近",
        "发布",
        "动态",
        "新闻",
        "公告",
        "官方",
        "高可信",
        "最多",
        "不超过",
        "论文",
        "开源",
        "财报",
        "github",
        "paper",
        "earnings",
        "release",
        "announcement",
    )
    return (
        any(verb in text for verb in research_verbs)
        and any(cue in text or cue in lowered for cue in research_cues)
    )
