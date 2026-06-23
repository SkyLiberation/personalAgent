from __future__ import annotations

import logging
import time

from openai import OpenAI

from ..core.config import Settings
from ..core.langsmith_tracing import langsmith_llm_span, report_usage_metadata
from ..core.llm_telemetry import record_llm_usage
from ..core.llm_trace import traced_chat_completion
from ..core.logging_utils import log_event
from ..core.prompts import get_prompt

logger = logging.getLogger(__name__)
_LLM_FAILURE_COOLDOWN_SECONDS = 30.0


class LlmClient:
    """Answer-generation LLM client (sync + streaming).

    Extracted from the former ``RuntimeLlmMixin`` so collaborators depend on an
    explicit object instead of a sibling method bolted onto a shared ``self``.
    Owns its own failure-cooldown state.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._unavailable_until = 0.0

    def _configured(self) -> bool:
        oa = self.settings.openai
        return bool(oa.api_key and oa.base_url and oa.model)

    def _in_cooldown(self) -> bool:
        return time.monotonic() < self._unavailable_until

    def _mark_failure(self) -> None:
        self._unavailable_until = time.monotonic() + _LLM_FAILURE_COOLDOWN_SECONDS

    def _mark_success(self) -> None:
        self._unavailable_until = 0.0

    def generate_answer(
        self,
        prompt: str,
        *,
        prompt_name: str = "answer_generation",
        prompt_version: str | None = None,
    ) -> str | None:
        if not self._configured():
            return None
        if self._in_cooldown():
            logger.info("Skipping answer generation while LLM failure cooldown is active")
            return None
        answer_prompt = get_prompt("answer_generation.system")
        try:
            result = traced_chat_completion(
                self.settings.openai,
                prompt_name=prompt_name,
                prompt_version=prompt_version or answer_prompt.version,
                messages=[
                    {"role": "system", "content": answer_prompt.template},
                    {"role": "user", "content": prompt},
                ],
                model=self.settings.openai.model,
                temperature=0.3,
                max_tokens=600,
                metadata={"component": "runtime_llm"},
                upload_inputs_outputs=self.settings.langsmith.upload_inputs,
            )
            self._mark_success()
            return result.content or None
        except Exception:
            self._mark_failure()
            logger.exception("Failed to generate answer from LLM")
            return None

    def generate_answer_stream(self, prompt: str):
        """Stream tokens from the LLM in real time via SSE-compatible chunks.

        Yields (event_type, payload) tuples suitable for SSE streaming.
        Completes with ('answer_complete', {'answer': full_text}).
        On failure, yields ('answer_error', {'error': message}) and stops.
        """
        if not self._configured():
            yield ("answer_error", {"error": "LLM not configured"})
            return
        if self._in_cooldown():
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
            answer_prompt = get_prompt("answer_generation.system")
            with langsmith_llm_span(
                self.settings.langsmith,
                name="llm.answer_generation_stream",
                metadata={
                    "component": "runtime_llm",
                    "prompt_name": "answer_generation_stream",
                    "prompt_version": answer_prompt.version,
                    "model": self.settings.openai.model,
                },
                tags=["llm", "stream", "answer_generation"],
            ) as run:
                stream = client.chat.completions.create(
                    model=self.settings.openai.model,
                    messages=[
                        {"role": "system", "content": answer_prompt.template},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=600,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                full_text = ""
                usage: dict[str, int] = {}
                for chunk in stream:
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        for key, attr in (
                            ("input_tokens", "prompt_tokens"),
                            ("output_tokens", "completion_tokens"),
                            ("total_tokens", "total_tokens"),
                        ):
                            value = getattr(chunk_usage, attr, None)
                            if isinstance(value, int):
                                usage[key] = value
                    delta = chunk.choices[0].delta.content if chunk.choices else ""
                    if delta:
                        full_text += delta
                        yield ("answer_delta", {"delta": delta, "answer": full_text})
                report_usage_metadata(run, usage)
                latency_ms = round((time.monotonic() - start) * 1000, 2)
                record_llm_usage(
                    latency_ms=latency_ms,
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    total_tokens=usage.get("total_tokens"),
                )
                if full_text.strip():
                    self._mark_success()
                    log_event(
                        logger,
                        logging.INFO,
                        "llm.stream",
                        prompt_name="answer_generation_stream",
                        model=self.settings.openai.model,
                        latency_ms=latency_ms,
                        response_chars=len(full_text.strip()),
                        input_tokens=usage.get("input_tokens"),
                        output_tokens=usage.get("output_tokens"),
                        total_tokens=usage.get("total_tokens"),
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
            self._mark_failure()
            logger.exception("Failed to stream answer from LLM")
            yield ("answer_error", {"error": "LLM streaming failed"})
