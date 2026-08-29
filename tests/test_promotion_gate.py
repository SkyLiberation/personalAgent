from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from evals.e2e_quality.promotion_gate import (
    MaximumCountConstraint,
    MaximumNearestRankPercentileConstraint,
    MaximumSumConstraint,
    MetricRef,
    MinimumConditionalRateConstraint,
    MinimumCountConstraint,
    PromotionGateController,
    PromotionGateError,
    PromotionGateSpec,
    PromotionSampleFact,
    sample_fact_from_archive,
    write_promotion_report,
)
from evals.e2e_quality.trace_archive import TraceArchive, archive_checksums_valid
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    load_finalized_product_evidence,
)
from evals.product_baselines import promotion_plugin
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


_DELIVERED = MetricRef(source="report", path=("delivered",))
_FAILED = MetricRef(source="report", path=("failed",))
_COMPLETED = MetricRef(source="report", path=("completed",))
_TOKENS = MetricRef(source="report", path=("tokens",))
_DURATION = MetricRef(source="duration_seconds")
_RESULT_REPORT_MISSING = MetricRef(source="result_report_missing")


def _spec(
    *constraints,
    expected_samples: int = 20,
    role: str = "target",
    stage: str = "formal_product_target",
) -> PromotionGateSpec:
    return PromotionGateSpec(
        gate_id="PROMOTION-TEST-001",
        case_id="CASE-001",
        role=role,
        stage=stage,
        expected_samples=expected_samples,
        constraints=constraints,
    )


def _sample(
    index: int,
    *,
    metrics: dict[str, bool | int | float],
    duration_seconds: float = 1,
    subject_digest: str | None = None,
    role: str = "target",
) -> PromotionSampleFact:
    return PromotionSampleFact(
        archive_ref=f"archive-{index}",
        archive_run_id=f"run-{index:02d}",
        case_id="CASE-001",
        role=role,
        evidence_class="product_e2e",
        formal_entrypoint="POST /api/conversation/turn",
        interaction_mode="auto",
        config_cohort="cohort-1",
        grader_version="grader-v1",
        subject_digest=subject_digest or "a" * 64,
        sample_key=canonical_evidence_digest({"sample": index}),
        duration_seconds=duration_seconds,
        metrics=metrics,
    )


def test_p95_gate_rejects_when_final_nearest_rank_is_irreversibly_over_limit():
    spec = _spec(
        MaximumNearestRankPercentileConstraint(
            constraint_id="p95",
            metric=_DURATION,
            percentile=95,
            maximum=45,
        )
    )
    controller = PromotionGateController(spec)

    for index, duration in enumerate((10, 50, 12, 13), start=1):
        decision = controller.observe(
            _sample(index, metrics={_DURATION.key(): duration})
        )
        assert decision.status == "continue"
    rejected = controller.observe(
        _sample(5, metrics={_DURATION.key(): 55})
    )

    assert rejected.status == "rejected"
    assert rejected.observed_samples == 5
    assert rejected.remaining_samples == 15
    assert rejected.first_failed_constraint == "p95"
    assert rejected.first_failed_at_sample == 5


def test_gate_never_passes_before_the_full_predeclared_sample_count():
    spec = _spec(
        MinimumCountConstraint(
            constraint_id="delivered",
            metric=_DELIVERED,
            minimum=3,
        ),
        expected_samples=3,
    )
    controller = PromotionGateController(spec)

    assert controller.observe(
        _sample(1, metrics={_DELIVERED.key(): True})
    ).status == "continue"
    assert controller.observe(
        _sample(2, metrics={_DELIVERED.key(): True})
    ).status == "continue"
    assert controller.observe(
        _sample(3, metrics={_DELIVERED.key(): True})
    ).status == "passed"


