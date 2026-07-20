"""Compile task understanding into deterministic task and goal-graph contracts."""

from __future__ import annotations

from dataclasses import dataclass

from personal_agent.runtime.contracts.task import (
    ContextInventory,
    ContextItem,
    EvidencePolicy,
    EvidenceRequirements,
    GoalDefinition,
    GoalConstraint,
    GoalDependency,
    GoalGraphDefinition,
    GoalRuntimeState,
    MutationIntent,
    ResourceRequirement,
    SuccessCriterion,
    TaskConstraints,
    TaskContract,
    TaskRuntimeProjection,
)
from personal_agent.planning.task_analyzer import Goal, ResourceHint, TaskAnalysis
from personal_agent.kernel.contracts.resource import mutating_operations
from personal_agent.runtime.task_validation import TaskContractValidator



@dataclass(frozen=True, slots=True)
class GoalCompilation:
    task_contract: TaskContract
    runtime: TaskRuntimeProjection
    context_inventory: ContextInventory


class GoalGraphValidator(TaskContractValidator):
    """Specification for a valid executable goal graph."""

    def validate_analysis(self, analysis: TaskAnalysis) -> None:
        goal_ids = {goal.goal_id for goal in analysis.goals}
        if len(goal_ids) != len(analysis.goals):
            raise ValueError("goal ids must be unique")
        seen_relations: set[tuple[str, str, str]] = set()
        hard_graph = {goal_id: set() for goal_id in goal_ids}
        for relation in analysis.relations:
            if relation.predecessor_goal_id not in goal_ids:
                raise ValueError(f"unknown predecessor goal: {relation.predecessor_goal_id}")
            if relation.successor_goal_id not in goal_ids:
                raise ValueError(f"unknown successor goal: {relation.successor_goal_id}")
            key = (
                relation.predecessor_goal_id,
                relation.successor_goal_id,
                relation.kind,
            )
            if key in seen_relations:
                raise ValueError("duplicate goal relation")
            seen_relations.add(key)
            if relation.kind != "ordering_preference":
                hard_graph[relation.successor_goal_id].add(relation.predecessor_goal_id)
        _validate_acyclic(hard_graph)

class GoalGraphCompiler:
    """Compiler pattern: semantic analysis in, executable contracts out."""

    def __init__(
        self,
        validator: GoalGraphValidator | None = None,
    ) -> None:
        self._validator = validator or GoalGraphValidator()

    def compile(self, analysis: TaskAnalysis, entry_text: str) -> GoalCompilation:
        self._validator.validate_analysis(analysis)
        goals = analysis.goals
        grouped_resources = [_resources_for_goal(goal) for goal in goals]
        mutation_operations = tuple(dict.fromkeys(
            operation
            for group in grouped_resources
            for operation in _mutation_operations(group)
        ))
        evidence_required = any(
            _requires_evidence(goal, group)
            for goal, group in zip(goals, grouped_resources, strict=True)
        )

        dependencies_by_goal: dict[str, list[GoalDependency]] = {
            goal.goal_id: [] for goal in goals
        }
        for relation in analysis.relations:
            dependencies_by_goal[relation.successor_goal_id].append(GoalDependency(
                dependency_goal_id=relation.predecessor_goal_id,
                kind=relation.kind,
                origin=relation.origin,
                rationale=relation.rationale,
            ))

        definitions: list[GoalDefinition] = []
        states: dict[str, GoalRuntimeState] = {}
        for goal, group in zip(goals, grouped_resources, strict=True):
            goal_criteria = _criteria_for_goal(goal, group)
            goal_constraints = tuple(
                GoalConstraint(
                    constraint_id=f"{goal.goal_id}:constraint:{index}",
                    description=constraint.description,
                    source="user" if constraint.origin == "user_explicit" else "model",
                    mutability=(
                        "immutable" if constraint.origin == "user_explicit" else "model_revisable"
                    ),
                )
                for index, constraint in enumerate(goal.constraints, start=1)
            )
            dependencies = tuple(dependencies_by_goal[goal.goal_id])
            definitions.append(GoalDefinition(
                goal_id=goal.goal_id,
                dependencies=dependencies,
                description=goal.description,
                result_contract=goal.result_contract,
                resources=group,
                criteria=goal_criteria,
                constraints=goal_constraints,
                output_contract=_output_contract(goal, group),
            ))
            states[goal.goal_id] = GoalRuntimeState(
                status="pending" if any(item.blocks_execution for item in dependencies) else "active",
                evidence_gaps=("initial_evidence_required",)
                if _requires_evidence(goal, group) else (),
            )

        mutation = MutationIntent(
            operations=mutation_operations,
            requires_confirmation=True,
        ) if mutation_operations else None
        goal_graph_revision = 1
        task = TaskContract(
            user_goal=analysis.user_goal,
            result_contract=_task_result_contract(goals),
            constraints=TaskConstraints(
                read_only=mutation is None,
                max_parallelism=min(max(len(goals), 1), 4),
            ),
            goal_graph=GoalGraphDefinition(
                revision=goal_graph_revision,
                goals=tuple(definitions),
            ),
            evidence_requirements=EvidenceRequirements(
                citation_required=evidence_required,
                minimum_source_count=1 if evidence_required else None,
                must_cover_all_subgoals=True,
                contradiction_check=evidence_required,
            ),
            mutation_intent=mutation,
            clarification_needed=analysis.requires_clarification,
        )
        runtime = TaskRuntimeProjection(
            task_id=task.task_id,
            task_revision=task.revision,
            goal_graph_revision=task.goal_graph.revision,
            goal_states=states,
        )
        self._validator.validate_runtime(task, runtime)
        context_item = ContextItem(
            item_id=task.task_id,
            category="run",
            kind="task_contract",
            provenance="runtime",
            trust="runtime",
            summary=task.user_goal[:1000],
            payload={"revision": task.revision},
            admission="admitted",
        )
        context = ContextInventory(items={context_item.item_id: context_item})
        return GoalCompilation(task, runtime, context)


