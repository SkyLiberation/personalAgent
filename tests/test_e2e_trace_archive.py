from __future__ import annotations

from hashlib import sha256
import json

from evals.e2e_quality.trace_archive import TraceArchive


def test_trace_archive_persists_outcome_summary_and_checksums(temp_dir) -> None:
    archive = TraceArchive(
        temp_dir,
        run_id="evidence-run",
        manifest_metadata={"structured_model": "test-model"},
    )
    trace_path = archive.write_trace(
        nodeid="evals/test_live.py::test_case",
        case_id="case-one",
        trace={"input": {"text": "hello"}, "output": {"run_status": "completed"}},
    )
    archive.record_test_result(
        nodeid="evals/test_live.py::test_case",
        phase="call",
        outcome="passed",
        duration_seconds=1.25,
    )
    archive.record_test_result(
        nodeid="evals/test_live.py::test_failed_before_trace",
        phase="call",
        outcome="failed",
        duration_seconds=0.5,
        detail="planner rejected the live plan",
    )

    summary_path = archive.finalize(exit_status=0)

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads((archive.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert trace["test_outcome"] == "passed"
    assert summary["counts"]["passed"] == 1
    assert summary["counts"]["failed"] == 1
    by_nodeid = {item["nodeid"]: item for item in summary["tests"]}
    assert by_nodeid["evals/test_live.py::test_case"]["trace_files"] == [trace_path.name]
    failed = by_nodeid["evals/test_live.py::test_failed_before_trace"]
    assert failed["trace_files"] == []
    assert failed["phases"]["call"]["detail"] == "planner rejected the live plan"
    assert manifest["environment"]["structured_model"] == "test-model"

    checksums = {}
    for line in (archive.run_dir / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        digest, filename = line.split("  ", maxsplit=1)
        checksums[filename] = digest
    for path in archive.run_dir.glob("*.json"):
        assert checksums[path.name] == sha256(path.read_bytes()).hexdigest()
