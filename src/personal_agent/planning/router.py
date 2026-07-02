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
RouteType = Literal[
    "single_workflow",
    "composite_workflow",
    "clarify",
    "unsupported",
    "direct_answer",
    "rejected",
]
CapabilityCoverage = Literal["full", "partial", "unsupported", "ambiguous"]


class GoalDraft(BaseModel):
    """Minimal transport contract emitted by the router LLM."""

    intent: EntryIntent
    input: str = Field(min_length=1)


class ClarificationDraft(BaseModel):
    missing_information: list[str] = Field(min_length=1)
    prompt: str = Field(min_length=1)


class RouterOutput(BaseModel):
    """Strict JSON-schema DTO; converted to domain goals after parsing."""

    user_goal: str = Field(min_length=1)
    route_type: RouteType
    matched_capabilities: list[EntryIntent] = Field(default_factory=list)
    coverage: CapabilityCoverage
    missing_requirements: list[str] = Field(default_factory=list)
    outcome: Literal["ready", "clarify", "unsupported", "rejected"]
    goals: list[GoalDraft]
    clarification: ClarificationDraft | None

    @model_validator(mode="after")
    def _validate_contract(self) -> "RouterOutput":
        if self.outcome == "ready":
            if not self.goals:
                raise ValueError("ready output requires at least one goal")
            if self.clarification is not None:
                raise ValueError("ready output cannot contain clarification")
            if self.route_type in {"clarify", "unsupported", "rejected"}:
                raise ValueError("ready output requires an executable route_type")
            if self.coverage != "full":
                raise ValueError("ready output requires full capability coverage")
            if not self.matched_capabilities:
                self.matched_capabilities = [goal.intent for goal in self.goals]
        else:
            if self.goals:
                raise ValueError(f"{self.outcome} output cannot contain goals")
            if self.outcome == "clarify":
                if self.route_type != "clarify":
                    raise ValueError("clarify output requires route_type=clarify")
                if self.coverage != "ambiguous":
                    raise ValueError("clarify output requires ambiguous coverage")
            if self.outcome == "unsupported":
                if self.route_type != "unsupported":
                    raise ValueError("unsupported output requires route_type=unsupported")
                if self.coverage not in {"partial", "unsupported"}:
                    raise ValueError("unsupported output requires partial or unsupported coverage")
            if self.outcome == "rejected":
                if self.route_type != "rejected":
                    raise ValueError("rejected output requires route_type=rejected")
                if self.coverage != "unsupported":
                    raise ValueError("rejected output requires unsupported coverage")
            if self.outcome == "clarify" and self.clarification is None:
                raise ValueError("clarify output requires clarification")
            if self.outcome != "clarify" and self.clarification is not None:
                raise ValueError(f"{self.outcome} output cannot contain clarification")
            if self.outcome in {"unsupported", "rejected"} and not self.missing_requirements:
                raise ValueError(f"{self.outcome} output requires missing_requirements")

        return self


class Goal(BaseModel):
    """Validated domain goal consumed by WorkflowPlanner."""

    goal_id: str
    intent: EntryIntent
    input: str = ""


