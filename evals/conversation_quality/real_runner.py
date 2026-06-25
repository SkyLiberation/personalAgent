"""Fully real multi-turn runner (real router LLM, runtime, checkpoint and store)."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.llm_telemetry import collect_llm_usage
from personal_agent.infra.structured_model import build_structured_model_client

from .dataset import ConversationEvalCase, ConversationRunOutput
from .runner import execute_conversation


def build_real_service() -> AgentService | None:
    try:
        settings = Settings.from_env()
    except Exception:
        return None
    if not settings.postgres_url:
        return None
    if build_structured_model_client(settings.router, settings.langsmith) is None:
        return None
    try:
        return AgentService(settings)
    except Exception:
        return None


def execute_real_case(
    service: AgentService,
    case: ConversationEvalCase,
) -> ConversationRunOutput:
    safe_id = case.id.replace("/", "-")
    invocation_id = uuid4().hex[:8]
    started = perf_counter()
    with collect_llm_usage() as usage:
        output = execute_conversation(
            service,
            case,
            user_id=f"conversation-real-{safe_id}-{invocation_id}",
            session_id=f"conversation-real-{safe_id}-{invocation_id}",
        )
    output.latency_ms = round((perf_counter() - started) * 1000, 2)
    output.llm_call_count = usage.call_count
    output.input_tokens = usage.input_tokens
    output.output_tokens = usage.output_tokens
    output.total_tokens = usage.total_tokens
    return output