def test_failure_baseline_can_stop_when_a_predeclared_limit_is_exceeded():
    spec = _spec(
        MaximumCountConstraint(
            constraint_id="maximum-tolerated-failures",
            metric=_FAILED,
            maximum=1,
        ),
        expected_samples=5,
        role="baseline",
        stage="failure_baseline",
    )
    controller = PromotionGateController(spec)

    assert controller.observe(
        _sample(1, metrics={_FAILED.key(): True}, role="baseline")
    ).status == "continue"
    decision = controller.observe(
        _sample(2, metrics={_FAILED.key(): True}, role="baseline")
    )

    assert decision.status == "rejected"
    assert decision.observed_samples == 2
    assert decision.remaining_samples == 3


def test_count_sum_and_conditional_rate_compute_irreversible_failure():
    count_gate = PromotionGateController(_spec(
        MinimumCountConstraint(
            constraint_id="minimum-delivered",
            metric=_DELIVERED,
            minimum=16,
        )
    ))
    for index in range(1, 6):
        decision = count_gate.observe(
            _sample(index, metrics={_DELIVERED.key(): False})
        )
    assert decision.status == "rejected"

    sum_gate = PromotionGateController(_spec(
        MaximumSumConstraint(
            constraint_id="token-budget",
            metric=_TOKENS,
            maximum=100,
        )
    ))
    assert sum_gate.observe(
        _sample(1, metrics={_TOKENS.key(): 60})
    ).status == "continue"
    assert sum_gate.observe(
        _sample(2, metrics={_TOKENS.key(): 41})
    ).status == "rejected"

    invalid_sum_gate = PromotionGateController(_spec(
        MaximumSumConstraint(
            constraint_id="non-negative-token-budget",
            metric=_TOKENS,
            maximum=100,
        )
    ))
    with pytest.raises(PromotionGateError, match="must be non-negative"):
        invalid_sum_gate.observe(
            _sample(1, metrics={_TOKENS.key(): -1})
        )

    conditional_gate = PromotionGateController(_spec(
        MinimumConditionalRateConstraint(
            constraint_id="completed-to-delivered",
            numerator_metric=_DELIVERED,
            denominator_metric=_COMPLETED,
            minimum_rate=0.8,
            minimum_denominator=5,
        )
    ))
    for index in range(1, 6):
        decision = conditional_gate.observe(
            _sample(
                index,
                metrics={
                    _DELIVERED.key(): False,
                    _COMPLETED.key(): True,
                },
            )
        )
    assert decision.status == "rejected"


def test_gate_rejects_wrong_cohort_duplicate_and_invalid_conditional_fact():
    spec = _spec(
        MaximumCountConstraint(
            constraint_id="failures",
            metric=_FAILED,
            maximum=1,
        )
    )
    controller = PromotionGateController(spec)
    first = _sample(1, metrics={_FAILED.key(): False})
    controller.observe(first)

    with pytest.raises(PromotionGateError, match="duplicate"):
        controller.observe(first)
    with pytest.raises(PromotionGateError, match="code, config"):
        controller.observe(
            _sample(
                2,
                metrics={_FAILED.key(): False},
                subject_digest="b" * 64,
            )
        )

    conditional = PromotionGateController(_spec(
        MinimumConditionalRateConstraint(
            constraint_id="invalid-conditional",
            numerator_metric=_DELIVERED,
            denominator_metric=_COMPLETED,
            minimum_rate=0.5,
            minimum_denominator=1,
        )
    ))
    with pytest.raises(PromotionGateError, match="numerator must imply"):
        conditional.observe(
            _sample(
                1,
                metrics={
                    _DELIVERED.key(): True,
                    _COMPLETED.key(): False,
                },
            )
        )


def _sealed_product_sample(root: Path) -> Path:
    archive = TraceArchive(root, run_id="sealed-sample")
    nodeid = "evals/product_baselines/test_case.py::test_case"
    archive.write_trace(
        nodeid=nodeid,
        case_id="CASE-001",
        trace={"delivered": True},
        product_evidence=ProductEvidenceIdentity(
            case_id="CASE-001",
            role="target",
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="tenant-1",
                user_id="user-1",
            ),
            user_input_digest=canonical_evidence_digest("request"),
            initial_state_digest=canonical_evidence_digest({"seed": 1}),
            config_cohort="cohort-1",
            grader_version="grader-v1",
        ),
    )
    archive.record_test_result(
        nodeid=nodeid,
        phase="call",
        outcome="passed",
        duration_seconds=2.5,
    )
    archive.finalize(exit_status=0)
    return archive.run_dir


