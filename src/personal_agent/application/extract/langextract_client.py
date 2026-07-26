"""Thin LangExtract client wrapper.

The adapter uses the canonical OpenAI-compatible generation provider by
default and can still be explicitly overridden for provider contract tests.

Schema is constructed by hand (see :mod:`.openai_schema`) and bound to the
language model directly so it cannot be overridden by LangExtract's
``factory.create_model`` example-derived schema. The hand-crafted schema
upgrades ``information_density`` from a free-form string to a closed enum,
which the auto-derived schema cannot express.
"""
from __future__ import annotations

import logging
from typing import Any

import langextract as lx
from langextract.providers.openai import OpenAILanguageModel

from personal_agent.kernel.config import LangExtractConfig
from langextract.providers.schemas.openai import OpenAISchema

from personal_agent.application.extract.openai_schema import build_section_openai_schema

logger = logging.getLogger(__name__)


class LangExtractMisconfiguredError(RuntimeError):
    """Raised when LangExtractConfig is enabled but missing required fields."""


def build_language_model(
    config: LangExtractConfig,
    *,
    openai_schema: OpenAISchema | None = None,
) -> OpenAILanguageModel:
    """Construct an OpenAILanguageModel pre-bound to our custom strict schema."""
    if not config.api_key:
        raise LangExtractMisconfiguredError(
            "LangExtractConfig.api_key is empty; set STRUCTURED_API_KEY or "
            "PERSONAL_AGENT_EXTRACT_API_KEY in the environment."
        )
    return OpenAILanguageModel(
        model_id=config.model_id,
        api_key=config.api_key,
        base_url=config.base_url,
        openai_schema=openai_schema or build_section_openai_schema(),
        max_workers=config.max_workers,
    )


def run_extract(
    text: str,
    *,
    prompt: str,
    examples: list[lx.data.ExampleData],
    config: LangExtractConfig,
    openai_schema: OpenAISchema | None = None,
    **extra_kwargs: Any,
) -> lx.data.AnnotatedDocument:
    """Run a single LangExtract pass against the configured endpoint.

    Caller is expected to handle exceptions; this wrapper does not swallow.
    """
    language_model = build_language_model(config, openai_schema=openai_schema)
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
        model=language_model,
        # The model already carries our custom schema; tell lx.extract not to
        # re-derive one from examples and not to emit the "ignored" warning.
        use_schema_constraints=False,
        max_char_buffer=config.max_char_buffer,
        extraction_passes=config.extraction_passes,
        max_workers=config.max_workers,
        **extra_kwargs,
    )
