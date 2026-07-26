"""Revision-scoped release projection for native and composed capabilities.

The gate consumes the canonical evidence catalog and immutable-shaped trace
archives. It does not mutate runtime capability state or persist its result.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict

from evals.e2e_quality.evidence_catalog import (
    EVIDENCE_CASES,
    EvidenceCase,
    EvidenceClaimKind,
)


class _GateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NativeCapabilityDefinition(_GateModel):
    capability_id: str
    required_evidence_ids: tuple[str, ...]


class CompositeCapabilityDefinition(_GateModel):
    capability_id: str
    required_evidence_id: str
    required_native_capability_ids: tuple[str, ...]


class LoopCapabilityDefinition(_GateModel):
    capability_id: str
    required_evidence_id: str


class EvidenceGateResult(_GateModel):
    evidence_id: str
    claim_kind: EvidenceClaimKind
    status: Literal["trusted", "unverified"]
    reasons: tuple[str, ...] = ()
    archive_run_ids: tuple[str, ...] = ()


class CapabilityGateResult(_GateModel):
    capability_id: str
    status: Literal["trusted", "unverified"]
    required_evidence_ids: tuple[str, ...]
    reasons: tuple[str, ...] = ()


class ReleaseCapabilityReport(_GateModel):
    revision: str
    target_dirty: bool
    native_evidence: tuple[EvidenceGateResult, ...]
    composite_evidence: tuple[EvidenceGateResult, ...]
    loop_evidence: tuple[EvidenceGateResult, ...]
    native_capabilities: tuple[CapabilityGateResult, ...]
    composite_capabilities: tuple[CapabilityGateResult, ...]
    loop_capabilities: tuple[CapabilityGateResult, ...]

    @property
    def trusted_native_capability_ids(self) -> tuple[str, ...]:
        return tuple(
            result.capability_id
            for result in self.native_capabilities
            if result.status == "trusted"
        )

    @property
    def trusted_composite_capability_ids(self) -> tuple[str, ...]:
        return tuple(
            result.capability_id
            for result in self.composite_capabilities
            if result.status == "trusted"
        )

    @property
    def trusted_loop_capability_ids(self) -> tuple[str, ...]:
        return tuple(
            result.capability_id
            for result in self.loop_capabilities
            if result.status == "trusted"
        )


# Canonical machine-readable release claim catalog. Runtime availability is
# deliberately absent: it is a separate, interaction-scoped projection.
NATIVE_CAPABILITIES: tuple[NativeCapabilityDefinition, ...] = (
    NativeCapabilityDefinition(
        capability_id="conversation",
        required_evidence_ids=("E01",),
    ),
    NativeCapabilityDefinition(
        capability_id="capture",
        required_evidence_ids=("E08", "E09"),
    ),
    NativeCapabilityDefinition(
        capability_id="grounded_ask",
        required_evidence_ids=("E02", "E03", "E08"),
    ),
    NativeCapabilityDefinition(
        capability_id="knowledge_lifecycle",
        required_evidence_ids=("E04", "E10"),
    ),
    NativeCapabilityDefinition(
        capability_id="review",
        required_evidence_ids=("E11",),
    ),
    NativeCapabilityDefinition(
        capability_id="knowledge_maintenance",
        required_evidence_ids=("E12",),
    ),
    NativeCapabilityDefinition(
        capability_id="research",
        required_evidence_ids=("E05",),
    ),
    NativeCapabilityDefinition(
        capability_id="scheduled_intelligence",
        required_evidence_ids=("E13",),
    ),
)

COMPOSITE_CAPABILITIES: tuple[CompositeCapabilityDefinition, ...] = (
    CompositeCapabilityDefinition(
        capability_id="personal_research_analyst",
        required_evidence_id="C01",
        required_native_capability_ids=(
            "conversation",
            "grounded_ask",
            "research",
            "capture",
            "knowledge_lifecycle",
        ),
    ),
    CompositeCapabilityDefinition(
        capability_id="continuous_knowledge_steward",
        required_evidence_id="C02",
        required_native_capability_ids=(
            "scheduled_intelligence",
            "research",
            "grounded_ask",
            "knowledge_maintenance",
            "knowledge_lifecycle",
        ),
    ),
    CompositeCapabilityDefinition(
        capability_id="personalized_learning_agent",
        required_evidence_id="C03",
        required_native_capability_ids=(
            "grounded_ask",
            "review",
            "research",
            "capture",
        ),
    ),
    CompositeCapabilityDefinition(
        capability_id="expert_collaboration_agent",
        required_evidence_id="C04",
        required_native_capability_ids=(
            "conversation",
            "grounded_ask",
            "research",
        ),
    ),
)

LOOP_CAPABILITIES: tuple[LoopCapabilityDefinition, ...] = (
    LoopCapabilityDefinition(capability_id="observation_replanning", required_evidence_id="L01"),
    LoopCapabilityDefinition(capability_id="safe_action_concurrency", required_evidence_id="L02"),
    LoopCapabilityDefinition(capability_id="canonical_fact_recovery", required_evidence_id="L03"),
    LoopCapabilityDefinition(capability_id="manager_specialists", required_evidence_id="L04"),
    LoopCapabilityDefinition(capability_id="budget_fail_closed", required_evidence_id="L05"),
    LoopCapabilityDefinition(capability_id="evaluator_optimizer", required_evidence_id="L06"),
)

REQUIRED_NATIVE_EVIDENCE_IDS = tuple(f"E{index:02d}" for index in range(1, 14))
REQUIRED_COMPOSITE_EVIDENCE_IDS = tuple(f"C{index:02d}" for index in range(1, 5))
REQUIRED_LOOP_EVIDENCE_IDS = tuple(f"L{index:02d}" for index in range(1, 7))


def evaluate_release_capabilities(
    *,
    revision: str,
    target_dirty: bool,
    trace_root: Path,
    evidence_cases: Iterable[EvidenceCase] = EVIDENCE_CASES,
) -> ReleaseCapabilityReport:
    """Derive the unique release result from catalog entries and trace facts.

    Decision Ownership Taxonomy: deterministic release admission. Uniqueness
    comes from the requested revision/dirty fact, catalog eligibility metadata,
    archive checksums, manifest repository identity, and recorded test outcome.
    The gate never repairs catalog metadata or invents missing evidence.
    """

    catalog = tuple(evidence_cases)
    passing = _passing_evidence_by_id(
        revision=revision,
        target_dirty=target_dirty,
        trace_root=trace_root,
        evidence_cases=catalog,
    )
    native_evidence = tuple(
        _evaluate_evidence(
            evidence_id=evidence_id,
            claim_kind=EvidenceClaimKind.PRODUCT_CAPABILITY,
            catalog=catalog,
            passing=passing,
            target_dirty=target_dirty,
        )
        for evidence_id in REQUIRED_NATIVE_EVIDENCE_IDS
    )
    composite_evidence = tuple(
        _evaluate_evidence(
            evidence_id=evidence_id,
            claim_kind=EvidenceClaimKind.COMPOSITE_CAPABILITY,
            catalog=catalog,
            passing=passing,
            target_dirty=target_dirty,
        )
        for evidence_id in REQUIRED_COMPOSITE_EVIDENCE_IDS
    )
    loop_evidence = tuple(
        _evaluate_evidence(
            evidence_id=evidence_id,
            claim_kind=EvidenceClaimKind.COMPLEX_LOOP,
            catalog=catalog,
            passing=passing,
            target_dirty=target_dirty,
        )
        for evidence_id in REQUIRED_LOOP_EVIDENCE_IDS
    )
    evidence_by_id = {
        result.evidence_id: result
        for result in (*native_evidence, *composite_evidence, *loop_evidence)
    }

    native_capabilities = tuple(
        _native_result(definition, evidence_by_id)
        for definition in NATIVE_CAPABILITIES
    )
    native_by_id = {
        result.capability_id: result for result in native_capabilities
    }
    composite_capabilities = tuple(
        _composite_result(definition, evidence_by_id, native_by_id)
        for definition in COMPOSITE_CAPABILITIES
    )
    loop_capabilities = tuple(
        _loop_result(definition, evidence_by_id)
        for definition in LOOP_CAPABILITIES
    )
    return ReleaseCapabilityReport(
        revision=revision,
        target_dirty=target_dirty,
        native_evidence=native_evidence,
        composite_evidence=composite_evidence,
        loop_evidence=loop_evidence,
        native_capabilities=native_capabilities,
        composite_capabilities=composite_capabilities,
        loop_capabilities=loop_capabilities,
    )


def _evaluate_evidence(
    *,
    evidence_id: str,
    claim_kind: EvidenceClaimKind,
    catalog: tuple[EvidenceCase, ...],
    passing: dict[tuple[EvidenceClaimKind, str], set[str]],
    target_dirty: bool,
) -> EvidenceGateResult:
    candidates = tuple(
        case for case in catalog
        if case.case_id == evidence_id and case.claim_kind is claim_kind
    )
    reasons: list[str] = []
    if target_dirty:
        reasons.append("target_revision_dirty")
    if not candidates:
        reasons.append("missing_release_catalog_entry")
    elif not any(case.release_eligible for case in candidates):
        reasons.append("release_catalog_entry_ineligible")
    archive_run_ids = tuple(sorted(passing.get((claim_kind, evidence_id), set())))
    if not archive_run_ids:
        reasons.append("missing_same_revision_passing_trace")
    return EvidenceGateResult(
        evidence_id=evidence_id,
        claim_kind=claim_kind,
        status="trusted" if not reasons else "unverified",
        reasons=tuple(dict.fromkeys(reasons)),
        archive_run_ids=archive_run_ids,
    )


def _native_result(
    definition: NativeCapabilityDefinition,
    evidence_by_id: dict[str, EvidenceGateResult],
) -> CapabilityGateResult:
    missing = tuple(
        evidence_id
        for evidence_id in definition.required_evidence_ids
        if evidence_by_id[evidence_id].status != "trusted"
    )
    return CapabilityGateResult(
        capability_id=definition.capability_id,
        status="trusted" if not missing else "unverified",
        required_evidence_ids=definition.required_evidence_ids,
        reasons=tuple(f"untrusted_evidence:{item}" for item in missing),
    )


def _composite_result(
    definition: CompositeCapabilityDefinition,
    evidence_by_id: dict[str, EvidenceGateResult],
    native_by_id: dict[str, CapabilityGateResult],
) -> CapabilityGateResult:
    reasons: list[str] = []
    if evidence_by_id[definition.required_evidence_id].status != "trusted":
        reasons.append(f"untrusted_evidence:{definition.required_evidence_id}")
    reasons.extend(
        f"untrusted_native_capability:{capability_id}"
        for capability_id in definition.required_native_capability_ids
        if native_by_id[capability_id].status != "trusted"
    )
    return CapabilityGateResult(
        capability_id=definition.capability_id,
        status="trusted" if not reasons else "unverified",
        required_evidence_ids=(definition.required_evidence_id,),
        reasons=tuple(reasons),
    )


def _loop_result(
    definition: LoopCapabilityDefinition,
    evidence_by_id: dict[str, EvidenceGateResult],
) -> CapabilityGateResult:
    trusted = evidence_by_id[definition.required_evidence_id].status == "trusted"
    return CapabilityGateResult(
        capability_id=definition.capability_id,
        status="trusted" if trusted else "unverified",
        required_evidence_ids=(definition.required_evidence_id,),
        reasons=() if trusted else (f"untrusted_evidence:{definition.required_evidence_id}",),
    )


def _passing_evidence_by_id(
    *,
    revision: str,
    target_dirty: bool,
    trace_root: Path,
    evidence_cases: tuple[EvidenceCase, ...],
) -> dict[tuple[EvidenceClaimKind, str], set[str]]:
    if target_dirty or not trace_root.exists():
        return {}
    by_nodeid = {
        f"evals/e2e_quality/{case.module}::{case.test_name}": case
        for case in evidence_cases
        if case.release_eligible
    }
    passing: dict[tuple[EvidenceClaimKind, str], set[str]] = {}
    for run_dir in sorted(path for path in trace_root.iterdir() if path.is_dir()):
        archive = _load_valid_archive(run_dir, revision=revision)
        if archive is None:
            continue
        manifest, summary = archive
        run_id = str(manifest["archive_run_id"])
        for result in summary.get("tests", ()):
            if not isinstance(result, dict) or result.get("outcome") != "passed":
                continue
            nodeid = result.get("nodeid")
            case = by_nodeid.get(nodeid) if isinstance(nodeid, str) else None
            trace_files = result.get("trace_files")
            if case is None or not isinstance(trace_files, list) or not trace_files:
                continue
            if not _trace_files_passed(run_dir, run_id, trace_files):
                continue
            passing.setdefault((case.claim_kind, case.case_id), set()).add(run_id)
    return passing


def _load_valid_archive(
    run_dir: Path,
    *,
    revision: str,
) -> tuple[dict[str, object], dict[str, object]] | None:
    manifest_path = run_dir / "manifest.json"
    summary_path = run_dir / "summary.json"
    checksum_path = run_dir / "checksums.sha256"
    if not manifest_path.is_file() or not summary_path.is_file() or not checksum_path.is_file():
        return None
    if not _checksums_valid(run_dir, checksum_path):
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(manifest, dict) or not isinstance(summary, dict):
        return None
    repository = manifest.get("repository")
    if not isinstance(repository, dict):
        return None
    if repository.get("commit") != revision or repository.get("dirty") is not False:
        return None
    if summary.get("exit_status") != 0:
        return None
    if manifest.get("archive_run_id") != summary.get("archive_run_id"):
        return None
    return manifest, summary


def _checksums_valid(run_dir: Path, checksum_path: Path) -> bool:
    try:
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    expected: dict[str, str] = {}
    for line in lines:
        parts = line.split("  ", maxsplit=1)
        if len(parts) != 2:
            return False
        expected[parts[1]] = parts[0]
    json_files = tuple(sorted(run_dir.glob("*.json")))
    if {path.name for path in json_files} != set(expected):
        return False
    return all(
        sha256(path.read_bytes()).hexdigest() == expected[path.name]
        for path in json_files
    )


def _trace_files_passed(
    run_dir: Path,
    run_id: str,
    trace_files: list[object],
) -> bool:
    for filename in trace_files:
        if not isinstance(filename, str):
            return False
        path = run_dir / filename
        if path.parent != run_dir or not path.is_file():
            return False
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        if (
            not isinstance(envelope, dict)
            or envelope.get("archive_run_id") != run_id
            or envelope.get("test_outcome") != "passed"
        ):
            return False
    return True


def _git_value(*args: str) -> str:
    return subprocess.check_output(
        ("git", *args),
        text=True,
        encoding="utf-8",
        stderr=subprocess.DEVNULL,
        timeout=5,
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="derive the trusted release capability baseline")
    parser.add_argument("--trace-root", type=Path, default=Path("data/e2e_traces"))
    parser.add_argument("--revision")
    args = parser.parse_args()
    revision = args.revision or _git_value("rev-parse", "HEAD")
    target_dirty = bool(_git_value("status", "--porcelain"))
    report = evaluate_release_capabilities(
        revision=revision,
        target_dirty=target_dirty,
        trace_root=args.trace_root,
    )
    print(report.model_dump_json(indent=2))
    return 0 if (
        len(report.trusted_native_capability_ids) == len(NATIVE_CAPABILITIES)
        and len(report.trusted_composite_capability_ids) == len(COMPOSITE_CAPABILITIES)
        and len(report.trusted_loop_capability_ids) == len(LOOP_CAPABILITIES)
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "COMPOSITE_CAPABILITIES",
    "NATIVE_CAPABILITIES",
    "LOOP_CAPABILITIES",
    "REQUIRED_COMPOSITE_EVIDENCE_IDS",
    "REQUIRED_NATIVE_EVIDENCE_IDS",
    "REQUIRED_LOOP_EVIDENCE_IDS",
    "CapabilityGateResult",
    "CompositeCapabilityDefinition",
    "EvidenceGateResult",
    "NativeCapabilityDefinition",
    "LoopCapabilityDefinition",
    "ReleaseCapabilityReport",
    "evaluate_release_capabilities",
]
