from __future__ import annotations

import os
import random
from contextlib import nullcontext
from typing import Any

from personal_agent.kernel.config import LangSmithConfig


def configure_langsmith_environment(config: LangSmithConfig) -> None:
    """Bridge project settings to LangSmith's standard environment variables."""
    if not config.enabled:
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGSMITH_TRACING_V2"] = "false"
        return

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_TRACING_V2"] = "true"
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
    """Return a LangSmith tracing context when enabled, otherwise a no-op.

    When tracing is enabled but this run is not sampled, we explicitly disable
    tracing for the context rather than returning a no-op: the ``LANGSMITH_*``
    environment variables install a global tracer that would otherwise keep
    emitting runs regardless of ``sample_rate``.
    """
    if not config.enabled:
        return nullcontext()

    try:
        from langsmith import tracing_context
    except Exception:
        return nullcontext()

    if not _sampled(config.sample_rate):
        return tracing_context(enabled=False)

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


def langsmith_llm_span(
    config: LangSmithConfig,
    *,
    name: str,
    metadata: dict[str, Any],
    tags: list[str] | None = None,
):
    """Open a LangSmith LLM run for hand-rolled (e.g. streaming) calls.

    Yields the active run (or ``None`` when tracing is off/unsampled) so the
    caller can attach ``usage_metadata`` and outputs once the stream finishes.
    """
    if not config.enabled or not _sampled(config.sample_rate):
        return nullcontext()

    try:
        from langsmith import trace
    except Exception:
        return nullcontext()

    return trace(
        name=name,
        run_type="llm",
        project_name=config.project,
        metadata=_sanitize_metadata(metadata),
        tags=tags or [],
    )


def report_usage_metadata(run: Any, usage: dict[str, int]) -> None:
    """Attach token usage to an open run/run-tree, tolerating no-op contexts."""
    if run is None or not usage:
        return
    try:
        run.set(usage_metadata=usage)
    except Exception:  # pragma: no cover - tracing must never break the call
        pass


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value is not None}