def test_sealed_product_sample_drives_a_checksum_sealed_promotion_report(temp_dir):
    spec = _spec(
        MinimumCountConstraint(
            constraint_id="delivered",
            metric=_DELIVERED,
            minimum=1,
        ),
        expected_samples=1,
    )
    sample_dir = _sealed_product_sample(temp_dir / "samples")
    fact = sample_fact_from_archive(spec, sample_dir)
    controller = PromotionGateController(spec)

    decision = controller.observe(fact)
    report_dir = write_promotion_report(controller, temp_dir / "reports")

    assert decision.status == "passed"
    assert fact.duration_seconds == 2.5
    assert fact.metrics == {_DELIVERED.key(): True}
    assert archive_checksums_valid(report_dir)


def test_archive_loader_reports_checksum_failure_as_gate_input_error(temp_dir):
    spec = _spec(
        MinimumCountConstraint(
            constraint_id="delivered",
            metric=_DELIVERED,
            minimum=1,
        ),
        expected_samples=1,
    )
    sample_dir = _sealed_product_sample(temp_dir / "samples")
    trace_path, = sample_dir.glob("*.trace.json")
    trace_path.write_text("{}", encoding="utf-8")

    with pytest.raises(PromotionGateError, match="checksum validation failed"):
        sample_fact_from_archive(spec, sample_dir)


def test_enrolled_failure_without_result_report_is_sealed_and_gate_visible(temp_dir):
    recorder = ProductEvidenceRecorder(temp_dir / "samples")
    identity = ProductEvidenceIdentity(
        case_id="CASE-001",
        role="target",
        evidence_class="product_e2e",
        formal_entrypoint="POST /api/conversation/turn",
        interaction_mode="auto",
        principal=AuthenticatedPrincipal(
            tenant_id="tenant-1",
            user_id="user-1",
        ),
        user_input_digest=canonical_evidence_digest("request"),
        initial_state_digest=canonical_evidence_digest({"seed": 1}),
        config_cohort="cohort-1",
        grader_version="grader-v1",
    )
    recorder.enroll(nodeid="test_case.py::test_case", identity=identity)

    archive_dir = recorder.finalize(
        outcome="failed",
        duration_seconds=1.5,
        detail="entry failed before result capture",
    )

    assert archive_dir is not None
    evidence = load_finalized_product_evidence(archive_dir)
    assert evidence.result_report_captured is False
    assert evidence.report == {
        "product_evidence_capture": {
            "schema_version": 1,
            "state": "enrolled_without_result_report",
            "pytest_outcome": "failed",
        }
    }
    spec = _spec(
        MaximumCountConstraint(
            constraint_id="zero-missing-result-reports",
            metric=_RESULT_REPORT_MISSING,
            maximum=0,
        ),
        expected_samples=1,
    )
    decision = PromotionGateController(spec).observe_archive(archive_dir)
    assert decision.status == "rejected"
    assert decision.first_failed_at_sample == 1


def test_pytest_plugin_requires_one_dedicated_item_per_expected_archive(
    monkeypatch,
):
    controller = PromotionGateController(_spec(
        MaximumCountConstraint(
            constraint_id="failures",
            metric=_FAILED,
            maximum=0,
        ),
        expected_samples=2,
    ))
    monkeypatch.setattr(promotion_plugin, "_CONTROLLER", controller)

    with pytest.raises(pytest.UsageError, match="exactly 2 pytest items"):
        promotion_plugin.pytest_collection_modifyitems(None, [object()] * 3)


