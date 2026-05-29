"""Thin LangExtract client wrapper.

Pinned to qwen3-coder-flash on Aliyun DashScope's OpenAI-compatible endpoint
because that is the cheapest model we tested that supports OpenAI-style
``response_format = json_schema``. DeepSeek and qwen3.6-flash do NOT support
json_schema and would require ``use_schema_constraints=False`` plus fence
output, which weakens schema enforcement.
"""
from __future__ import annotations

import logging
from typing import Any

import langextract as lx
from langextract.factory import ModelConfig

from ..core.config import LangExtractConfig

logger = logging.getLogger(__name__)


class LangExtractMisconfiguredError(RuntimeError):
    """Raised when LangExtractConfig is enabled but missing required fields."""


def build_model_config(config: LangExtractConfig) -> ModelConfig:
    if not config.api_key:
        raise LangExtractMisconfiguredError(
            "LangExtractConfig.api_key is empty; set PERSONAL_AGENT_EXTRACT_API_KEY "
            "or EMBEDDING_API_KEY in the environment."
        )
    return ModelConfig(
        model_id=config.model_id,
        provider="openai",
        provider_kwargs={
            "api_key": config.api_key,
            "base_url": config.base_url,
        },
    )


def run_extract(
    text: str,
    *,
    prompt: str,
    examples: list[lx.data.ExampleData],
    config: LangExtractConfig,
    **extra_kwargs: Any,
) -> lx.data.AnnotatedDocument:
    """Run a single LangExtract pass against the configured endpoint.

    Caller is expected to handle exceptions; this wrapper does not swallow.
    """
    model_config = build_model_config(config)
    logger.info(
        "langextract.run model=%s base_url=%s text_len=%d passes=%d max_workers=%d",
        config.model_id,
        config.base_url,
        len(text),
        config.extraction_passes,
        config.max_workers,
    )
    return lx.extract(
        text_or_documents=text,
        prompt_description=prompt,
        examples=examples,
        config=model_config,
        max_char_buffer=config.max_char_buffer,
        extraction_passes=config.extraction_passes,
        max_workers=config.max_workers,
        **extra_kwargs,
    )
