"""Append-only execution events and governed goal-graph projection."""

from __future__ import annotations

from dataclasses import dataclass

from personal_agent.kernel.contracts.agentic import (
    AttemptRef,
    ExecutionEvent,
    GoalDefinition,
    GoalDependency,
    GoalGraphDefinition,
    GoalRuntimeState,
    ResourceRequirement,
    SuccessCriterion,
    TaskContract,
    TaskRuntimeProjection,
    materialize_goals,
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
    task_contract: TaskContract
    runtime: TaskRuntimeProjection
    events: tuple[tuple[str, str | None, dict], ...]


class GoalDecompositionValidator:
    """Specification for observation-derived operational subgoals."""

    def prepare(
        self,
        task: TaskContract,
        runtime: TaskRuntimeProjection,
        proposal: GoalDecompositionProposal,
        *,
        available_observation_ids: set[str],
    ) -> PreparedGoalDecomposition:
        if proposal.base_task_revision != task.revision:
            raise LedgerTransitionError("goal decomposition has stale task revision")
        if proposal.base_goal_graph_revision != runtime.goal_graph_revision:
            raise LedgerTransitionError("goal decomposition has stale goal graph revision")
        source_ids = set(proposal.derived_from_observation_ids)
        if not source_ids.issubset(available_observation_ids):
            raise LedgerTransitionError("goal decomposition references unknown observations")
        views = materialize_goals(task, runtime)
        view_by_id = {item.goal_id: item for item in views}
        parent = view_by_id.get(proposal.parent_goal_id)
        if parent is None:
            raise LedgerTransitionError("goal decomposition parent does not exist")
        if parent.status in {"verified", "degraded", "abandoned"}:
            raise LedgerTransitionError("terminal goal cannot be decomposed")
        runtime_count = sum(item.origin == "runtime_derived" for item in views)
        if runtime_count + len(proposal.children) > task.constraints.goal_expansion_budget:
            raise LedgerTransitionError("runtime goal budget exceeded")
        allowed_domains = {item.semantic_domain for item in task.resource_requirements}
        allowed_operations = set(task.requested_operations).union(
            operation
            for item in task.resource_requirements
            for operation in item.required_operations
        )
        definitions = task.goal_graph.by_id()
        states = dict(runtime.goal_states)
        events: list[tuple[str, str | None, dict]] = []
        child_ids: list[str] = []
        for child in proposal.children:
            if child.goal_id in definitions:
                raise LedgerTransitionError("derived goal id already exists")
            depth = parent.decomposition_depth + 1
            if depth > task.constraints.max_derived_goal_depth:
                raise LedgerTransitionError("derived goal exceeds maximum decomposition depth")
            child_resources: list[ResourceRequirement] = []
            for requirement in child.resource_requirements:
                if requirement.side_effect_class != "none":
                    raise LedgerTransitionError("derived goals cannot introduce side effects")
                if allowed_domains and not set(requirement.semantic_domains).issubset(allowed_domains):
                    raise LedgerTransitionError("derived goal expands semantic resource scope")
                if allowed_operations and not set(requirement.operations).issubset(allowed_operations):
                    raise LedgerTransitionError("derived goal expands operation scope")
                child_resources.extend(
                    ResourceRequirement.from_dimensions(
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
            definition = GoalDefinition(
                goal_id=child.goal_id,
                parent_goal_id=parent.goal_id,
                description=child.description,
                result_contract=child.result_contract,
                origin="runtime_derived",
                decomposition_depth=depth,
                resources=tuple(child_resources),
                criteria=child_criteria,
                output_contract=child.output_contract,
            )
            state = GoalRuntimeState(status="active")
            definitions[child.goal_id] = definition
            states[child.goal_id] = state
            child_ids.append(child.goal_id)
            events.append(("goal_added", child.goal_id, {"runtime": state.model_dump(mode="json")}))
        dependencies = (*parent.dependencies, *(
            GoalDependency(
                dependency_goal_id=child_id,
                kind="requires_completion",
                origin="runtime_derived",
                rationale=proposal.objective,
            )
            for child_id in child_ids
        ))
        definitions[parent.goal_id] = parent.definition.model_copy(
            update={"dependencies": dependencies}
        )
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
        graph_revision = task.goal_graph.revision + len(events)
        new_task_revision = task.revision + 1
        updated_task = task.model_copy(update={
            "revision": new_task_revision,
            "goal_graph": GoalGraphDefinition(
                revision=graph_revision,
                goals=tuple(definitions.values()),
            ),
        })
        projected = runtime.model_copy(update={
            "task_revision": new_task_revision,
            "goal_graph_revision": graph_revision,
            "goal_states": states,
        })
        GoalGraphValidator().validate_runtime(updated_task, projected)
        return PreparedGoalDecomposition(
            task_contract=updated_task,
            runtime=projected,
            events=tuple(events),
        )


class TaskRuntimeProjector:
    def project(self, ledger: TaskRuntimeProjection, events: tuple[ExecutionEvent, ...]) -> TaskRuntimeProjection:
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

    def _apply(self, ledger: TaskRuntimeProjection, event: ExecutionEvent) -> TaskRuntimeProjection:
        states = dict(ledger.goal_states)
        state = states.get(event.goal_id or "")
        status_by_event = {
            "goal_activated": "active",
            "goal_blocked": "blocked",
            "goal_candidate_complete": "candidate_complete",
            "goal_verified": "verified",
            "goal_degraded": "degraded",
            "goal_abandoned": "abandoned",
        }
        if event.event_type == "goal_added":
            if event.goal_id is None:
                raise LedgerTransitionError("goal_added requires goal_id")
            added = GoalRuntimeState.model_validate(event.payload["runtime"])
            if event.goal_id in states:
                raise LedgerTransitionError(f"goal already exists {event.goal_id}")
            states[event.goal_id] = added
        elif event.event_type in status_by_event:
            if state is None:
                raise LedgerTransitionError(f"event references unknown goal {event.goal_id}")
            target = status_by_event[event.event_type]
            if target != state.status and target not in _ALLOWED_TRANSITIONS[state.status]:
                raise LedgerTransitionError(f"illegal goal transition {state.status}->{target}")
            update = {"status": target}
            if "evidence_gaps" in event.payload:
                update["evidence_gaps"] = tuple(event.payload["evidence_gaps"])
            if "verification" in event.payload:
                update["verification"] = VerificationReport.model_validate(
                    event.payload["verification"]
                )
            states[event.goal_id] = state.model_copy(update=update)
        elif event.event_type == "attempt_recorded":
            if state is None:
                raise LedgerTransitionError(f"event references unknown goal {event.goal_id}")
            attempt = AttemptRef.model_validate(event.payload["attempt"])
            states[event.goal_id] = state.model_copy(
                update={"attempts": (*state.attempts, attempt)}
            )
        elif event.event_type == "coverage_recorded":
            if state is None:
                raise LedgerTransitionError(f"event references unknown goal {event.goal_id}")
            states[event.goal_id] = state.model_copy(update={
                "coverage": tuple(
                    CapabilityCoverage.model_validate(value)
                    for value in event.payload.get("coverage", ())
                ),
                "evidence_gaps": tuple(event.payload.get("evidence_gaps", state.evidence_gaps)),
            })
        elif event.event_type == "verification_recorded":
            if state is None:
                raise LedgerTransitionError(f"event references unknown goal {event.goal_id}")
            states[event.goal_id] = state.model_copy(update={
                "verification": VerificationReport.model_validate(event.payload["verification"]),
            })
        elif event.event_type == "skill_activated":
            skill_id = str(event.payload["skill_id"])
            if skill_id not in ledger.active_skill_ids:
                ledger = ledger.model_copy(update={
                    "active_skill_ids": (*ledger.active_skill_ids, skill_id),
                })
        elif event.event_type == "task_completed":
            ledger = ledger.model_copy(update={"lifecycle": "completed"})
        elif event.event_type == "task_stopped":
            ledger = ledger.model_copy(update={"lifecycle": "stopped"})
        graph_events = {
            "goal_added", "goal_dependency_added", "goal_dependency_removed",
            "goal_dependency_updated", "goal_abandoned",
        }
        return ledger.model_copy(update={
            "goal_states": states,
            "revision": ledger.revision + 1,
            "goal_graph_revision": (
                ledger.goal_graph_revision + 1
                if event.event_type in graph_events else ledger.goal_graph_revision
            ),
            "last_event_sequence": event.sequence,
        })


def next_execution_event(
    ledger: TaskRuntimeProjection,
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
    "TaskRuntimeProjector", "GoalDecompositionValidator", "LedgerTransitionError",
    "PreparedGoalDecomposition", "next_execution_event",
]
