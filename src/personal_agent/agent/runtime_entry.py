from __future__ import annotations

import logging

from ..core.models import EntryInput
from .nodes import digest_node
from .router import RouterDecision
from .runtime_results import DigestResult

logger = logging.getLogger(__name__)


class RuntimeEntryMixin:
    def execute_digest(self, user_id: str | None = None) -> DigestResult:
        normalized_user = user_id or self.settings.default_user
        logger.info("Generating digest user=%s", normalized_user)
        return DigestResult(
            message=digest_node(self.store, normalized_user),
            recent_notes=self.store.list_notes(normalized_user)[-5:],
            due_reviews=self.store.due_reviews(normalized_user),
        )

    def classify_intent(self, entry_input: EntryInput) -> RouterDecision:
        """Public wrapper for intent classification."""
        return self._intent_router.classify(entry_input)

    def _summarize_thread(self, messages_text: str, _user_id: str) -> str:
        if not messages_text.strip():
            return "没有可总结的消息内容。"
        prompt = (
            "你是个人知识库助手。请用自然中文总结以下群聊对话的核心要点。"
            "按主题分点列出讨论的关键事项、达成的结论和待办事项。"
            "保持简洁，每个要点一句话。如果对话内容较少或主题分散，直接概括即可。\n\n"
            f"群聊消息：\n{messages_text}"
        )
        generated = self._generate_answer(prompt)
        if generated:
            return generated
        return "暂时无法生成群聊总结，请稍后重试。"