def test_pytest_plugin_fails_a_passing_enrollment_without_result_report(
    temp_dir,
    monkeypatch,
):
    recorder = ProductEvidenceRecorder(temp_dir / "samples")
    recorder.enroll(
        nodeid="test_case.py::test_case",
        identity=ProductEvidenceIdentity(
            case_id="CASE-001",
            role="target",
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="tenant-1",
                user_id="user-1",
            ),
            user_input_digest=canonical_evidence_digest("request"),
            initial_state_digest=canonical_evidence_digest({"seed": 1}),
            config_cohort="cohort-1",
            grader_version="grader-v1",
        ),
    )

    class _Report:
        when = "call"
        outcome = "passed"
        duration = 0.1
        longrepr = None

        @property
        def passed(self):
            return self.outcome == "passed"

        @property
        def failed(self):
            return self.outcome == "failed"

    class _Outcome:
        def __init__(self, report):
            self._report = report

        def get_result(self):
            return self._report

    class _Session:
        shouldstop = False

    class _Item:
        funcargs = {"product_evidence_recorder": recorder}
        session = _Session()

    monkeypatch.setattr(promotion_plugin, "_CONTROLLER", None)
    report = _Report()
    hook = promotion_plugin.pytest_runtest_makereport(_Item(), None)
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(_Outcome(report))

    assert report.outcome == "failed"
    assert "no result report" in report.longrepr
    archive_dir = next((temp_dir / "samples").rglob("manifest.json")).parent
    evidence = load_finalized_product_evidence(archive_dir)
    assert evidence.outcome == "failed"
    assert evidence.result_report_captured is False


def test_pytest_plugin_stops_an_irreversibly_rejected_cohort_and_seals_report(
    temp_dir,
):
    sample_root = temp_dir / "samples"
    report_root = temp_dir / "promotion-reports"
    spec_path = temp_dir / "promotion-spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gate_id": "PLUGIN-REJECTION-001",
                "case_id": "CASE-001",
                "role": "target",
                "stage": "formal_product_target",
                "expected_samples": 3,
                "constraints": [
                    {
                        "kind": "maximum_count",
                        "constraint_id": "zero-missing-result-reports",
                        "metric": {
                            "source": "result_report_missing",
                        },
                        "maximum": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (temp_dir / "conftest.py").write_text(
        f"""
from pathlib import Path
import pytest
from evals.product_baselines.evidence import ProductEvidenceRecorder

@pytest.fixture
def product_evidence_recorder():
    return ProductEvidenceRecorder(Path({str(sample_root)!r}))
""",
        encoding="utf-8",
    )
    (temp_dir / "test_product_sample.py").write_text(
        """
import pytest
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    canonical_evidence_digest,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

@pytest.mark.parametrize("sample", [1, 2, 3])
def test_product_sample(sample, request, product_evidence_recorder):
    product_evidence_recorder.enroll(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id="CASE-001",
            role="target",
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="tenant-1",
                user_id="user-1",
            ),
            user_input_digest=canonical_evidence_digest(f"request-{sample}"),
            initial_state_digest=canonical_evidence_digest({"seed": 1}),
            config_cohort="cohort-1",
            grader_version="grader-v1",
        ),
    )
    if sample == 2:
        raise RuntimeError("entry failed before result report capture")
    product_evidence_recorder.capture_report({"delivered": True})
""",
        encoding="utf-8",
    )

    repository_root = Path.cwd()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (str(repository_root), environment.get("PYTHONPATH")),
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "evals.product_baselines.promotion_plugin",
            f"--product-promotion-spec={spec_path}",
            f"--product-promotion-output={report_root}",
            "-q",
        ],
        cwd=temp_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == pytest.ExitCode.TESTS_FAILED, result.stdout + result.stderr
    assert "1 failed, 1 passed" in result.stdout
    assert "PRODUCT_PROMOTION_DECISION=rejected:2/3" in result.stdout
    report_dirs = [path.parent for path in report_root.rglob("manifest.json")]
    assert len(report_dirs) == 1
    report_dir = report_dirs[0]
    assert archive_checksums_valid(report_dir)
    trace_path, = report_dir.glob("*.trace.json")
    report = json.loads(trace_path.read_text(encoding="utf-8"))["trace"]
    assert report["status"] == "rejected"
    assert report["observed_samples"] == 2
    assert report["first_failed_at_sample"] == 2
