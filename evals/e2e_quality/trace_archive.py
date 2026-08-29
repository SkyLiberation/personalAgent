"""Non-production trace archive for live E2E evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from evals.e2e_quality.measurements import (
    CaseMeasurement,
    MeasurementProfile,
    measurement_from_trace_payload,
)


TRACE_SCHEMA_VERSION = 3


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat().replace("+00:00", "Z")


def _safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)
    return cleaned.strip("-")[:100] or "trace"


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ("git", *args),
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _git_dirty_digest() -> str | None:
    status = _git_value("status", "--porcelain=v1")
    if not status:
        return None
    try:
        diff = subprocess.check_output(
            ("git", "diff", "--binary", "HEAD", "--"),
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        diff = b""
    digest = sha256(status.encode("utf-8") + b"\0" + diff)
    try:
        root = Path(_git_value("rev-parse", "--show-toplevel") or ".")
        untracked = subprocess.check_output(
            ("git", "ls-files", "--others", "--exclude-standard", "-z"),
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).split(b"\0")
        for relative_bytes in sorted(item for item in untracked if item):
            digest.update(b"\0untracked\0" + relative_bytes + b"\0")
            path = root / relative_bytes.decode("utf-8")
            if path.is_file():
                digest.update(path.read_bytes())
    except (OSError, UnicodeDecodeError, subprocess.SubprocessError):
        pass
    return digest.hexdigest()


class TraceArchive:
    """Write immutable-shaped E2E evidence without coupling production code."""

    def __init__(
        self,
        output_root: Path,
        *,
        run_id: str | None = None,
        manifest_metadata: dict[str, Any] | None = None,
        measurement_profile: MeasurementProfile | None = None,
    ) -> None:
        started_at = _utc_now()
        self.run_id = run_id or (
            started_at.strftime("%Y%m%dT%H%M%S.%fZ") + f"-{os.getpid()}-{uuid4().hex[:8]}"
        )
        self.run_dir = output_root / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._started_at = started_at
        self._trace_files_by_nodeid: dict[str, list[Path]] = {}
        self._test_results: dict[str, dict[str, Any]] = {}
        self._manifest = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "archive_run_id": self.run_id,
            "started_at": _iso(started_at),
            "repository": {
                "commit": _git_value("rev-parse", "HEAD"),
                "branch": _git_value("branch", "--show-current"),
                "dirty": bool(_git_value("status", "--porcelain")),
                "dirty_digest": _git_dirty_digest(),
            },
            "runtime": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "environment": manifest_metadata or {},
            "measurement_profile": (
                measurement_profile.model_dump(mode="json")
                if measurement_profile is not None
                else None
            ),
        }
        self._write_json(self.run_dir / "manifest.json", self._manifest)

    def update_environment(self, values: dict[str, Any]) -> None:
        self._manifest["environment"] = {
            **self._manifest.get("environment", {}),
            **values,
        }
        self._write_json(self.run_dir / "manifest.json", self._manifest)

    def write_trace(
        self,
        *,
        nodeid: str,
        case_id: str,
        trace: dict[str, Any],
        measurement: CaseMeasurement | None = None,
        product_evidence: BaseModel | None = None,
    ) -> Path:
        if measurement is None:
            measurement = measurement_from_trace_payload(trace)
        paths = self._trace_files_by_nodeid.setdefault(nodeid, [])
        sequence = len(paths) + 1
        path = self.run_dir / f"{_safe_name(case_id)}.{sequence}.trace.json"
        envelope = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "archive_run_id": self.run_id,
            "nodeid": nodeid,
            "case_id": case_id,
            "captured_at": _iso(),
            "test_outcome": "pending",
            "measurement": (
                measurement.model_dump(mode="json")
                if measurement is not None
                else None
            ),
            "product_evidence": (
                product_evidence.model_dump(mode="json")
                if product_evidence is not None
                else None
            ),
            "trace": trace,
        }
        self._write_json(path, envelope)
        paths.append(path)
        return path

    def record_test_result(
        self,
        *,
        nodeid: str,
        phase: str,
        outcome: str,
        duration_seconds: float,
        detail: str | None = None,
    ) -> None:
        current = self._test_results.setdefault(nodeid, {
            "nodeid": nodeid,
            "outcome": "pending",
            "phases": {},
            "trace_files": [],
        })
        current["phases"][phase] = {
            "outcome": outcome,
            "duration_seconds": round(duration_seconds, 6),
            "detail": detail[:20_000] if detail else None,
        }
        if outcome == "failed" or current["outcome"] == "pending" or phase == "call":
            current["outcome"] = outcome
        trace_paths = self._trace_files_by_nodeid.get(nodeid, [])
        current["trace_files"] = [path.name for path in trace_paths]
        for path in trace_paths:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["test_outcome"] = current["outcome"]
            self._write_json(path, envelope)

    def finalize(self, *, exit_status: int | None = None) -> Path:
        finished_at = _utc_now()
        results = sorted(self._test_results.values(), key=lambda item: item["nodeid"])
        counts = {
            status: sum(item["outcome"] == status for item in results)
            for status in ("passed", "failed", "skipped", "pending")
        }
        summary_path = self.run_dir / "summary.json"
        self._write_json(summary_path, {
            "schema_version": TRACE_SCHEMA_VERSION,
            "archive_run_id": self.run_id,
            "started_at": _iso(self._started_at),
            "finished_at": _iso(finished_at),
            "duration_seconds": round((finished_at - self._started_at).total_seconds(), 6),
            "exit_status": exit_status,
            "counts": counts,
            "tests": results,
        })
        self._write_checksums()
        return summary_path

    def _write_checksums(self) -> None:
        lines = []
        for path in sorted(self.run_dir.glob("*.json")):
            digest = sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.name}")
        self._atomic_write(
            self.run_dir / "checksums.sha256",
            ("\n".join(lines) + "\n").encode("utf-8"),
        )

    @classmethod
    def _write_json(cls, path: Path, value: dict[str, Any]) -> None:
        data = (json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        ) + "\n").encode("utf-8")
        cls._atomic_write(path, data)

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        # Keep the temporary basename short.  Appending ``.tmp`` to the final
        # evidence filename can push an otherwise valid Windows path over the
        # legacy MAX_PATH boundary after an expensive cohort has finished.
        temporary = path.parent / f".tmp-{uuid4().hex[:12]}"
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def archive_checksums_valid(run_dir: Path) -> bool:
    """Return whether every archived JSON file matches the sealed checksum set."""

    checksum_path = run_dir / "checksums.sha256"
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


__all__ = [
    "TRACE_SCHEMA_VERSION",
    "TraceArchive",
    "archive_checksums_valid",
]
