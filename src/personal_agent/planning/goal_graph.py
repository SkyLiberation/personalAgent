"""Compile task understanding into deterministic task and goal-graph contracts."""

from __future__ import annotations

from dataclasses import dataclass

from personal_agent.kernel.contracts.agentic import (
    ContextEnvelope,
    ContextItem,
    EvidencePolicy,
    EvidenceRequirements,
    ExecutionLedger,
    ExecutionLedgerItem,
    GoalDependency,
    MutationIntent,
    ResourceRequirement,
    SuccessCriterion,
    TaskConstraints,
    TaskSpec,
)
from personal_agent.planning.task_analyzer import Goal, ResourceHint, TaskAnalysis


_WRITE_OPERATIONS = frozenset({"create", "update", "delete", "ingest", "repair"})


@dataclass(frozen=True, slots=True)
class GoalCompilation:
    task_spec: TaskSpec
    ledger: ExecutionLedger
    context_envelope: ContextEnvelope


class GoalGraphValidator:
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

    def validate_ledger(self, ledger: ExecutionLedger) -> None:
        goal_ids = {item.goal_id for item in ledger.items}
        if len(goal_ids) != len(ledger.items):
            raise ValueError("goal ids must be unique")
        hard_graph = {goal_id: set() for goal_id in goal_ids}
        for item in ledger.items:
            seen: set[tuple[str, str]] = set()
            for dependency in item.dependencies:
                if dependency.dependency_goal_id not in goal_ids:
                    raise ValueError(
                        f"goal {item.goal_id} has unknown dependency "
                        f"{dependency.dependency_goal_id}"
                    )
                if dependency.dependency_goal_id == item.goal_id:
                    raise ValueError(f"goal {item.goal_id} cannot depend on itself")
                key = (dependency.dependency_goal_id, dependency.kind)
                if key in seen:
                    raise ValueError("duplicate goal dependency")
                seen.add(key)
                if dependency.blocks_execution:
                    hard_graph[item.goal_id].add(dependency.dependency_goal_id)
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
        grouped_resources = [
            _resources_for_goal(goal)
            for goal in goals
        ]
        resources = tuple(resource for group in grouped_resources for resource in group)
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

        criteria: list[SuccessCriterion] = []
        items: list[ExecutionLedgerItem] = []
        for goal, group in zip(goals, grouped_resources, strict=True):
            goal_criteria = _criteria_for_goal(goal, group)
            criteria.extend(goal_criteria)
            dependencies = tuple(dependencies_by_goal[goal.goal_id])
            items.append(ExecutionLedgerItem(
                goal_id=goal.goal_id,
                dependencies=dependencies,
                description=goal.description or entry_text,
                result_contract=goal.result_contract,
                status="pending" if any(item.blocks_execution for item in dependencies) else "active",
                success_criterion_ids=tuple(item.criterion_id for item in goal_criteria),
                output_contract=_output_contract(goal, group),
                evidence_gaps=("initial_evidence_required",)
                if _requires_evidence(goal, group) else (),
            ))

        mutation = MutationIntent(
            operation="+".join(mutation_operations),
            requires_confirmation=True,
        ) if mutation_operations else None
        task = TaskSpec(
            user_goal=analysis.user_goal or entry_text,
            result_contract=_task_result_contract(goals),
            subjects=tuple(goal.description for goal in goals if goal.description),
            resource_requirements=resources,
            requested_operations=tuple(dict.fromkeys(
                operation for resource in resources for operation in resource.required_operations
            )),
            constraints=TaskConstraints(
                read_only=mutation is None,
                max_parallelism=min(max(len(goals), 1), 4),
            ),
            success_criteria=tuple(criteria),
            evidence_requirements=EvidenceRequirements(
                citation_required=evidence_required,
                minimum_source_count=1 if evidence_required else None,
                must_cover_all_subgoals=True,
                contradiction_check=evidence_required,
            ),
            mutation_intent=mutation,
            clarification_needed=analysis.requires_clarification,
        )
        ledger = ExecutionLedger(
            task_id=task.task_id,
            items=tuple(items),
            active_goal_ids=tuple(item.goal_id for item in items),
        )
        self._validator.validate_ledger(ledger)
        context = ContextEnvelope(run_context=(ContextItem(
            ref_id=task.task_id,
            kind="task_spec",
            provenance="runtime",
            trust_tier="runtime",
            summary=task.user_goal[:1000],
            payload={"revision": task.revision},
            admitted=True,
        ),))
        return GoalCompilation(task, ledger, context)


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
    return tuple(_resource_from_hint(goal.goal_id, hint) for hint in goal.resource_hints)


def _resource_from_hint(goal_id: str, hint: ResourceHint) -> ResourceRequirement:
    return ResourceRequirement(
        goal_id=goal_id,
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
    operations = tuple(
        operation for resource in resources for operation in resource.required_operations
        if operation in _WRITE_OPERATIONS
    )
    return operations


def _criteria_for_goal(
    goal: Goal,
    resources: tuple[ResourceRequirement, ...],
) -> tuple[SuccessCriterion, ...]:
    requires_evidence = _requires_evidence(goal, resources)
    declared = goal.success_criteria or [f"完成目标：{goal.description}"]
    criteria = [SuccessCriterion(
        criterion_id=f"{goal.goal_id}:result:{index}",
        description=description,
        required=True,
        source="user_explicit",
        mutability="immutable",
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
    ) for index, description in enumerate(declared, start=1)]
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
