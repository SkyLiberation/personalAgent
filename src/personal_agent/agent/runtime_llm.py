from __future__ import annotations

import logging
import time

from openai import OpenAI

logger = logging.getLogger(__name__)
_LLM_FAILURE_COOLDOWN_SECONDS = 30.0


class RuntimeLlmMixin:
    def _generate_answer(self, prompt: str) -> str | None:
        if not (self.settings.openai.api_key and self.settings.openai.base_url and self.settings.openai.model):
            return None
        if time.monotonic() < getattr(self, "_answer_llm_unavailable_until", 0.0):
            logger.info("Skipping answer generation while LLM failure cooldown is active")
            return None
        try:
            client = OpenAI(
                api_key=self.settings.openai.api_key,
                base_url=self.settings.openai.base_url,
                timeout=self.settings.openai.timeout_seconds,
                max_retries=self.settings.openai.max_retries,
            )
            response = client.chat.completions.create(
                model=self.settings.openai.model,
                messages=[
                    {"role": "system", "content": "你是一个严谨、善于归纳总结的个人知识库问答助手。你的首要任务不是复述检索片段，而是把证据整理成简洁、可信、可读的答案。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=600,
            )
            self._answer_llm_unavailable_until = 0.0
            return (response.choices[0].message.content or "").strip() or None
        except Exception:
            self._answer_llm_unavailable_until = time.monotonic() + _LLM_FAILURE_COOLDOWN_SECONDS
            logger.exception("Failed to generate answer from LLM")
            return None

    def _generate_answer_stream(self, prompt: str):
        """Stream tokens from the LLM in real time via SSE-compatible chunks.

        Yields (event_type, payload) tuples suitable for SSE streaming.
        Completes with ('answer_complete', {'answer': full_text}).
        On failure, yields ('answer_error', {'error': message}) and stops.
        """
        if not (self.settings.openai.api_key and self.settings.openai.base_url and self.settings.openai.model):
            yield ("answer_error", {"error": "LLM not configured"})
            return
        if time.monotonic() < getattr(self, "_answer_llm_unavailable_until", 0.0):
            yield ("answer_error", {"error": "LLM temporarily unavailable"})
            return
        try:
            client = OpenAI(
                api_key=self.settings.openai.api_key,
                base_url=self.settings.openai.base_url,
                timeout=self.settings.openai.timeout_seconds,
                max_retries=self.settings.openai.max_retries,
            )
            stream = client.chat.completions.create(
                model=self.settings.openai.model,
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
                self._answer_llm_unavailable_until = 0.0
                yield ("answer_complete", {"answer": full_text.strip()})
            else:
                yield ("answer_error", {"error": "LLM returned empty response"})
        except Exception:
            self._answer_llm_unavailable_until = time.monotonic() + _LLM_FAILURE_COOLDOWN_SECONDS
            logger.exception("Failed to stream answer from LLM")
            yield ("answer_error", {"error": "LLM streaming failed"})