class RouterDecision(BaseModel):
    """Goal understanding and capability coverage for the entry request."""

    user_goal: str = ""
    route_type: RouteType = "unsupported"
    matched_capabilities: list[EntryIntent] = Field(default_factory=list)
    coverage: CapabilityCoverage = "unsupported"
    missing_requirements: list[str] = Field(default_factory=list)
    goals: list[Goal] = Field(default_factory=list)
    requires_clarification: bool = False
    missing_information: list[str] = Field(default_factory=list)
    clarification_prompt: str = ""
    error: Literal["router_unavailable"] | None = None

    @property
    def primary_intent(self) -> EntryIntent:
        return self.goals[-1].intent if self.goals else "unknown"

    @model_validator(mode="after")
    def _normalize_domain_contract(self) -> "RouterDecision":
        if self.requires_clarification:
            self.route_type = "clarify"
            self.coverage = "ambiguous"
            self.matched_capabilities = []
            if not self.missing_requirements:
                self.missing_requirements = list(self.missing_information)
            return self

        if self.goals and self.route_type == "unsupported" and not self.missing_requirements:
            intents = [goal.intent for goal in self.goals]
            if intents == ["direct_answer"]:
                self.route_type = "direct_answer"
            elif len(intents) > 1:
                self.route_type = "composite_workflow"
            else:
                self.route_type = "single_workflow"
            self.coverage = "full"
            if not self.matched_capabilities:
                self.matched_capabilities = intents
        return self


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
    user_goal: str = "",
    route_type: RouteType = "single_workflow",
    coverage: CapabilityCoverage = "full",
    matched_capabilities: list[EntryIntent] | None = None,
    requires_clarification: bool = False,
    missing_information: list[str] | None = None,
    clarification_prompt: str = "",
) -> RouterDecision:
    return RouterDecision(
        user_goal=user_goal or input_text or intent,
        route_type="clarify" if requires_clarification else route_type,
        matched_capabilities=[] if requires_clarification else (matched_capabilities or [intent]),
        coverage="ambiguous" if requires_clarification else coverage,
        missing_requirements=missing_information or [],
        goals=[Goal(
            goal_id="goal_1",
            intent=intent,
            input=input_text,
        )] if not requires_clarification else [],
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
        user_goal=output.user_goal,
        route_type=output.route_type,
        matched_capabilities=output.matched_capabilities,
        coverage=output.coverage,
        missing_requirements=output.missing_requirements,
        goals=goals,
        requires_clarification=output.outcome == "clarify",
        missing_information=(
            clarification.missing_information if clarification else []
        ),
        clarification_prompt=clarification.prompt if clarification else "",
    )


def _router_unavailable_decision() -> RouterDecision:
    return RouterDecision(
        user_goal="无法完成入口路由",
        route_type="unsupported",
        coverage="unsupported",
        missing_requirements=["router_model"],
        error="router_unavailable",
    )


def describe_router_decision(decision: RouterDecision | None) -> str:
    """Generate presentation text outside the LLM transport contract."""
    if decision is None:
        return "未提供路由结果。"
    if decision.error == "router_unavailable":
        return "入口路由模型当前不可用，请检查 LLM 配置或稍后重试。"
    if decision.requires_clarification:
        return decision.clarification_prompt or "入口信息不足，需要用户补充。"
    if decision.route_type == "unsupported":
        return "当前能力无法完整覆盖该请求。"
    if decision.route_type == "rejected":
        return "当前请求不能执行。"
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
        artifact_decision = _deterministic_artifact_decision(entry_input)
        if artifact_decision is not None:
            self._log_decision(entry_input, artifact_decision, strategy="artifact_rule")
            return artifact_decision

        compound_decision = _deterministic_compound_capture_ask_decision(entry_input.text)
        if compound_decision is not None:
            self._log_decision(entry_input, compound_decision, strategy="compound_rule")
            return compound_decision

        deterministic = _deterministic_research_decision(entry_input.text)
        if deterministic is not None:
            self._log_decision(entry_input, deterministic, strategy="rule")
            return deterministic

        result = self._classify_with_llm(
            _router_text(entry_input),
            conversation_messages or [],
        )
        if result is not None:
            decision = _to_domain_decision(result)
            self._log_decision(
                entry_input,
                decision,
                strategy="empty" if not entry_input.text.strip() else "llm",
            )
            return decision

        deterministic_fallback = _deterministic_basic_decision(entry_input.text)
        if deterministic_fallback is not None:
            self._log_decision(entry_input, deterministic_fallback, strategy="offline_fallback")
            return deterministic_fallback

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
                user_goal="识别用户想完成的目标",
                route_type="clarify",
                matched_capabilities=[],
                coverage="ambiguous",
                missing_requirements=["明确的目标、问题或操作对象"],
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
            user_goal=decision.user_goal,
            route_type=decision.route_type,
            matched_capabilities=decision.matched_capabilities,
            coverage=decision.coverage,
            missing_requirements=decision.missing_requirements,
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


