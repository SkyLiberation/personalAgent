"""Append-only execution events and governed goal-graph projection."""

from __future__ import annotations

from dataclasses import dataclass

from personal_agent.kernel.contracts.agentic import (
    AttemptRef,
    ExecutionEvent,
    ExecutionLedger,
    ExecutionLedgerItem,
    GoalDependency,
    ResourceRequirement,
    SuccessCriterion,
    TaskSpec,
)
from personal_agent.kernel.contracts.capability import CapabilityCoverage
from personal_agent.kernel.contracts.executive import VerificationReport
from personal_agent.kernel.contracts.planning import GoalDecompositionProposal
from personal_agent.planning.goal_graph import GoalGraphValidator


class LedgerTransitionError(ValueError):
    pass


_ALLOWED_TRANSITIONS = {
    "pending": {"active", "abandoned"},
    "active": {"blocked", "awaiting_input", "candidate_complete", "degraded", "abandoned"},
    "blocked": {"active", "degraded", "abandoned"},
    "awaiting_input": {"active", "abandoned"},
    "candidate_complete": {"verified", "active", "degraded"},
    "verified": set(),
    "degraded": set(),
    "abandoned": set(),
}


@dataclass(frozen=True)
class PreparedGoalDecomposition:
    task_spec: TaskSpec
    ledger: ExecutionLedger
    events: tuple[tuple[str, str | None, dict], ...]


class GoalDecompositionValidator:
    """Specification for observation-derived operational subgoals."""

    def prepare(
        self,
        task: TaskSpec,
        ledger: ExecutionLedger,
        proposal: GoalDecompositionProposal,
        *,
        available_observation_ids: set[str],
    ) -> PreparedGoalDecomposition:
        if proposal.base_task_revision != task.revision:
            raise LedgerTransitionError("goal decomposition has stale task revision")
        if proposal.base_goal_graph_revision != ledger.goal_graph_revision:
            raise LedgerTransitionError("goal decomposition has stale goal graph revision")
        source_ids = set(proposal.derived_from_observation_ids)
        if not source_ids.issubset(available_observation_ids):
            raise LedgerTransitionError("goal decomposition references unknown observations")
        item_by_id = {item.goal_id: item for item in ledger.items}
        parent = item_by_id.get(proposal.parent_goal_id)
        if parent is None:
            raise LedgerTransitionError("goal decomposition parent does not exist")
        if parent.status in {"verified", "degraded", "abandoned"}:
            raise LedgerTransitionError("terminal goal cannot be decomposed")
        runtime_count = sum(item.origin == "runtime_derived" for item in ledger.items)
        if runtime_count + len(proposal.children) > task.constraints.goal_expansion_budget:
            raise LedgerTransitionError("runtime goal budget exceeded")
        allowed_domains = {item.semantic_domain for item in task.resource_requirements}
        allowed_operations = set(task.requested_operations).union(
            operation
            for item in task.resource_requirements
            for operation in item.required_operations
        )
        criteria = list(task.success_criteria)
        resources = list(task.resource_requirements)
        events: list[tuple[str, str | None, dict]] = []
        child_ids: list[str] = []
        for child in proposal.children:
            if child.goal_id in item_by_id:
                raise LedgerTransitionError("derived goal id already exists")
            depth = parent.decomposition_depth + 1
            if depth > task.constraints.max_derived_goal_depth:
                raise LedgerTransitionError("derived goal exceeds maximum decomposition depth")
            for requirement in child.resource_requirements:
                if requirement.side_effect_class != "none":
                    raise LedgerTransitionError("derived goals cannot introduce side effects")
                if allowed_domains and not set(requirement.semantic_domains).issubset(allowed_domains):
                    raise LedgerTransitionError("derived goal expands semantic resource scope")
                if allowed_operations and not set(requirement.operations).issubset(allowed_operations):
                    raise LedgerTransitionError("derived goal expands operation scope")
                resources.extend(
                    ResourceRequirement(
                        goal_id=child.goal_id,
                        semantic_domain=domain,
                        locator=requirement.resource_locator,
                        resource_types=requirement.resource_types,
                        required_operations=requirement.operations,
                        origin="runtime_derived",
                        freshness_required=requirement.freshness_required,
                        required_providers=requirement.required_providers,
                    )
                    for domain in requirement.semantic_domains
                )
            child_criteria = tuple(
                SuccessCriterion(
                    criterion_id=value.criterion_id,
                    description=value.description,
                    source="model_derived",
                    mutability="runtime_derived",
                    acceptance_contract=value.acceptance_contract,
                )
                for value in child.criteria
            )
            criteria.extend(child_criteria)
            item = ExecutionLedgerItem(
                goal_id=child.goal_id,
                parent_goal_id=parent.goal_id,
                description=child.description,
                result_contract=child.result_contract,
                origin="runtime_derived",
                decomposition_depth=depth,
                status="active",
                success_criterion_ids=tuple(value.criterion_id for value in child_criteria),
                output_contract=child.output_contract,
            )
            item_by_id[item.goal_id] = item
            child_ids.append(item.goal_id)
            events.append(("goal_added", item.goal_id, {"goal": item.model_dump(mode="json")}))
        dependencies = (*parent.dependencies, *(
            GoalDependency(
                dependency_goal_id=child_id,
                kind="requires_completion",
                origin="runtime_derived",
                rationale=proposal.objective,
            )
            for child_id in child_ids
        ))
        item_by_id[parent.goal_id] = parent.model_copy(update={"dependencies": dependencies})
        for child_id in child_ids:
            dependency = next(
                item for item in dependencies if item.dependency_goal_id == child_id
            )
            events.append((
                "goal_dependency_added",
                parent.goal_id,
                {
                    "dependency_goal_id": child_id,
                    "dependency": dependency.model_dump(mode="json"),
                },
            ))
        projected = ledger.model_copy(update={"items": tuple(item_by_id.values())})
        GoalGraphValidator().validate_ledger(projected)
        return PreparedGoalDecomposition(
            task_spec=task.model_copy(update={
                "success_criteria": tuple(criteria),
                "resource_requirements": tuple(resources),
            }),
            ledger=projected,
            events=tuple(events),
        )


