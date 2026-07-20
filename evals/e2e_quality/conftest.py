from __future__ import annotations

import os
from pathlib import Path

import pytest

from evals.e2e_quality.trace_archive import TraceArchive


_ARCHIVE: TraceArchive | None = None


@pytest.fixture(scope="session")
def trace_archive() -> TraceArchive:
    global _ARCHIVE
    output_root = Path(
        os.getenv("PERSONAL_AGENT_E2E_TRACE_DIR", "data/e2e_traces")
    ).resolve()
    archive = TraceArchive(output_root)
    _ARCHIVE = archive
    yield archive


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    archive = item.funcargs.get("trace_archive") or _ARCHIVE
    if archive is None:
        return
    detail = str(report.longrepr) if report.failed else None
    archive.record_test_result(
        nodeid=item.nodeid,
        phase=report.when,
        outcome=report.outcome,
        duration_seconds=report.duration,
        detail=detail,
    )


def pytest_sessionfinish(session, exitstatus: int) -> None:
    global _ARCHIVE
    if _ARCHIVE is not None:
        _ARCHIVE.finalize(exit_status=exitstatus)
        print(f"LIVE_E2E_TRACE_DIR={_ARCHIVE.run_dir}")
        _ARCHIVE = None
