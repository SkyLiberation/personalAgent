"""Measure snapshot-journal amplification and cold reconstruction consistency."""

from __future__ import annotations

import argparse
import json
from math import ceil
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from personal_agent.application.conversation.journal import FileInteractionJournal
from evals.e2e_quality.trace_archive import archive_checksums_valid


def _p95(values: list[float | int]) -> float | int:
    ordered = sorted(values)
    return ordered[ceil(0.95 * len(ordered)) - 1]


def _archived_traces(
    evidence_root: Path,
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    traces: dict[str, dict[str, Any]] = {}
    config_cohorts: set[str] = set()
    archive_dirs = sorted(path.parent for path in evidence_root.rglob("manifest.json"))
    invalid_archives = [
        str(path) for path in archive_dirs if not archive_checksums_valid(path)
    ]
    if invalid_archives:
        raise ValueError(f"Archive checksum validation failed: {invalid_archives}")
    for path in evidence_root.rglob("*.trace.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        trace = payload["trace"]["interaction_trace"]
        traces[str(trace["interaction_run_ref"])] = trace
        config_cohorts.add(str(payload["product_evidence"]["config_cohort"]))
    if len(archive_dirs) != len(traces):
        raise ValueError(
            "Archive/trace count mismatch: "
            f"archives={len(archive_dirs)}, traces={len(traces)}"
        )
    return traces, config_cohorts


def measure(journal_root: Path, evidence_root: Path) -> dict[str, Any]:
    archived, config_cohorts = _archived_traces(evidence_root)
    snapshot_rows: list[dict[str, Any]] = []
    cold_load_ms: list[float] = []
    mismatches: list[str] = []

    for run_dir in sorted(path for path in journal_root.iterdir() if path.is_dir()):
        snapshots = sorted(run_dir.glob("*.json"))
        if not snapshots:
            continue
        sizes = [path.stat().st_size for path in snapshots]
        total_bytes = sum(sizes)
        final_bytes = sizes[-1]
        snapshot_rows.append({
            "interaction_run_ref": run_dir.name,
            "versions": len(snapshots),
            "total_bytes": total_bytes,
            "final_bytes": final_bytes,
            "write_amplification": total_bytes / final_bytes,
        })

        started = perf_counter_ns()
        reconstructed = FileInteractionJournal(journal_root).get(run_dir.name)
        cold_load_ms.append((perf_counter_ns() - started) / 1_000_000)
        if (
            reconstructed is None
            or reconstructed.model_dump(mode="json") != archived.get(run_dir.name)
        ):
            mismatches.append(run_dir.name)

    if not snapshot_rows:
        raise ValueError(f"No interaction snapshots found under {journal_root}")
    if len(archived) != len(snapshot_rows):
        raise ValueError(
            "Journal/evidence run count mismatch: "
            f"journal={len(snapshot_rows)}, evidence={len(archived)}"
        )

    context_rows = [
        row
        for trace in archived.values()
        for row in trace.get("context_composition", [])
    ]
    input_tokens = [int(row["input_tokens"]) for row in context_rows]
    typed_input_chars = [int(row["typed_inputs_chars"]) for row in context_rows]
    versions = [int(row["versions"]) for row in snapshot_rows]
    amplifications = [float(row["write_amplification"]) for row in snapshot_rows]

    return {
        "schema_version": 1,
        "journal_root": str(journal_root.resolve()),
        "evidence_root": str(evidence_root.resolve()),
        "archive_count": len(archived),
        "archive_checksum_error_count": 0,
        "config_cohort_count": len(config_cohorts),
        "interaction_count": len(snapshot_rows),
        "snapshot_versions": {
            "minimum": min(versions),
            "p95": _p95(versions),
            "maximum": max(versions),
        },
        "snapshot_bytes": {
            "cumulative": sum(int(row["total_bytes"]) for row in snapshot_rows),
            "final": sum(int(row["final_bytes"]) for row in snapshot_rows),
            "write_amplification_minimum": round(min(amplifications), 3),
            "write_amplification_p95": round(float(_p95(amplifications)), 3),
            "write_amplification_maximum": round(max(amplifications), 3),
        },
        "cold_reconstruction": {
            "p95_ms": round(float(_p95(cold_load_ms)), 3),
            "maximum_ms": round(max(cold_load_ms), 3),
            "api_trace_mismatch_count": len(mismatches),
            "mismatched_interaction_run_refs": mismatches,
        },
        "context_composition": {
            "model_turn_count": len(context_rows),
            "input_tokens_p95": _p95(input_tokens),
            "input_tokens_maximum": max(input_tokens),
            "typed_input_chars_p95": _p95(typed_input_chars),
            "typed_input_chars_maximum": max(typed_input_chars),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure a FileInteractionJournal cohort against archived API traces."
        )
    )
    parser.add_argument("journal_root", type=Path)
    parser.add_argument("evidence_root", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            measure(args.journal_root, args.evidence_root),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
