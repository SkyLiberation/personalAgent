"""Event-rehydrated Investigation Project aggregate and deterministic rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from personal_agent.domain.investigation_project.models import (
    AcceptedPlanVersion,
    AgentRunLinkedData,
    ArtifactLinkedData,
    BudgetChargedData,
    BudgetReleasedData,
    BudgetReservedData,
    CommandApprovedData,
    CommandPreparedData,
    CompletionCommittedData,
    CompletionReport,
    DecisionFeedback,
    EvidenceAdmissionCommittedData,
    EvidenceRef,
    ExecutionCommittedData,
    ExecutionProposalAcceptedData,
    ExecutionProposalRejectedData,
    ExecutionRef,
    ExternalDelegationCommand,
    InvestigationProjectDefinition,
    LateResultQuarantinedData,
    OutcomeCommittedData,
    PlanAcceptedData,
    ProjectEvent,
    ProjectState,
    ProjectUsage,
    ProjectView,
    ReplanRequest,
    ReplanRequestedData,
    StateChangedData,
    SubGoalExecutionProposal,
    SubGoalOutcome,
    UserRequirementVersion,
    UserRequirementsRevisedData,
    WaitingReason,
    WaitingReasonClearedData,
    WaitingReasonSetData,
)
from personal_agent.kernel.contracts.resource import ResourceRef


TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_ALLOWED_TRANSITIONS: dict[ProjectState, frozenset[ProjectState]] = {
    "planning": frozenset({"active", "paused", "failed", "cancelled"}),
    "active": frozenset({"paused", "cancelling", "completing", "failed"}),
    "paused": frozenset({"active", "cancelling", "failed"}),
    "cancelling": frozenset({"cancelled"}),
    "completing": frozenset({"completed", "active", "failed"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


@dataclass(slots=True)
class InvestigationProject:
    definition: InvestigationProjectDefinition
    state: ProjectState = "planning"
    last_state_reason: str = "project_created"
    event_sequence: int = 0
    user_requirements: UserRequirementVersion | None = None
    accepted_plan: AcceptedPlanVersion | None = None
    accepted_execution_proposals: dict[tuple[str, int], SubGoalExecutionProposal] = field(
        default_factory=dict
    )
    execution_proposal_feedback: dict[
        tuple[str, int],
        list[DecisionFeedback],
    ] = field(default_factory=dict)
    execution_refs: dict[tuple[str, int], ExecutionRef] = field(default_factory=dict)
    admitted_evidence: dict[str, EvidenceRef] = field(default_factory=dict)
    outcomes: dict[tuple[str, int], SubGoalOutcome] = field(default_factory=dict)
    waiting_reasons: dict[tuple[str, int], WaitingReason] = field(default_factory=dict)
    commands: dict[str, ExternalDelegationCommand] = field(default_factory=dict)
    agent_runs: dict[tuple[str, int], tuple[str, str]] = field(default_factory=dict)
    artifact_refs: dict[tuple[str, int], ResourceRef] = field(default_factory=dict)
    final_artifact_ref: ResourceRef | None = None
    completion_report: CompletionReport | None = None
    plan_revision_count: int = 0
    semantic_replan_count: int = 0
    evidence_repair_replan_count: int = 0
    usages: list[ProjectUsage] = field(default_factory=list)
    active_reservations: dict[str, ProjectUsage] = field(default_factory=dict)
    replan_request_digests: set[str] = field(default_factory=set)
    pending_replan_requests: list[ReplanRequest] = field(default_factory=list)
    steering_idempotency_keys: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.user_requirements is None:
            self.user_requirements = self.definition.user_requirements

    @classmethod
    def rehydrate(
        cls,
        definition: InvestigationProjectDefinition,
        events: Iterable[ProjectEvent],
    ) -> "InvestigationProject":
        project = cls(definition=definition)
        for event in events:
            project.apply(event)
        return project

    def apply(self, event: ProjectEvent) -> None:
        if event.project_id != self.definition.project_id:
            raise ValueError("project event belongs to a different project")
        if event.sequence != self.event_sequence + 1:
            raise ValueError(
                f"project event sequence mismatch: expected {self.event_sequence + 1}, "
                f"got {event.sequence}"
            )
        data = event.data
        if isinstance(data, PlanAcceptedData):
            self.accepted_plan = data.plan
            self.plan_revision_count = max(self.plan_revision_count, data.plan.plan_version)
            self.replan_request_digests.clear()
            self.pending_replan_requests.clear()
        elif isinstance(data, StateChangedData):
            if data.from_state != self.state:
                raise ValueError("state transition starts from stale project state")
            if data.to_state not in _ALLOWED_TRANSITIONS[self.state]:
                raise ValueError(f"illegal project transition {self.state}->{data.to_state}")
            self.state = data.to_state
            self.last_state_reason = data.reason
        elif isinstance(data, ExecutionProposalAcceptedData):
            key = (data.proposal.logical_subgoal_id, data.proposal.subgoal_version)
            self.accepted_execution_proposals[key] = data.proposal
            self.execution_proposal_feedback.pop(key, None)
        elif isinstance(data, ExecutionProposalRejectedData):
            key = (data.logical_subgoal_id, data.subgoal_version)
            self.execution_proposal_feedback.setdefault(key, []).append(data.feedback)
        elif isinstance(data, BudgetReservedData):
            if data.usage.reservation_id in self.active_reservations:
                raise ValueError("budget reservation already exists")
            self.active_reservations[data.usage.reservation_id] = data.usage
        elif isinstance(data, BudgetChargedData):
            self.active_reservations.pop(data.usage.reservation_id, None)
            self.usages.append(data.usage)
        elif isinstance(data, BudgetReleasedData):
            self.active_reservations.pop(data.reservation_id, None)
        elif isinstance(data, ExecutionCommittedData):
            self.execution_refs[(data.logical_subgoal_id, data.subgoal_version)] = data.execution_ref
        elif isinstance(data, EvidenceAdmissionCommittedData):
            if data.decision.admitted:
                evidence = data.decision.evidence_ref
                self.admitted_evidence[evidence.evidence_id] = evidence
        elif isinstance(data, OutcomeCommittedData):
            outcome = data.outcome
            self.outcomes[(outcome.logical_subgoal_id, outcome.subgoal_version)] = outcome
        elif isinstance(data, WaitingReasonSetData):
            reason = data.waiting_reason
            self.waiting_reasons[(reason.logical_subgoal_id, reason.subgoal_version)] = reason
        elif isinstance(data, WaitingReasonClearedData):
            self.waiting_reasons.pop(
                (data.logical_subgoal_id, data.subgoal_version),
                None,
            )
        elif isinstance(data, ReplanRequestedData):
            self.replan_request_digests.add(data.request.trigger_digest)
            self.pending_replan_requests.append(data.request)
            if data.request.trigger_kind == "verification_gap":
                self.evidence_repair_replan_count += 1
            elif data.request.trigger_kind not in {"admission_feedback"}:
                self.semantic_replan_count += 1
        elif isinstance(data, UserRequirementsRevisedData):
            if data.requirements.version != self.user_requirements.version + 1:
                raise ValueError("user requirement revision must be monotonic")
            self.user_requirements = data.requirements
            self.steering_idempotency_keys.add(data.steering.idempotency_key)
        elif isinstance(data, CommandPreparedData):
            self.commands[data.command.command_id] = data.command
        elif isinstance(data, CommandApprovedData):
            existing = self.commands.get(data.command_id)
            if existing is None:
                raise ValueError("approval references unknown command")
            if existing.authorization_digest != data.authorization_digest:
                raise ValueError("approval authorization digest mismatch")
            self.commands[data.command_id] = existing.model_copy(update={"approved": True})
        elif isinstance(data, AgentRunLinkedData):
            self.agent_runs[(data.logical_subgoal_id, data.subgoal_version)] = (
                data.agent_run_id,
                data.submission_key,
            )
        elif isinstance(data, ArtifactLinkedData):
            self.artifact_refs[
                (data.artifact_ref.resource_id, data.artifact_ref.revision)
            ] = data.artifact_ref
            if data.disposition == "final":
                self.final_artifact_ref = data.artifact_ref
        elif isinstance(data, CompletionCommittedData):
            self.completion_report = data.report
        elif isinstance(data, LateResultQuarantinedData):
            for artifact_ref in data.artifact_refs:
                self.artifact_refs[
                    (artifact_ref.resource_id, artifact_ref.revision)
                ] = artifact_ref
        self.event_sequence = event.sequence

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def active_plan_subgoals(self):
        return self.accepted_plan.proposal.subgoals if self.accepted_plan else ()

    def ready_subgoals(self):
        if self.state != "active" or self.accepted_plan is None:
            return ()
        active_ids = {
            item.logical_subgoal_id: item for item in self.accepted_plan.proposal.subgoals
        }
        completed_ids = {
            logical_id
            for logical_id, version in self.outcomes
            if (
                logical_id in active_ids
                and active_ids[logical_id].subgoal_version == version
                and self.outcomes[(logical_id, version)].assessment.satisfied
            )
        }
        ready = []
        for subgoal in self.accepted_plan.proposal.subgoals:
            key = (subgoal.logical_subgoal_id, subgoal.subgoal_version)
            if (
                key in self.outcomes
                or key in self.execution_refs
                or key in self.waiting_reasons
                or key in self.accepted_execution_proposals
            ):
                continue
            if all(dependency in completed_ids for dependency in subgoal.depends_on):
                ready.append(subgoal)
        return tuple(ready)

    def requirement_coverage(self) -> dict[str, str]:
        coverage: dict[str, str] = {}
        requirements = {
            item.requirement_id: item
            for item in self.user_requirements.requirements
        }
        if self.accepted_plan is not None:
            requirements.update({
                item.requirement_id: item
                for item in self.accepted_plan.proposal.derived_requirements
                if item.completion_relevance == "required"
            })
            mappings = {
                item.requirement_id: item.logical_subgoal_ids
                for item in self.accepted_plan.proposal.requirement_mappings
            }
        else:
            mappings = {}
        for requirement_id, requirement in requirements.items():
            if getattr(requirement, "status", "active") == "waived":
                coverage[requirement_id] = "waived"
                continue
            linked_ids = mappings.get(requirement_id, ())
            if linked_ids and all(
                any(
                    outcome.logical_subgoal_id == linked_id
                    and outcome.assessment.satisfied
                    for outcome in self.outcomes.values()
                )
                for linked_id in linked_ids
            ):
                coverage[requirement_id] = "verified"
            else:
                coverage[requirement_id] = "unmet"
        return coverage

    def charged_tokens(self, category: str | None = None) -> int:
        return sum(
            item.tokens
            for item in self.usages
            if category is None or item.category == category
        )

    def reserved_tokens(self, category: str | None = None) -> int:
        return sum(
            item.tokens
            for item in self.active_reservations.values()
            if category is None or item.category == category
        )

    def to_view(self) -> ProjectView:
        return ProjectView(
            definition=self.definition,
            state=self.state,
            last_state_reason=self.last_state_reason,
            event_sequence=self.event_sequence,
            user_requirements=self.user_requirements,
            accepted_plan=self.accepted_plan,
            accepted_execution_proposals=tuple(self.accepted_execution_proposals.values()),
            execution_refs=tuple(self.execution_refs.values()),
            admitted_evidence=tuple(self.admitted_evidence.values()),
            outcomes=tuple(self.outcomes.values()),
            waiting_reasons=tuple(self.waiting_reasons.values()),
            commands=tuple(self.commands.values()),
            artifact_refs=tuple(self.artifact_refs.values()),
            completion_report=self.completion_report,
            plan_revision_count=self.plan_revision_count,
            usage=tuple(self.usages),
        )


__all__ = ["InvestigationProject", "TERMINAL_STATES"]