def _validate_acyclic(graph: dict[str, set[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(goal_id: str) -> None:
        if goal_id in visiting:
            raise ValueError("blocking goal dependencies contain a cycle")
        if goal_id in visited:
            return
        visiting.add(goal_id)
        for dependency_id in graph[goal_id]:
            visit(dependency_id)
        visiting.remove(goal_id)
        visited.add(goal_id)

    for goal_id in graph:
        visit(goal_id)


def _resources_for_goal(
    goal: Goal,
) -> tuple[ResourceRequirement, ...]:
    return tuple(_resource_from_hint(hint) for hint in goal.resource_hints)


def _resource_from_hint(hint: ResourceHint) -> ResourceRequirement:
    return ResourceRequirement.from_dimensions(
        semantic_domain=hint.semantic_domain,
        locator=hint.locator,
        resource_types=tuple(hint.resource_types),
        required_operations=tuple(hint.operations),
        origin=hint.origin,
        freshness_required=hint.freshness_required,
        required_providers=(hint.user_required_provider,)
        if hint.user_required_provider else (),
    )


def _mutation_operations(
    resources: tuple[ResourceRequirement, ...],
) -> tuple[str, ...]:
    return mutating_operations(
        operation
        for resource in resources
        for operation in resource.required_operations
    )


def _criteria_for_goal(
    goal: Goal,
    resources: tuple[ResourceRequirement, ...],
) -> tuple[SuccessCriterion, ...]:
    requires_evidence = _requires_evidence(goal, resources)
    declared = goal.success_criteria
    criteria = [SuccessCriterion(
        criterion_id=f"{goal.goal_id}:result:{index}",
        description=criterion.description,
        required=True,
        source=("user_explicit" if criterion.origin == "user_explicit" else "model_derived"),
        mutability=("user_revisable" if criterion.origin == "user_explicit" else "immutable"),
        evidence_policy=EvidencePolicy(
            citation_required=(
                goal.evidence_requirement.citation_required
                if goal.evidence_requirement else requires_evidence
            ),
            minimum_source_count=(
                goal.evidence_requirement.minimum_source_count
                if goal.evidence_requirement else (1 if requires_evidence else None)
            ),
            contradiction_check=(
                goal.evidence_requirement.contradiction_check
                if goal.evidence_requirement else requires_evidence
            ),
        ),
        acceptance_contract="VerifiedAnswer" if requires_evidence else "UserVisibleResult",
    ) for index, criterion in enumerate(declared, start=1)]
    if _mutation_operations(resources):
        criteria.append(SuccessCriterion(
            criterion_id=f"{goal.goal_id}:receipt",
            description="状态变更经过确认并产生可审计 receipt",
            required=True,
            source="contract_derived",
            mutability="immutable",
            acceptance_contract="MutationReceipt",
        ))
    return tuple(criteria)


def _requires_evidence(
    goal: Goal,
    resources: tuple[ResourceRequirement, ...],
) -> bool:
    return goal.evidence_requirement is not None or any(
        set(resource.required_operations).intersection({"search", "verify"})
        for resource in resources
    )


def _output_contract(
    goal: Goal,
    resources: tuple[ResourceRequirement, ...],
) -> str:
    if _mutation_operations(resources):
        return "MutationReceipt"
    if _requires_evidence(goal, resources):
        return "VerifiedAnswer"
    return "Answer"


def _task_result_contract(goals: list[Goal]) -> str:
    if len(goals) > 1:
        return "compound"
    return goals[0].result_contract


__all__ = ["GoalCompilation", "GoalGraphCompiler", "GoalGraphValidator"]