def _deterministic_basic_decision(text: str) -> RouterDecision | None:
    stripped = text.strip()
    if not stripped:
        return _single_goal_decision(
            "unknown",
            input_text="",
            requires_clarification=True,
            missing_information=["明确的目标、问题或操作对象"],
            clarification_prompt="请补充你想记录、查询、总结或执行的具体内容。",
        )
    lowered = stripped.lower()
    if _has_any(stripped, ("知识简报", "复习简报", "今日简报", "今天简报")):
        return _single_goal_decision("review_digest", input_text=stripped)
    if (
        _has_any(stripped, ("知识缺口", "缺口", "知识孤岛", "薄弱连接"))
        or ("知识库" in stripped and _has_any(stripped, ("冲突", "薄弱", "孤岛")))
    ):
        return _single_goal_decision("inspect_knowledge_gaps", input_text=stripped)
    if _has_any(stripped, ("workflow", "run_id", "执行历史")) and _has_any(
        stripped,
        ("查看", "诊断", "步骤", "失败", "执行"),
    ):
        return _single_goal_decision("inspect_workflow", input_text=stripped)
    if _has_any(stripped, ("worker", "队列", "后台任务", "失败任务", "dead 任务")) and _has_any(
        stripped,
        ("查看", "诊断", "堆积", "重试", "失败"),
    ):
        return _single_goal_decision("inspect_operations", input_text=stripped)
    if _has_any(stripped, ("过期", "替换", "修正", "标记冲突")) and _has_any(
        stripped,
        ("知识", "笔记", "这条"),
    ):
        return _single_goal_decision("maintain_knowledge", input_text=stripped)
    if _has_any(stripped, ("暂停", "恢复", "马上跑", "立即运行", "改成")) and _has_any(
        stripped,
        ("订阅", "简报", "research", "调研"),
    ):
        return _single_goal_decision("manage_research", input_text=stripped)
    if _has_any(stripped, ("每天", "每周", "每日", "定时")) and _has_any(
        stripped,
        ("收集", "简报", "订阅", "调研"),
    ):
        return _single_goal_decision("create_research_subscription", input_text=stripped)
    if _has_any(stripped, ("删除", "删掉", "移除")) and _has_any(
        stripped,
        ("知识", "笔记", "记录"),
    ):
        return _single_goal_decision("delete_knowledge", input_text=stripped)
    if _has_any(stripped, ("固化", "沉淀")) or (
        _has_any(stripped, ("刚才", "上述", "前面", "对话"))
        and _has_any(stripped, ("记下来", "保存", "入库"))
    ):
        return _single_goal_decision("solidify_conversation", input_text=stripped)
    if _has_any(stripped, ("总结", "概括")) and _has_any(
        stripped,
        ("线程", "会话", "群聊", "聊天", "对话"),
    ):
        return _single_goal_decision("summarize_thread", input_text=stripped)
    if _has_any(stripped, ("整理成一篇综述", "整理相关笔记", "合并笔记", "巩固")):
        return _single_goal_decision("consolidate_knowledge", input_text=stripped)
    answer_markers = (
        "然后回答",
        "然后直接回答",
        "再回答",
        "再直接回答",
        "并回答",
        "并直接回答",
    )
    if any(word in stripped for word in ("记住", "记一下")) and any(
        word in stripped for word in answer_markers
    ):
        return _compound_capture_ask_decision(stripped)
    if stripped.startswith(("http://", "https://")):
        return _single_goal_decision("capture_link", input_text=stripped)
    if any(word in stripped for word in ("记一下", "记住", "记录", "保存这段")):
        return _single_goal_decision("capture_text", input_text=stripped)
    if any(word in stripped for word in ("你好", "谢谢", "你是谁")):
        return _single_goal_decision(
            "direct_answer",
            input_text=stripped,
            route_type="direct_answer",
        )
    if any(word in lowered for word in ("delete", "send email")):
        return None
    return _single_goal_decision("ask", input_text=stripped)


def _deterministic_compound_capture_ask_decision(text: str) -> RouterDecision | None:
    stripped = text.strip()
    if not stripped:
        return None
    answer_markers = (
        "然后回答",
        "然后直接回答",
        "再回答",
        "再直接回答",
        "并回答",
        "并直接回答",
    )
    if any(word in stripped for word in ("记住", "记一下")) and any(
        word in stripped for word in answer_markers
    ):
        return _compound_capture_ask_decision(stripped)
    return None


def _compound_capture_ask_decision(stripped: str) -> RouterDecision:
    return RouterDecision(
        user_goal="记录一条知识并基于该主题回答后续问题",
        route_type="composite_workflow",
        matched_capabilities=["capture_text", "ask"],
        coverage="full",
        goals=[
            Goal(goal_id="goal_1", intent="capture_text", input=stripped),
            Goal(goal_id="goal_2", intent="ask", input=stripped),
        ],
    )


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _deterministic_artifact_decision(entry_input: EntryInput) -> RouterDecision | None:
    if not entry_input.artifacts:
        return None
    text = entry_input.text.strip()
    if _looks_like_artifact_capture(text):
        return _single_goal_decision("capture_file", input_text=text or "保存上传附件")
    if not text or _looks_like_artifact_analysis(text):
        return _single_goal_decision(
            "analyze_artifact",
            input_text=text or "请概述上传附件的内容",
        )
    return None


