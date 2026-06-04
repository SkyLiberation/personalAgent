from __future__ import annotations

import logging
import time

from openai import OpenAI

from ..core.langsmith_tracing import langsmith_trace_context
from ..core.llm_trace import traced_chat_completion
from ..core.logging_utils import log_event

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
            result = traced_chat_completion(
                self.settings.openai,
                prompt_name="answer_generation",
                messages=[
                    {"role": "system", "content": "你是一个严谨、善于归纳总结的个人知识库问答助手。你的首要任务不是复述检索片段，而是把证据整理成简洁、可信、可读的答案。"},
                    {"role": "user", "content": prompt},
                ],
                model=self.settings.openai.model,
                temperature=0.3,
                max_tokens=600,
                metadata={"component": "runtime_llm"},
                upload_inputs_outputs=self.settings.langsmith.upload_inputs,
            )
            self._answer_llm_unavailable_until = 0.0
            return result.content or None
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
            start = time.monotonic()
            with langsmith_trace_context(
                self.settings.langsmith,
                metadata={"component": "runtime_llm", "prompt_name": "answer_generation_stream"},
                tags=["llm", "stream", "answer_generation"],
            ):
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
                latency_ms = round((time.monotonic() - start) * 1000, 2)
                if full_text.strip():
                    self._answer_llm_unavailable_until = 0.0
                    log_event(
                        logger,
                        logging.INFO,
                        "llm.stream",
                        prompt_name="answer_generation_stream",
                        model=self.settings.openai.model,
                        latency_ms=latency_ms,
                        response_chars=len(full_text.strip()),
                    )
                    yield ("answer_complete", {"answer": full_text.strip()})
                else:
                    log_event(
                        logger,
                        logging.WARNING,
                        "llm.stream",
                        prompt_name="answer_generation_stream",
                        model=self.settings.openai.model,
                        latency_ms=latency_ms,
                        response_chars=0,
                    )
                    yield ("answer_error", {"error": "LLM returned empty response"})
        except Exception:
            self._answer_llm_unavailable_until = time.monotonic() + _LLM_FAILURE_COOLDOWN_SECONDS
            logger.exception("Failed to stream answer from LLM")
            yield ("answer_error", {"error": "LLM streaming failed"})


