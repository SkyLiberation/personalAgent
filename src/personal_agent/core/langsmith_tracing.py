from __future__ import annotations

import os
import random
from contextlib import nullcontext
from typing import Any

from .config import LangSmithConfig


def configure_langsmith_environment(config: LangSmithConfig) -> None:
    """Bridge project settings to LangSmith's standard environment variables."""
    if not config.enabled:
        os.environ["LANGSMITH_TRACING"] = "false"
        return

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = config.project
    os.environ["LANGSMITH_ENDPOINT"] = config.endpoint
    if config.api_key:
        os.environ["LANGSMITH_API_KEY"] = config.api_key
    if config.workspace_id:
        os.environ["LANGSMITH_WORKSPACE_ID"] = config.workspace_id


def langsmith_trace_context(
    config: LangSmithConfig,
    *,
    metadata: dict[str, Any],
    tags: list[str] | None = None,
):
    """Return a LangSmith tracing context when enabled, otherwise a no-op."""
    if not config.enabled or not _sampled(config.sample_rate):
        return nullcontext()

    try:
        from langsmith import tracing_context
    except Exception:
        return nullcontext()

    return tracing_context(
        project_name=config.project,
        metadata=_sanitize_metadata(metadata),
        tags=tags or [],
        enabled=True,
    )


def _sampled(sample_rate: float) -> bool:
    if sample_rate <= 0:
        return False
    if sample_rate >= 1:
        return True
    return random.random() < sample_rate


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value is not None}
