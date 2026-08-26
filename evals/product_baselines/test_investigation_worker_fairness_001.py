"""Focused product E2E for fair Investigation Project worker leasing."""

from __future__ import annotations

from math import ceil
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError

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
    _turn,
)
from evals.product_baselines.test_investigation_delegation_budget_001 import (
    _project_url,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = (
    "evals.e2e_quality.test_release_user_outcomes",
    "evals.e2e_quality.test_product_capability_outcomes",
)

_CASE_ID = "INVESTIGATION-WORKER-FAIRNESS-001-FOCUSED"
_REVISION_REASON = "interaction_lifecycle_revision_required"
_OBSERVATION_SECONDS = 240


def _revision_feedback_count(trace):
    return sum(
        isinstance(item, dict) and item.get("reason_code") == _REVISION_REASON
        for item in trace.get("inputs") or ()
    )


def _start_worker(server: LiveWebProcess, log_path: Path):
    log_handle = log_path.open("ab")
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "personal_agent.adapters.cli.main",
            "worker",
            "--queue",
            "investigation",
            "--poll-seconds",
            "0.1",
        ),
        cwd=server.cwd,
        env=server.child_env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return process, log_handle


def test_two_waiting_projects_receive_plan_cycles_before_execution_continues(
    request,
    server_temp_dir: Path,
    live_web_search_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
):
    settings = live_web_search_process.settings
    assert settings.structured.model == "mimo-v2.5"
    assert settings.structured.output_transport == "json_schema"
    assert settings.structured.extra_body == {"thinking": {"type": "disabled"}}

    user_id = "investigation-worker-fairness-focused"
    samples = []
    for index, scenario in enumerate(_BACKGROUND_SCENARIOS[:2], start=1):
        try:
            started, trace, elapsed = _turn(
                live_web_search_process,
                user_id=user_id,
                conversation_id=f"worker-fairness-{index}",
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
        samples.append({
            "scenario_id": scenario.scenario_id,
            "request": scenario.request,
            "started": started,
            "trace": trace,
            "elapsed_seconds": round(elapsed, 6),
            "error": error,
            "project_url": _project_url(
                started.get("project_reference"),
                live_web_search_process.base_url,
            ),
            "view": {},
            "observation_errors": [],
        })

    worker_log_path = server_temp_dir / "fairness-worker.log"
    worker, worker_log_handle = _start_worker(
        live_web_search_process,
        worker_log_path,
    )
    try:
        deadline = time.monotonic() + _OBSERVATION_SECONDS
        while time.monotonic() < deadline and worker.poll() is None:
            for sample in samples:
                if sample["project_url"] is None:
                    continue
                try:
                    sample["view"] = _get_json(str(sample["project_url"]))
                except (
                    HTTPError,
                    URLError,
                    TimeoutError,
                    ConnectionResetError,
                ) as exc:
                    sample["observation_errors"].append({
                        "type": type(exc).__name__,
                        "status": getattr(exc, "code", None),
                        "message": str(exc),
                    })
            if all(sample["view"].get("accepted_plan") for sample in samples):
                break
            time.sleep(1)
        worker_exited = worker.poll() is not None
    finally:
        if worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=10)
        worker_log_handle.close()

    worker_log = worker_log_path.read_text(encoding="utf-8", errors="replace")
    prompt_stages = re.findall(r'"prompt_name": "([^"]+)"', worker_log)
    elapsed_values = sorted(float(sample["elapsed_seconds"]) for sample in samples)
    initial_p95 = elapsed_values[ceil(len(elapsed_values) * 0.95) - 1]
    initial_tokens = sum(
        int((sample["trace"].get("usage") or {}).get("total_tokens") or 0)
        for sample in samples
    )
    passed = (
        len(samples) == 2
        and all(sample["error"] is None for sample in samples)
        and all(
            sample["started"].get("disposition") == "background_started"
            for sample in samples
        )
        and all(sample["project_url"] is not None for sample in samples)
        and all(_revision_feedback_count(sample["trace"]) == 0 for sample in samples)
        and all(sample["view"].get("accepted_plan") for sample in samples)
        and all(int(sample["view"].get("event_sequence") or 0) >= 1 for sample in samples)
        and all(not sample["observation_errors"] for sample in samples)
        and not worker_exited
        and prompt_stages[:2] == [
            "investigation_project_plan",
            "investigation_project_plan",
        ]
        and initial_tokens <= 12_000
        and initial_p95 <= 120
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
            user_input_digest=canonical_evidence_digest(
                [sample["request"] for sample in samples]
            ),
            initial_state_digest=canonical_evidence_digest({
                "sample_count": 2,
                "initial_projects": 0,
                "worker_started_after_project_creation": True,
                "worker_count": 1,
            }),
            config_cohort=canonical_evidence_digest({
                "model": settings.structured.model,
                "base_url": str(settings.structured.base_url),
                "output_transport": settings.structured.output_transport,
                "extra_body": settings.structured.extra_body,
                "timeout_seconds": settings.structured.timeout_seconds,
                "max_retries": settings.structured.max_retries,
                "project_cycles_per_lease": 1,
                "observation_seconds": _OBSERVATION_SECONDS,
                "grader": "investigation-worker-fairness-001-v1",
            }),
            grader_version="investigation-worker-fairness-001-v1",
        ),
        report={
            "passed": passed,
            "sample_count": len(samples),
            "initial_tokens": initial_tokens,
            "initial_p95_elapsed_seconds": initial_p95,
            "worker_exited": worker_exited,
            "prompt_stages": prompt_stages,
            "samples": samples,
            "worker_log_tail": worker_log[-20_000:],
        },
    )
    assert passed, {
        "initial_tokens": initial_tokens,
        "initial_p95_elapsed_seconds": initial_p95,
        "worker_exited": worker_exited,
        "prompt_stages": prompt_stages,
        "samples": samples,
        "worker_log_tail": worker_log[-5_000:],
    }
