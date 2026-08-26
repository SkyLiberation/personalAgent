"""Read-only Docker resource evidence for live product evaluations."""

from __future__ import annotations

from dataclasses import dataclass
from json import JSONDecodeError, loads
import re
import subprocess
from threading import Lock, Thread
from time import perf_counter
from typing import Any


_BYTE_UNITS = {
    "b": 1,
    "kb": 1_000,
    "kib": 1_024,
    "mb": 1_000**2,
    "mib": 1_024**2,
    "gb": 1_000**3,
    "gib": 1_024**3,
    "tb": 1_000**4,
    "tib": 1_024**4,
}
_BYTE_VALUE = re.compile(
    r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[kmgt]?i?b)\s*$",
    re.IGNORECASE,
)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def docker_size_bytes(value: str) -> int:
    match = _BYTE_VALUE.match(value)
    if match is None:
        raise ValueError(f"unsupported Docker size: {value!r}")
    return round(
        float(match.group("value"))
        * _BYTE_UNITS[match.group("unit").casefold()]
    )


def _percent(value: str) -> float:
    return float(value.strip().removesuffix("%"))


def docker_stats_payload(line: str) -> dict[str, Any] | None:
    value = _ANSI_ESCAPE.sub("", line).strip()
    if not value:
        return None
    payload = loads(value)
    if not isinstance(payload, dict):
        raise TypeError("Docker stats sample must be a JSON object")
    return payload


def normalize_docker_stats(
    payload: dict[str, Any],
    *,
    elapsed_seconds: float,
) -> dict[str, Any]:
    memory_parts = str(payload.get("MemUsage") or "").split("/", maxsplit=1)
    if len(memory_parts) != 2:
        raise ValueError("Docker stats MemUsage must contain usage and limit")
    return {
        "elapsed_seconds": round(elapsed_seconds, 3),
        "container": str(payload.get("Name") or payload.get("Container") or ""),
        "cpu_percent": _percent(str(payload.get("CPUPerc") or "0%")),
        "memory_bytes": docker_size_bytes(memory_parts[0]),
        "memory_limit_bytes": docker_size_bytes(memory_parts[1]),
        "memory_percent": _percent(str(payload.get("MemPerc") or "0%")),
        "pids": int(payload.get("PIDs") or 0),
    }


def summarize_docker_stats(
    samples: tuple[dict[str, Any], ...],
    *,
    container: str,
    errors: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not samples:
        return {
            "captured": False,
            "container": container,
            "sample_count": 0,
            "sampling_errors": list(errors),
            "samples": [],
        }
    return {
        "captured": True,
        "container": container,
        "sample_count": len(samples),
        "max_cpu_percent": max(item["cpu_percent"] for item in samples),
        "max_memory_bytes": max(item["memory_bytes"] for item in samples),
        "max_memory_percent": max(item["memory_percent"] for item in samples),
        "memory_limit_bytes": max(
            item["memory_limit_bytes"] for item in samples
        ),
        "max_pids": max(item["pids"] for item in samples),
        "sampling_errors": list(errors),
        "samples": list(samples),
    }


def discover_gpt_researcher_container() -> str:
    completed = subprocess.run(
        (
            "docker",
            "ps",
            "--filter",
            "label=com.docker.compose.service=gpt-researcher-a2a",
            "--format",
            "{{.Names}}",
        ),
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    names = tuple(
        line.strip() for line in completed.stdout.splitlines() if line.strip()
    )
    if len(names) != 1:
        raise RuntimeError(
            "resource evidence requires exactly one running "
            f"gpt-researcher-a2a container, found {len(names)}"
        )
    return names[0]


@dataclass
class DockerStatsSampler:
    container: str

    def __post_init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._thread: Thread | None = None
        self._started_at = 0.0
        self._samples: list[dict[str, Any]] = []
        self._errors: list[str] = []
        self._lock = Lock()
        self._summary: dict[str, Any] | None = None

    def start(self) -> None:
        if self._process is not None:
            return
        self._started_at = perf_counter()
        self._process = subprocess.Popen(
            (
                "docker",
                "stats",
                "--format",
                "{{json .}}",
                self.container,
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self._thread = Thread(
            target=self._read_samples,
            name="gpt-researcher-resource-evidence",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> dict[str, Any]:
        if self._summary is not None:
            return self._summary
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if self._thread is not None:
            self._thread.join(timeout=10)
        with self._lock:
            samples = tuple(self._samples)
            errors = tuple(self._errors)
        self._summary = summarize_docker_stats(
            samples,
            container=self.container,
            errors=errors,
        )
        return self._summary

    def _read_samples(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            try:
                payload = docker_stats_payload(line)
                if payload is None:
                    continue
                sample = normalize_docker_stats(
                    payload,
                    elapsed_seconds=perf_counter() - self._started_at,
                )
            except (JSONDecodeError, TypeError, ValueError) as exc:
                with self._lock:
                    self._errors.append(f"{type(exc).__name__}: {exc}")
                continue
            with self._lock:
                self._samples.append(sample)


__all__ = [
    "DockerStatsSampler",
    "discover_gpt_researcher_container",
    "docker_size_bytes",
    "docker_stats_payload",
    "normalize_docker_stats",
    "summarize_docker_stats",
]
