"""Subagent scope attenuation and parent-owned budget reservations."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from personal_agent.kernel.contracts.agent import SubagentProfile
from personal_agent.kernel.contracts.executive import SubtaskSpec


@dataclass(frozen=True, slots=True)
class DelegationBudgetReservation:
    parent_run_id: str
    child_run_id: str
    token_budget: int
    cost_budget: float
    time_budget_seconds: int


@dataclass(frozen=True, slots=True)
class EffectiveSubagentScope:
    capability_ids: tuple[str, ...]
    operations: tuple[str, ...]


class SubagentRuntime:
    def __init__(self) -> None:
        self._reservations: dict[str, DelegationBudgetReservation] = {}
        self._lock = RLock()

    def effective_scope(
        self,
        *,
        profile: SubagentProfile,
        parent_capability_ids: tuple[str, ...],
        parent_operations: tuple[str, ...],
        policy_capability_ids: tuple[str, ...],
        policy_operations: tuple[str, ...],
        subtask: SubtaskSpec,
    ) -> EffectiveSubagentScope:
        requested_ids = set(subtask.requested_capability_ids or parent_capability_ids)
        requested_ops = set(subtask.requested_operations or subtask.required_capability.operations)
        return EffectiveSubagentScope(
            capability_ids=tuple(sorted(
                set(parent_capability_ids)
                & set(profile.capability_ids)
                & set(policy_capability_ids)
                & requested_ids
            )),
            operations=tuple(sorted(
                set(parent_operations)
                & set(profile.allowed_operations)
                & set(policy_operations)
                & requested_ops
            )),
        )

    def reserve(
        self,
        *,
        parent_run_id: str,
        child_run_id: str,
        subtask: SubtaskSpec,
        parent_token_remaining: int,
        parent_cost_remaining: float,
        parent_time_remaining: int,
    ) -> DelegationBudgetReservation:
        if (
            subtask.token_budget > parent_token_remaining
            or subtask.cost_budget > parent_cost_remaining
            or subtask.time_budget_seconds > parent_time_remaining
        ):
            raise ValueError("subagent budget exceeds parent remainder")
        reservation = DelegationBudgetReservation(
            parent_run_id=parent_run_id,
            child_run_id=child_run_id,
            token_budget=subtask.token_budget,
            cost_budget=subtask.cost_budget,
            time_budget_seconds=subtask.time_budget_seconds,
        )
        with self._lock:
            if child_run_id in self._reservations:
                raise ValueError("child budget is already reserved")
            self._reservations[child_run_id] = reservation
        return reservation

    def release(self, child_run_id: str) -> DelegationBudgetReservation:
        with self._lock:
            try:
                return self._reservations.pop(child_run_id)
            except KeyError as exc:
                raise KeyError(f"unknown child reservation: {child_run_id}") from exc


__all__ = [
    "DelegationBudgetReservation",
    "EffectiveSubagentScope",
    "SubagentRuntime",
]
