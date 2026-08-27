"""Optional pytest integration for deterministic product-evidence promotion gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.e2e_quality.promotion_gate import (
    PromotionGateController,
    PromotionGateError,
    load_promotion_spec,
    write_promotion_report,
)

_CONTROLLER: PromotionGateController | None = None
_OUTPUT_ROOT: Path | None = None
_PROMOTION_ERROR: str | None = None
_TERMINAL_STOP: str | None = None


def pytest_addoption(parser) -> None:
    group = parser.getgroup("product-promotion")
    group.addoption(
        "--product-promotion-spec",
        type=Path,
        help=(
            "typed promotion-gate JSON for one dedicated product target cohort; "
            "the gate may reject early but never passes before expected_samples"
        ),
    )
    group.addoption(
        "--product-promotion-output",
        type=Path,
        default=Path("data/e2e_traces/promotion_gates"),
        help="root for checksum-sealed promotion decision archives",
    )


def pytest_configure(config) -> None:
    global _CONTROLLER, _OUTPUT_ROOT, _PROMOTION_ERROR, _TERMINAL_STOP
    spec_path = config.getoption("--product-promotion-spec")
    _CONTROLLER = None
    _OUTPUT_ROOT = None
    _PROMOTION_ERROR = None
    _TERMINAL_STOP = None
    if spec_path is None:
        return
    try:
        _CONTROLLER = PromotionGateController(load_promotion_spec(spec_path))
    except PromotionGateError as exc:
        raise pytest.UsageError(str(exc)) from exc
    _OUTPUT_ROOT = config.getoption("--product-promotion-output")


def pytest_collection_modifyitems(config, items) -> None:
    del config
    if _CONTROLLER is None:
        return
    expected = _CONTROLLER.spec.expected_samples
    if len(items) != expected:
        raise pytest.UsageError(
            "product promotion gate requires a dedicated selection of "
            f"exactly {expected} pytest items; collected {len(items)}"
        )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    global _PROMOTION_ERROR, _TERMINAL_STOP
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    recorder = item.funcargs.get("product_evidence_recorder")
    if recorder is None:
        return
    missing_result_report = recorder.enrolled and not recorder.result_report_captured
    if missing_result_report and report.passed:
        report.outcome = "failed"
        report.longrepr = (
            "product evidence was enrolled but no result report was captured"
        )
    archive_dir = recorder.finalize(
        outcome=report.outcome,
        duration_seconds=report.duration,
        detail=str(report.longrepr) if report.failed else None,
    )
    if archive_dir is None:
        return
    print(f"PRODUCT_EVIDENCE_ARCHIVE={archive_dir}")
    if _CONTROLLER is None:
        return
    try:
        decision = _CONTROLLER.observe_archive(archive_dir)
    except PromotionGateError as exc:
        _PROMOTION_ERROR = str(exc)
        item.session.shouldstop = f"product promotion gate input invalid: {exc}"
        return
    print(
        "PRODUCT_PROMOTION_DECISION="
        f"{decision.status}:{decision.observed_samples}/"
        f"{decision.spec.expected_samples}"
    )
    if decision.status != "continue":
        _TERMINAL_STOP = decision.status
        item.session.shouldstop = (
            f"product promotion gate {decision.status}: "
            f"{decision.first_failed_constraint or 'all constraints passed'}"
        )


def pytest_sessionfinish(session, exitstatus: int) -> None:
    if _CONTROLLER is None or _OUTPUT_ROOT is None:
        return
    try:
        report_dir = write_promotion_report(_CONTROLLER, _OUTPUT_ROOT)
    except Exception as exc:  # The runner must fail closed if evidence cannot seal.
        session.exitstatus = pytest.ExitCode.INTERNAL_ERROR
        print(f"PRODUCT_PROMOTION_REPORT_ERROR={type(exc).__name__}:{exc}")
        return
    decision = _CONTROLLER.decision()
    print(f"PRODUCT_PROMOTION_REPORT_ARCHIVE={report_dir}")
    if _PROMOTION_ERROR is not None or decision.status != "passed":
        if exitstatus not in {
            pytest.ExitCode.INTERNAL_ERROR,
            pytest.ExitCode.USAGE_ERROR,
        }:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
    elif (
        _TERMINAL_STOP == "passed"
        and exitstatus == pytest.ExitCode.INTERRUPTED
    ):
        # A completed dedicated cohort stops collection through shouldstop.
        # Preserve every unrelated non-zero pytest outcome.
        session.exitstatus = pytest.ExitCode.OK


def pytest_unconfigure(config) -> None:
    del config
    global _CONTROLLER, _OUTPUT_ROOT, _PROMOTION_ERROR, _TERMINAL_STOP
    _CONTROLLER = None
    _OUTPUT_ROOT = None
    _PROMOTION_ERROR = None
    _TERMINAL_STOP = None


__all__ = [
    "pytest_addoption",
    "pytest_collection_modifyitems",
    "pytest_configure",
    "pytest_runtest_makereport",
    "pytest_sessionfinish",
    "pytest_unconfigure",
]
