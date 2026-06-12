from __future__ import annotations

import logging
from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator
from typing import Literal, Protocol

from ..core.config import Settings
from ..core.llm_schemas import structured_response_format, strip_json_fence
from ..core.llm_trace import log_llm_parse, traced_chat_completion
from ..core.logging_utils import log_event
from ..core.models import EntryInput, EntryIntent
from ..core.prompts import get_prompt, render_prompt

logger = logging.getLogger(__name__)

RiskLevel = Literal["low", "medium", "high"]
ConversationMessage = dict[str, str]


class RouterDecision(BaseModel):
    """Structured routing decision with metadata for downstream projector / executor."""

    route: EntryIntent = "unknown"
    confidence: float = 0.5
    requires_tools: bool = False
    requires_retrieval: bool = False
    requires_step_projection: bool = False
    risk_level: RiskLevel = "low"
    requires_confirmation: bool = False
    requires_clarification: bool = False
    missing_information: list[str] = Field(default_factory=list)
    clarification_prompt: str = ""
    candidate_tools: list[str] = Field(default_factory=list)
    user_visible_message: str = ""

    @field_validator(
        "missing_information",
        "clarification_prompt",
        "candidate_tools",
        "user_visible_message",
        mode="before",
    )
    @classmethod
    def _coerce_null_to_default(cls, value: object, info: ValidationInfo) -> object:
        """Treat null from the LLM as the field's empty default.

        Some models emit ``null`` for optional list/string fields instead of
        omitting them or returning ``[]`` / ``""``.
        """
        if value is None:
            return [] if info.field_name in {"missing_information", "candidate_tools"} else ""
        return value


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
            requires_step_projection=True,
            risk_level="high",
            requires_confirmation=True,
            candidate_tools=["graph_search"],
            user_visible_message=reason or "删除知识需要你确认后再执行。",
        )
    if intent == "solidify_conversation":
        return RouterDecision(
            route=intent,
            confidence=0.75,
            requires_step_projection=True,
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


_ROUTER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "route": {
            "type": "string",
            "enum": sorted(_RECOGNIZED_INTENTS),
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "requires_tools": {"type": "boolean"},
        "requires_retrieval": {"type": "boolean"},
        "requires_step_projection": {"type": "boolean"},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
        "requires_confirmation": {"type": "boolean"},
        "requires_clarification": {"type": "boolean"},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "clarification_prompt": {"type": "string"},
        "candidate_tools": {"type": "array", "items": {"type": "string"}},
        "user_visible_message": {"type": "string"},
    },
    "required": [
        "route",
        "confidence",
        "requires_tools",
        "requires_retrieval",
        "requires_step_projection",
        "risk_level",
        "requires_confirmation",
        "requires_clarification",
        "missing_information",
        "clarification_prompt",
        "candidate_tools",
        "user_visible_message",
    ],
    "additionalProperties": False,
}


def _merge_with_defaults(llm_result: RouterDecision) -> RouterDecision:
    """Merge LLM classification result with default decision to fill control fields.

    The LLM returns intent, clarification metadata and risk metadata, but does
    not populate requires_tools/requires_retrieval/requires_step_projection/candidate_tools.
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
        requires_step_projection=defaults.requires_step_projection,
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
    control fields (requires_tools, requires_retrieval, requires_step_projection,
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
                bool(self._settings.router.api_key),
                bool(self._settings.router.base_url),
                bool(self._settings.router.model),
            )
            return None

        system_prompt = get_prompt("router.classify.system")
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt.template},
        ]
        for message in conversation_messages or []:
            role = message.get("role")
            content = str(message.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": render_prompt("router.classify.user", text=text)})
        content = ""
        model = self._settings.router.model
        latency_ms = None
        try:
            llm_result = traced_chat_completion(
                self._settings.router,
                prompt_name="router",
                prompt_version=system_prompt.version,
                messages=messages,
                temperature=0,
                max_tokens=500,
                response_format=structured_response_format(
                    "router_decision",
                    _ROUTER_RESPONSE_SCHEMA,
                    self._settings.router.structured_output,
                ),
                metadata={"source": "intent_router"},
                upload_inputs_outputs=self._settings.langsmith.upload_inputs,
                extra_body=self._settings.router.extra_body or None,
            )
            content = llm_result.content
            model = llm_result.model
            latency_ms = llm_result.latency_ms
            logger.info("LLM intent classification raw response: %s", content)
            llm_decision = RouterDecision.model_validate_json(strip_json_fence(content))
            log_llm_parse(
                prompt_name="router",
                prompt_version=system_prompt.version,
                model=model,
                parse_ok=True,
                parse_schema="RouterDecision",
                latency_ms=latency_ms,
            )
            if llm_decision.route not in _RECOGNIZED_INTENTS:
                logger.warning(
                    "LLM returned unrecognised intent=%s",
                    llm_decision.route,
                )
                log_llm_parse(
                    prompt_name="router",
                    prompt_version=system_prompt.version,
                    model=model,
                    parse_ok=False,
                    parse_schema="RouterDecision",
                    parse_error=f"unrecognised intent={llm_decision.route}",
                    latency_ms=latency_ms,
                )
                return None
            return llm_decision
        except ValidationError as exc:
            log_llm_parse(
                prompt_name="router",
                prompt_version=system_prompt.version,
                model=model,
                parse_ok=False,
                parse_schema="RouterDecision",
                parse_error=str(exc),
                latency_ms=latency_ms,
            )
            logger.exception(
                "Router LLM schema validation failed: %s, raw content (first 500 chars): %s",
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
            self._settings.router.api_key
            and self._settings.router.base_url
            and self._settings.router.model
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
            requires_step_projection=decision.requires_step_projection,
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
