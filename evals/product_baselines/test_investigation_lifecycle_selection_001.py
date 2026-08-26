"""Formal product E2E for selecting an independent investigation lifecycle."""

from __future__ import annotations

from math import ceil
from urllib.error import HTTPError, URLError

import pytest

from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from evals.product_baselines.test_investigation_consolidation_001 import (
    _BACKGROUND_SCENARIOS,
    _turn,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = (
    "evals.e2e_quality.test_release_user_outcomes",
    "evals.e2e_quality.test_product_capability_outcomes",
)

_CASE_ID = "INVESTIGATION-LIFECYCLE-SELECTION-001"
_FOCUSED_CASE_ID = "INVESTIGATION-LIFECYCLE-SELECTION-001-FOCUSED"
_REPETITIONS = 5


def test_one_background_request_crosses_the_lifecycle_boundary(
    request,
    live_web_search_process,
    product_evidence_recorder: ProductEvidenceRecorder,
):
    settings = live_web_search_process.settings
    assert settings.structured.model == "mimo-v2.5"
    assert settings.structured.output_transport == "json_schema"
    assert settings.structured.extra_body == {"thinking": {"type": "disabled"}}
    scenario = _BACKGROUND_SCENARIOS[0]
    user_id = "investigation-lifecycle-selection-focused"
    try:
        started, trace, elapsed = _turn(
            live_web_search_process,
            user_id=user_id,
            conversation_id="lifecycle-focused-protocol-release-comparison",
            text=scenario.request,
        )
        error = None
    except (HTTPError, URLError, TimeoutError) as exc:
        started = {}
        trace = {}
        elapsed = 0.0
        error = {
            "type": type(exc).__name__,
            "status": getattr(exc, "code", None),
            "message": str(exc),
        }
    usage = trace.get("usage") or {}
    passed = (
        error is None
        and started.get("disposition") == "background_started"
        and bool(started.get("project_reference"))
        and trace.get("execution_lifecycle") == "durable_investigation"
        and trace.get("working_plan") is None
        and usage.get("tool_calls") == 0
        and usage.get("agent_calls") == 0
        and not trace.get("context_composition")
        and usage.get("model_calls") == 2
        and usage.get("model_turns") == 1
        and int(usage.get("total_tokens") or 0) <= 3_000
    )
    product_evidence_recorder.capture(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id=_FOCUSED_CASE_ID,
            role=product_evidence_role(_FOCUSED_CASE_ID),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=user_id,
            ),
            user_input_digest=canonical_evidence_digest([scenario.request]),
            initial_state_digest=canonical_evidence_digest({
                "scenario_count": 1,
                "repetitions": 1,
                "isolated_web_process": True,
                "initial_projects": 0,
            }),
            config_cohort=canonical_evidence_digest({
                "model": settings.structured.model,
                "base_url": str(settings.structured.base_url),
                "output_transport": settings.structured.output_transport,
                "extra_body": settings.structured.extra_body,
                "timeout_seconds": settings.structured.timeout_seconds,
                "max_retries": settings.structured.max_retries,
                "intent_contract": "interaction_intent:v2",
                "request_contract": "durable_investigation_start_proposal:v1",
            }),
            grader_version="investigation-lifecycle-selection-001-v1",
        ),
        report={
            "passed": passed,
            "elapsed_seconds": round(elapsed, 6),
            "error": error,
            "started": started,
            "trace": trace,
        },
    )
    assert passed, {"started": started, "trace": trace, "error": error}


