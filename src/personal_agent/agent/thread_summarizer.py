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
    "这不是面向用户的纪要，目标是维护结构化 ThreadSummary。\n"
    "要求：\n"
    "- 只压缩、不展开，不要补充对话中没有的信息；\n"
    "- 用户明确确认的内容才能进入 user_goals、user_constraints、confirmed_decisions 或 pending_tasks；\n"
    "- 助手历史回复、建议、推测只能进入 assistant_assumptions，不能当事实；\n"
    "- 对话中出现但没有证据支撑或用户确认的事实判断放入 unverified_claims；\n"
    "- 开放问题、冲突点、待澄清事项放入 open_questions；\n"
    "- evidence_refs 只能放对话里明确出现的 note_id、citation、tool ref 或文件/URL 引用。\n"
    "只返回合法 JSON，不要 Markdown，不要解释。JSON schema:\n"
    "{\n"
    '  "user_goals": ["..."],\n'
    '  "user_constraints": ["..."],\n'
    '  "confirmed_decisions": ["..."],\n'
    '  "pending_tasks": ["..."],\n'
    '  "open_questions": ["..."],\n'
    '  "assistant_assumptions": ["..."],\n'
    '  "unverified_claims": ["..."],\n'
    '  "evidence_refs": ["..."],\n'
    '  "context_notes": ["..."]\n'
    "}\n\n"
    "待更新的摘要和新增较早对话：\n{messages_text}"
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
