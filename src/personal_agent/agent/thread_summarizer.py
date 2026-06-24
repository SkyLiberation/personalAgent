"""Thread summarization collaborators.

Two genuinely different jobs that were previously conflated under a single
``_summarize_thread`` prompt:

- ``summarize_chat``: user explicitly asked to summarize a group chat / thread.
  Produces a reader-facing digest (topics, conclusions, todos).
- ``compress_context``: rolling-summary of overflow dialogue for the short-term
  context window. Produces a context cue that preserves references, the user's
  goal, and confirmed corrections — NOT a polished digest — and explicitly marks
  assistant-side guesses so they are never mistaken for user-stated facts.
"""

from __future__ import annotations

import logging

from personal_agent.agent.runtime_llm import LlmClient
from personal_agent.kernel.prompts import get_prompt

logger = logging.getLogger(__name__)


class ThreadSummarizer:
    """Two summarization jobs over a shared LLM client.

    Kept separate on purpose: a user-facing chat digest and a context-window
    compression cue have different goals and must not share a prompt.
    """

    def __init__(self, llm: LlmClient) -> None:
        self._llm = llm

    def summarize_chat(self, messages_text: str, _user_id: str = "default") -> str:
        """User-facing digest for an explicit ``summarize_thread`` request."""
        if not messages_text.strip():
            return "没有可总结的消息内容。"
        prompt_spec = get_prompt("thread_digest.user")
        prompt = prompt_spec.render(messages_text=messages_text)
        generated = self._llm.generate_answer(
            prompt,
            prompt_name="thread_digest",
            prompt_version=prompt_spec.version,
        )
        if generated:
            return generated
        return "暂时无法生成群聊总结，请稍后重试。"

    def compress_context(self, messages_text: str, _user_id: str = "default") -> str:
        """Rolling-summary cue for overflow dialogue in the short-term window.

        Returns an empty string on failure/empty input so callers can fall back
        to plain truncation instead of injecting a misleading summary.
        """
        if not messages_text.strip():
            return ""
        prompt_spec = get_prompt("thread_context_compression.user")
        prompt = prompt_spec.render(messages_text=messages_text)
        generated = self._llm.generate_answer(
            prompt,
            prompt_name="thread_context_compression",
            prompt_version=prompt_spec.version,
        )
        return generated or ""
