from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, TYPE_CHECKING

import anthropic
import openai
from anthropic import AsyncAnthropic
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, LLMConfig, ModelSize
from graphiti_core.llm_client.openai_generic_client import (
    DEFAULT_MODEL,
    OpenAIGenericClient,
)
from graphiti_core.prompts.models import Message
from pydantic import BaseModel

from .deepseek_compatible_client import (
    _extract_json_text,
    normalize_structured_payload,
    _THINK_BLOCK_RE,
    _JSON_BLOCK_RE,
)

if TYPE_CHECKING:
    from ..core.config import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalized OpenAI-generic client
# ---------------------------------------------------------------------------


class NormalizedOpenAIGenericClient(OpenAIGenericClient):
    """Official ``OpenAIGenericClient`` with reasoning-model response normalization.

    Adds think-block stripping (MiniMax M2.7, DeepSeek-R1), markdown code-block
    extraction, and structured-payload normalization (entity/edge/summary field
    aliases, missing ``name`` fallback, nested JSON-string expansion) on top of
    the upstream client that Graphiti recommends for non-OpenAI providers.
    """

    MAX_RETRIES: ClassVar[int] = 2

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        import asyncio as _asyncio
        import time as _time

        openai_messages = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == "user":
                openai_messages.append({"role": "user", "content": m.content})
            elif m.role == "system":
                openai_messages.append({"role": "system", "content": m.content})

        # Kimi K2.6: json_schema requires thinking disabled to avoid whitespace
        # output from stripped reasoning tokens. Use json_schema for strict
        # schema adherence when response_model is provided.
        if response_model is not None:
            json_schema = response_model.model_json_schema()
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "schema": json_schema,
                },
            }
        else:
            response_format = {"type": "json_object"}

        # Kimi API rate limit: 20 RPM. Use a class-level timestamp so the
        # delay works across client instances (graphiti_core recreates the
        # client for each call).
        last_call: float = getattr(NormalizedOpenAIGenericClient, "_last_api_call_ts", 0.0)
        elapsed = _time.monotonic() - last_call
        if elapsed < 2.0:
            await _asyncio.sleep(2.0 - elapsed)

        last_error = None
        for retry in range(3):
            try:
                NormalizedOpenAIGenericClient._last_api_call_ts = _time.monotonic()
                response = await self.client.chat.completions.create(
                    model=self.model or DEFAULT_MODEL,
                    messages=openai_messages,
                    temperature=0.6,  # Kimi K2.6 only supports temperature=0.6
                    max_tokens=self.max_tokens,
                    response_format=response_format,  # type: ignore[arg-type]
                    extra_body={"thinking": {"type": "disabled"}},
                )
                raw = response.choices[0].message.content or ""

                text = _extract_json_text(raw)
                try:
                    result = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning(
                        "LLM returned non-JSON content (len=%d): %.200s...", len(text), text
                    )
                    raise

                if response_model is not None:
                    result = normalize_structured_payload(result, response_model)

                return result
            except openai.RateLimitError as _rle:
                from graphiti_core.llm_client.errors import RateLimitError as _RateLimitError

                raw_msg = str(_rle)
                logger.warning("Kimi rate limit raw: %s", raw_msg[:200])
                last_error = _RateLimitError("Rate limit exceeded. Please try again later.")
                if retry < 2:
                    wait = 5.0 * (retry + 1)  # 5s, 10s
                    logger.warning("Kimi rate limit hit, retrying in %.1fs (attempt %d/3)...", wait, retry + 1)
                    await _asyncio.sleep(wait)
            except Exception:
                logger.error("Error in generating LLM response: %s", raw if "raw" in locals() else "<no response>")
                raise

        raise last_error  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------


class LlmClientStrategy(Protocol):
    """Interface for a Graphiti LLM-client factory."""

    name: str
    description: str

    def build_client(self, settings: Any) -> Any:
        """Create a Graphiti-compatible LLM client from project settings."""
        ...


@dataclass(frozen=True)
class OpenAIGenericStrategy:
    """OpenAI-compatible providers via ``OpenAIGenericClient`` with normalization."""

    name: str = "openai_generic"
    description: str = (
        "Graphiti official OpenAIGenericClient with reasoning-model "
        "response normalization (think-block stripping, entity/edge "
        "field aliases, missing-name fallback)."
    )

    def build_client(self, settings: Settings) -> NormalizedOpenAIGenericClient:
        return NormalizedOpenAIGenericClient(
            config=LLMConfig(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_model,
                small_model=settings.openai_small_model,
            )
        )


