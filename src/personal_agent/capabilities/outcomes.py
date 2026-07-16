"""Outcome-aware ranking over separate execution and effectiveness facts."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Callable, Protocol

from personal_agent.capabilities.contracts.execution import Capability, ExecutionCapabilityRequest
from personal_agent.capabilities.contracts.outcomes import (
    CapabilityEffectivenessEvent,
    CapabilityExecutionOutcomeEvent,
)


@dataclass(frozen=True, slots=True)
class CapabilityOutcomeSnapshot:
    execution_sample_count: int = 0
    execution_success_count: int = 0
    effectiveness_sample_count: int = 0
    effective_count: int = 0
    total_latency_ms: float = 0.0
    total_cost: float = 0.0

    @property
    def success_rate(self) -> float:
        return (
            self.execution_success_count / self.execution_sample_count
            if self.execution_sample_count else 0.0
        )

    @property
    def verifier_pass_rate(self) -> float:
        return (
            self.effective_count / self.effectiveness_sample_count
            if self.effectiveness_sample_count else 0.0
        )

    @property
    def average_latency_ms(self) -> float:
        return self.total_latency_ms / self.execution_sample_count if self.execution_sample_count else 0.0

    @property
    def average_cost(self) -> float:
        return self.total_cost / self.execution_sample_count if self.execution_sample_count else 0.0


class CapabilityOutcomeStore:
    def __init__(self) -> None:
        self._execution: dict[str, CapabilityExecutionOutcomeEvent] = {}
        self._effectiveness: dict[str, CapabilityEffectivenessEvent] = {}
        self._lock = RLock()

    def append_execution(self, event: CapabilityExecutionOutcomeEvent) -> None:
        with self._lock:
            self._execution.setdefault(event.event_id, event)

    def append_effectiveness(self, event: CapabilityEffectivenessEvent) -> None:
        with self._lock:
            execution = self._execution.get(event.execution_outcome_ref)
            if execution is None or execution.capability_ref != event.capability_ref:
                raise ValueError("effectiveness must reference execution of the same capability")
            self._effectiveness.setdefault(event.event_id, event)

    def snapshot(self, capability_ref: str) -> CapabilityOutcomeSnapshot:
        with self._lock:
            execution = [
                item for item in self._execution.values()
                if item.capability_ref == capability_ref and item.outcome in {"succeeded", "failed"}
            ]
            effectiveness = [
                item for item in self._effectiveness.values()
                if item.capability_ref == capability_ref
                and item.verdict in {"effective", "ineffective"}
            ]
            return CapabilityOutcomeSnapshot(
                execution_sample_count=len(execution),
                execution_success_count=sum(item.outcome == "succeeded" for item in execution),
                effectiveness_sample_count=len(effectiveness),
                effective_count=sum(item.verdict == "effective" for item in effectiveness),
                total_latency_ms=sum(item.latency_ms for item in execution),
                total_cost=sum(item.cost for item in execution),
            )


class CapabilityRanker(Protocol):
    def rank(
        self,
        candidates: list[Capability],
        request: ExecutionCapabilityRequest,
        base_key: Callable[[Capability], tuple],
    ) -> tuple[list[Capability], dict[str, object]]: ...


class OutcomeAwareCapabilityRanker:
    feature_version = "capability-outcome-v2"

    def __init__(self, store: CapabilityOutcomeStore | None = None, *, minimum_samples: int = 3) -> None:
        self.store = store or CapabilityOutcomeStore()
        self.minimum_samples = minimum_samples

    def rank(
        self,
        candidates: list[Capability],
        request: ExecutionCapabilityRequest,
        base_key: Callable[[Capability], tuple],
    ) -> tuple[list[Capability], dict[str, object]]:
        snapshots = {item.capability_id: self.store.snapshot(item.capability_id) for item in candidates}

        def rank_key(capability: Capability) -> tuple:
            outcome = snapshots[capability.capability_id]
            has_evidence = int(outcome.effectiveness_sample_count >= self.minimum_samples)
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
                    "execution_sample_count": value.execution_sample_count,
                    "effectiveness_sample_count": value.effectiveness_sample_count,
                    "success_rate": value.success_rate,
                    "verifier_pass_rate": value.verifier_pass_rate,
                    "average_latency_ms": value.average_latency_ms,
                    "average_cost": value.average_cost,
                }
                for capability_id, value in snapshots.items()
            },
        }


__all__ = [
    "CapabilityOutcomeSnapshot", "CapabilityOutcomeStore", "CapabilityRanker",
    "OutcomeAwareCapabilityRanker",
]
