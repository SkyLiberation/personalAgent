"""Real-environment runner for the router-quality golden set.

The offline gate (test_router_gate.py) drives the deterministic
``stub_router_decision`` — reproducible, but blind to how the *real* LLM router
behaves. This runner closes that gap: it builds a real ``DefaultIntentRouter``
from ``Settings.from_env()`` and classifies each golden-set case through the
live model, projecting the decision into the same ``RouterRunOutput`` the
offline scorer already consumes. Same cases, same metrics, same baseline shape —
only the system under test changes (stub → real LLM).

This is the layer that would have caught the DNS incident: the stub routed
"什么是DNS" to ``ask`` correctly, but the real LLM mis-routed it to
``solidify_conversation``. A real-environment tier scores the real model.

Requires a configured router LLM (ROUTER_* / OPENAI_* env). When unconfigured,
``build_real_router`` returns None so the gate can skip rather than fail — this
is the Golden Test runner; the offline runner remains a contract test.
"""

from __future__ import annotations

from time import perf_counter

from personal_agent.planning.router import DefaultIntentRouter
from personal_agent.kernel.config import Settings
from personal_agent.kernel.llm_telemetry import collect_llm_usage
from personal_agent.kernel.models import EntryInput
from personal_agent.infra.structured_model import build_structured_model_client

from .dataset import RouterEvalCase, RouterRunOutput
from .runner import run_output_from_decision


def build_real_router() -> DefaultIntentRouter | None:
    """Build a real LLM-backed router from env, or None when unconfigured."""
    settings = Settings.from_env()
    client = build_structured_model_client(settings.router, settings.langsmith)
    if client is None:
        return None
    return DefaultIntentRouter(client)


def classify_case(router: DefaultIntentRouter, case: RouterEvalCase) -> RouterRunOutput:
    """Route one case through the real router and project to a RouterRunOutput."""
    started = perf_counter()
    with collect_llm_usage() as usage:
        decision = router.classify(
            EntryInput(
                text=case.text,
                user_id="router-eval",
                session_id=f"router-eval-{case.id}",
                source_type=case.source_type,
            )
        )
    output = run_output_from_decision(decision)
    output.latency_ms = round((perf_counter() - started) * 1000, 2)
    output.llm_call_count = usage.call_count
    output.input_tokens = usage.input_tokens
    output.output_tokens = usage.output_tokens
    output.total_tokens = usage.total_tokens
    return output
