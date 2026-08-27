"""Typed, checksum-sealed evidence capture for standalone product baselines."""

from __future__ import annotations

import os
import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from evals.e2e_quality.trace_archive import (
    TraceArchive,
    archive_checksums_valid,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


class ProductEvidenceIdentity(BaseModel):
    """Stable comparison facts for one product baseline or target artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    role: Literal["baseline", "target"]
    evidence_class: Literal[
        "product_e2e",
        "behavior_regression",
        "runtime_conformance",
    ]
    formal_entrypoint: str = Field(min_length=1)
    interaction_mode: Literal["default", "auto"] = "default"
    principal: AuthenticatedPrincipal
    user_input_digest: str = Field(pattern="^[0-9a-f]{64}$")
    initial_state_digest: str = Field(pattern="^[0-9a-f]{64}$")
    config_cohort: str = Field(min_length=1)
    grader_version: str = Field(min_length=1)


class ProductEvidenceCaptureFailure(BaseModel):
    """Typed fact emitted when a test ends after enrollment but before its report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    state: Literal["enrolled_without_result_report"] = (
        "enrolled_without_result_report"
    )
    pytest_outcome: Literal["passed", "failed", "skipped"]


class MissingProductResultReport(BaseModel):
    """Reserved trace payload for an enrolled sample with no result report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_evidence_capture: ProductEvidenceCaptureFailure


class EvidencePairError(ValueError):
    """Raised when baseline and target are not a comparable evidence pair."""


@dataclass(frozen=True, slots=True)
class FinalizedProductEvidence:
    """One checksum-verified product evidence sample for cohort evaluation."""

    archive_dir: Path
    archive_run_id: str
    identity: ProductEvidenceIdentity
    report: dict[str, Any]
    outcome: Literal["passed", "failed", "skipped"]
    duration_seconds: float
    subject_digest: str
    result_report_captured: bool


def canonical_evidence_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class ProductEvidenceRecorder:
    """Enroll and capture one case, then seal it after pytest knows the outcome."""

    def __init__(self, output_root: Path) -> None:
        self._output_root = output_root
        self._identity: ProductEvidenceIdentity | None = None
        self._nodeid: str | None = None
        self._report: dict[str, Any] | None = None
        self._finalized = False

    @property
    def result_report_captured(self) -> bool:
        return self._report is not None

    @property
    def enrolled(self) -> bool:
        return self._identity is not None

    def enroll(
        self,
        *,
        nodeid: str,
        identity: ProductEvidenceIdentity,
    ) -> None:
        """Freeze sample identity before the operation that may fail."""

        if self._identity is not None:
            raise RuntimeError("product evidence was already enrolled for this test")
        if self._finalized:
            raise RuntimeError("product evidence was already finalized")
        self._nodeid = nodeid
        self._identity = identity

    def capture_report(self, report: dict[str, Any]) -> None:
        """Attach the product result to the previously enrolled identity."""

        if self._identity is None:
            raise RuntimeError("product evidence must be enrolled before its report")
        if self._report is not None:
            raise RuntimeError("product evidence report was already captured")
        if self._finalized:
            raise RuntimeError("product evidence was already finalized")
        if "product_evidence_capture" in report:
            raise ValueError("product result report uses a reserved evidence key")
        self._report = report

    def capture(
        self,
        *,
        nodeid: str,
        identity: ProductEvidenceIdentity,
        report: dict[str, Any],
    ) -> None:
        """Legacy one-shot enrollment and result capture."""

        self.enroll(nodeid=nodeid, identity=identity)
        self.capture_report(report)

    def finalize(
        self,
        *,
        outcome: str,
        duration_seconds: float,
        detail: str | None,
    ) -> Path | None:
        if self._identity is None or self._nodeid is None:
            return None
        if self._finalized:
            raise RuntimeError("product evidence was already finalized")
        if outcome not in {"passed", "failed", "skipped"}:
            raise ValueError(f"unsupported pytest outcome: {outcome}")
        self._finalized = True
        trace_report = self._report or MissingProductResultReport(
            product_evidence_capture=ProductEvidenceCaptureFailure(
                pytest_outcome=cast(
                    Literal["passed", "failed", "skipped"],
                    outcome,
                )
            )
        ).model_dump(mode="json")
        archive = TraceArchive(
            self._output_root
            / self._identity.case_id.lower()
            / self._identity.role
        )
        archive.write_trace(
            nodeid=self._nodeid,
            case_id=self._identity.case_id,
            trace=trace_report,
            product_evidence=self._identity,
        )
        archive.record_test_result(
            nodeid=self._nodeid,
            phase="call",
            outcome=outcome,
            duration_seconds=duration_seconds,
            detail=detail,
        )
        archive.finalize(exit_status=0 if outcome == "passed" else 1)
        return archive.run_dir


def validate_product_evidence_pair(
    baseline_run_dir: Path,
    target_run_dir: Path,
) -> tuple[ProductEvidenceIdentity, ProductEvidenceIdentity]:
    """Validate that two sealed archives differ only in implementation/config."""

    baseline, baseline_manifest = _load_product_evidence(
        baseline_run_dir,
        expected_role="baseline",
    )
    target, target_manifest = _load_product_evidence(
        target_run_dir,
        expected_role="target",
    )
    comparable_fields = (
        "case_id",
        "evidence_class",
        "formal_entrypoint",
        "interaction_mode",
        "principal",
        "user_input_digest",
        "initial_state_digest",
        "grader_version",
    )
    mismatches = [
        field
        for field in comparable_fields
        if getattr(baseline, field) != getattr(target, field)
    ]
    if mismatches:
        raise EvidencePairError(
            "baseline and target differ in comparison identity: "
            + ", ".join(mismatches)
        )
    if _subject_identity(baseline, baseline_manifest) == _subject_identity(
        target,
        target_manifest,
    ):
        raise EvidencePairError(
            "baseline and target identify the same code and configuration subject"
        )
    return baseline, target


def load_finalized_product_evidence(run_dir: Path) -> FinalizedProductEvidence:
    """Load one sealed sample without promoting its evidence class."""

    if not archive_checksums_valid(run_dir):
        raise EvidencePairError(f"archive checksum validation failed: {run_dir}")
    try:
        manifest = json.loads(
            (run_dir / "manifest.json").read_text(encoding="utf-8")
        )
        summary = json.loads(
            (run_dir / "summary.json").read_text(encoding="utf-8")
        )
        trace_paths = tuple(sorted(run_dir.glob("*.trace.json")))
        if len(trace_paths) != 1:
            raise EvidencePairError(
                f"archive must contain exactly one product trace: {run_dir}"
            )
        envelope = json.loads(trace_paths[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidencePairError(f"invalid product evidence archive: {run_dir}") from exc
    if not all(isinstance(item, dict) for item in (manifest, summary, envelope)):
        raise EvidencePairError(f"product evidence archive must contain objects: {run_dir}")
    raw_identity = envelope.get("product_evidence")
    raw_report = envelope.get("trace")
    tests = summary.get("tests")
    if not isinstance(raw_identity, dict) or not isinstance(raw_report, dict):
        raise EvidencePairError(f"archive lacks product evidence payload: {run_dir}")
    if not isinstance(tests, list) or len(tests) != 1 or not isinstance(tests[0], dict):
        raise EvidencePairError(f"archive must contain one finalized test result: {run_dir}")
    outcome = tests[0].get("outcome")
    phases = tests[0].get("phases")
    call = phases.get("call") if isinstance(phases, dict) else None
    duration = call.get("duration_seconds") if isinstance(call, dict) else None
    if outcome not in {"passed", "failed", "skipped"}:
        raise EvidencePairError(f"archive test outcome is not finalized: {run_dir}")
    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or not isfinite(duration)
        or duration < 0
    ):
        raise EvidencePairError(f"archive lacks call duration: {run_dir}")
    try:
        identity = ProductEvidenceIdentity.model_validate(raw_identity)
    except ValueError as exc:
        raise EvidencePairError(
            f"archive has invalid product evidence identity: {run_dir}"
        ) from exc
    archive_run_id = manifest.get("archive_run_id")
    if not isinstance(archive_run_id, str) or not archive_run_id:
        raise EvidencePairError(f"archive lacks run identity: {run_dir}")
    result_report_captured = True
    if "product_evidence_capture" in raw_report:
        try:
            capture_failure = MissingProductResultReport.model_validate(raw_report)
        except ValueError as exc:
            raise EvidencePairError(
                f"archive has invalid capture-failure report: {run_dir}"
            ) from exc
        if capture_failure.product_evidence_capture.pytest_outcome != outcome:
            raise EvidencePairError(
                f"archive capture failure disagrees with pytest outcome: {run_dir}"
            )
        result_report_captured = False
    return FinalizedProductEvidence(
        archive_dir=run_dir,
        archive_run_id=archive_run_id,
        identity=identity,
        report=raw_report,
        outcome=outcome,
        duration_seconds=float(duration),
        subject_digest=canonical_evidence_digest(
            _subject_identity(identity, manifest)
        ),
        result_report_captured=result_report_captured,
    )


def _load_product_evidence(
    run_dir: Path,
    *,
    expected_role: Literal["baseline", "target"],
) -> tuple[ProductEvidenceIdentity, dict[str, Any]]:
    if not archive_checksums_valid(run_dir):
        raise EvidencePairError(f"archive checksum validation failed: {run_dir}")
    try:
        manifest = json.loads(
            (run_dir / "manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidencePairError(f"invalid archive manifest: {run_dir}") from exc
    identities: list[ProductEvidenceIdentity] = []
    for path in sorted(run_dir.glob("*.trace.json")):
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            raw_identity = envelope.get("product_evidence")
            if raw_identity is not None:
                identities.append(ProductEvidenceIdentity.model_validate(raw_identity))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise EvidencePairError(f"invalid product evidence: {path}") from exc
    if len(identities) != 1:
        raise EvidencePairError(
            f"archive must contain exactly one product evidence identity: {run_dir}"
        )
    identity = identities[0]
    if identity.role != expected_role:
        raise EvidencePairError(
            f"expected {expected_role} archive, got {identity.role}: {run_dir}"
        )
    return identity, manifest


def _subject_identity(
    evidence: ProductEvidenceIdentity,
    manifest: dict[str, Any],
) -> tuple[object, ...]:
    repository = manifest.get("repository")
    if not isinstance(repository, dict):
        raise EvidencePairError("archive manifest lacks repository identity")
    return (
        repository.get("commit"),
        repository.get("dirty_digest"),
        evidence.config_cohort,
    )


def product_evidence_output_root() -> Path:
    return Path(os.environ.get(
        "PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR",
        "data/e2e_traces/product_baselines",
    ))


def product_evidence_role(case_id: str) -> Literal["baseline", "target"]:
    env_name = (
        "PERSONAL_AGENT_"
        + case_id.replace("-", "_").upper()
        + "_EVIDENCE_ROLE"
    )
    value = os.environ.get(env_name, "target")
    if value not in {"baseline", "target"}:
        raise ValueError(f"{env_name} must be 'baseline' or 'target'")
    return cast(Literal["baseline", "target"], value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="validate a checksum-sealed product baseline/target pair"
    )
    parser.add_argument("baseline", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    baseline, target = validate_product_evidence_pair(
        args.baseline,
        args.target,
    )
    print(
        f"valid product evidence pair: {baseline.case_id} "
        f"({baseline.role} -> {target.role})"
    )
    return 0


__all__ = [
    "EvidencePairError",
    "FinalizedProductEvidence",
    "MissingProductResultReport",
    "ProductEvidenceCaptureFailure",
    "ProductEvidenceIdentity",
    "ProductEvidenceRecorder",
    "canonical_evidence_digest",
    "load_finalized_product_evidence",
    "product_evidence_output_root",
    "product_evidence_role",
    "validate_product_evidence_pair",
]


if __name__ == "__main__":
    raise SystemExit(main())
