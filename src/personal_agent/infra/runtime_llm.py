from __future__ import annotations

import logging
import time

from personal_agent.kernel.config import Settings
from personal_agent.kernel.prompts import get_prompt

logger = logging.getLogger(__name__)
_LLM_FAILURE_COOLDOWN_SECONDS = 30.0


class LlmClient:
    """Answer-generation LLM client (sync + streaming).

    Depends on the unified ``StructuredModelClient`` / ``StreamingModelClient``
    ports — never on ``OpenAI`` or ``traced_chat_completion`` directly. Owns its
    own failure-cooldown state so transient provider outages don't cascade.
    """

    def __init__(
        self,
        settings: Settings,
        model_client: "object | None" = None,
        streaming_client: "object | None" = None,
    ) -> None:
        self.settings = settings
        self._model_client = model_client
        self._streaming_client = streaming_client
        self._unavailable_until = 0.0

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
        from personal_agent.infra.structured_model import StructuredModelRequest
        from pydantic import BaseModel

        if self._model_client is None:
            return None
        if self._in_cooldown():
            logger.info("Skipping answer generation while LLM failure cooldown is active")
            return None
        answer_prompt = get_prompt("answer_generation.system")
        try:
            response = self._model_client.generate(StructuredModelRequest(
                operation=prompt_name,
                version=prompt_version or answer_prompt.version,
                messages=[
                    {"role": "system", "content": answer_prompt.template},
                    {"role": "user", "content": prompt},
                ],
                output_type=BaseModel,
                temperature=0.3,
                max_tokens=_max_tokens_for_prompt(prompt_name),
                kind="text",
                metadata={"component": "runtime_llm"},
            ))
            self._mark_success()
            return response.content or None
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
        from personal_agent.infra.structured_model import StructuredModelRequest
        from pydantic import BaseModel

        if self._streaming_client is None:
            yield ("answer_error", {"error": "LLM not configured"})
            return
        if self._in_cooldown():
            yield ("answer_error", {"error": "LLM temporarily unavailable"})
            return
        try:
            answer_prompt = get_prompt("answer_generation.system")
            request = StructuredModelRequest(
                operation="answer_generation_stream",
                version=answer_prompt.version,
                messages=[
                    {"role": "system", "content": answer_prompt.template},
                    {"role": "user", "content": prompt},
                ],
                output_type=BaseModel,
                temperature=0.3,
                max_tokens=_max_tokens_for_prompt("answer_generation_stream"),
                kind="text",
                metadata={"component": "runtime_llm"},
            )
            full_text = ""
            for chunk in self._streaming_client.stream(request):
                full_text = chunk.accumulated
                yield ("answer_delta", {"delta": chunk.delta, "answer": full_text})
            if full_text.strip():
                self._mark_success()
                yield ("answer_complete", {"answer": full_text.strip()})
            else:
                yield ("answer_error", {"error": "LLM returned empty response"})
        except Exception:
            self._mark_failure()
            logger.exception("Failed to stream answer from LLM")
            yield ("answer_error", {"error": "LLM streaming failed"})


def _max_tokens_for_prompt(prompt_name: str) -> int:
    if prompt_name == "research_request_understanding":
        return 1600
    if prompt_name in {"research_policy_decision", "research_satisfaction", "research_next_action"}:
        return 900
    return 600
