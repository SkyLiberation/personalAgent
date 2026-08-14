from __future__ import annotations

import pytest

from evals.e2e_quality.conftest import (  # noqa: F401
    clean_e2e_database,
    server_temp_dir,
)
from evals.product_baselines.evidence import (
    ProductEvidenceRecorder,
    product_evidence_output_root,
)
from evals.e2e_quality.test_release_user_outcomes import live_web_process  # noqa: F401
from tests.conftest import (  # noqa: F401
    clean_postgres_business_tables,
    postgres_url,
    temp_dir,
)


@pytest.fixture
def product_evidence_recorder() -> ProductEvidenceRecorder:
    return ProductEvidenceRecorder(product_evidence_output_root())


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    recorder = item.funcargs.get("product_evidence_recorder")
    if recorder is None:
        return
    archive_dir = recorder.finalize(
        outcome=report.outcome,
        duration_seconds=report.duration,
        detail=str(report.longrepr) if report.failed else None,
    )
    if archive_dir is not None:
        print(f"PRODUCT_EVIDENCE_ARCHIVE={archive_dir}")