class NormalizedAnthropicClient(AnthropicClient):
    """AnthropicClient with robust JSON extraction for reasoning-model providers.

    When providers (e.g. MiniMax Anthropic endpoint) return ThinkingBlock +
    TextBlock instead of tool_use blocks, the upstream ``_extract_json_from_text``
    (simple ``find('{')`` / ``rfind('}')``) can't reliably extract clean JSON
    from verbose mixed-content responses.  This subclass:

    - Skips ``ThinkingBlock`` items when searching for text/tool_use content
      (the upstream ``else: raise ValueError`` fires on the first non-text item).
    - Strips ``<think>`` tags embedded in text content.
    - Extracts JSON from markdown code blocks before falling back to the
      parent's bracket-based extraction.
    """

    def _extract_json_from_text(self, text: str) -> dict[str, Any]:
        cleaned = _THINK_BLOCK_RE.sub("", text).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        match = _JSON_BLOCK_RE.search(cleaned)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        return super()._extract_json_from_text(text)

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        model_size: ModelSize = ModelSize.medium,
    ) -> tuple[dict[str, Any], int, int]:
        # Replicate the parent's message-building and API call, then fix the
        # response-parsing loop so ThinkingBlock items don't short-circuit the
        # text fallback.
        import typing

        from anthropic.types import MessageParam

        system_message = messages[0]
        user_messages = [{"role": m.role, "content": m.content} for m in messages[1:]]
        user_messages_cast = typing.cast(list[MessageParam], user_messages)

        max_creation_tokens: int = self._resolve_max_tokens(max_tokens, self.model)  # type: ignore[arg-type]

        try:
            tools, tool_choice = self._create_tool(response_model)
            result = await self.client.messages.create(
                system=system_message.content,
                max_tokens=max_creation_tokens,
                temperature=self.temperature,
                messages=user_messages_cast,
                model=self.model,
                tools=tools,
                tool_choice=tool_choice,
            )

            input_tokens = 0
            output_tokens = 0
            if hasattr(result, "usage") and result.usage:
                input_tokens = getattr(result.usage, "input_tokens", 0) or 0
                output_tokens = getattr(result.usage, "output_tokens", 0) or 0

            # --- Fixed response parsing: skip thinking blocks ---
            text_block: str | None = None

            for content_item in result.content:
                if content_item.type == "tool_use":
                    if isinstance(content_item.input, dict):
                        tool_args: dict[str, Any] = content_item.input
                    else:
                        tool_args = json.loads(str(content_item.input))
                    return tool_args, input_tokens, output_tokens
                elif content_item.type == "text":
                    text_block = content_item.text

            if text_block is not None:
                return (
                    self._extract_json_from_text(text_block),
                    input_tokens,
                    output_tokens,
                )

            raise ValueError(
                f"Could not extract structured data from model response: {result.content}"
            )

        except anthropic.RateLimitError as e:
            from graphiti_core.llm_client.errors import RateLimitError

            raise RateLimitError from e
        except anthropic.APIError as e:
            from graphiti_core.llm_client.errors import RefusalError

            if "refused to respond" in str(e).lower():
                raise RefusalError(str(e)) from e
            raise e


@dataclass(frozen=True)
class AnthropicStrategy:
    """Anthropic Messages API via ``NormalizedAnthropicClient``.

    Works with Anthropic official API and Anthropic-compatible endpoints
    (e.g. ``https://api.minimaxi.com/anthropic``).  Uses native tool-use
    for structured output with a robust text-extraction fallback for
    reasoning-model providers that return text instead of tool_use blocks.
    """

    name: str = "anthropic"
    description: str = (
        "Graphiti AnthropicClient with native tool-use structured output "
        "and robust JSON text-extraction fallback for reasoning-model "
        "providers (MiniMax Anthropic endpoint)."
    )

    def build_client(self, settings: Settings) -> NormalizedAnthropicClient:
        api_key = settings.anthropic_api_key
        base_url = settings.anthropic_base_url
        model = settings.anthropic_model

        if base_url:
            client = AsyncAnthropic(
                api_key=api_key,
                base_url=base_url,
                max_retries=1,
            )
        else:
            client = None

        return NormalizedAnthropicClient(
            config=LLMConfig(
                api_key=api_key,
                base_url=base_url or "",
                model=model,
            ),
            client=client,
        )


STRATEGIES: dict[str, LlmClientStrategy] = {
    "openai_generic": OpenAIGenericStrategy(),
    "anthropic": AnthropicStrategy(),
}


def get_llm_strategy(name: str | None) -> LlmClientStrategy:
    normalized = (name or "openai_generic").strip().lower()
    if normalized not in STRATEGIES:
        available = ", ".join(sorted(STRATEGIES))
        raise ValueError(f"Unknown LLM strategy '{name}'. Available: {available}")
    return STRATEGIES[normalized]


def list_llm_strategies() -> list[dict[str, str]]:
    return [
        {"name": s.name, "description": s.description} for s in STRATEGIES.values()
    ]
