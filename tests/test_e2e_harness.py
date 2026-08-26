from __future__ import annotations

import pytest

from personal_agent.kernel.config import Settings


def test_live_web_process_retries_connection_reset_during_startup(
    monkeypatch,
    temp_dir,
):
    from evals.e2e_quality import test_release_user_outcomes as harness

    class Process:
        def poll(self):
            return None

    class HealthyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    attempts = 0

    def probe(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionResetError("server accepted then reset during startup")
        return HealthyResponse()

    monkeypatch.setattr(harness.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(harness, "urlopen", probe)
    monkeypatch.setattr(harness.time, "sleep", lambda _seconds: None)
    server = harness.LiveWebProcess(
        base_url="http://127.0.0.1:12345",
        log_path=temp_dir / "server.log",
        settings=Settings(),
        cwd=temp_dir,
        child_env={},
        port=12345,
    )

    try:
        server.start()
    finally:
        if server.log_handle is not None:
            server.log_handle.close()

    assert attempts == 2


def test_web_search_profile_does_not_inherit_unrelated_mcp_resources() -> None:
    from evals.e2e_quality.test_product_capability_outcomes import (
        _web_search_child_overrides,
    )

    overrides = _web_search_child_overrides(Settings())

    assert overrides["PERSONAL_AGENT_MCP_SERVERS"] == '{"enabled":false}'
    assert overrides["PERSONAL_AGENT_GITHUB_MCP_ENABLED"] == "false"
    assert overrides["PERSONAL_AGENT_NOTION_MCP_ENABLED"] == "false"


def test_live_web_process_reports_the_last_health_probe_error(
    monkeypatch,
    temp_dir,
) -> None:
    from evals.e2e_quality import test_release_user_outcomes as harness

    class Process:
        returncode = None

        def poll(self):
            return None

    monotonic_values = iter((0.0, 0.1, 31.0))
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(harness.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(harness.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        harness,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("probe timed out")),
    )
    server = harness.LiveWebProcess(
        base_url="http://127.0.0.1:12345",
        log_path=temp_dir / "server.log",
        settings=Settings(),
        cwd=temp_dir,
        child_env={},
        port=12345,
    )

    with pytest.raises(pytest.fail.Exception, match="TimeoutError: probe timed out"):
        server.start()

    if server.log_handle is not None:
        server.log_handle.close()