def test_background_request_enters_the_project_lifecycle_before_resource_selection(
    request,
    live_web_search_process,
    product_evidence_recorder: ProductEvidenceRecorder,
):
    settings = live_web_search_process.settings
    assert settings.structured.model == "mimo-v2.5"
    assert settings.structured.output_transport == "json_schema"
    assert settings.structured.extra_body == {"thinking": {"type": "disabled"}}

    user_id = "investigation-lifecycle-selection-cohort"
    all_inputs = [
        scenario.request
        for scenario in _BACKGROUND_SCENARIOS
        for _ in range(_REPETITIONS)
    ]
    reports = []
    for scenario in _BACKGROUND_SCENARIOS:
        for repetition in range(1, _REPETITIONS + 1):
            try:
                started, trace, elapsed = _turn(
                    live_web_search_process,
                    user_id=user_id,
                    conversation_id=(
                        f"lifecycle-{scenario.scenario_id}-{repetition}"
                    ),
                    text=scenario.request,
                )
                error = None
            except (HTTPError, URLError, TimeoutError) as exc:
                started = {}
                trace = {}
                elapsed = 0.0
                error = {
                    "type": type(exc).__name__,
                    "status": getattr(exc, "code", None),
                    "message": str(exc),
                }
            usage = trace.get("usage") or {}
            reports.append({
                "scenario_id": scenario.scenario_id,
                "repetition": repetition,
                "background_started": (
                    started.get("disposition") == "background_started"
                ),
                "project_reference_present": bool(started.get("project_reference")),
                "execution_lifecycle": trace.get("execution_lifecycle"),
                "working_plan_absent": trace.get("working_plan") is None,
                "no_resource_execution": (
                    usage.get("tool_calls") == 0
                    and usage.get("agent_calls") == 0
                    and not trace.get("context_composition")
                ),
                "model_calls": usage.get("model_calls"),
                "model_turns": usage.get("model_turns"),
                "total_tokens": usage.get("total_tokens"),
                "elapsed_seconds": round(elapsed, 6),
                "error": error,
                "started": started,
                "trace": trace,
            })

    elapsed_values = sorted(
        item["elapsed_seconds"] for item in reports if item["error"] is None
    )
    p95 = (
        elapsed_values[ceil(len(elapsed_values) * 0.95) - 1]
        if elapsed_values
        else None
    )
    total_tokens = sum(
        int(item["total_tokens"] or 0) for item in reports
    )
    passed = all(
        item["error"] is None
        and item["background_started"]
        and item["project_reference_present"]
        and item["execution_lifecycle"] == "durable_investigation"
        and item["working_plan_absent"]
        and item["no_resource_execution"]
        and item["model_calls"] == 2
        and item["model_turns"] == 1
        and int(item["total_tokens"] or 0) <= 3_000
        for item in reports
    )
    product_evidence_recorder.capture(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id=_CASE_ID,
            role=product_evidence_role(_CASE_ID),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=user_id,
            ),
            user_input_digest=canonical_evidence_digest(all_inputs),
            initial_state_digest=canonical_evidence_digest({
                "scenario_count": len(_BACKGROUND_SCENARIOS),
                "repetitions": _REPETITIONS,
                "isolated_web_process": True,
                "initial_projects": 0,
            }),
            config_cohort=canonical_evidence_digest({
                "model": settings.structured.model,
                "base_url": str(settings.structured.base_url),
                "output_transport": settings.structured.output_transport,
                "extra_body": settings.structured.extra_body,
                "timeout_seconds": settings.structured.timeout_seconds,
                "max_retries": settings.structured.max_retries,
                "intent_contract": "interaction_intent:v2",
                "request_contract": "durable_investigation_start_proposal:v1",
            }),
            grader_version="investigation-lifecycle-selection-001-v1",
        ),
        report={
            "sample_count": len(reports),
            "background_started_count": sum(
                bool(item["background_started"]) for item in reports
            ),
            "project_reference_count": sum(
                bool(item["project_reference_present"]) for item in reports
            ),
            "provider_failure_count": sum(
                item["error"] is not None for item in reports
            ),
            "model_turn_count": sum(
                int(item["model_turns"] or 0) for item in reports
            ),
            "total_tokens": total_tokens,
            "p95_elapsed_seconds": p95,
            "passed": passed,
            "reports": reports,
        },
    )

    assert len(reports) == 20
    assert passed, reports
    assert total_tokens <= 110_901
    assert p95 is not None and p95 <= 120
