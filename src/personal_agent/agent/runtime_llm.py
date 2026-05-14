from __future__ import annotations

import logging

from openai import OpenAI

logger = logging.getLogger(__name__)


class RuntimeLlmMixin:
    def _generate_answer(self, prompt: str) -> str | None:
        if not (self.settings.openai_api_key and self.settings.openai_base_url and self.settings.openai_model):
            return None
        try:
            client = OpenAI(api_key=self.settings.openai_api_key, base_url=self.settings.openai_base_url)
            response = client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": "你是一个严谨、善于归纳总结的个人知识库问答助手。你的首要任务不是复述检索片段，而是把证据整理成简洁、可信、可读的答案。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=600,
            )
            return (response.choices[0].message.content or "").strip() or None
        except Exception:
            logger.exception("Failed to generate answer from LLM")
            return None

    def _generate_answer_stream(self, prompt: str):
        """Stream tokens from the LLM in real time via SSE-compatible chunks.

        Yields (event_type, payload) tuples suitable for SSE streaming.
        Completes with ('answer_complete', {'answer': full_text}).
        On failure, yields ('answer_error', {'error': message}) and stops.
        """
        if not (self.settings.openai_api_key and self.settings.openai_base_url and self.settings.openai_model):
            yield ("answer_error", {"error": "LLM not configured"})
            return
        try:
            client = OpenAI(api_key=self.settings.openai_api_key, base_url=self.settings.openai_base_url)
            stream = client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": "你是一个严谨、善于归纳总结的个人知识库问答助手。你的首要任务不是复述检索片段，而是把证据整理成简洁、可信、可读的答案。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=600,
                stream=True,
            )
            full_text = ""
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else ""
                if delta:
                    full_text += delta
                    yield ("answer_delta", {"delta": delta, "answer": full_text})
            if full_text.strip():
                yield ("answer_complete", {"answer": full_text.strip()})
            else:
                yield ("answer_error", {"error": "LLM returned empty response"})
        except Exception:
            logger.exception("Failed to stream answer from LLM")
            yield ("answer_error", {"error": "LLM streaming failed"})


