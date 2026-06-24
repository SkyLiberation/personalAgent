"""Real-environment runner for the orchestration-quality golden set.

The offline gate (test_orchestration_gate.py) drives a real ``AgentRuntime`` but
with the router LLM stubbed. This runner removes the last stub: it builds a real
``AgentService`` from ``Settings.from_env()`` — real router LLM, real planning,
real step execution — and runs each case through ``execute_entry``, projecting
the result into the same ``OrchestrationRunOutput`` the offline scorer consumes.

This is the only tier where routing, planning, and orchestration are ALL real,
so it is the one that scores true end-to-end behavior (including the multi-goal
decomposition the stub cannot produce).

Requires a configured router LLM + Postgres. ``build_real_service`` returns None
when unconfigured so the gate skips. This Golden Test is slow:
real runs may drive live LLM planning and (for capture/solidify) background
graph ingestion.
"""

from __future__ import annotations

from time import perf_counter

from personal_agent.agent.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.llm_telemetry import collect_llm_usage
from personal_agent.kernel.models import EntryInput
from personal_agent.core.structured_model import build_structured_model_client

from .dataset import OrchestrationRunOutput
from .runner import run_output_from_entry_result


def build_real_service() -> AgentService | None:
    """Build a real AgentService (real router LLM) from env, or None when
    the router LLM or Postgres is unconfigured."""
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


def execute_case(service: AgentService, case) -> OrchestrationRunOutput:
    """Run one case through the real entry pipeline and project the result."""
    started = perf_counter()
    with collect_llm_usage() as usage:
        result = service.execute_entry(
            EntryInput(
                text=case.text,
                user_id="orch-real-eval",
                session_id=f"orch-real-{case.id}",
            )
        )
    output = run_output_from_entry_result(result)
    output.latency_ms = round((perf_counter() - started) * 1000, 2)
    output.llm_call_count = usage.call_count
    output.input_tokens = usage.input_tokens
    output.output_tokens = usage.output_tokens
    output.total_tokens = usage.total_tokens
    return output
