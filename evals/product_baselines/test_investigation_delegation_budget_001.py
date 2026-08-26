"""Product mechanism E2E for bounded investigation Agent delegation."""

from __future__ import annotations

from math import ceil
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

import pytest

from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
)
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from evals.product_baselines.test_investigation_consolidation_001 import (
    _BACKGROUND_SCENARIOS,
    _repeated_proposal_keys,
    _turn,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = (
    "evals.e2e_quality.test_release_user_outcomes",
    "evals.e2e_quality.test_product_capability_outcomes",
)

_CASE_ID = "INVESTIGATION-DELEGATION-BUDGET-001"
_FOCUSED_CASE_ID = "INVESTIGATION-DELEGATION-BUDGET-001-FOCUSED"
_REPETITIONS = 5


def _project_url(reference: object, base_url: str) -> str | None:
    if not isinstance(reference, dict) or not reference.get("project_id"):
        return None
    query = urlencode({
        "tenant_id": str(reference["tenant_id"]),
        "user_id": str(reference["user_id"]),
    })
    return (
        f"{base_url}/api/investigation-projects/"
        f"{reference['project_id']}?{query}"
    )


def _agent_proposals(view: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        item
        for item in view.get("accepted_execution_proposals") or ()
        if isinstance(item, dict)
        and isinstance(item.get("operation"), dict)
        and item["operation"].get("kind") == "agent"
    )


def _agent_commands(view: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        item
        for item in view.get("commands") or ()
        if isinstance(item, dict)
        and item.get("target_agent_id")
    )


def _boundary_report(
    view: dict[str, Any],
    *,
    max_runtime_seconds: int,
) -> dict[str, Any]:
    proposals = _agent_proposals(view)
    commands = _agent_commands(view)
    project_budget = (
        ((view.get("definition") or {}).get("budget") or {})
        if isinstance(view.get("definition"), dict)
        else {}
    )
    max_project_tokens = min(
        int(project_budget.get("total_tokens") or 0),
        int(project_budget.get("external_delegation_tokens") or 0),
    )
    max_project_cost = float(project_budget.get("total_cost") or 0.0)
    proposal_ids = {
        str(item.get("proposal_id"))
        for item in proposals
        if item.get("proposal_id")
    }
    oversized_runtime_proposals = tuple(
        item
        for item in proposals
        if not 1 <= int(item["operation"].get("time_budget_seconds") or 0)
        <= max_runtime_seconds
    )
    oversized_runtime_commands = tuple(
        item
        for item in commands
        if not 1 <= int(item.get("time_budget_seconds") or 0)
        <= max_runtime_seconds
    )
    oversized_project_budget_proposals = tuple(
        item
        for item in proposals
        if (
            not 1 <= int(item["operation"].get("token_budget") or 0)
            <= max_project_tokens
            or not 0 <= float(item["operation"].get("cost_budget") or 0.0)
            <= max_project_cost
        )
    )
    oversized_project_budget_commands = tuple(
        item
        for item in commands
        if (
            not 1 <= int(item.get("token_budget") or 0) <= max_project_tokens
            or not 0 <= float(item.get("cost_budget") or 0.0) <= max_project_cost
        )
    )
    agent_execution_refs = tuple(
        item
        for item in view.get("execution_refs") or ()
        if isinstance(item, dict) and item.get("execution_kind") == "agent"
    )
    unbound_agent_execution_refs = tuple(
        item
        for item in agent_execution_refs
        if str(item.get("owner_ref") or "") not in proposal_ids
    )
    return {
        "agent_proposal_count": len(proposals),
        "agent_command_count": len(commands),
        "agent_execution_ref_count": len(agent_execution_refs),
        "max_project_agent_tokens": max_project_tokens,
        "max_project_agent_cost": max_project_cost,
        "oversized_runtime_proposals": oversized_runtime_proposals,
        "oversized_runtime_commands": oversized_runtime_commands,
        "oversized_project_budget_proposals": (
            oversized_project_budget_proposals
        ),
        "oversized_project_budget_commands": oversized_project_budget_commands,
        "oversized_proposals": tuple(
            item
            for item in proposals
            if (
                item in oversized_runtime_proposals
                or item in oversized_project_budget_proposals
            )
        ),
        "oversized_commands": tuple(
            item
            for item in commands
            if (
                item in oversized_runtime_commands
                or item in oversized_project_budget_commands
            )
        ),
        "unbound_agent_execution_refs": unbound_agent_execution_refs,
        "repeated_proposal_keys": _repeated_proposal_keys(view),
    }


def _observe_one(
    project_url: str | None,
    *,
    worker,
    timeout_seconds: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if project_url is None:
        return {}, []
    view: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_seconds
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
        if _agent_proposals(view) or view.get("state") in {
            "completed",
            "failed",
            "cancelled",
            "paused",
        }:
            break
        time.sleep(2)
    return view, errors


def _config_cohort(server: LiveWebProcess, *, observation_window_seconds: int):
    settings = server.settings
    return canonical_evidence_digest({
        "profile": "background-project-agent-budget-boundary",
        "structured_model": settings.structured.model,
        "structured_base_url": str(settings.structured.base_url),
        "structured_output_transport": settings.structured.output_transport,
        "structured_extra_body": settings.structured.extra_body,
        "structured_timeout_seconds": settings.structured.timeout_seconds,
        "structured_max_retries": settings.structured.max_retries,
        "web_search_provider": settings.web_search.provider,
        "gpt_researcher_timeout_seconds": (
            settings.gpt_researcher_a2a.timeout_seconds
        ),
        "gpt_researcher_max_search_results": int(
            server.child_env.get(
                "PERSONAL_AGENT_GPT_RESEARCHER_A2A_MAX_SEARCH_RESULTS",
                "0",
            )
        ),
        "observation_window_seconds": observation_window_seconds,
        "intent_contract": "interaction_intent:v2",
        "proposal_contract": "investigation_execution_proposal:v1",
        "grader": "investigation-delegation-budget-001-v2",
    })


def test_one_background_project_reaches_a_bounded_agent_proposal(
    request,
    live_web_search_process: LiveWebProcess,
    live_investigation_worker,
    product_evidence_recorder: ProductEvidenceRecorder,
):
    settings = live_web_search_process.settings
    assert settings.structured.model == "mimo-v2.5"
    assert settings.structured.output_transport == "json_schema"
    assert settings.structured.extra_body == {"thinking": {"type": "disabled"}}
    max_runtime_seconds = max(
        1,
        int(settings.gpt_researcher_a2a.timeout_seconds),
    )
    assert max_runtime_seconds == 240
    scenario = _BACKGROUND_SCENARIOS[1]
    user_id = "investigation-delegation-budget-focused"
    worker, worker_log_path = live_investigation_worker
    log_offset = worker_log_path.stat().st_size
    try:
        started, initial_trace, initial_elapsed = _turn(
            live_web_search_process,
            user_id=user_id,
            conversation_id="investigation-delegation-budget-focused",
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
    final_view, observation_errors = _observe_one(
        project_url,
        worker=worker,
        timeout_seconds=180,
    )
    boundary = _boundary_report(
        final_view,
        max_runtime_seconds=max_runtime_seconds,
    )
    worker_log = worker_log_path.read_text(
        encoding="utf-8",
        errors="replace",
    )[log_offset:]
    passed = (
        initial_error is None
        and started.get("disposition") == "background_started"
        and project_url is not None
        and initial_trace.get("execution_lifecycle") == "durable_investigation"
        and worker.poll() is None
        and bool(final_view)
        and boundary["agent_proposal_count"] >= 1
        and not boundary["oversized_proposals"]
        and not boundary["oversized_commands"]
        and not boundary["unbound_agent_execution_refs"]
        and not boundary["repeated_proposal_keys"]
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
                "initial_projects": 0,
                "independent_worker": True,
            }),
            config_cohort=_config_cohort(
                live_web_search_process,
                observation_window_seconds=180,
            ),
            grader_version="investigation-delegation-budget-001-v2",
        ),
        report={
            "passed": passed,
            "max_runtime_seconds": max_runtime_seconds,
            "initial_error": initial_error,
            "observation_errors": observation_errors,
            "initial_elapsed_seconds": round(initial_elapsed, 6),
            "started": started,
            "initial_trace": initial_trace,
            "final_view": final_view,
            "boundary": boundary,
            "worker_log_tail": worker_log[-20_000:],
        },
    )
    assert passed, {
        "started": started,
        "initial_error": initial_error,
        "observation_errors": observation_errors,
        "state": final_view.get("state"),
        "boundary": boundary,
        "worker_log_tail": worker_log[-5_000:],
    }


