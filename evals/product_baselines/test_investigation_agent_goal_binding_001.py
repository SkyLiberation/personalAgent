"""Focused Product E2E for accepted SubGoal binding across Agent delegation."""

from __future__ import annotations

import time
from typing import Any
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
    _project_selected,
    _provider_source_urls,
    _turn,
)
from evals.product_baselines.test_investigation_delegation_budget_001 import (
    _agent_proposals,
    _project_url,
)
from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
)
from personal_agent.infra.storage.postgres_agent_run_store import (
    PostgresAgentRunStore,
)
from personal_agent.application.investigation_project import ProjectExecutionPolicy
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = (
    "evals.e2e_quality.test_release_user_outcomes",
    "evals.e2e_quality.test_product_capability_outcomes",
)

_CASE_ID = "INVESTIGATION-AGENT-GOAL-BINDING-001-FOCUSED"
_OBSERVATION_WINDOW_SECONDS = 300


def _observe_until_outcome(
    project_url: str | None,
    *,
    worker,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if project_url is None:
        return {}, []
    view: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    deadline = time.monotonic() + _OBSERVATION_WINDOW_SECONDS
    while time.monotonic() < deadline and worker.poll() is None:
        try:
            view = _get_json(project_url)
        except (HTTPError, URLError, TimeoutError, ConnectionResetError) as exc:
            errors.append({
                "type": type(exc).__name__,
                "status": getattr(exc, "code", None),
                "message": str(exc),
            })
            time.sleep(2)
            continue
        if view.get("outcomes") or view.get("state") in {
            "completed",
            "failed",
            "cancelled",
            "paused",
        }:
            break
        time.sleep(3)
    return view, errors


def _agent_goal_bindings(view: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    accepted_plan = view.get("accepted_plan") or {}
    proposal = accepted_plan.get("proposal") or {}
    subgoals = {
        (str(item.get("logical_subgoal_id")), int(item.get("subgoal_version") or 0)):
        item
        for item in proposal.get("subgoals") or ()
        if isinstance(item, dict)
    }
    bindings: list[dict[str, Any]] = []
    for execution in _agent_proposals(view):
        key = (
            str(execution.get("logical_subgoal_id")),
            int(execution.get("subgoal_version") or 0),
        )
        subgoal = subgoals.get(key)
        expected = (
            ""
            if subgoal is None
            else (
                f"Objective:\n{subgoal.get('objective', '')}\n\n"
                f"Required output:\n{subgoal.get('required_output', '')}"
            )
        )
        actual = str((execution.get("operation") or {}).get(
            "bounded_sub_goal",
            "",
        ))
        bindings.append({
            "logical_subgoal_id": key[0],
            "subgoal_version": key[1],
            "expected": expected,
            "actual": actual,
            "matches": bool(expected) and actual == expected,
            "is_logical_id_only": actual == key[0],
        })
    return tuple(bindings)


def test_real_agent_receives_the_accepted_subgoal_contract(
    request: pytest.FixtureRequest,
    live_web_search_process: LiveWebProcess,
    live_investigation_worker,
    product_evidence_recorder: ProductEvidenceRecorder,
    postgres_url: str,
) -> None:
    settings = live_web_search_process.settings
    scenario = _BACKGROUND_SCENARIOS[0]
    user_id = "investigation-agent-goal-binding-focused"
    worker, worker_log_path = live_investigation_worker
    log_offset = worker_log_path.stat().st_size
    started_at = time.monotonic()
    try:
        started, initial_trace, initial_elapsed = _turn(
            live_web_search_process,
            user_id=user_id,
            conversation_id=user_id,
            text=scenario.request,
        )
        initial_error = None
    except (HTTPError, URLError, TimeoutError) as exc:
        started = {}
        initial_trace = {}
        initial_elapsed = 0.0
        initial_error = {
            "type": type(exc).__name__,
            "status": getattr(exc, "code", None),
            "message": str(exc),
        }
    project_url = _project_url(
        started.get("project_reference"),
        live_web_search_process.base_url,
    )
    final_view, observation_errors = _observe_until_outcome(
        project_url,
        worker=worker,
    )
    bindings = _agent_goal_bindings(final_view)
    provider_source_urls = _provider_source_urls(
        PostgresAgentRunStore(postgres_url),
        final_view,
    )
    off_topic_source_urls = tuple(
        url
        for url in provider_source_urls
        if "lawinsider.com" in url.casefold()
        or "acquisition.com" in url.casefold()
    )
    artifacts = tuple(final_view.get("artifact_refs") or ())
    outcomes = tuple(final_view.get("outcomes") or ())
    event_sequence = int(final_view.get("event_sequence") or 0)
    external_wait_retry_seconds = (
        ProjectExecutionPolicy().external_wait_retry_seconds
    )
    wait_reschedule_passed = event_sequence <= 200
    worker_log = worker_log_path.read_text(
        encoding="utf-8",
        errors="replace",
    )[log_offset:]
    passed = (
        settings.structured.model == "mimo-v2.5"
        and settings.structured.output_transport == "json_schema"
        and settings.structured.extra_body == {"thinking": {"type": "disabled"}}
        and initial_error is None
        and started.get("disposition") == "background_started"
        and _project_selected(started, initial_trace)
        and initial_trace.get("execution_lifecycle") == "durable_investigation"
        and project_url is not None
        and worker.poll() is None
        and bool(bindings)
        and all(item["matches"] for item in bindings)
        and not any(item["is_logical_id_only"] for item in bindings)
        and bool(artifacts)
        and bool(outcomes)
        and not off_topic_source_urls
        and wait_reschedule_passed
    )
    elapsed = round(time.monotonic() - started_at, 6)
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
            user_input_digest=canonical_evidence_digest([scenario.request]),
            initial_state_digest=canonical_evidence_digest({
                "scenario_count": 1,
                "repetitions": 1,
                "initial_projects": 0,
                "independent_worker": True,
                "no_followup_conversation_turn": True,
            }),
            config_cohort=canonical_evidence_digest({
                "profile": "accepted-subgoal-agent-binding",
                "structured_model": settings.structured.model,
                "structured_base_url": str(settings.structured.base_url),
                "structured_output_transport": settings.structured.output_transport,
                "structured_extra_body": settings.structured.extra_body,
                "structured_max_retries": settings.structured.max_retries,
                "gpt_researcher_timeout_seconds": (
                    settings.gpt_researcher_a2a.timeout_seconds
                ),
                "observation_window_seconds": _OBSERVATION_WINDOW_SECONDS,
                "external_wait_retry_seconds": external_wait_retry_seconds,
                "grader": "investigation-agent-goal-binding-001-v3",
            }),
            grader_version="investigation-agent-goal-binding-001-v3",
        ),
        report={
            "passed": passed,
            "elapsed_seconds": elapsed,
            "initial_error": initial_error,
            "observation_errors": observation_errors,
            "initial_elapsed_seconds": round(initial_elapsed, 6),
            "started": started,
            "initial_trace": initial_trace,
            "final_view": final_view,
            "agent_goal_bindings": bindings,
            "provider_source_urls": provider_source_urls,
            "off_topic_source_urls": off_topic_source_urls,
            "artifact_count": len(artifacts),
            "outcome_count": len(outcomes),
            "event_sequence": event_sequence,
            "wait_reschedule_passed": wait_reschedule_passed,
            "worker_log_tail": worker_log[-20_000:],
        },
    )
    assert passed, {
        "initial_error": initial_error,
        "observation_errors": observation_errors,
        "state": final_view.get("state"),
        "bindings": bindings,
        "artifact_count": len(artifacts),
            "outcome_count": len(outcomes),
            "off_topic_source_urls": off_topic_source_urls,
            "event_sequence": event_sequence,
            "wait_reschedule_passed": wait_reschedule_passed,
            "worker_log_tail": worker_log[-5_000:],
    }
