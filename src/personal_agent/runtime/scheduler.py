"""Physical scheduling policy for already resolved actions."""

from __future__ import annotations

from personal_agent.kernel.contracts.resource import side_effect_requires_write_set
from personal_agent.runtime.contracts.control import ResolvedActionSpec
from personal_agent.runtime.contracts.planning import DispatchGroup, JoinPolicy


class SchedulingError(ValueError):
    pass


class RunScheduler:
    def validate_dispatch(self, action: ResolvedActionSpec) -> None:
        plan = action.resource_access_plan
        if not plan.complete:
            raise SchedulingError("resource access plan is incomplete")
        if side_effect_requires_write_set(plan.side_effect_class) and not plan.write_set:
            raise SchedulingError("resource-changing side effects require a resolved write set")

    def can_run_concurrently(self, left: ResolvedActionSpec, right: ResolvedActionSpec) -> bool:
        self.validate_dispatch(left)
        self.validate_dispatch(right)
        left_plan = left.resource_access_plan
        right_plan = right.resource_access_plan
        if left_plan.side_effect_class != "none" or right_plan.side_effect_class != "none":
            return False
        left_writes = _refs(left_plan.write_set)
        right_writes = _refs(right_plan.write_set)
        return not (
            left_writes.intersection(_refs(right_plan.read_set) | right_writes)
            or right_writes.intersection(_refs(left_plan.read_set) | left_writes)
        )

    def create_dispatch_groups(
        self,
        actions: tuple[ResolvedActionSpec, ...],
        *,
        requested_join_policy: JoinPolicy = "all",
    ) -> tuple[DispatchGroup, ...]:
        """Partition a semantic frontier using resolved physical resource facts."""
        if not actions:
            return ()
        groups: list[list[ResolvedActionSpec]] = []
        for action in actions:
            self.validate_dispatch(action)
            placed = False
            for group in groups:
                if all(self.can_run_concurrently(action, existing) for existing in group):
                    group.append(action)
                    placed = True
                    break
            if not placed:
                groups.append([action])
        return tuple(
            DispatchGroup(
                action_spec_ids=tuple(item.action_spec_id for item in group),
                join_policy=requested_join_policy if len(group) > 1 else "all",
                resolved_resource_snapshot=tuple(
                    ref
                    for item in group
                    for ref in item.resource_access_plan.source_refs
                ),
            )
            for group in groups
        )


def _refs(values) -> set[tuple[str, str | None]]:
    return {(item.semantic_domain, item.locator) for item in values}


__all__ = ["RunScheduler", "SchedulingError"]
