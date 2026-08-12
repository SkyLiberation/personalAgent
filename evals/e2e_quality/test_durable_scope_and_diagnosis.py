"""Production baselines for DUR-001 and OBS-001.

The two cases intentionally share one natural interaction failure: a caller
outside the interaction owner scope attempts to read a durable run after the
web process has restarted.  DUR-001 owns the user-visible isolation result;
OBS-001 owns the operator's same-run diagnosis evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Iterator
from urllib.error import HTTPError
from urllib.parse import urlencode
from uuid import uuid4

import pytest

from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _post_json,
)
from evals.e2e_quality.trace_archive import TraceArchive


pytestmark = pytest.mark.integration
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)


@pytest.fixture(scope="module")
def durable_scoped_interaction(
    live_web_process: LiveWebProcess,
) -> Iterator[dict[str, object]]:
    owner_id = f"dur-owner-{uuid4().hex}"
    other_id = f"dur-other-{uuid4().hex}"
    secret = f"只属于本次会话的临时口令-{uuid4().hex}"
    user_text = f"请原样复述这句话：{secret}。这只是当前会话内容，不要保存为长期知识。"
    result = _post_json(
        f"{live_web_process.base_url}/api/conversation/turn",
        {
            "conversation_id": f"dur-001-{uuid4().hex}",
            "user_id": owner_id,
            "messages": [{"role": "user", "content": user_text}],
        },
    )
    live_web_process.restart()
    yield {
        "server": live_web_process,
        "owner_id": owner_id,
        "other_id": other_id,
        "secret": secret,
        "user_text": user_text,
        "result": result,
        "run_ref": str(result["interaction_run_ref"]),
    }


def _read_trace_as(
    server: LiveWebProcess,
    run_ref: str,
    user_id: str,
) -> tuple[int, object]:
    url = f"{server.base_url}/api/conversation/runs/{run_ref}?" + urlencode(
        {"user_id": user_id}
    )
    try:
        return 200, _get_json(url)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def _diagnostic_lines(log_path: Path, run_ref: str) -> list[str]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        content = (
            log_path.read_text(encoding="utf-8", errors="replace")
            if log_path.exists()
            else ""
        )
        lines = [line for line in content.splitlines() if run_ref in line]
        if any("conversation_run_scope_mismatch" in line for line in lines):
            return lines
        time.sleep(0.05)
    return lines


def test_dur_001_durable_interaction_scope_survives_process_restart(
    durable_scoped_interaction: dict[str, object],
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    scenario = durable_scoped_interaction
    server = scenario["server"]
    assert isinstance(server, LiveWebProcess)
    run_ref = str(scenario["run_ref"])
    owner_status, owner_trace = _read_trace_as(
        server,
        run_ref,
        str(scenario["owner_id"]),
    )
    other_status, other_response = _read_trace_as(
        server,
        run_ref,
        str(scenario["other_id"]),
    )
    serialized_other = json.dumps(other_response, ensure_ascii=False, default=str)
    trace_archive.write_trace(
        nodeid=request.node.nodeid,
        case_id="DUR-001.baseline",
        trace={
            "natural_user_text": scenario["user_text"],
            "initial_result": scenario["result"],
            "owner_status": owner_status,
            "owner_trace": owner_trace,
            "other_status": other_status,
            "other_response": other_response,
        },
    )

    assert owner_status == 200
    assert str(scenario["secret"]) in json.dumps(
        owner_trace,
        ensure_ascii=False,
        default=str,
    )
    assert other_status == 404
    assert str(scenario["secret"]) not in serialized_other


def test_obs_001_scope_failure_is_diagnosable_from_the_same_run_ref(
    durable_scoped_interaction: dict[str, object],
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    scenario = durable_scoped_interaction
    server = scenario["server"]
    assert isinstance(server, LiveWebProcess)
    run_ref = str(scenario["run_ref"])
    status, response = _read_trace_as(
        server,
        run_ref,
        str(scenario["other_id"]),
    )
    diagnostic_lines = _diagnostic_lines(server.log_path, run_ref)
    matching_lines = [
        line for line in diagnostic_lines if "conversation_run_scope_mismatch" in line
    ]
    trace_archive.write_trace(
        nodeid=request.node.nodeid,
        case_id="OBS-001.baseline",
        trace={
            "failed_run_ref": run_ref,
            "http_status": status,
            "response": response,
            "same_run_diagnostic_lines": diagnostic_lines,
        },
    )

    assert status == 404
    assert matching_lines
    assert all("policy.decision" in line for line in matching_lines)
    assert all('"action": "conversation_trace_read"' in line for line in matching_lines)
    assert all('"effect": "deny"' in line for line in matching_lines)
    assert all(
        '"rule": "conversation_run_scope_mismatch"' in line for line in matching_lines
    )