def _looks_like_artifact_capture(text: str) -> bool:
    if not text:
        return False
    capture_terms = (
        "保存",
        "收录",
        "收进",
        "存进",
        "存入",
        "采集",
        "入库",
        "记录",
        "记住",
        "写入知识库",
        "存到知识库",
        "capture",
        "save",
    )
    return any(term in text.lower() or term in text for term in capture_terms)


def _looks_like_artifact_analysis(text: str) -> bool:
    lowered = text.lower()
    artifact_refs = (
        "文件",
        "附件",
        "图片",
        "图里",
        "图中",
        "照片",
        "语音",
        "音频",
        "录音",
        "这个",
        "这张",
        "这段",
        "this file",
        "image",
        "audio",
        "attachment",
    )
    analysis_terms = (
        "总结",
        "概述",
        "解释",
        "回答",
        "分析",
        "识别",
        "提取",
        "翻译",
        "里面",
        "内容",
        "什么",
        "多少",
        "哪里",
        "哪个",
        "谁",
        "吗",
        "?",
        "？",
        "summary",
        "summarize",
        "answer",
        "describe",
        "what",
        "when",
        "where",
        "who",
        "which",
        "how",
    )
    return (
        any(term in text or term in lowered for term in artifact_refs)
        and any(term in text or term in lowered for term in analysis_terms)
    )


def _router_text(entry_input: EntryInput) -> str:
    text = entry_input.text.strip()
    if not entry_input.artifacts:
        return text
    artifact_lines = [
        f"- {artifact.filename} ({artifact.source_type}, {artifact.content_type or 'unknown'})"
        for artifact in entry_input.artifacts
    ]
    return (
        f"{text or '用户上传了附件，但没有额外文字说明。'}\n\n"
        "当前请求附带 artifacts：\n"
        + "\n".join(artifact_lines)
    )


def _looks_like_research_subscription(text: str, lowered: str) -> bool:
    schedule_terms = ("每天", "每周", "工作日", "定时", "周期", "订阅", "跟踪")
    subject_terms = ("新闻", "资讯", "动态", "简报", "公告", "发布")
    return (
        any(term in text for term in schedule_terms)
        and any(term in text for term in subject_terms)
    ) or "subscription" in lowered


def _looks_like_one_shot_research(text: str, lowered: str) -> bool:
    explicit_research_verbs = (
        "调研",
        "研究一下",
        "研究最近",
        "搜集最新",
        "搜集最近",
        "收集最新",
        "收集最近",
        "关注",
    )
    weak_lookup_verbs = ("查一下", "帮我查", "查询")
    research_deliverable_cues = (
        "最新",
        "最近",
        "多来源",
        "多源",
        "高可信",
        "官方",
        "整理",
        "最多",
        "不超过",
        "简报",
        "动态",
        "发布",
        "趋势",
        "发展",
        "进展",
        "新闻",
        "公告",
        "论文",
        "开源",
        "财报",
        "报告",
        "github",
        "paper",
        "earnings",
        "release",
        "announcement",
    )
    simple_qa_prefixes = (
        "什么是",
        "什么叫",
        "解释一下",
        "介绍一下",
        "如何",
        "怎么",
        "为什么",
        "是否",
    )
    simple_qa_cues = ("是什么", "是多少", "怎么用", "如何使用", "区别")
    has_research_cue = any(
        cue in text or cue in lowered
        for cue in research_deliverable_cues
    )
    has_explicit_research_verb = any(verb in text for verb in explicit_research_verbs)
    has_weak_lookup_verb = any(verb in text for verb in weak_lookup_verbs)
    looks_like_simple_qa = (
        text.startswith(simple_qa_prefixes)
        or any(cue in text for cue in simple_qa_cues)
    )
    if has_explicit_research_verb and has_research_cue:
        return True
    if has_weak_lookup_verb and has_research_cue and not looks_like_simple_qa:
        return True
    return False