class ExecutionLedgerProjector:
    def project(self, ledger: ExecutionLedger, events: tuple[ExecutionEvent, ...]) -> ExecutionLedger:
        current = ledger
        expected = current.last_event_sequence + 1
        for event in events:
            if event.task_id != current.task_id:
                raise LedgerTransitionError("event task_id does not match ledger")
            if event.sequence != expected:
                raise LedgerTransitionError(f"expected event sequence {expected}, got {event.sequence}")
            current = self._apply(current, event)
            expected += 1
        return current

    def _apply(self, ledger: ExecutionLedger, event: ExecutionEvent) -> ExecutionLedger:
        items = list(ledger.items)
        index = next((i for i, item in enumerate(items) if item.goal_id == event.goal_id), None)
        status_by_event = {
            "goal_activated": "active",
            "goal_blocked": "blocked",
            "goal_candidate_complete": "candidate_complete",
            "goal_verified": "verified",
            "goal_degraded": "degraded",
            "goal_abandoned": "abandoned",
        }
        if event.event_type == "goal_added":
            items.append(ExecutionLedgerItem.model_validate(event.payload["goal"]))
        elif event.event_type in status_by_event:
            if index is None:
                raise LedgerTransitionError(f"event references unknown goal {event.goal_id}")
            item = items[index]
            target = status_by_event[event.event_type]
            if target != item.status and target not in _ALLOWED_TRANSITIONS[item.status]:
                raise LedgerTransitionError(f"illegal goal transition {item.status}->{target}")
            update = {"status": target}
            if "evidence_gaps" in event.payload:
                update["evidence_gaps"] = tuple(event.payload["evidence_gaps"])
            if "verification" in event.payload:
                update["verification"] = VerificationReport.model_validate(
                    event.payload["verification"]
                )
            items[index] = item.model_copy(update=update)
        elif event.event_type == "attempt_recorded":
            if index is None:
                raise LedgerTransitionError(f"event references unknown goal {event.goal_id}")
            item = items[index]
            attempt = AttemptRef.model_validate(event.payload["attempt"])
            items[index] = item.model_copy(update={"attempts": (*item.attempts, attempt)})
        elif event.event_type == "coverage_recorded":
            if index is None:
                raise LedgerTransitionError(f"event references unknown goal {event.goal_id}")
            item = items[index]
            items[index] = item.model_copy(update={
                "coverage": tuple(
                    CapabilityCoverage.model_validate(value)
                    for value in event.payload.get("coverage", ())
                ),
                "evidence_gaps": tuple(event.payload.get("evidence_gaps", item.evidence_gaps)),
            })
        elif event.event_type in {
            "goal_dependency_added", "goal_dependency_removed", "goal_dependency_updated",
        }:
            if index is None:
                raise LedgerTransitionError(f"event references unknown goal {event.goal_id}")
            item = items[index]
            dependency_id = str(event.payload["dependency_goal_id"])
            if event.event_type == "goal_dependency_removed":
                dependencies = tuple(
                    value for value in item.dependencies
                    if value.dependency_goal_id != dependency_id
                )
            else:
                dependency = GoalDependency.model_validate(event.payload["dependency"])
                dependencies = tuple(
                    value for value in item.dependencies
                    if value.dependency_goal_id != dependency_id
                ) + (dependency,)
            items[index] = item.model_copy(update={"dependencies": dependencies})
        elif event.event_type == "skill_activated":
            skill_id = str(event.payload["skill_id"])
            if skill_id not in ledger.active_skill_ids:
                ledger = ledger.model_copy(update={
                    "active_skill_ids": (*ledger.active_skill_ids, skill_id),
                })
        active = tuple(item.goal_id for item in items if item.status in {
            "pending", "active", "blocked", "awaiting_input", "candidate_complete",
        })
        graph_events = {
            "goal_added", "goal_dependency_added", "goal_dependency_removed",
            "goal_dependency_updated", "goal_abandoned",
        }
        return ledger.model_copy(update={
            "items": tuple(items),
            "active_goal_ids": active,
            "revision": ledger.revision + 1,
            "goal_graph_revision": (
                ledger.goal_graph_revision + 1
                if event.event_type in graph_events else ledger.goal_graph_revision
            ),
            "last_event_sequence": event.sequence,
        })


def next_execution_event(
    ledger: ExecutionLedger,
    event_type: str,
    *,
    goal_id: str | None = None,
    payload: dict | None = None,
) -> ExecutionEvent:
    return ExecutionEvent(
        sequence=ledger.last_event_sequence + 1,
        task_id=ledger.task_id,
        event_type=event_type,
        goal_id=goal_id,
        payload=payload or {},
    )


__all__ = [
    "ExecutionLedgerProjector", "GoalDecompositionValidator", "LedgerTransitionError",
    "PreparedGoalDecomposition", "next_execution_event",
]
