"""Translate semantic router output into provider-neutral task goals."""

from __future__ import annotations

from dataclasses import dataclass

from personal_agent.kernel.contracts.agentic import (
    ContextEnvelope,
    ContextItem,
    EvidencePolicy,
    EvidenceRequirements,
    ExecutionLedger,
    ExecutionLedgerItem,
    MutationIntent,
    ResourceRequirement,
    SuccessCriterion,
    TaskConstraints,
    TaskSpec,
)
from personal_agent.planning.router import Goal, RouterDecision


_PROTOCOL_INTENTS = frozenset({
    "capture_text", "capture_link", "capture_file", "analyze_artifact",
    "delete_knowledge", "solidify_conversation", "review_digest",
    "consolidate_knowledge", "inspect_knowledge_gaps", "research_once",
    "execute_research_run", "create_research_subscription", "manage_research",
    "maintain_knowledge", "inspect_operations", "inspect_workflow",
})
_MUTATION_INTENTS = frozenset({
    "capture_text", "capture_link", "capture_file", "delete_knowledge",
    "solidify_conversation", "create_research_subscription", "manage_research",
    "maintain_knowledge", "execute_research_run",
})


@dataclass(frozen=True, slots=True)
class GoalInterpretation:
    task_spec: TaskSpec
    ledger: ExecutionLedger
    context_envelope: ContextEnvelope


class GoalInterpreter:
    """Build the task objective without choosing a pattern or provider."""

    def interpret(self, decision: RouterDecision, entry_text: str) -> GoalInterpretation:
        goals = decision.goals or [Goal(goal_id="goal_1", intent="direct_answer", input=entry_text)]
        resources = tuple(_resource_for_goal(goal) for goal in goals)
        outcome = _outcome_kind(goals)
        mutation_operations = tuple(goal.intent for goal in goals if goal.intent in _MUTATION_INTENTS)
        evidence_required = any(
            resource.semantic_domain not in {"conversation"}
            and not _is_protocol_only(goal)
            for goal, resource in zip(goals, resources, strict=True)
        )

        criteria: list[SuccessCriterion] = []
        items: list[ExecutionLedgerItem] = []
        for goal, resource in zip(goals, resources, strict=True):
            goal_criteria = _criteria_for_goal(goal, resource)
            criteria.extend(goal_criteria)
            items.append(ExecutionLedgerItem(
                goal_id=goal.goal_id,
                description=goal.input or entry_text,
                goal_kind=_goal_kind(goal),
                protocol_id=goal.intent if goal.intent in _PROTOCOL_INTENTS else None,
                status="active",
                success_criterion_ids=tuple(item.criterion_id for item in goal_criteria),
                output_contract=_output_contract(goal),
                evidence_gaps=("initial_evidence_required",) if _requires_evidence(goal) else (),
            ))

        mutation = None
        if mutation_operations:
            mutation = MutationIntent(
                operation="+".join(mutation_operations),
                requires_confirmation=True,
            )
        task = TaskSpec(
            user_goal=decision.user_goal or entry_text,
            outcome_kind=outcome,
            subjects=tuple(goal.input for goal in goals if goal.input),
            resource_requirements=resources,
            requested_operations=tuple(sorted({
                operation for resource in resources for operation in resource.required_operations
            })),
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
            clarification_needed=decision.requires_clarification,
        )
        ledger = ExecutionLedger(
            task_id=task.task_id,
            items=tuple(items),
            active_goal_ids=tuple(item.goal_id for item in items),
        )
        context = ContextEnvelope(run_context=(ContextItem(
            ref_id=task.task_id,
            kind="task_spec",
            provenance="runtime",
            trust_tier="runtime",
            summary=task.user_goal[:1000],
            payload={"revision": task.revision},
            admitted=True,
        ),))
        return GoalInterpretation(task, ledger, context)


def _resource_for_goal(goal: Goal) -> ResourceRequirement:
    mapping = {
        "ask": ("knowledge", ("note", "evidence"), ("search", "read")),
        "external_codebase_qa": ("codebase", ("repository", "code", "file"), ("search", "read")),
        "external_workspace_qa": ("workspace", ("page", "data_source"), ("search", "read")),
        "external_project_ops": ("project", ("issue",), ("search", "read")),
        "gpt_researcher_a2a": ("external_research", ("agent",), ("delegate",)),
    }
    if goal.intent in mapping:
        domain, resource_types, operations = mapping[goal.intent]
        return ResourceRequirement(
            semantic_domain=domain,
            resource_types=resource_types,
            required_operations=operations,
        )
    if goal.intent in _PROTOCOL_INTENTS:
        operations = ("create",) if goal.intent in _MUTATION_INTENTS else ("read",)
        return ResourceRequirement(
            semantic_domain="knowledge" if "research" not in goal.intent else "external_research",
            resource_types=("protocol",),
            required_operations=operations,
        )
    return ResourceRequirement(
        semantic_domain="conversation",
        resource_types=("message",),
        required_operations=("read",),
    )


def _criteria_for_goal(goal: Goal, resource: ResourceRequirement) -> tuple[SuccessCriterion, ...]:
    evidence = EvidencePolicy(
        citation_required=_requires_evidence(goal),
        minimum_source_count=1 if _requires_evidence(goal) else None,
        contradiction_check=_requires_evidence(goal),
    )
    criteria = [SuccessCriterion(
        criterion_id=f"{goal.goal_id}:result",
        description=f"完成目标：{goal.input}",
        required=True,
        origin="user_explicit",
        mutability="user_revisable",
        evidence_policy=evidence,
        acceptance_contract="VerifiedAnswer" if _requires_evidence(goal) else "UserVisibleResult",
    )]
    if goal.intent in _MUTATION_INTENTS:
        criteria.append(SuccessCriterion(
            criterion_id=f"{goal.goal_id}:receipt",
            description="状态变更经过确认并产生可审计 receipt",
            required=True,
            origin="policy_required",
            mutability="immutable",
            acceptance_contract="MutationReceipt",
        ))
    return tuple(criteria)


def _requires_evidence(goal: Goal) -> bool:
    return goal.intent in {
        "ask", "external_codebase_qa", "external_workspace_qa", "external_project_ops",
        "gpt_researcher_a2a", "research_once",
    }


def _is_protocol_only(goal: Goal) -> bool:
    return goal.intent in _PROTOCOL_INTENTS and goal.intent != "research_once"


def _goal_kind(goal: Goal) -> str:
    if goal.intent in _PROTOCOL_INTENTS:
        return "protocol"
    if goal.intent == "gpt_researcher_a2a":
        return "delegate"
    if goal.intent in {"external_codebase_qa", "external_workspace_qa", "external_project_ops"}:
        return "investigation"
    if goal.intent == "ask":
        return "evidence_answer"
    return "direct_response"


def _output_contract(goal: Goal) -> str:
    if goal.intent in _MUTATION_INTENTS:
        return "MutationReceipt"
    if goal.intent in _PROTOCOL_INTENTS:
        return "ProtocolOutcome"
    if _requires_evidence(goal):
        return "VerifiedAnswer"
    return "Answer"


def _outcome_kind(goals: list[Goal]) -> str:
    if len(goals) > 1:
        return "compound"
    goal = goals[0]
    if goal.intent in _MUTATION_INTENTS:
        return "knowledge_change"
    if goal.intent in _PROTOCOL_INTENTS:
        return "operation"
    if goal.intent == "gpt_researcher_a2a" or goal.intent == "research_once":
        return "research"
    if goal.intent.startswith("external_"):
        return "investigation"
    return "answer"


__all__ = ["GoalInterpretation", "GoalInterpreter"]
