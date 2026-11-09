from __future__ import annotations

import logging
import time

from personal_agent.kernel.config import Settings
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
from personal_agent.kernel.prompt_registry import PromptCatalog

logger = logging.getLogger(__name__)
_LLM_FAILURE_COOLDOWN_SECONDS = 30.0


class LlmClient:
    """Answer generation through the governed model Port.

    Depends on ``StructuredModelClient`` instead of a provider SDK. Owns its
    own failure-cooldown state so transient provider outages don't cascade.
    """

    def __init__(
        self,
        settings: Settings,
        model_client: "object | None" = None,
        *, prompts: PromptCatalog = DEFAULT_PROMPTS,
    ) -> None:
        self.settings = settings
        self._prompts = prompts
        self._model_client = model_client
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
        from personal_agent.capabilities.contracts.model import (
            StructuredModelRequest,
            sealed_context_projection_ref,
        )
        from pydantic import BaseModel

        if self._model_client is None:
            return None
        if self._in_cooldown():
            logger.info("Skipping answer generation while LLM failure cooldown is active")
            return None
        answer_prompt = self._prompts.get("answer_generation.system")
        try:
            messages = [
                {"role": "system", "content": answer_prompt.template},
                {"role": "user", "content": prompt},
            ]
            response = self._model_client.generate(StructuredModelRequest(
                operation=prompt_name,
                version=prompt_version or answer_prompt.version,
                messages=messages,
                output_type=BaseModel,
                context_projection_ref=sealed_context_projection_ref(
                    purpose=prompt_name, messages=messages,
                ),
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


def _max_tokens_for_prompt(prompt_name: str) -> int:
    if prompt_name == "research_request_understanding":
        return 1600
    if prompt_name in {"research_policy_decision", "research_satisfaction", "research_next_action"}:
        return 900
    return 600
