"""PLAN-REVIEW-BOUNDARY-001 live product evidence for the first review boundary."""

from __future__ import annotations

import os
from typing import Any
from urllib.error import HTTPError

import pytest

from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from evals.product_baselines.test_plan_replan_001_obligation_revision_baseline import (
    _MAX_MODEL_TURNS,
    _MAX_TOTAL_TOKENS,
    _SCENARIOS,
    _Scenario,
    _config_cohort,
    _failure_from_http,
    _feedback_reason_codes,
    _trace,
    _turn,
)
from evals.e2e_quality.test_release_user_outcomes import LiveWebProcess
from personal_agent.application.conversation.interaction_intent import (
    _DERIVATION_INSTRUCTION,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


_CASE_ID = "PLAN-REVIEW-BOUNDARY-001"
_NODE_ID = (
    "evals/product_baselines/test_plan_review_boundary_001.py::"
    "test_plan_review_boundary_001"
)


def _capture(
    recorder: ProductEvidenceRecorder,
    server: LiveWebProcess,
    *,
    scenario: _Scenario,
    repetition: int,
    report: dict[str, Any],
) -> None:
    recorder.capture(
        nodeid=_NODE_ID,
        identity=ProductEvidenceIdentity(
            case_id=_CASE_ID,
            role=product_evidence_role(_CASE_ID),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="default",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="default",
            ),
            user_input_digest=canonical_evidence_digest(scenario.initial_request),
            initial_state_digest=canonical_evidence_digest({"seeded_facts": ()}),
            config_cohort=canonical_evidence_digest({
                "runtime_cohort": _config_cohort(server),
                "review_contract_revision": "interaction_intent:v2",
                "review_instruction_digest": canonical_evidence_digest(
                    _DERIVATION_INSTRUCTION
                ),
                "turn_budget": {
                    "max_model_turns": _MAX_MODEL_TURNS,
                    "max_total_tokens": _MAX_TOTAL_TOKENS,
                },
            }),
            grader_version="plan-review-boundary-001-deterministic-v1",
        ),
        report={
            "case_id": _CASE_ID,
            "scenario_id": scenario.scenario_id,
            "repetition": repetition,
            **report,
        },
    )


@pytest.mark.parametrize("repetition", range(1, 6), ids=lambda value: f"run-{value}")
@pytest.mark.parametrize(
    "scenario",
    _SCENARIOS,
    ids=lambda scenario: scenario.scenario_id,
)
def test_plan_review_boundary_001(
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    scenario: _Scenario,
    repetition: int,
) -> None:
    expected_transport = os.getenv("PERSONAL_AGENT_PLAN_REVIEW_EXPECTED_TRANSPORT")
    if expected_transport:
        assert live_web_process.settings.structured.output_transport == expected_transport

    live_web_process.child_env[
        "PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS"
    ] = str(_MAX_MODEL_TURNS)
    live_web_process.child_env[
        "PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS"
    ] = str(_MAX_TOTAL_TOKENS)
    live_web_process.restart()
    conversation_id = f"plan-review-boundary-001-{scenario.scenario_id}-{repetition}"
    messages = [{"role": "user", "content": scenario.initial_request}]
    try:
        result = _turn(
            live_web_process,
            conversation_id=conversation_id,
            messages=messages,
        )
    except (HTTPError, TimeoutError) as error:
        metrics = {"failure_stage": "initial_turn", **_failure_from_http(error)}
        _capture(
            product_evidence_recorder,
            live_web_process,
            scenario=scenario,
            repetition=repetition,
            report={"initial_request": scenario.initial_request, "result_metrics": metrics},
        )
        pytest.fail(str(metrics))

    trace = _trace(live_web_process, result)
    plan = result.get("working_plan")
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    pending_count = sum(step.get("status") == "pending" for step in steps)
    plan_ready = (
        result.get("disposition") == "plan_ready"
        and isinstance(plan, dict)
        and pending_count > 0
        and trace.get("final_message") is None
    )
    failed_tools = sum(
        item.get("kind") == "tool_result" and item.get("status") != "succeeded"
        for item in trace.get("inputs", [])
    )
    metrics = {
        "failure_class": (
            "delivered"
            if plan_ready
            else "provider_failure"
            if failed_tools
            else "review_boundary_missing"
        ),
        "first_disposition": result.get("disposition"),
        "pending_step_count": pending_count,
        "failed_tool_result_count": failed_tools,
        "feedback_reason_codes": _feedback_reason_codes(trace),
        "usage": trace.get("usage"),
    }
    _capture(
        product_evidence_recorder,
        live_web_process,
        scenario=scenario,
        repetition=repetition,
        report={
            "initial_request": scenario.initial_request,
            "result": result,
            "trace": trace,
            "result_metrics": metrics,
        },
    )
    assert plan_ready, metrics
