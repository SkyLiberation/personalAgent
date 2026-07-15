"""Outcome-aware ranking applied only after capability hard filtering."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Callable, Protocol

from personal_agent.kernel.contracts.capability import Capability, CapabilityResolutionRequest


@dataclass(frozen=True, slots=True)
class CapabilityOutcome:
    sample_count: int = 0
    success_count: int = 0
    verifier_pass_count: int = 0
    total_latency_ms: float = 0.0
    total_cost: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.sample_count if self.sample_count else 0.0

    @property
    def verifier_pass_rate(self) -> float:
        return self.verifier_pass_count / self.sample_count if self.sample_count else 0.0

    @property
    def average_latency_ms(self) -> float:
        return self.total_latency_ms / self.sample_count if self.sample_count else 0.0

    @property
    def average_cost(self) -> float:
        return self.total_cost / self.sample_count if self.sample_count else 0.0


class CapabilityOutcomeStore:
    def __init__(self) -> None:
        self._values: dict[str, CapabilityOutcome] = {}
        self._lock = RLock()

    def record(
        self,
        capability_id: str,
        *,
        succeeded: bool,
        verifier_passed: bool,
        latency_ms: float,
        cost: float = 0.0,
    ) -> CapabilityOutcome:
        with self._lock:
            current = self._values.get(capability_id, CapabilityOutcome())
            updated = CapabilityOutcome(
                sample_count=current.sample_count + 1,
                success_count=current.success_count + int(succeeded),
                verifier_pass_count=current.verifier_pass_count + int(verifier_passed),
                total_latency_ms=current.total_latency_ms + max(latency_ms, 0.0),
                total_cost=current.total_cost + max(cost, 0.0),
            )
            self._values[capability_id] = updated
            return updated

    def snapshot(self, capability_id: str) -> CapabilityOutcome:
        with self._lock:
            return self._values.get(capability_id, CapabilityOutcome())


class CapabilityRanker(Protocol):
    def rank(
        self,
        candidates: list[Capability],
        request: CapabilityResolutionRequest,
        base_key: Callable[[Capability], tuple],
    ) -> tuple[list[Capability], dict[str, object]]: ...


class OutcomeAwareCapabilityRanker:
    feature_version = "capability-outcome-v1"

    def __init__(
        self,
        store: CapabilityOutcomeStore | None = None,
        *,
        minimum_samples: int = 3,
    ) -> None:
        self.store = store or CapabilityOutcomeStore()
        self.minimum_samples = minimum_samples

    def rank(
        self,
        candidates: list[Capability],
        request: CapabilityResolutionRequest,
        base_key: Callable[[Capability], tuple],
    ) -> tuple[list[Capability], dict[str, object]]:
        snapshots = {
            item.capability_id: self.store.snapshot(item.capability_id)
            for item in candidates
        }

        def rank_key(capability: Capability) -> tuple:
            outcome = snapshots[capability.capability_id]
            has_evidence = int(outcome.sample_count >= self.minimum_samples)
            learned = (
                outcome.verifier_pass_rate,
                outcome.success_rate,
                -outcome.average_latency_ms,
                -outcome.average_cost,
            ) if has_evidence else (0.0, 0.0, 0.0, 0.0)
            return has_evidence, learned, base_key(capability)

        ranked = sorted(candidates, key=rank_key, reverse=True)
        return ranked, {
            "ranker": type(self).__name__,
            "feature_version": self.feature_version,
            "minimum_samples": self.minimum_samples,
            "outcomes": {
                capability_id: {
                    "sample_count": value.sample_count,
                    "success_rate": value.success_rate,
                    "verifier_pass_rate": value.verifier_pass_rate,
                    "average_latency_ms": value.average_latency_ms,
                    "average_cost": value.average_cost,
                }
                for capability_id, value in snapshots.items()
            },
        }


__all__ = [
    "CapabilityOutcome",
    "CapabilityOutcomeStore",
    "CapabilityRanker",
    "OutcomeAwareCapabilityRanker",
]
