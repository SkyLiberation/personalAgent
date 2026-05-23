from __future__ import annotations

import json
import logging
from pydantic import BaseModel, Field
from typing import Literal, Protocol

from openai import OpenAI

from ..core.config import Settings
from ..core.logging_utils import log_event
from ..core.models import EntryInput, EntryIntent
from .entry_nodes import heuristic_entry_intent

logger = logging.getLogger(__name__)

RiskLevel = Literal["low", "medium", "high"]


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
    def classify(self, entry_input: EntryInput) -> RouterDecision: ...


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
        risk_level=llm_result.risk_level,
        requires_confirmation=llm_result.requires_confirmation,
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


def _with_clarification(
    decision: RouterDecision,
    *,
    prompt: str,
    missing_information: list[str],
) -> RouterDecision:
    """Mark a fallback routing decision as requiring user clarification."""
    return decision.model_copy(
        update={
            "requires_clarification": True,
            "clarification_prompt": prompt,
            "missing_information": missing_information,
        }
    )


def _apply_heuristic_clarification(text: str, decision: RouterDecision) -> RouterDecision:
    """Handle unmistakably incomplete fragments when no LLM is available."""
    stripped = (text or "").strip()
    ambiguous_fragments = {
        "帮我", "帮我看看", "看看", "处理一下", "帮我处理", "搞一下", "弄一下",
        "继续", "这个", "那个", "这条", "那条", "一下",
    }
    action_only = {
        "记录", "记一下", "保存", "收录", "总结", "汇总", "删除", "删掉",
        "查询", "问一下", "解释一下",
    }
    if stripped in ambiguous_fragments:
        return _with_clarification(
            _default_router_decision("unknown", f"输入 `{stripped}` 缺少明确目标。"),
            prompt="请补充你希望我处理的具体内容，并说明要记录、查询、总结还是执行操作。",
            missing_information=["具体目标或待处理内容"],
        )
    if stripped in action_only:
        return _with_clarification(
            decision,
            prompt=f"请补充“{stripped}”所针对的具体内容或对象。",
            missing_information=["操作对象或内容"],
        )
    return decision


class DefaultIntentRouter:
    """LLM-first intent classification with heuristic fallback.

    Uses the small model for fast, low-cost classification.
    Falls back to heuristic rules when the LLM is unavailable or returns
    an unrecognised intent.

    LLM results are merged with _default_router_decision() to ensure
    control fields (requires_tools, requires_retrieval, requires_planning,
    candidate_tools) are always populated.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def classify(self, entry_input: EntryInput) -> RouterDecision:
        if entry_input.source_type == "file":
            decision = _default_router_decision("capture_file", "来源消息类型是文件。")
            self._log_decision(entry_input, decision, strategy="source_type")
            return decision

        llm_result = self._classify_with_llm(entry_input.text)
        if llm_result is not None:
            decision = _merge_with_defaults(llm_result)
            strategy = "empty" if not entry_input.text.strip() else "llm"
            self._log_decision(entry_input, decision, strategy=strategy)
            return decision

        intent, reason = heuristic_entry_intent(entry_input.text)
        decision = _apply_heuristic_clarification(
            entry_input.text,
            _default_router_decision(intent, reason),
        )
        self._log_decision(entry_input, decision, strategy="heuristic")
        return decision

    def _classify_with_llm(self, text: str) -> RouterDecision | None:
        if not text.strip():
            return _default_router_decision("unknown", "消息内容为空。")
        if not self._llm_configured:
            return None

        prompt = (
            "你是一个入口路由分类器。"
            "请把用户输入分类到以下意图之一：capture_text, capture_link, capture_file, ask, summarize_thread, delete_knowledge, solidify_conversation, direct_answer, unknown。"
            "capture_text: 用户想记录文字内容。capture_link: 用户发来链接想收录。ask: 需要检索知识库才能回答的问题。"
            "summarize_thread: 需要总结群聊/会话。delete_knowledge: 删除过时或错误的知识笔记。"
            "solidify_conversation: 把对话结论沉淀为知识。"
            "direct_answer: 闲聊、问候、感谢、澄清性问题、无需检索的简单说明或常识性问题。"
            "当输入不足以安全确定或执行意图时设置 requires_clarification=true，并提供 missing_information 和 clarification_prompt；"
            "例如“帮我”“删除”需要澄清，而“你是谁”“你好”是完整的 direct_answer，不需要澄清。"
            "只返回 JSON，字段：intent(必填), reason(必填), risk_level(low/medium/high, 可选), requires_confirmation(bool, 可选), "
            "requires_clarification(bool, 可选), missing_information(字符串数组, 可选), clarification_prompt(字符串, 可选)。"
            "risk_level: 删除类操作应为 high，一般操作为 low。"
            "requires_confirmation: 删除操作应为 true。\n\n"
            f"用户输入：{text}"
        )
        try:
            client = OpenAI(
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url,
            )
            response = client.chat.completions.create(
                model=self._settings.openai_small_model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个严谨的意图分类器，只输出 JSON。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            logger.info("LLM intent classification raw response: %s", content)
            payload = json.loads(content)
            intent = payload.get("intent", "unknown")
            if intent not in _RECOGNIZED_INTENTS:
                logger.warning(
                    "LLM returned unrecognised intent=%s, falling back to heuristic",
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
        except Exception:
            logger.exception(
                "Failed to classify entry intent with LLM, falling back to heuristic"
            )
            return None

    @property
    def _llm_configured(self) -> bool:
        return bool(
            self._settings.openai_api_key
            and self._settings.openai_base_url
            and self._settings.openai_small_model
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
