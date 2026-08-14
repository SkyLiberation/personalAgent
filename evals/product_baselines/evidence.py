"""Typed, checksum-sealed evidence capture for standalone product baselines."""

from __future__ import annotations

import os
import argparse
from hashlib import sha256
import json
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


class EvidencePairError(ValueError):
    """Raised when baseline and target are not a comparable evidence pair."""


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
    """Capture one standalone case and seal it after pytest knows the outcome."""

    def __init__(self, output_root: Path) -> None:
        self._output_root = output_root
        self._identity: ProductEvidenceIdentity | None = None
        self._nodeid: str | None = None
        self._report: dict[str, Any] | None = None
        self._finalized = False

    def capture(
        self,
        *,
        nodeid: str,
        identity: ProductEvidenceIdentity,
        report: dict[str, Any],
    ) -> None:
        if self._identity is not None:
            raise RuntimeError("product evidence was already captured for this test")
        self._nodeid = nodeid
        self._identity = identity
        self._report = report

    def finalize(
        self,
        *,
        outcome: str,
        duration_seconds: float,
        detail: str | None,
    ) -> Path | None:
        if self._identity is None or self._nodeid is None or self._report is None:
            return None
        if self._finalized:
            raise RuntimeError("product evidence was already finalized")
        self._finalized = True
        archive = TraceArchive(
            self._output_root
            / self._identity.case_id.lower()
            / self._identity.role
        )
        archive.write_trace(
            nodeid=self._nodeid,
            case_id=self._identity.case_id,
            trace=self._report,
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
    "ProductEvidenceIdentity",
    "ProductEvidenceRecorder",
    "canonical_evidence_digest",
    "product_evidence_output_root",
    "product_evidence_role",
    "validate_product_evidence_pair",
]


if __name__ == "__main__":
    raise SystemExit(main())
