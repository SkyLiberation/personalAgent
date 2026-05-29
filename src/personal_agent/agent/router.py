from __future__ import annotations

import json
import logging
from pydantic import BaseModel, Field
from typing import Literal, Protocol

from openai import OpenAI

from ..core.config import Settings
from ..core.logging_utils import log_event
from ..core.models import EntryInput, EntryIntent

logger = logging.getLogger(__name__)

RiskLevel = Literal["low", "medium", "high"]
ConversationMessage = dict[str, str]


class RouterDecision(BaseModel):
    """Structured routing decision with metadata for downstream planner / executor."""

    route: EntryIntent = "unknown"
    confidence: float = 0.5
    requires_tools: bool = False
    requires_retrieval: bool = False
    requires_planning: bool = False
    risk_level: RiskLevel = "low"
    requires_confirmation: bool = False
    requires_clarification: bool = False
    missing_information: list[str] = Field(default_factory=list)
    clarification_prompt: str = ""
    candidate_tools: list[str] = Field(default_factory=list)
    user_visible_message: str = ""


class IntentRouter(Protocol):
    def classify(
        self,
        entry_input: EntryInput,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> RouterDecision: ...


def _default_router_decision(intent: EntryIntent, reason: str = "") -> RouterDecision:
    """Populate sensible defaults for each intent type."""
    if intent in ("capture_text", "capture_link", "capture_file"):
        return RouterDecision(
            route=intent,
            confidence=0.9,
            requires_tools=intent == "capture_link",
            risk_level="low",
            user_visible_message=reason or "将内容采集进知识库。",
        )
    if intent == "ask":
        return RouterDecision(
            route=intent,
            confidence=0.85,
            requires_retrieval=True,
            risk_level="low",
            candidate_tools=["graph_search", "web_search"],
            user_visible_message=reason or "检索知识库并生成回答。",
        )
    if intent == "summarize_thread":
        return RouterDecision(
            route=intent,
            confidence=0.8,
            requires_retrieval=True,
            risk_level="low",
            user_visible_message=reason or "总结群聊内容。",
        )
    if intent == "delete_knowledge":
        return RouterDecision(
            route=intent,
            confidence=0.7,
            requires_tools=True,
            requires_retrieval=True,
            requires_planning=True,
            risk_level="high",
            requires_confirmation=True,
            candidate_tools=["graph_search"],
            user_visible_message=reason or "删除知识需要你确认后再执行。",
        )
    if intent == "solidify_conversation":
        return RouterDecision(
            route=intent,
            confidence=0.75,
            requires_planning=True,
            risk_level="low",
            user_visible_message=reason or "将对话结论沉淀为知识。",
        )
    if intent == "direct_answer":
        return RouterDecision(
            route=intent,
            confidence=0.85,
            risk_level="low",
            user_visible_message=reason or "直接回复，无需检索或工具。",
        )
    return RouterDecision(
        route="unknown",
        confidence=0.3,
        risk_level="low",
        requires_clarification=True,
        missing_information=["明确的目标、问题或操作对象"],
        clarification_prompt="请补充你想记录、查询、总结或执行的具体内容。",
        user_visible_message="无法确定意图，请重新描述。",
    )


_RECOGNIZED_INTENTS = {
    "capture_text",
    "capture_link",
    "capture_file",
    "ask",
    "summarize_thread",
    "delete_knowledge",
    "solidify_conversation",
    "direct_answer",
    "unknown",
}


def _merge_with_defaults(llm_result: RouterDecision) -> RouterDecision:
    """Merge LLM classification result with default decision to fill control fields.

    The LLM returns intent, clarification metadata and risk metadata, but does
    not populate requires_tools/requires_retrieval/requires_planning/candidate_tools.
    This function merges LLM result with the defaults for the matched intent.
    """
    defaults = _default_router_decision(
        llm_result.route, llm_result.user_visible_message
    )
    return RouterDecision(
        route=llm_result.route,
        confidence=llm_result.confidence,
        requires_tools=defaults.requires_tools,
        requires_retrieval=defaults.requires_retrieval,
        requires_planning=defaults.requires_planning,
        risk_level=(
            defaults.risk_level
            if defaults.risk_level == "high"
            else llm_result.risk_level
        ),
        requires_confirmation=(
            False
            if llm_result.route == "solidify_conversation"
            else defaults.requires_confirmation or llm_result.requires_confirmation
        ),
        requires_clarification=(
            llm_result.requires_clarification or defaults.requires_clarification
        ),
        missing_information=llm_result.missing_information,
        clarification_prompt=(
            llm_result.clarification_prompt or defaults.clarification_prompt
        ),
        candidate_tools=defaults.candidate_tools,
        user_visible_message=llm_result.user_visible_message,
    )


def _router_unavailable_decision() -> RouterDecision:
    """Return an explicit runtime error when LLM routing cannot be performed."""
    return RouterDecision(
        route="unknown",
        confidence=0.0,
        risk_level="low",
        user_visible_message="入口路由模型当前不可用，请检查 LLM 配置或稍后重试。",
    )


class DefaultIntentRouter:
    """LLM-only intent classification for text entries.

    Uses the small model for classification. If it is unconfigured or remains
    unavailable after configured retries, returns an explicit model error
    instead of guessing a route from text keywords.

    LLM results are merged with _default_router_decision() to ensure
    control fields (requires_tools, requires_retrieval, requires_planning,
    candidate_tools) are always populated.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def classify(
        self,
        entry_input: EntryInput,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> RouterDecision:
        if entry_input.source_type == "file":
            decision = _default_router_decision("capture_file", "来源消息类型是文件。")
            self._log_decision(entry_input, decision, strategy="source_type")
            return decision

        llm_result = self._classify_with_llm(
            entry_input.text, conversation_messages or []
        )
        if llm_result is not None:
            decision = _merge_with_defaults(llm_result)
            strategy = "empty" if not entry_input.text.strip() else "llm"
            self._log_decision(entry_input, decision, strategy=strategy)
            return decision

        decision = _router_unavailable_decision()
        strategy = "llm_unavailable" if self._llm_configured else "llm_unconfigured"
        self._log_decision(entry_input, decision, strategy=strategy)
        return decision

    def _classify_with_llm(
        self, text: str, conversation_messages: list[ConversationMessage] | None = None
    ) -> RouterDecision | None:
        if not text.strip():
            return _default_router_decision("unknown", "消息内容为空。")
        if not self._llm_configured:
            logger.warning(
                "Router LLM not configured: api_key=%s, base_url=%s, model=%s",
                bool(self._settings.openai.api_key),
                bool(self._settings.openai.base_url),
                bool(self._settings.openai.small_model),
            )
            return None

        prompt = (
            "你是一个入口路由分类器。"
            "请把用户输入分类到以下意图之一：capture_text, capture_link, capture_file, ask, summarize_thread, delete_knowledge, solidify_conversation, direct_answer, unknown。"
            "capture_text: 用户想记录文字内容。capture_link: 用户发来链接想收录。"
            "ask: 需要检索个人知识库、公共网络或最新外部事实才能可靠回答的问题。"
            "summarize_thread: 需要总结群聊/会话。delete_knowledge: 删除过时或错误的知识笔记。"
            "solidify_conversation: 把对话结论沉淀为知识。"
            "例如已有对话在讨论 DNS，用户再说“将DNS相关知识存储至知识库”，是在要求整理已有会话知识，"
            "必须归为 solidify_conversation，不能把这条操作指令本身按 capture_text 存储。"
            "只有用户输入本身提供了需要原样记录的实质正文时，才归为 capture_text。"
            "direct_answer: 闲聊、问候、感谢、澄清性问题、无需检索的简单说明或常识性问题。"
            "请重点判断信息是否具有时效性：当前天气、实时价格、最新新闻、航班状态等依赖最新外部事实的问题应归为 ask，"
            "不得仅因问题简单而归为 direct_answer。"
            "当输入不足以安全确定或执行意图时设置 requires_clarification=true，并提供 missing_information 和 clarification_prompt；"
            "例如仅说“帮我”或“删除”需要澄清，而“删除关于 DNS 的知识”已提供检索范围，"
            "应归为 delete_knowledge 且 requires_clarification=false，后续会检索候选并要求用户确认。"
            "“你是谁”“你好”是完整的 direct_answer，不需要澄清。"
            "只返回 JSON，字段：intent(必填), reason(必填), risk_level(low/medium/high, 可选), requires_confirmation(bool, 可选), "
            "requires_clarification(bool, 可选), missing_information(字符串数组, 可选), clarification_prompt(字符串, 可选)。"
            "risk_level: 删除类操作应为 high，一般操作为 low。"
            "requires_confirmation: 删除操作应为 true。"
            "历史 chat messages 只用于理解指代和已有讨论主题；"
            "请分类最后一条当前用户输入，不要把历史助手回复当作事实证据。"
        )
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "你是一个严谨的意图分类器，只输出 JSON。\n"
                    f"{prompt}"
                ),
            },
        ]
        for message in conversation_messages or []:
            role = message.get("role")
            content = str(message.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": f"当前用户输入：{text}"})
        try:
            client = OpenAI(
                api_key=self._settings.openai.api_key,
                base_url=self._settings.openai.base_url,
                timeout=self._settings.openai.timeout_seconds,
                max_retries=self._settings.openai.max_retries,
            )
            response = client.chat.completions.create(
                model=self._settings.openai.small_model,
                messages=messages,
                temperature=0,
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            logger.info("LLM intent classification raw response: %s", content)
            payload = json.loads(content)
            intent = payload.get("intent", "unknown")
            if intent not in _RECOGNIZED_INTENTS:
                logger.warning(
                    "LLM returned unrecognised intent=%s",
                    intent,
                )
                return None
            reason = str(payload.get("reason") or "由模型完成意图分类。")
            risk = (
                payload.get("risk_level", "low")
                if isinstance(payload.get("risk_level"), str)
                else None
            )
            return RouterDecision(
                route=intent,
                confidence=0.8,
                risk_level=risk if risk in ("low", "medium", "high") else "low",
                requires_confirmation=bool(payload.get("requires_confirmation", False)),
                requires_clarification=bool(payload.get("requires_clarification", False)),
                missing_information=payload.get("missing_information")
                if isinstance(payload.get("missing_information"), list)
                else [],
                clarification_prompt=str(payload.get("clarification_prompt") or ""),
                user_visible_message=reason,
            )
        except json.JSONDecodeError as exc:
            logger.exception(
                "Router LLM JSON decode failed: %s, raw content (first 500 chars): %s",
                exc,
                content[:500],
            )
            return None
        except Exception as exc:
            logger.exception(
                "Router LLM call failed: type=%s, message=%s",
                type(exc).__name__,
                exc,
            )
            return None

    @property
    def _llm_configured(self) -> bool:
        return bool(
            self._settings.openai.api_key
            and self._settings.openai.base_url
            and self._settings.openai.small_model
        )

    def _log_decision(
        self, entry_input: EntryInput, decision: RouterDecision, strategy: str
    ) -> None:
        log_event(
            logger,
            logging.INFO,
            "router.decision",
            strategy=strategy,
            route=decision.route,
            confidence=decision.confidence,
            risk_level=decision.risk_level,
            requires_tools=decision.requires_tools,
            requires_retrieval=decision.requires_retrieval,
            requires_planning=decision.requires_planning,
            requires_confirmation=decision.requires_confirmation,
            requires_clarification=decision.requires_clarification,
            candidate_tools=decision.candidate_tools,
            missing_information=decision.missing_information,
            source_type=entry_input.source_type,
            source_platform=entry_input.source_platform,
            user_id=entry_input.user_id,
            session_id=entry_input.session_id,
            text_preview=entry_input.text[:120],
        )
