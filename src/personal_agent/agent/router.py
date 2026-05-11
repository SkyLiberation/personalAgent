from __future__ import annotations

import json
import logging
from typing import Protocol

from openai import OpenAI

from ..core.config import Settings
from ..core.models import EntryInput, EntryIntent
from .entry_nodes import heuristic_entry_intent

logger = logging.getLogger(__name__)


class IntentRouter(Protocol):
    def classify(self, entry_input: EntryInput) -> tuple[EntryIntent, str]:
        ...


class DefaultIntentRouter:
    """LLM-first intent classification with heuristic fallback.

    Uses the small model for fast, low-cost classification.
    Falls back to heuristic rules when the LLM is unavailable or returns
    an unrecognised intent.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def classify(self, entry_input: EntryInput) -> tuple[EntryIntent, str]:
        if entry_input.source_type == "file":
            return "capture_file", "来源消息类型是文件。"

        llm_result = self._classify_with_llm(entry_input.text)
        if llm_result is not None:
            return llm_result
        return heuristic_entry_intent(entry_input.text)

    def _classify_with_llm(self, text: str) -> tuple[EntryIntent, str] | None:
        if not text.strip():
            return "unknown", "消息内容为空。"
        if not self._llm_configured:
            return None

        prompt = (
            "你是一个入口路由分类器。"
            "请把用户输入分类到以下意图之一：capture_text, capture_link, capture_file, ask, summarize_thread, unknown。"
            "只返回 JSON，对象字段固定为 intent 和 reason。"
            "intent 必须是上述枚举之一，reason 用一句简短中文说明依据。\n\n"
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
                    {"role": "system", "content": "你是一个严谨的意图分类器，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            payload = json.loads(content)
            intent = payload.get("intent", "unknown")
            valid_intents = {
                "capture_text", "capture_link", "capture_file",
                "ask", "summarize_thread", "unknown",
            }
            if intent not in valid_intents:
                logger.warning("LLM returned unrecognised intent=%s, falling back to heuristic", intent)
                return None
            reason = str(payload.get("reason") or "由模型完成意图分类。")
            return intent, reason
        except Exception:
            logger.exception("Failed to classify entry intent with LLM, falling back to heuristic")
            return None

    @property
    def _llm_configured(self) -> bool:
        return bool(
            self._settings.openai_api_key
            and self._settings.openai_base_url
            and self._settings.openai_small_model
        )
