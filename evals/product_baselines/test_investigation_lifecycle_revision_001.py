"""Product E2E for bounded revision of a rejected lifecycle proposal."""

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

_CASE_ID = "INVESTIGATION-LIFECYCLE-REVISION-001"
_FOCUSED_CASE_ID = "INVESTIGATION-LIFECYCLE-REVISION-001-FOCUSED"
_REPETITIONS = 5
_REVISION_REASON = "interaction_lifecycle_revision_required"


def _sample_report(started, trace, elapsed, error):
    usage = trace.get("usage") or {}
    revision_feedback_count = sum(
        isinstance(item, dict) and item.get("reason_code") == _REVISION_REASON
        for item in trace.get("inputs") or ()
    )
    return {
        "background_started": started.get("disposition") == "background_started",
        "project_reference_present": bool(started.get("project_reference")),
        "execution_lifecycle": trace.get("execution_lifecycle"),
        "working_plan_absent": trace.get("working_plan") is None,
        "no_conversation_resource_execution": (
            usage.get("tool_calls") == 0
            and usage.get("agent_calls") == 0
            and not trace.get("context_composition")
        ),
        "revision_feedback_count": revision_feedback_count,
        "model_calls": usage.get("model_calls"),
        "model_turns": usage.get("model_turns"),
        "total_tokens": usage.get("total_tokens"),
        "elapsed_seconds": round(elapsed, 6),
        "error": error,
        "started": started,
        "trace": trace,
    }


def _sample_passed(report):
    return (
        report["error"] is None
        and report["background_started"]
        and report["project_reference_present"]
        and report["execution_lifecycle"] == "durable_investigation"
        and report["working_plan_absent"]
        and report["no_conversation_resource_execution"]
        and report["revision_feedback_count"] in {0, 1}
        and report["model_calls"] == 2 + report["revision_feedback_count"]
        and report["model_turns"] == 1
        and int(report["total_tokens"] or 0) <= 6_000
    )


def _config_cohort(server):
    settings = server.settings
    return canonical_evidence_digest({
        "model": settings.structured.model,
        "base_url": str(settings.structured.base_url),
        "output_transport": settings.structured.output_transport,
        "extra_body": settings.structured.extra_body,
        "timeout_seconds": settings.structured.timeout_seconds,
        "max_retries": settings.structured.max_retries,
        "intent_contract": "interaction_intent:v2",
        "intent_revision_contract": "single-typed-revision:v1",
        "request_contract": "durable_investigation_start_proposal:v1",
        "grader": "investigation-lifecycle-revision-001-v2",
    })


def _execute_turn(server, *, user_id, conversation_id, text):
    try:
        started, trace, elapsed = _turn(
            server,
            user_id=user_id,
            conversation_id=conversation_id,
            text=text,
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
    return _sample_report(started, trace, elapsed, error)


def _assert_canonical_provider(server):
    settings = server.settings
    assert settings.structured.model == "mimo-v2.5"
    assert settings.structured.output_transport == "json_schema"
    assert settings.structured.extra_body == {"thinking": {"type": "disabled"}}


def test_one_background_request_preserves_the_lifecycle_boundary(
    request,
    live_web_search_process,
    product_evidence_recorder: ProductEvidenceRecorder,
):
    _assert_canonical_provider(live_web_search_process)
    scenario = _BACKGROUND_SCENARIOS[0]
    user_id = "investigation-lifecycle-revision-focused"
    report = _execute_turn(
        live_web_search_process,
        user_id=user_id,
        conversation_id="lifecycle-revision-focused-protocol-release-comparison",
        text=scenario.request,
    )
    passed = _sample_passed(report)
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
                "initial_projects": 0,
            }),
            config_cohort=_config_cohort(live_web_search_process),
            grader_version="investigation-lifecycle-revision-001-v2",
        ),
        report={"passed": passed, "sample": report},
    )
    assert passed, report


def test_lifecycle_revision_meets_the_formal_product_gate(
    request,
    live_web_search_process,
    product_evidence_recorder: ProductEvidenceRecorder,
):
    _assert_canonical_provider(live_web_search_process)
    user_id = "investigation-lifecycle-revision-cohort"
    all_inputs = [
        scenario.request
        for scenario in _BACKGROUND_SCENARIOS
        for _ in range(_REPETITIONS)
    ]
    reports = []
    for scenario in _BACKGROUND_SCENARIOS:
        for repetition in range(1, _REPETITIONS + 1):
            report = _execute_turn(
                live_web_search_process,
                user_id=user_id,
                conversation_id=(
                    f"lifecycle-revision-{scenario.scenario_id}-{repetition}"
                ),
                text=scenario.request,
            )
            reports.append({
                "scenario_id": scenario.scenario_id,
                "repetition": repetition,
                **report,
            })

    elapsed_values = sorted(
        item["elapsed_seconds"] for item in reports if item["error"] is None
    )
    p95 = (
        elapsed_values[ceil(len(elapsed_values) * 0.95) - 1]
        if elapsed_values
        else None
    )
    total_tokens = sum(int(item["total_tokens"] or 0) for item in reports)
    passed = (
        len(reports) == 20
        and all(_sample_passed(item) for item in reports)
        and total_tokens <= 120_000
        and p95 is not None
        and p95 <= 120
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
                "initial_projects": 0,
            }),
            config_cohort=_config_cohort(live_web_search_process),
            grader_version="investigation-lifecycle-revision-001-v2",
        ),
        report={
            "sample_count": len(reports),
            "background_started_count": sum(
                item["background_started"] for item in reports
            ),
            "project_reference_count": sum(
                item["project_reference_present"] for item in reports
            ),
            "revision_feedback_count": sum(
                item["revision_feedback_count"] for item in reports
            ),
            "provider_failure_count": sum(
                item["error"] is not None for item in reports
            ),
            "model_call_count": sum(
                int(item["model_calls"] or 0) for item in reports
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
    assert passed, reports
