"""E1/P1: real formal HTTP baseline, one independent process per request."""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest

from evals.e2e_quality.evidence_catalog import RETRIEVAL_EXPERIMENT_OUTCOMES
from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess, _get_json, _new_live_web_process, _post_json, _require_live_dependencies,
)
from evals.product_baselines.evidence import ProductEvidenceIdentity, ProductEvidenceRecorder, canonical_evidence_digest
from evals.product_baselines.retrieval_baseline import (
    DEADLINE_SECONDS, OWNER, ROOT, SCENARIOS, RetrievalScenario, grade_missing_delivery, prepare_world,
)
from evals.product_baselines.retrieval_http_server import redact_payload
from personal_agent.adapters.web.routes.conversation import ConversationTurnResponse
from personal_agent.application.conversation.models import InteractionTrace
from personal_agent.application.retrieval_experiment.models import ExperimentLimits

pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]


def _start_observed(server: LiveWebProcess, sdk_dir: Path) -> None:
    server.child_env.update(RETRIEVAL_E2E_SDK_DIRECTORY=str(sdk_dir), RETRIEVAL_E2E_HTTP_PORT=str(server.port))
    server.log_handle = server.log_path.open("a", encoding="utf-8")
    server.process = subprocess.Popen((sys.executable, "-m", "evals.product_baselines.retrieval_http_server"),
                                      cwd=server.cwd, env=server.child_env, stdout=server.log_handle,
                                      stderr=subprocess.STDOUT)
    deadline = monotonic() + 30
    while monotonic() < deadline:
        if server.process.poll() is not None:
            raise RuntimeError("正式Web应用启动失败；原日志封存在本样本目录")
        try:
            _get_json(server.base_url + "/api/health")
            return
        except (HTTPError, URLError, OSError):
            sleep(0.1)
    raise RuntimeError("正式Web应用健康检查超时")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.key)
