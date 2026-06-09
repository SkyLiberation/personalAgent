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

from .runtime_llm import LlmClient

logger = logging.getLogger(__name__)

_CHAT_DIGEST_PROMPT = (
    "你是个人知识库助手。请用自然中文总结以下群聊对话的核心要点。"
    "按主题分点列出讨论的关键事项、达成的结论和待办事项。"
    "保持简洁，每个要点一句话。如果对话内容较少或主题分散，直接概括即可。\n\n"
    "群聊消息：\n{messages_text}"
)

_CONTEXT_COMPRESSION_PROMPT = (
    "你在为一个多轮对话压缩较早的历史，供后续轮次理解上下文使用。"
    "这不是面向用户的纪要，目标是保留后续对话所需的线索：\n"
    "- 用户想做什么、当前未完成的目标和约束；\n"
    "- 指代对象（人名、文件、概念等代词所指）；\n"
    "- 用户明确给出的事实或更正。\n"
    "要求：\n"
    "- 只压缩、不展开，不要补充对话中没有的信息；\n"
    "- 区分「用户陈述」与「助手推测」，对助手的推测性结论用「（助手推测）」标注，"
    "不要把助手的历史回复当成已确认事实；\n"
    "- 用紧凑的中文要点，不需要标题和客套。\n\n"
    "较早的对话：\n{messages_text}"
)


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
        prompt = _CHAT_DIGEST_PROMPT.format(messages_text=messages_text)
        generated = self._llm.generate_answer(prompt)
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
        prompt = _CONTEXT_COMPRESSION_PROMPT.format(messages_text=messages_text)
        generated = self._llm.generate_answer(prompt)
        return generated or ""