def test_background_agent_budgets_remain_bounded_across_the_formal_cohort(
    request,
    live_web_search_process: LiveWebProcess,
    live_investigation_worker,
    product_evidence_recorder: ProductEvidenceRecorder,
):
    settings = live_web_search_process.settings
    assert settings.structured.model == "mimo-v2.5"
    assert settings.structured.output_transport == "json_schema"
    assert settings.structured.extra_body == {"thinking": {"type": "disabled"}}
    max_runtime_seconds = max(
        1,
        int(settings.gpt_researcher_a2a.timeout_seconds),
    )
    assert max_runtime_seconds == 240
    worker, worker_log_path = live_investigation_worker
    log_offset = worker_log_path.stat().st_size
    samples: list[dict[str, Any]] = []
    all_inputs: list[str] = []
    for scenario in _BACKGROUND_SCENARIOS:
        for repetition in range(1, _REPETITIONS + 1):
            all_inputs.append(scenario.request)
            user_id = (
                f"investigation-consolidation-background-{scenario.scenario_id}-"
                f"{repetition}"
            )
            try:
                started, initial_trace, initial_elapsed = _turn(
                    live_web_search_process,
                    user_id=user_id,
                    conversation_id=f"{user_id}-conversation",
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
            samples.append({
                "scenario_id": scenario.scenario_id,
                "repetition": repetition,
                "started": started,
                "initial_trace": initial_trace,
                "initial_elapsed_seconds": round(initial_elapsed, 6),
                "initial_error": initial_error,
                "project_url": _project_url(
                    started.get("project_reference"),
                    live_web_search_process.base_url,
                ),
                "final_view": {},
                "observation_errors": [],
            })

    live_web_search_process.restart()
    pending = {
        index
        for index, sample in enumerate(samples)
        if sample["project_url"] is not None
    }
    deadline = time.monotonic() + 300
    while pending and time.monotonic() < deadline and worker.poll() is None:
        reached: set[int] = set()
        for index in pending:
            sample = samples[index]
            try:
                view = _get_json(str(sample["project_url"]))
            except (HTTPError, URLError, TimeoutError, ConnectionResetError) as exc:
                sample["observation_errors"].append({
                    "type": type(exc).__name__,
                    "status": getattr(exc, "code", None),
                    "message": str(exc),
                })
                continue
            sample["final_view"] = view
            if _agent_proposals(view) or view.get("state") in {
                "completed",
                "failed",
                "cancelled",
                "paused",
            }:
                reached.add(index)
        pending.difference_update(reached)
        if pending:
            time.sleep(2)

    for sample in samples:
        sample["boundary"] = _boundary_report(
            sample["final_view"],
            max_runtime_seconds=max_runtime_seconds,
        )
    elapsed_values = sorted(
        float(sample["initial_elapsed_seconds"])
        for sample in samples
        if sample["initial_error"] is None
    )
    p95 = (
        elapsed_values[ceil(len(elapsed_values) * 0.95) - 1]
        if elapsed_values
        else None
    )
    worker_log = worker_log_path.read_text(
        encoding="utf-8",
        errors="replace",
    )[log_offset:]
    agent_proposal_count = sum(
        int(sample["boundary"]["agent_proposal_count"])
        for sample in samples
    )
    passed = (
        len(samples) == 20
        and all(
            sample["initial_error"] is None
            and sample["started"].get("disposition") == "background_started"
            and sample["project_url"] is not None
            and sample["initial_trace"].get("execution_lifecycle")
            == "durable_investigation"
            and bool(sample["final_view"])
            and not sample["boundary"]["oversized_proposals"]
            and not sample["boundary"]["oversized_commands"]
            and not sample["boundary"]["unbound_agent_execution_refs"]
            and not sample["boundary"]["repeated_proposal_keys"]
            for sample in samples
        )
        and agent_proposal_count >= 1
        and worker.poll() is None
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
                user_id="investigation-consolidation-background-cohort",
            ),
            user_input_digest=canonical_evidence_digest(all_inputs),
            initial_state_digest=canonical_evidence_digest({
                "scenario_count": len(_BACKGROUND_SCENARIOS),
                "repetitions": _REPETITIONS,
                "sample_count": len(samples),
                "initial_projects": 0,
                "independent_worker": True,
                "no_followup_conversation_turn": True,
                "web_restart_after_creation": True,
            }),
            config_cohort=_config_cohort(
                live_web_search_process,
                observation_window_seconds=300,
            ),
            grader_version="investigation-delegation-budget-001-v2",
        ),
        report={
            "sample_count": len(samples),
            "passed": passed,
            "background_started_count": sum(
                sample["started"].get("disposition") == "background_started"
                for sample in samples
            ),
            "project_reference_count": sum(
                sample["project_url"] is not None for sample in samples
            ),
            "provider_failure_count": sum(
                sample["initial_error"] is not None for sample in samples
            ),
            "environment_failure_count": sum(
                not sample["final_view"] and bool(sample["observation_errors"])
                for sample in samples
            ),
            "agent_proposal_count": agent_proposal_count,
            "oversized_proposal_count": sum(
                len(sample["boundary"]["oversized_proposals"])
                for sample in samples
            ),
            "oversized_command_count": sum(
                len(sample["boundary"]["oversized_commands"])
                for sample in samples
            ),
            "oversized_project_budget_proposal_count": sum(
                len(sample["boundary"]["oversized_project_budget_proposals"])
                for sample in samples
            ),
            "oversized_project_budget_command_count": sum(
                len(sample["boundary"]["oversized_project_budget_commands"])
                for sample in samples
            ),
            "unbound_agent_execution_ref_count": sum(
                len(sample["boundary"]["unbound_agent_execution_refs"])
                for sample in samples
            ),
            "repeated_proposal_count": sum(
                len(sample["boundary"]["repeated_proposal_keys"])
                for sample in samples
            ),
            "worker_exited": worker.poll() is not None,
            "p95_initial_elapsed_seconds": p95,
            "worker_log_tail": worker_log[-20_000:],
            "samples": samples,
        },
    )
    assert passed, {
        "background_started_count": sum(
            sample["started"].get("disposition") == "background_started"
            for sample in samples
        ),
        "project_reference_count": sum(
            sample["project_url"] is not None for sample in samples
        ),
        "agent_proposal_count": agent_proposal_count,
        "pending_count": len(pending),
        "failures": [
            {
                "scenario_id": sample["scenario_id"],
                "repetition": sample["repetition"],
                "initial_error": sample["initial_error"],
                "state": sample["final_view"].get("state"),
                "boundary": sample["boundary"],
            }
            for sample in samples
            if (
                sample["initial_error"] is not None
                or sample["started"].get("disposition") != "background_started"
                or sample["project_url"] is None
                or not sample["final_view"]
                or sample["boundary"]["oversized_proposals"]
                or sample["boundary"]["oversized_commands"]
                or sample["boundary"]["unbound_agent_execution_refs"]
                or sample["boundary"]["repeated_proposal_keys"]
            )
        ],
        "worker_log_tail": worker_log[-5_000:],
    }