def test_retrieval_experiment_formal_baseline(
    request: pytest.FixtureRequest, scenario: RetrievalScenario,
    product_evidence_recorder: ProductEvidenceRecorder,
) -> None:
    settings = _require_live_dependencies()
    expected = (32, 48, 4, 2000000)
    budget = settings.interaction_loop
    assert (budget.max_model_turns, budget.max_tool_calls, budget.max_agent_calls, budget.max_total_tokens) == expected
    assert settings.structured.timeout_seconds == 120 and settings.structured.max_retries == 2
    evidence_root = Path(os.environ["PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR"]).resolve()
    sample = evidence_root / "inputs" / f"{scenario.key}-{uuid4().hex}"
    sample.mkdir(parents=True, exist_ok=False)
    server = _new_live_web_process(sample, settings, child_env_overrides={
        "PERSONAL_AGENT_MCP_SERVERS": '{"enabled":false}',
        "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false", "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
        "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED": "false",
    })
    data_dir = Path(server.child_env["PERSONAL_AGENT_DATA_DIR"])
    world = prepare_world(
        settings.model_copy(update={"data_dir": data_dir}), scenario,
        limits=ExperimentLimits(run_timeout_seconds=DEADLINE_SECONDS, max_execution_seconds=DEADLINE_SECONDS),
    )
    (sample / "world.json").write_text(world.model_dump_json(indent=2), encoding="utf-8")
    patch = subprocess.check_output(("git", "diff", "--binary", "HEAD"), cwd=ROOT)
    (sample / "repository.patch").write_bytes(patch)
    source_snapshot = sample / "harness-source"
    source_snapshot.mkdir()
    for source in (Path(__file__), Path(__file__).with_name("retrieval_baseline.py"), Path(__file__).with_name("retrieval_http_server.py")):
        (source_snapshot / source.name).write_bytes(source.read_bytes())
    extra_body = redact_payload(settings.structured.extra_body)
    configuration = {"budget": budget.model_dump(), "timeout_seconds": 120, "max_retries": 2,
                     "profile": "configured", "model": settings.structured.model,
                     "provider_digest": sha256((settings.structured.base_url or "").encode()).hexdigest(),
                     "transport": settings.structured.output_transport,
                     "extra_body_keys": sorted(settings.structured.extra_body),
                     "extra_body_digest": canonical_evidence_digest(settings.structured.extra_body),
                     "extra_body": {key: extra_body[key] for key in ("thinking", "enable_thinking", "reasoning_effort") if key in extra_body},
                     "deadline_seconds": DEADLINE_SECONDS, "model_window": None}
    (sample / "configuration.json").write_text(json.dumps(configuration, ensure_ascii=False, indent=2), encoding="utf-8")
    sdk_dir = sample / "sdk"
    cancelled = Event()
    expired = Event()
    process = None
    exitcode = None
    trace = {}
    response = {}
    entry_error = None
    started = monotonic()
    product_evidence_recorder.enroll(nodeid=request.node.nodeid, identity=ProductEvidenceIdentity(
        case_id=scenario.case_id, role="baseline", evidence_class="product_e2e",
        formal_entrypoint="POST /api/conversation/turn", interaction_mode="auto", principal=OWNER,
        user_input_digest=canonical_evidence_digest(world.user_input),
        initial_state_digest=canonical_evidence_digest(world.model_dump(mode="json", exclude={"user_input"})),
        config_cohort=canonical_evidence_digest(configuration), grader_version="retrieval-agent-progress-v2"))
    try:
        _start_observed(server, sdk_dir)
        process = server.process
        assert process is not None
        def enforce_deadline() -> None:
            remaining = max(0, DEADLINE_SECONDS - (monotonic() - started))
            if not cancelled.wait(remaining):
                expired.set()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)

        supervisor = Thread(target=enforce_deadline, daemon=True)
        supervisor.start()
        try:
            response = _post_json(server.base_url + "/api/conversation/turn", {
                "user_id": OWNER.user_id, "conversation_id": world.conversation_id,
                "interaction_run_ref": world.interaction_run_ref, "interaction_mode": "auto",
                "messages": [{"role": "user", "content": world.user_input}],
            }, timeout=DEADLINE_SECONDS + 30)
            ConversationTurnResponse.model_validate(response)
            trace = _get_json(server.base_url + f"/api/conversation/runs/{world.interaction_run_ref}?user_id={OWNER.user_id}")
            InteractionTrace.model_validate(trace)
        except (HTTPError, URLError, OSError, ValueError) as error:
            entry_error = type(error).__name__
        finally:
            cancelled.set()
            supervisor.join(timeout=25)
    finally:
        if process is None:
            process = server.process
        if process is not None:
            server.stop()
            exitcode = process.poll()
        else:
            server.stop()
        lifecycle = {"pid": process.pid if process is not None else None, "exitcode": exitcode,
                     "actual_process_stopped": process is not None and exitcode is not None,
                     "hard_deadline_reached": expired.is_set(), "wall_seconds": monotonic() - started}
        (sample / "lifecycle.json").write_text(json.dumps(lifecycle), encoding="utf-8")
    calls = [json.loads(path.read_text(encoding="utf-8")) for path in sdk_dir.glob("*.response.json")]
    completed = sum(call.get("completed") is True for call in calls)
    outcome = grade_missing_delivery(trace=trace, data_dir=data_dir, model_calls_completed=completed,
                                     entry_error=entry_error, program_required=scenario.key == "p1")
    report = {"case_id": scenario.case_id, "user_request": world.user_input,
              "user_outcome_contract": asdict(RETRIEVAL_EXPERIMENT_OUTCOMES[scenario.key]),
              "outcome": outcome.model_dump(), "response": response, "trace": trace,
              "entry_error": entry_error, "lifecycle": lifecycle, "configuration": configuration,
              "world": world.model_dump(mode="json"), "sample_directory": str(sample),
              "files": {str(path.relative_to(sample)): sha256(path.read_bytes()).hexdigest()
                        for path in sample.rglob("*") if path.is_file()}}
    product_evidence_recorder.capture_report(report)
    assert lifecycle["actual_process_stopped"], "Web子进程未确认终态"
    assert outcome.result != "inconclusive", outcome.reason
    assert outcome.delivered, outcome.reason
