"""Application use cases and durable execution loop for Investigation Projects."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import re
from typing import Callable
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.investigation_project.admission import (
    EvidenceAdmission,
    ExecutionProposalAdmission,
    PlanAdmission,
    ProposalRejected,
    execution_evidence_subgoal_keys,
    frozen_subgoal_keys,
    observed_url_locators,
)
from personal_agent.application.investigation_project.budget import (
    BudgetExceeded,
    CompletionGate,
    ProjectBudgetLedger,
)
from personal_agent.application.investigation_project.ports import (
    CapabilitySnapshotPort,
    DisclosureManifestPort,
    EvidenceMaterial,
    GeneratedArtifactWritePort,
    GeneratedContent,
    InvestigationPlannerPort,
    InvestigationProjectStorePort,
    ProjectAgentCapacityUnavailable,
    ProjectAgentExecutionFailed,
    ProjectAgentPort,
    ProjectAgentOutcomeUnknown,
    ProjectDelegationPolicyPort,
    ProjectSynthesisPort,
    ProjectToolPort,
    ProjectVerifierPort,
    ExecutionProposerPort,
    ExecutionResult,
)
from personal_agent.application.worker_queue import WorkerQueuePort
from personal_agent.domain.investigation_project import (
    AgentExecutionOperation,
    AgentRunLinkedData,
    ArtifactLinkedData,
    BudgetCategory,
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
    InvestigationProject,
    InvestigationProjectDefinition,
    LateResultQuarantinedData,
    OutcomeCommittedData,
    PlanAcceptedData,
    ProjectBudgetLimit,
    ProjectEvent,
    ProjectUsage,
    ProjectView,
    ReplanRequest,
    ReplanRequestedData,
    StateChangedData,
    SteeringCommand,
    SubGoalExecutionProposal,
    SubGoalDefinitionVersion,
    SubGoalOutcome,
    UserRequirement,
    UserRequirementVersion,
    UserRequirementsRevisedData,
    WaitingReason,
    WaitingReasonClearedData,
    WaitingReasonSetData,
    canonical_digest,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope, AuthenticatedPrincipal


class ApplicationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateInvestigationProject(ApplicationModel):
    principal: AuthenticatedPrincipal
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    requirements: tuple[UserRequirement, ...] = Field(min_length=1)
    budget: ProjectBudgetLimit = Field(default_factory=ProjectBudgetLimit)
    idempotency_key: str = Field(min_length=1)


class QueryInvestigationProject(ApplicationModel):
    principal: AuthenticatedPrincipal
    project_id: str = Field(min_length=1)


class GetInvestigationReport(QueryInvestigationProject):
    pass


class ProcessInvestigationProject(QueryInvestigationProject):
    max_cycles: int = Field(default=100, ge=1, le=1000)


class SteerInvestigationProject(QueryInvestigationProject):
    expected_plan_version: int = Field(ge=1)
    statement: str = Field(min_length=1)
    waived_requirement_ids: tuple[str, ...] = ()
    added_requirements: tuple[UserRequirement, ...] = ()
    idempotency_key: str = Field(min_length=1)


class ApproveInvestigationCommand(QueryInvestigationProject):
    command_id: str = Field(min_length=1)
    authorization_digest: str = Field(min_length=16)


class CancelInvestigationProject(QueryInvestigationProject):
    reason: str = Field(default="user_cancelled", min_length=1)


class PauseInvestigationProject(QueryInvestigationProject):
    pass


class ResumeInvestigationProject(QueryInvestigationProject):
    pass


@dataclass(frozen=True, slots=True)
class ProjectExecutionPolicy:
    planning_reservation_tokens: int = 2_000
    execution_proposal_reservation_tokens: int = 800
    verification_reservation_tokens: int = 800
    synthesis_reservation_tokens: int = 2_000
    external_delegation_reservation_tokens: int = 4_000
    external_wait_retry_seconds: int = 5


@dataclass(frozen=True, slots=True)
class _ProcessCycle:
    project: InvestigationProject
    yield_for_external: bool = False


class InvestigationProjectService:
    """Coordinates typed semantic ports while Project remains the state owner."""

    def __init__(
        self,
        *,
        store: InvestigationProjectStorePort,
        queue: WorkerQueuePort,
        clock: Callable[[], datetime],
        capabilities: CapabilitySnapshotPort,
        planner: InvestigationPlannerPort,
        execution_proposer: ExecutionProposerPort,
        tool_port: ProjectToolPort,
        agent_port: ProjectAgentPort,
        synthesis_port: ProjectSynthesisPort,
        verifier: ProjectVerifierPort,
        artifact_writer: GeneratedArtifactWritePort,
        delegation_policy: ProjectDelegationPolicyPort,
        disclosure_manifest: DisclosureManifestPort,
        execution_policy: ProjectExecutionPolicy | None = None,
    ) -> None:
        self.store = store
        self.queue = queue
        self.clock = clock
        self.capabilities = capabilities
        self.planner = planner
        self.execution_proposer = execution_proposer
        self.tool_port = tool_port
        self.agent_port = agent_port
        self.synthesis_port = synthesis_port
        self.verifier = verifier
        self.artifact_writer = artifact_writer
        self.delegation_policy = delegation_policy
        self.disclosure_manifest = disclosure_manifest
        self.execution_policy = execution_policy or ProjectExecutionPolicy()
        self.plan_admission = PlanAdmission()
        self.execution_admission = ExecutionProposalAdmission()
        self.evidence_admission = EvidenceAdmission()
        self.budget = ProjectBudgetLedger()
        self.completion_gate = CompletionGate()

    def create(self, command: CreateInvestigationProject) -> ProjectView:
        requirement_ids = [item.requirement_id for item in command.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("user requirement ids must be unique")
        definition = InvestigationProjectDefinition(
            principal=command.principal,
            title=command.title,
            goal=command.goal,
            user_requirements=UserRequirementVersion(
                version=1,
                requirements=command.requirements,
            ),
            budget=command.budget,
            create_idempotency_key=command.idempotency_key,
        )
        project = self.store.create(definition)
        self._authorize(project, command.principal)
        self._enqueue(project, reason="planning")
        return project.to_view()

    def get(self, query: QueryInvestigationProject) -> ProjectView:
        return self._require_project(query).to_view()

    def get_report(self, query: GetInvestigationReport):
        project = self._require_project(query)
        report = project.completion_report
        if project.state != "completed" or report is None:
            raise ValueError("investigation report is not available before completion")
        if project.final_artifact_ref != report.final_artifact_ref:
            raise RuntimeError("completion report final artifact binding is inconsistent")
        return self.artifact_writer.read_generated(
            report.final_artifact_ref,
            principal=query.principal,
            owner=query.principal,
        )

    def recover(self, *, limit: int = 100) -> int:
        """Re-enqueue non-terminal projects after a queue/process outage."""

        recovered = self.store.list_recoverable(limit=limit)
        for project in recovered:
            if project.state != "paused":
                self._enqueue(project, reason=f"recovery:{project.event_sequence}")
        return sum(project.state != "paused" for project in recovered)

    def process(self, command: ProcessInvestigationProject) -> ProjectView:
        project = self._require_project(command)
        for _ in range(command.max_cycles):
            before = project.event_sequence
            cycle = self._process_once(project)
            project = cycle.project
            if (
                cycle.yield_for_external
                or project.event_sequence == before
                or project.is_terminal
                or project.state == "paused"
            ):
                break
        if not project.is_terminal and project.state != "paused":
            self._enqueue(
                project,
                reason=f"continue:{project.event_sequence}",
                defer_seconds=(
                    self.execution_policy.external_wait_retry_seconds
                    if cycle.yield_for_external
                    else 0
                ),
            )
        return project.to_view()

    def steer(self, command: SteerInvestigationProject) -> ProjectView:
        project = self._require_project(command)
        if project.is_terminal:
            raise ValueError("terminal project cannot be steered")
        if project.accepted_plan is None:
            raise ValueError("project has no accepted plan")
        if project.accepted_plan.plan_version != command.expected_plan_version:
            raise ValueError("steering expected plan version is stale")
        previous = {
            item.requirement_id: item
            for item in project.user_requirements.requirements
        }
        unknown = set(command.waived_requirement_ids) - set(previous)
        if unknown:
            raise ValueError(f"cannot waive unknown requirements: {sorted(unknown)}")
        revised = tuple(
            item.model_copy(update={"status": "waived"})
            if item.requirement_id in command.waived_requirement_ids
            else item
            for item in previous.values()
        )
        added_ids = {item.requirement_id for item in command.added_requirements}
        if added_ids.intersection(previous):
            raise ValueError("added user requirements must use new ids")
        steering_digest = canonical_digest({
            "project_id": command.project_id,
            "expected_plan_version": command.expected_plan_version,
            "statement": command.statement,
            "waived_requirement_ids": command.waived_requirement_ids,
            "added_requirements": [
                item.model_dump(mode="json") for item in command.added_requirements
            ],
            "idempotency_key": command.idempotency_key,
        })
        if command.idempotency_key in project.steering_idempotency_keys:
            return project.to_view()
        steering = SteeringCommand(
            project_id=project.definition.project_id,
            expected_plan_version=command.expected_plan_version,
            statement=command.statement,
            waived_requirement_ids=command.waived_requirement_ids,
            added_requirements=command.added_requirements,
            idempotency_key=command.idempotency_key,
            steering_digest=steering_digest,
        )
        requirements = UserRequirementVersion(
            version=project.user_requirements.version + 1,
            requirements=(*revised, *command.added_requirements),
            steering_ref=steering.steering_id,
        )
        replan = ReplanRequest(
            trigger_kind="steering",
            trigger_ref=steering.steering_id,
            affected_requirement_ids=(
                *command.waived_requirement_ids,
                *(item.requirement_id for item in command.added_requirements),
            ),
            revision_scope=tuple(
                item.logical_subgoal_id
                for item in project.accepted_plan.proposal.subgoals
                if (
                    item.logical_subgoal_id,
                    item.subgoal_version,
                ) not in project.outcomes
            ),
            trigger_digest=steering_digest,
        )
        data = [
            UserRequirementsRevisedData(steering=steering, requirements=requirements),
            ReplanRequestedData(request=replan),
        ]
        if project.state == "paused":
            data.append(StateChangedData(
                from_state="paused",
                to_state="active",
                reason="user_steering",
            ))
        project = self._append(project, *data)
        self._enqueue(project, reason=f"steering:{steering.steering_id}")
        return project.to_view()

    def approve(self, command: ApproveInvestigationCommand) -> ProjectView:
        project = self._require_project(command)
        prepared = project.commands.get(command.command_id)
        if prepared is None:
            raise KeyError("unknown project command")
        if prepared.authorization_digest != command.authorization_digest:
            raise PermissionError("authorization digest mismatch")
        if prepared.approved:
            return project.to_view()
        data: list = [
            CommandApprovedData(
                command_id=prepared.command_id,
                authorization_digest=prepared.authorization_digest,
                approved_by_principal_id=command.principal.principal_id,
            ),
            WaitingReasonClearedData(
                logical_subgoal_id=prepared.logical_subgoal_id,
                subgoal_version=prepared.subgoal_version,
            ),
        ]
        if project.state == "paused":
            data.append(StateChangedData(
                from_state="paused",
                to_state="active",
                reason="command_approved",
            ))
        project = self._append(project, *data)
        self._enqueue(project, reason=f"approval:{prepared.command_id}")
        return project.to_view()

    def cancel(self, command: CancelInvestigationProject) -> ProjectView:
        project = self._require_project(command)
        if project.state == "cancelled":
            return project.to_view()
        if project.is_terminal:
            raise ValueError("completed or failed project cannot be cancelled")
        if project.state == "planning":
            return self._append(project, StateChangedData(
                from_state="planning",
                to_state="cancelled",
                reason=command.reason,
            )).to_view()
        project = self._append(project, StateChangedData(
            from_state=project.state,
            to_state="cancelling",
            reason=command.reason,
        ))
        return self._finish_cancellation(project).to_view()

    def _finish_cancellation(
        self,
        project: InvestigationProject,
    ) -> InvestigationProject:
        if project.state != "cancelling":
            return project
        late_artifacts: list[ResourceRef] = []
        for (logical_id, version), (agent_run_id, _) in project.agent_runs.items():
            scope = self._execution_scope(project, logical_id, version, agent_run_id)
            late_artifacts.extend(self.agent_port.cancel(agent_run_id, execution_scope=scope))
        data: list = []
        if late_artifacts:
            data.append(LateResultQuarantinedData(
                agent_run_id="cancel-reconcile",
                artifact_refs=tuple(late_artifacts),
            ))
        data.append(StateChangedData(
            from_state="cancelling",
            to_state="cancelled",
            reason="cancellation_completed",
        ))
        return self._append(project, *data)

    def pause(self, command: PauseInvestigationProject) -> ProjectView:
        project = self._require_project(command)
        if project.state == "paused":
            return project.to_view()
        if project.state != "active":
            raise ValueError("only an active project can be paused")
        return self._append(project, StateChangedData(
            from_state=project.state,
            to_state="paused",
            reason="user_paused",
        )).to_view()

    def resume(self, command: ResumeInvestigationProject) -> ProjectView:
        project = self._require_project(command)
        if project.state != "paused":
            raise ValueError("only a paused project can be resumed")
        if project.last_state_reason != "user_paused":
            raise ValueError(
                "system-paused project requires its typed repair, approval, "
                "budget, or capability condition to be resolved"
            )
        project = self._append(project, StateChangedData(
            from_state="paused",
            to_state="active",
            reason="user_resumed",
        ))
        self._enqueue(project, reason=f"resume:{project.event_sequence}")
        return project.to_view()

    def admit_late_result(
        self,
        query: QueryInvestigationProject,
        *,
        agent_run_id: str,
        artifact_refs: tuple[ResourceRef, ...],
    ) -> ProjectView:
        project = self._require_project(query)
        if not project.is_terminal:
            raise ValueError("late-result admission is only valid after terminal state")
        for artifact_ref in artifact_refs:
            if artifact_ref.owner != project.definition.principal:
                raise PermissionError("late artifact belongs to another scope")
        return self._append(project, LateResultQuarantinedData(
            agent_run_id=agent_run_id,
            artifact_refs=artifact_refs,
        )).to_view()

    def _process_once(self, project: InvestigationProject) -> _ProcessCycle:
        if project.is_terminal or project.state == "paused":
            return _ProcessCycle(project)
        if project.state == "cancelling":
            return _ProcessCycle(self._finish_cancellation(project))
        if project.state == "completing":
            return _ProcessCycle(self._complete(project))
        if project.state == "planning":
            return _ProcessCycle(self._plan(
                project,
                revision=(
                    self._latest_replan_request(project)
                    if project.replan_request_digests
                    else None
                ),
            ))
        if project.replan_request_digests:
            request = self._latest_replan_request(project)
            return _ProcessCycle(self._plan(project, revision=request))
        ready = project.ready_subgoals()
        if ready:
            return _ProcessCycle(self._propose_execution(project, ready[0]))
        pending = [
            proposal
            for key, proposal in project.accepted_execution_proposals.items()
            if key not in project.execution_refs and key not in project.outcomes
            and key not in project.waiting_reasons
        ]
        if pending:
            if len(pending) > 1 and self._parallel_batch_allowed(project, pending):
                return self._dispatch_parallel_batch(project, pending)
            return self._dispatch_proposal(project, pending[0])
        if self.completion_gate.required_coverage_complete(project):
            return _ProcessCycle(self._complete(project))
        return _ProcessCycle(self._derive_blocked_state(project))

    def _parallel_batch_allowed(
        self,
        project: InvestigationProject,
        proposals: list[SubGoalExecutionProposal],
    ) -> bool:
        for proposal in proposals:
            if proposal.operation.kind == "tool":
                continue
            if proposal.operation.kind != "agent":
                return False
            scope = self._execution_scope(
                project,
                proposal.logical_subgoal_id,
                proposal.subgoal_version,
                proposal.proposal_id,
            )
            decision = self.delegation_policy.evaluate(
                proposal,
                execution_scope=scope,
            )
            if not decision.allowed or decision.requires_approval:
                return False
        return True

    def _dispatch_parallel_batch(
        self,
        project: InvestigationProject,
        proposals: list[SubGoalExecutionProposal],
    ) -> _ProcessCycle:
        prepared: list[tuple[SubGoalExecutionProposal, ExecutionScope, ProjectUsage, object]] = []
        for proposal in proposals:
            operation = proposal.operation
            scope = self._execution_scope(
                project,
                proposal.logical_subgoal_id,
                proposal.subgoal_version,
                proposal.proposal_id,
            )
            try:
                if operation.kind == "tool":
                    reservation = self.budget.reserve(
                        project,
                        category="execution_proposal",
                        tool_calls=1,
                    )
                    policy_decision = None
                else:
                    policy_decision = self.delegation_policy.evaluate(
                        proposal,
                        execution_scope=scope,
                    )
                    reservation = self.budget.reserve(
                        project,
                        category="external_delegation",
                        tokens=min(
                            operation.token_budget,
                            self.execution_policy.external_delegation_reservation_tokens,
                        ),
                        cost=operation.cost_budget,
                        agent_calls=1,
                        reservation_id=f"agent:{proposal.proposal_digest}",
                    )
            except BudgetExceeded as exc:
                if prepared:
                    break
                return _ProcessCycle(self._pause_with_wait(
                    project,
                    logical_subgoal_id=proposal.logical_subgoal_id,
                    subgoal_version=proposal.subgoal_version,
                    reason="budget_exhausted",
                    authority="user",
                    detail=str(exc),
                ))
            project = self._append(project, BudgetReservedData(usage=reservation))
            prepared.append((proposal, scope, reservation, policy_decision))

        def execute(item):
            proposal, scope, _, policy_decision = item
            if proposal.operation.kind == "tool":
                return self.tool_port.execute(proposal, execution_scope=scope)
            submission_key = canonical_digest({
                "project_id": proposal.project_id,
                "plan_version": proposal.plan_version,
                "logical_subgoal_id": proposal.logical_subgoal_id,
                "subgoal_version": proposal.subgoal_version,
                "proposal_digest": proposal.proposal_digest,
            })
            return self.agent_port.submit_or_reconcile(
                proposal,
                execution_scope=scope,
                submission_key=submission_key,
                authorization_digest=policy_decision.authorization_digest,
            )

        with ThreadPoolExecutor(
            max_workers=len(prepared),
            thread_name_prefix="investigation-dispatch",
        ) as executor:
            futures = [executor.submit(execute, item) for item in prepared]
            results: list[ExecutionResult | Exception] = []
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(exc)
        yield_for_external = False
        for item, result in zip(prepared, results, strict=True):
            proposal, scope, reservation, _ = item
            if isinstance(result, Exception):
                if isinstance(result, ProjectAgentCapacityUnavailable):
                    project = self._release(project, reservation)
                    yield_for_external = True
                    continue
                if isinstance(result, ProjectAgentExecutionFailed):
                    project = self._record_agent_execution_failure(
                        project,
                        proposal,
                        reservation,
                        result,
                    )
                    continue
                project = self._release(project, reservation)
                reason = (
                    "outcome_unknown"
                    if isinstance(result, ProjectAgentOutcomeUnknown)
                    else "provider_unavailable"
                )
                project = self._append(
                    project,
                    WaitingReasonSetData(waiting_reason=WaitingReason(
                        logical_subgoal_id=proposal.logical_subgoal_id,
                        subgoal_version=proposal.subgoal_version,
                        reason=reason,
                        recovery_authority="provider",
                        detail=f"{type(result).__name__}: {result}",
                    )),
                )
                continue
            if result.pending:
                yield_for_external = True
                data: list = [BudgetReleasedData(
                    reservation_id=reservation.reservation_id,
                    category=reservation.category,
                )]
                if result.provider_task_ref:
                    data.append(AgentRunLinkedData(
                        logical_subgoal_id=proposal.logical_subgoal_id,
                        subgoal_version=proposal.subgoal_version,
                        agent_run_id=result.provider_task_ref,
                        submission_key=result.submission_key or "",
                    ))
                project = self._append(project, *data)
                continue
            project = self._commit_execution(
                project,
                proposal,
                result,
                reservation,
                scope,
            )
        return _ProcessCycle(project, yield_for_external=yield_for_external)

    def _plan(
        self,
        project: InvestigationProject,
        *,
        revision: ReplanRequest | None,
    ) -> InvestigationProject:
        if revision is not None and (
            (
                revision.trigger_kind == "verification_gap"
                and project.evidence_repair_replan_count
                > project.definition.budget.max_evidence_repair_revisions
            )
            or (
                revision.trigger_kind not in {
                    "verification_gap",
                    "admission_feedback",
                }
                and project.semantic_replan_count
                > project.definition.budget.max_plan_revisions
            )
        ):
            detail = (
                "maximum evidence repair revisions reached"
                if revision.trigger_kind == "verification_gap"
                else "maximum semantic plan revisions reached"
            )
            return self._pause_with_wait(
                project,
                logical_subgoal_id="planning",
                subgoal_version=1,
                reason="budget_exhausted",
                authority="user",
                detail=detail,
            )
        inventory = self.capabilities.snapshot(project.definition.principal)
        capability_revision = self.capabilities.revision(inventory)
        try:
            project, reservation = self._reserve_model(
                project,
                category="planning",
                tokens=self.execution_policy.planning_reservation_tokens,
            )
        except BudgetExceeded as exc:
            return self._pause_with_wait(
                project,
                logical_subgoal_id="planning",
                subgoal_version=1,
                reason="budget_exhausted",
                authority="user",
                detail=str(exc),
            )
        try:
            decision = (
                self.planner.propose_revision(
                    project,
                    revision,
                    evidence_material=self._materialize_evidence(
                        project,
                        tuple(project.admitted_evidence.values()),
                    ),
                    capabilities=inventory,
                    capability_revision=capability_revision,
                )
                if revision is not None and project.accepted_plan is not None
                else self.planner.propose_initial(
                    project.definition,
                    based_on_event_sequence=project.event_sequence,
                    repair_request=revision,
                    capabilities=inventory,
                    capability_revision=capability_revision,
                )
            )
            accepted = self.plan_admission.accept(
                project,
                decision.value,
                capabilities=inventory,
            )
        except ProposalRejected as exc:
            project = self._release(project, reservation)
            request = self._admission_feedback_request(
                stage="plan_admission",
                trigger_ref=f"plan-admission:{project.event_sequence}",
                feedback=exc.feedback,
            )
            if self._feedback_retry_limit_reached(project, request):
                return self._pause_with_wait(
                    project,
                    logical_subgoal_id="planning",
                    subgoal_version=1,
                    reason="verification_repair",
                    authority="user",
                    detail=exc.feedback.reason,
                )
            return self._append(project, ReplanRequestedData(request=request))
        except Exception as exc:
            project = self._release(project, reservation)
            return self._pause_with_wait(
                project,
                logical_subgoal_id="planning",
                subgoal_version=1,
                reason="provider_unavailable",
                authority="provider",
                detail=f"{type(exc).__name__}: {exc}",
            )
        data: list = [
            BudgetChargedData(usage=self._charged_usage(reservation, decision.usage)),
        ]
        if accepted is not None:
            data.append(PlanAcceptedData(plan=accepted))
            mapped_subgoal_ids = {
                logical_subgoal_id
                for mapping in accepted.proposal.requirement_mappings
                for logical_subgoal_id in mapping.logical_subgoal_ids
            }
            data.extend(
                WaitingReasonClearedData(
                    logical_subgoal_id=logical_subgoal_id,
                    subgoal_version=subgoal_version,
                )
                for (logical_subgoal_id, subgoal_version), waiting_reason
                in project.waiting_reasons.items()
                if (
                    waiting_reason.reason == "verification_repair"
                    and logical_subgoal_id not in mapped_subgoal_ids
                )
            )
        if project.state == "planning":
            data.append(StateChangedData(
                from_state="planning",
                to_state="active",
                reason="plan_accepted",
            ))
        return self._append(project, *data)

    def _propose_execution(
        self,
        project: InvestigationProject,
        subgoal,
    ) -> InvestigationProject:
        inventory = self.capabilities.snapshot(project.definition.principal)
        try:
            project, reservation = self._reserve_model(
                project,
                category="execution_proposal",
                tokens=self.execution_policy.execution_proposal_reservation_tokens,
            )
        except BudgetExceeded as exc:
            return self._pause_with_wait(
                project,
                logical_subgoal_id=subgoal.logical_subgoal_id,
                subgoal_version=subgoal.subgoal_version,
                reason="budget_exhausted",
                authority="user",
                detail=str(exc),
            )
        scope = self._execution_scope(
            project,
            subgoal.logical_subgoal_id,
            subgoal.subgoal_version,
            f"proposal:{project.event_sequence}",
        )
        evidence_material = self._materialize_evidence(
            project,
            self._execution_evidence_refs(project, subgoal),
        )
        try:
            decision = self.execution_proposer.propose(
                project,
                subgoal,
                evidence_material=evidence_material,
                execution_scope=scope,
                capabilities=inventory,
            )
            accepted = self.execution_admission.accept(
                project,
                subgoal,
                decision.value,
                execution_scope=scope,
                capabilities=inventory,
                observed_url_locators=observed_url_locators(
                    project,
                    evidence_material,
                ),
            )
        except ProposalRejected as exc:
            rejection = ExecutionProposalRejectedData(
                logical_subgoal_id=subgoal.logical_subgoal_id,
                subgoal_version=subgoal.subgoal_version,
                feedback=exc.feedback,
                rejection_digest=canonical_digest({
                    "logical_subgoal_id": subgoal.logical_subgoal_id,
                    "subgoal_version": subgoal.subgoal_version,
                    "feedback": exc.feedback.model_dump(mode="json"),
                }),
            )
            if exc.feedback.disposition == "capability_missing":
                project = self._release(project, reservation)
                return self._pause_if_globally_blocked(self._append(
                    project,
                    rejection,
                    WaitingReasonSetData(waiting_reason=WaitingReason(
                        logical_subgoal_id=subgoal.logical_subgoal_id,
                        subgoal_version=subgoal.subgoal_version,
                        reason="capability_missing",
                        recovery_authority="provider",
                        detail=exc.feedback.reason,
                    )),
                ))
            feedback_history = project.execution_proposal_feedback.get(
                (subgoal.logical_subgoal_id, subgoal.subgoal_version),
                (),
            )
            equivalent_feedback_count = sum(
                previous == exc.feedback for previous in feedback_history
            )
            repair_limit = project.definition.budget.same_feedback_revision_limit
            charged = BudgetChargedData(
                usage=self._charged_usage(reservation, decision.usage)
            )
            if equivalent_feedback_count >= repair_limit:
                project = self._append(project, charged, rejection)
                return self._pause_with_wait(
                    project,
                    logical_subgoal_id=subgoal.logical_subgoal_id,
                    subgoal_version=subgoal.subgoal_version,
                    reason="verification_repair",
                    authority="user",
                    detail=(
                        "execution proposal repair limit reached: "
                        f"{exc.feedback.reason}"
                    ),
                )
            return self._append(project, charged, rejection)
        except Exception as exc:
            project = self._release(project, reservation)
            return self._pause_with_wait(
                project,
                logical_subgoal_id=subgoal.logical_subgoal_id,
                subgoal_version=subgoal.subgoal_version,
                reason="provider_unavailable",
                authority="provider",
                detail=f"{type(exc).__name__}: {exc}",
            )
        return self._append(
            project,
            BudgetChargedData(usage=self._charged_usage(reservation, decision.usage)),
            ExecutionProposalAcceptedData(proposal=accepted),
        )

    def _dispatch_proposal(
        self,
        project: InvestigationProject,
        proposal: SubGoalExecutionProposal,
    ) -> _ProcessCycle:
        operation = proposal.operation
        scope = self._execution_scope(
            project,
            proposal.logical_subgoal_id,
            proposal.subgoal_version,
            proposal.proposal_id,
        )
        if operation.kind == "user_input":
            return _ProcessCycle(self._pause_if_globally_blocked(self._append(
                project,
                WaitingReasonSetData(waiting_reason=WaitingReason(
                    logical_subgoal_id=proposal.logical_subgoal_id,
                    subgoal_version=proposal.subgoal_version,
                    reason="user_input_required",
                    recovery_authority="user",
                    detail=operation.question,
                )),
            )))
        if operation.kind == "agent":
            return self._dispatch_agent(project, proposal, operation, scope)
        category: BudgetCategory = (
            "synthesis" if operation.kind == "synthesis" else "execution_proposal"
        )
        reserve_tokens = (
            self.execution_policy.synthesis_reservation_tokens
            if operation.kind == "synthesis"
            else 0
        )
        try:
            reservation = self.budget.reserve(
                project,
                category=category,
                tokens=reserve_tokens,
                tool_calls=1 if operation.kind == "tool" else 0,
            )
            project = self._append(project, BudgetReservedData(usage=reservation))
        except BudgetExceeded as exc:
            return _ProcessCycle(self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="budget_exhausted",
                authority="user",
                detail=str(exc),
            ))
        try:
            result = (
                self.tool_port.execute(proposal, execution_scope=scope)
                if operation.kind == "tool"
                else self._execute_synthesis(project, proposal, scope)
            )
        except Exception as exc:
            project = self._release(project, reservation)
            return _ProcessCycle(self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="provider_unavailable",
                authority="provider",
                detail=f"{type(exc).__name__}: {exc}",
            ))
        return _ProcessCycle(
            self._commit_execution(project, proposal, result, reservation, scope)
        )

    def _dispatch_agent(
        self,
        project: InvestigationProject,
        proposal: SubGoalExecutionProposal,
        operation: AgentExecutionOperation,
        scope: ExecutionScope,
    ) -> _ProcessCycle:
        decision = self.delegation_policy.evaluate(proposal, execution_scope=scope)
        if not decision.allowed:
            return _ProcessCycle(self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="capability_missing",
                authority="user",
                detail=decision.reason or "external delegation denied",
            ))
        command = next(
            (
                item
                for item in project.commands.values()
                if item.execution_proposal_digest == proposal.proposal_digest
            ),
            None,
        )
        if decision.requires_approval and command is None:
            manifest = self.disclosure_manifest.materialize(
                operation.context_artifact_refs,
                owner=project.definition.principal,
                execution_scope=scope,
            )
            command_payload = {
                "scope": scope.model_dump(mode="json"),
                "proposal_digest": proposal.proposal_digest,
                "target_agent_id": operation.agent_id,
                "bounded_sub_goal": operation.bounded_sub_goal,
                "artifact_refs": [
                    item.model_dump(mode="json")
                    for item in operation.context_artifact_refs
                ],
                "manifest_digest": manifest.content_digest,
                "authorization_digest": decision.authorization_digest,
            }
            command_digest = canonical_digest(command_payload)
            command = ExternalDelegationCommand(
                principal=project.definition.principal,
                execution_scope=scope,
                plan_version=proposal.plan_version,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                execution_proposal_digest=proposal.proposal_digest,
                target_agent_id=operation.agent_id,
                bounded_sub_goal=operation.bounded_sub_goal,
                context_artifact_refs=operation.context_artifact_refs,
                disclosure_manifest=manifest,
                token_budget=operation.token_budget,
                cost_budget=operation.cost_budget,
                time_budget_seconds=operation.time_budget_seconds,
                authorization_digest=decision.authorization_digest,
                execution_command_digest=command_digest,
            )
            project = self._append(
                project,
                CommandPreparedData(command=command),
                WaitingReasonSetData(waiting_reason=WaitingReason(
                    logical_subgoal_id=proposal.logical_subgoal_id,
                    subgoal_version=proposal.subgoal_version,
                    reason="approval_required",
                    recovery_authority="user",
                    detail=command.command_id,
                )),
            )
            return _ProcessCycle(self._pause_if_globally_blocked(project))
        if decision.requires_approval and command is not None and not command.approved:
            return _ProcessCycle(project)
        reservation_id = f"agent:{proposal.proposal_digest}"
        reservation = project.active_reservations.get(reservation_id)
        try:
            if reservation is None:
                reservation = self.budget.reserve(
                    project,
                    category="external_delegation",
                    tokens=min(
                        operation.token_budget,
                        self.execution_policy.external_delegation_reservation_tokens,
                    ),
                    cost=operation.cost_budget,
                    agent_calls=1,
                    reservation_id=reservation_id,
                )
                project = self._append(project, BudgetReservedData(usage=reservation))
        except BudgetExceeded as exc:
            return _ProcessCycle(self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="budget_exhausted",
                authority="user",
                detail=str(exc),
            ))
        submission_key = canonical_digest({
            "project_id": proposal.project_id,
            "plan_version": proposal.plan_version,
            "logical_subgoal_id": proposal.logical_subgoal_id,
            "subgoal_version": proposal.subgoal_version,
            "proposal_digest": proposal.proposal_digest,
        })
        try:
            result = self.agent_port.submit_or_reconcile(
                proposal,
                execution_scope=scope,
                submission_key=submission_key,
                authorization_digest=decision.authorization_digest,
                execution_command_digest=(
                    command.execution_command_digest if command is not None else None
                ),
            )
        except ProjectAgentCapacityUnavailable:
            return _ProcessCycle(
                self._release(project, reservation),
                yield_for_external=True,
            )
        except ProjectAgentExecutionFailed as exc:
            return _ProcessCycle(self._record_agent_execution_failure(
                project,
                proposal,
                reservation,
                exc,
            ))
        except ProjectAgentOutcomeUnknown as exc:
            project = self._release(project, reservation)
            return _ProcessCycle(self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="outcome_unknown",
                authority="provider",
                detail=str(exc),
            ))
        if result.pending:
            existing = project.agent_runs.get(
                (proposal.logical_subgoal_id, proposal.subgoal_version)
            )
            data: list = [BudgetReleasedData(
                reservation_id=reservation.reservation_id,
                category=reservation.category,
            )]
            if existing is None and result.provider_task_ref:
                data.append(AgentRunLinkedData(
                    logical_subgoal_id=proposal.logical_subgoal_id,
                    subgoal_version=proposal.subgoal_version,
                    agent_run_id=result.provider_task_ref,
                    submission_key=submission_key,
                ))
            return _ProcessCycle(
                self._append(project, *data),
                yield_for_external=True,
            )
        return _ProcessCycle(
            self._commit_execution(project, proposal, result, reservation, scope)
        )

    def _record_agent_execution_failure(
        self,
        project: InvestigationProject,
        proposal: SubGoalExecutionProposal,
        reservation: ProjectUsage,
        failure: ProjectAgentExecutionFailed,
    ) -> InvestigationProject:
        trigger_payload = {
            "agent_run_id": failure.agent_run_id,
            "status": failure.status,
            "detail": str(failure),
            "proposal_digest": proposal.proposal_digest,
        }
        request = ReplanRequest(
            trigger_kind="verification_gap",
            trigger_ref=failure.agent_run_id,
            affected_logical_subgoal_ids=(proposal.logical_subgoal_id,),
            revision_scope=(proposal.logical_subgoal_id,),
            trigger_digest=canonical_digest(trigger_payload),
        )
        return self._append(
            project,
            BudgetChargedData(usage=self._charged_usage(
                reservation,
                ProjectUsage(
                    category=reservation.category,
                    reservation_id=reservation.reservation_id,
                    agent_calls=1,
                ),
            )),
            ExecutionCommittedData(
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                execution_ref=failure.execution_ref,
            ),
            WaitingReasonSetData(waiting_reason=WaitingReason(
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="verification_repair",
                recovery_authority="planner",
                detail=(
                    f"child Agent run {failure.agent_run_id} ended with "
                    f"status={failure.status}: {failure}"
                ),
            )),
            ReplanRequestedData(request=request),
        )

    def _execute_synthesis(
        self,
        project: InvestigationProject,
        proposal: SubGoalExecutionProposal,
        scope: ExecutionScope,
    ) -> ExecutionResult:
        evidence_material = self._materialize_evidence(
            project,
            tuple(project.admitted_evidence.values()),
        )
        decision = self.synthesis_port.synthesize_subgoal(
            project,
            proposal,
            evidence_material=evidence_material,
            execution_scope=scope,
        )
        source_evidence = self._referenced_source_evidence(
            project,
            decision.value.evidence_refs,
        )
        producer_key = canonical_digest({
            "project_id": project.definition.project_id,
            "plan_version": proposal.plan_version,
            "logical_subgoal_id": proposal.logical_subgoal_id,
            "subgoal_version": proposal.subgoal_version,
            "proposal_digest": proposal.proposal_digest,
        })
        artifact_ref = self.artifact_writer.write_generated(
            owner=project.definition.principal,
            execution_scope=scope,
            producer_key=producer_key,
            producer_ref=proposal.proposal_id,
            kind="subgoal_synthesis",
            content=decision.value.content,
            content_digest=decision.value.content_digest,
            source_artifact_refs=self._evidence_artifact_refs(source_evidence),
            evidence_refs=decision.value.evidence_refs,
            limitations=decision.value.limitations,
        )
        execution_ref = ExecutionRef(
            execution_id=scope.execution_id,
            execution_kind="synthesis",
            owner_ref=artifact_ref.resource_id,
            execution_digest=producer_key,
        )
        evidence = EvidenceRef(
            evidence_id=f"ipev_{decision.value.content_digest[:20]}",
            execution_ref=execution_ref,
            artifact_ref=artifact_ref,
            source="synthesis",
            content_digest=decision.value.content_digest,
            summary=decision.value.content[:500],
        )
        return ExecutionResult(
            execution_ref=execution_ref,
            evidence=(evidence,),
            artifact_refs=(artifact_ref,),
            usage=decision.usage,
        )

    def _commit_execution(
        self,
        project: InvestigationProject,
        proposal: SubGoalExecutionProposal,
        result: ExecutionResult,
        reservation: ProjectUsage,
        scope: ExecutionScope,
    ) -> InvestigationProject:
        usage = result.usage or ProjectUsage(
            category=reservation.category,
            reservation_id=reservation.reservation_id,
            tokens=0,
            cost=0,
            tool_calls=reservation.tool_calls,
            agent_calls=reservation.agent_calls,
        )
        project = self._append(
            project,
            BudgetChargedData(usage=self._charged_usage(reservation, usage)),
            ExecutionCommittedData(
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                execution_ref=result.execution_ref,
            ),
            *(
                ArtifactLinkedData(
                    artifact_ref=artifact_ref,
                    disposition="active",
                    logical_subgoal_id=proposal.logical_subgoal_id,
                )
                for artifact_ref in result.artifact_refs
            ),
        )
        decisions = tuple(
            self.evidence_admission.decide(project, evidence)
            for evidence in result.evidence
        )
        project = self._append(
            project,
            *(EvidenceAdmissionCommittedData(decision=item) for item in decisions),
        )
        admitted = tuple(
            item.evidence_ref for item in decisions if item.admitted
        )
        if not admitted:
            return self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="verification_repair",
                authority="planner",
                detail="execution produced no admitted evidence",
            )
        subgoal = next(
            item
            for item in project.accepted_plan.proposal.subgoals
            if item.logical_subgoal_id == proposal.logical_subgoal_id
            and item.subgoal_version == proposal.subgoal_version
        )
        verification_evidence = admitted
        if proposal.operation.kind == "synthesis":
            generated_artifact = next(
                (
                    item.artifact_ref
                    for item in admitted
                    if item.artifact_ref is not None
                ),
                None,
            )
            if generated_artifact is None:
                return self._pause_with_wait(
                    project,
                    logical_subgoal_id=proposal.logical_subgoal_id,
                    subgoal_version=proposal.subgoal_version,
                    reason="verification_repair",
                    authority="runtime",
                    detail="synthesis produced no generated artifact",
                )
            generated = self.artifact_writer.read_generated(
                generated_artifact,
                principal=project.definition.principal,
                owner=project.definition.principal,
            )
            verification_evidence = (
                *admitted,
                *self._referenced_source_evidence(
                    project,
                    generated.evidence_refs,
                ),
            )
        try:
            evidence_material = self._materialize_evidence(
                project,
                verification_evidence,
            )
        except (ValueError, PermissionError, FileNotFoundError) as exc:
            return self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="verification_repair",
                authority="runtime",
                detail=f"evidence materialization failed: {exc}",
            )
        try:
            project, verification_reservation = self._reserve_model(
                project,
                category="semantic_verification",
                tokens=self.execution_policy.verification_reservation_tokens,
            )
        except BudgetExceeded as exc:
            return self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="budget_exhausted",
                authority="user",
                detail=str(exc),
            )
        verification = self.verifier.verify_subgoal(
            project,
            subgoal,
            verification_evidence,
            evidence_material=evidence_material,
            execution_scope=scope,
        )
        project = self._append(
            project,
            BudgetChargedData(
                usage=self._charged_usage(
                    verification_reservation,
                    verification.usage,
                )
            ),
        )
        if not verification.value.satisfied:
            request = ReplanRequest(
                trigger_kind="verification_gap",
                trigger_ref=verification.value.assessment_id,
                affected_logical_subgoal_ids=(proposal.logical_subgoal_id,),
                revision_scope=(proposal.logical_subgoal_id,),
                trigger_digest=verification.value.assessment_digest,
            )
            return self._append(
                project,
                WaitingReasonSetData(waiting_reason=WaitingReason(
                    logical_subgoal_id=proposal.logical_subgoal_id,
                    subgoal_version=proposal.subgoal_version,
                    reason="verification_repair",
                    recovery_authority="planner",
                    detail=verification.value.feedback,
                )),
                ReplanRequestedData(request=request),
            )
        outcome = SubGoalOutcome(
            logical_subgoal_id=proposal.logical_subgoal_id,
            subgoal_version=proposal.subgoal_version,
            execution_ref=result.execution_ref,
            assessment=verification.value,
            artifact_refs=result.artifact_refs,
        )
        data: list = [
            OutcomeCommittedData(outcome=outcome),
            WaitingReasonClearedData(
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
            ),
        ]
        assumption_ids = {
            item.assumption_id
            for item in project.accepted_plan.proposal.assumptions
        }
        for observation in verification.value.observations:
            contradicted = assumption_ids.intersection(
                observation.contradicted_assumption_ids
            )
            if contradicted:
                data.append(ReplanRequestedData(request=ReplanRequest(
                    trigger_kind="assumption_conflict",
                    trigger_ref=observation.observation_id,
                    affected_logical_subgoal_ids=(
                        observation.affected_logical_subgoal_ids
                    ),
                    revision_scope=tuple(
                        item.logical_subgoal_id
                        for item in project.accepted_plan.proposal.subgoals
                        if (
                            item.logical_subgoal_id,
                            item.subgoal_version,
                        ) not in project.outcomes
                        and item.logical_subgoal_id
                        != proposal.logical_subgoal_id
                    ),
                    trigger_digest=observation.observation_digest,
                )))
        return self._append(project, *data)

    def _materialize_evidence(
        self,
        project: InvestigationProject,
        evidence: tuple[EvidenceRef, ...],
    ) -> tuple[EvidenceMaterial, ...]:
        material: list[EvidenceMaterial] = []
        for item in evidence:
            content = item.summary
            if item.artifact_ref is not None:
                stored = self.artifact_writer.read_generated(
                    item.artifact_ref,
                    principal=project.definition.principal,
                    owner=project.definition.principal,
                )
                if stored.content_digest != item.content_digest:
                    raise ValueError("evidence artifact content digest mismatch")
                content = stored.content
            if item.source == "tool:web_search":
                content = _web_search_evidence_context(content)
            material.append(EvidenceMaterial(reference=item, content=content))
        return tuple(material)

    @staticmethod
    def _execution_evidence_refs(
        project: InvestigationProject,
        subgoal: SubGoalDefinitionVersion,
    ) -> tuple[EvidenceRef, ...]:
        scoped_keys = execution_evidence_subgoal_keys(project, subgoal)
        scoped_executions = {
            (
                execution_ref.execution_id,
                execution_ref.execution_digest,
            )
            for key, execution_ref in project.execution_refs.items()
            if key in scoped_keys
        }
        return tuple(
            evidence
            for evidence in project.admitted_evidence.values()
            if (
                evidence.execution_ref.execution_id,
                evidence.execution_ref.execution_digest,
            )
            in scoped_executions
        )

    def _referenced_source_evidence(
        self,
        project: InvestigationProject,
        evidence_refs: tuple[str, ...],
    ) -> tuple[EvidenceRef, ...]:
        if not evidence_refs:
            raise ValueError("generated content requires direct admitted evidence")
        unknown = set(evidence_refs) - set(project.admitted_evidence)
        if unknown:
            raise ValueError(
                f"generated content cites unknown evidence: {sorted(unknown)}"
            )
        selected = tuple(
            project.admitted_evidence[evidence_id]
            for evidence_id in dict.fromkeys(evidence_refs)
        )
        derived = tuple(
            item.evidence_id for item in selected if item.source == "synthesis"
        )
        if derived:
            raise ValueError(
                "generated content cannot use derived synthesis as source evidence: "
                f"{list(derived)}"
            )
        return selected

    @staticmethod
    def _evidence_artifact_refs(
        evidence: tuple[EvidenceRef, ...],
    ) -> tuple[ResourceRef, ...]:
        unique: dict[tuple[str, int], ResourceRef] = {}
        for item in evidence:
            if item.artifact_ref is not None:
                key = (item.artifact_ref.resource_id, item.artifact_ref.revision)
                unique[key] = item.artifact_ref
        return tuple(unique.values())

    def _complete(self, project: InvestigationProject) -> InvestigationProject:
        if project.accepted_plan is None:
            return project
        if project.state == "active":
            project = self._append(project, StateChangedData(
                from_state="active",
                to_state="completing",
                reason="required_coverage_satisfied",
            ))
        elif project.state != "completing":
            return project
        scope = self._execution_scope(
            project,
            "final-report",
            1,
            f"final:{project.accepted_plan.plan_digest}",
        )
        try:
            producer_key = canonical_digest({
                "project_id": project.definition.project_id,
                "plan_version": project.accepted_plan.plan_version,
                "kind": "final_report",
                "plan_digest": project.accepted_plan.plan_digest,
            })
            artifact_ref = project.final_artifact_ref
            if artifact_ref is None:
                project, reservation = self._reserve_model(
                    project,
                    category="synthesis",
                    tokens=self.execution_policy.synthesis_reservation_tokens,
                    reservation_id=(
                        f"final-synthesis:{project.accepted_plan.plan_digest}"
                    ),
                )
                decision = self.synthesis_port.synthesize_final(
                    project,
                    project.accepted_plan,
                    evidence_material=self._materialize_evidence(
                        project,
                        tuple(project.admitted_evidence.values()),
                    ),
                    execution_scope=scope,
                )
                source_evidence = self._referenced_source_evidence(
                    project,
                    decision.value.evidence_refs,
                )
                artifact_ref = self.artifact_writer.write_generated(
                    owner=project.definition.principal,
                    execution_scope=scope,
                    producer_key=producer_key,
                    producer_ref=project.accepted_plan.plan_digest,
                    kind="final_report",
                    content=decision.value.content,
                    content_digest=decision.value.content_digest,
                    source_artifact_refs=self._evidence_artifact_refs(
                        source_evidence
                    ),
                    evidence_refs=decision.value.evidence_refs,
                    limitations=decision.value.limitations,
                )
                project = self._append(
                    project,
                    BudgetChargedData(
                        usage=self._charged_usage(reservation, decision.usage)
                    ),
                    ArtifactLinkedData(
                        artifact_ref=artifact_ref,
                        disposition="final",
                        logical_subgoal_id=None,
                    ),
                )
                generated = decision.value
            else:
                stored = self.artifact_writer.read_generated(
                    artifact_ref,
                    principal=project.definition.principal,
                    owner=project.definition.principal,
                )
                generated = GeneratedContent(
                    content=stored.content,
                    content_digest=stored.content_digest,
                    evidence_refs=stored.evidence_refs,
                    limitations=stored.limitations,
                )
                source_evidence = self._referenced_source_evidence(
                    project,
                    generated.evidence_refs,
                )
            project, verification_reservation = self._reserve_model(
                project,
                category="semantic_verification",
                tokens=self.execution_policy.verification_reservation_tokens,
                reservation_id=(
                    f"final-verification:{project.accepted_plan.plan_digest}"
                ),
            )
            verified = self.verifier.verify_final(
                project,
                generated,
                evidence_material=self._materialize_evidence(
                    project,
                    source_evidence,
                ),
                execution_scope=scope,
            )
        except Exception as exc:
            if "verification_reservation" in locals():
                project = self._release(project, verification_reservation)
            elif "reservation" in locals() and reservation.reservation_id in project.active_reservations:
                project = self._release(project, reservation)
            return self._append(project, StateChangedData(
                from_state="completing",
                to_state="active",
                reason=f"finalization_retry:{type(exc).__name__}",
            ))
        project = self._append(
            project,
            BudgetChargedData(
                usage=self._charged_usage(
                    verification_reservation,
                    verified.usage,
                )
            ),
        )
        if not verified.value.passed:
            return self._append(
                project,
                WaitingReasonSetData(waiting_reason=WaitingReason(
                    logical_subgoal_id="final-report",
                    subgoal_version=project.accepted_plan.plan_version,
                    reason="verification_repair",
                    recovery_authority="user",
                    detail=(
                        verified.value.feedback
                        or "final report failed semantic verification"
                    ),
                )),
                StateChangedData(
                    from_state="completing",
                    to_state="active",
                    reason="final_verification_failed",
                ),
                StateChangedData(
                    from_state="active",
                    to_state="paused",
                    reason="final_verification_failed",
                ),
            )
        coverage = project.requirement_coverage()
        report = CompletionReport(
            project_id=project.definition.project_id,
            plan_version=project.accepted_plan.plan_version,
            requirement_assessment_refs=tuple(
                outcome.assessment.assessment_id
                for outcome in project.outcomes.values()
            ),
            final_artifact_ref=artifact_ref,
            coverage=coverage,
            completion_digest=canonical_digest({
                "project_id": project.definition.project_id,
                "plan_version": project.accepted_plan.plan_version,
                "coverage": coverage,
                "artifact_ref": artifact_ref.model_dump(mode="json"),
            }),
        )
        return self._append(
            project,
            CompletionCommittedData(report=report),
            StateChangedData(
                from_state="completing",
                to_state="completed",
                reason="completion_gate_passed",
            ),
        )

    def _derive_blocked_state(
        self,
        project: InvestigationProject,
    ) -> InvestigationProject:
        if project.state != "active":
            return project
        ready = project.ready_subgoals()
        dispatchable = any(
            key not in project.execution_refs
            and key not in project.outcomes
            and key not in project.waiting_reasons
            for key in project.accepted_execution_proposals
        )
        if (
            project.waiting_reasons
            and not ready
            and not dispatchable
        ):
            return self._append(project, StateChangedData(
                from_state="active",
                to_state="paused",
                reason="all_remaining_required_work_waiting",
            ))
        if (
            project.accepted_plan is not None
            and not ready
            and not dispatchable
        ):
            coverage = project.requirement_coverage()
            unmet_requirement_ids = tuple(sorted(
                requirement_id
                for requirement_id, status in coverage.items()
                if status == "unmet"
            ))
            if unmet_requirement_ids:
                mappings = {
                    item.requirement_id: item.logical_subgoal_ids
                    for item in project.accepted_plan.proposal.requirement_mappings
                }
                affected_logical_subgoal_ids = tuple(sorted({
                    logical_subgoal_id
                    for requirement_id in unmet_requirement_ids
                    for logical_subgoal_id in mappings.get(requirement_id, ())
                }))
                frozen_keys = frozen_subgoal_keys(project)
                revision_scope = tuple(
                    item.logical_subgoal_id
                    for item in project.accepted_plan.proposal.subgoals
                    if (
                        item.logical_subgoal_id,
                        item.subgoal_version,
                    ) not in frozen_keys
                )
                trigger_payload = {
                    "plan_digest": project.accepted_plan.plan_digest,
                    "coverage": coverage,
                    "affected_logical_subgoal_ids": affected_logical_subgoal_ids,
                    "revision_scope": revision_scope,
                }
                return self._append(
                    project,
                    ReplanRequestedData(request=ReplanRequest(
                        trigger_kind="coverage_deadlock",
                        trigger_ref=project.accepted_plan.plan_digest,
                        affected_requirement_ids=unmet_requirement_ids,
                        affected_logical_subgoal_ids=affected_logical_subgoal_ids,
                        revision_scope=revision_scope,
                        trigger_digest=canonical_digest(trigger_payload),
                    )),
                )
        return project

    def _pause_if_globally_blocked(
        self,
        project: InvestigationProject,
    ) -> InvestigationProject:
        return self._derive_blocked_state(project)

    def _pause_with_wait(
        self,
        project: InvestigationProject,
        *,
        logical_subgoal_id: str,
        subgoal_version: int,
        reason,
        authority,
        detail: str,
    ) -> InvestigationProject:
        if reason == "budget_exhausted" and project.accepted_plan is not None:
            coverage = project.requirement_coverage()
            report_text = (
                "Investigation Project paused because its accepted budget is exhausted.\n"
                f"Coverage: {coverage}\n"
                f"Reason: {detail}"
            )
            scope = self._execution_scope(
                project,
                "partial-coverage",
                1,
                f"partial:{project.event_sequence}",
            )
            artifact_ref = self.artifact_writer.write_generated(
                owner=project.definition.principal,
                execution_scope=scope,
                producer_key=canonical_digest({
                    "project_id": project.definition.project_id,
                    "plan_version": project.accepted_plan.plan_version,
                    "kind": "partial_coverage",
                    "coverage": coverage,
                }),
                producer_ref=project.accepted_plan.plan_digest,
                kind="partial_coverage",
                content=report_text,
                content_digest=canonical_digest({"content": report_text}),
                source_artifact_refs=tuple(
                    artifact
                    for outcome in project.outcomes.values()
                    for artifact in outcome.artifact_refs
                ),
                evidence_refs=tuple(project.admitted_evidence),
            )
            project = self._append(project, ArtifactLinkedData(
                artifact_ref=artifact_ref,
                disposition="partial",
                logical_subgoal_id=None,
            ))
        data: list = [
            WaitingReasonSetData(waiting_reason=WaitingReason(
                logical_subgoal_id=logical_subgoal_id,
                subgoal_version=subgoal_version,
                reason=reason,
                recovery_authority=authority,
                detail=detail,
            ))
        ]
        if project.state in {"planning", "active"}:
            data.append(StateChangedData(
                from_state=project.state,
                to_state="paused",
                reason=reason,
            ))
        return self._append(project, *data)

    def _reserve_model(
        self,
        project: InvestigationProject,
        *,
        category: BudgetCategory,
        tokens: int,
        reservation_id: str | None = None,
    ) -> tuple[InvestigationProject, ProjectUsage]:
        if reservation_id is not None:
            existing = project.active_reservations.get(reservation_id)
            if existing is not None:
                return project, existing
        reservation = self.budget.reserve(
            project,
            category=category,
            tokens=tokens,
            reservation_id=reservation_id,
        )
        return (
            self._append(project, BudgetReservedData(usage=reservation)),
            reservation,
        )

    def _release(
        self,
        project: InvestigationProject,
        reservation: ProjectUsage,
    ) -> InvestigationProject:
        return self._append(project, BudgetReleasedData(
            reservation_id=reservation.reservation_id,
            category=reservation.category,
        ))

    @staticmethod
    def _charged_usage(
        reservation: ProjectUsage,
        actual: ProjectUsage,
    ) -> ProjectUsage:
        return ProjectUsage(
            category=reservation.category,
            reservation_id=reservation.reservation_id,
            tokens=actual.tokens,
            cost=actual.cost,
            tool_calls=max(reservation.tool_calls, actual.tool_calls),
            agent_calls=max(reservation.agent_calls, actual.agent_calls),
            estimated=actual.estimated,
        )

    def _execution_scope(
        self,
        project: InvestigationProject,
        logical_subgoal_id: str,
        subgoal_version: int,
        execution_id: str,
    ) -> ExecutionScope:
        return ExecutionScope(
            principal=project.definition.principal,
            execution_id=execution_id,
            project_id=project.definition.project_id,
            plan_version=(
                project.accepted_plan.plan_version
                if project.accepted_plan is not None
                else 1
            ),
            logical_subgoal_id=logical_subgoal_id,
            subgoal_version=subgoal_version,
        )

    def _append(self, project: InvestigationProject, *data) -> InvestigationProject:
        events = tuple(
            ProjectEvent(
                project_id=project.definition.project_id,
                sequence=project.event_sequence + index,
                data=item,
            )
            for index, item in enumerate(data, start=1)
        )
        return self.store.append(
            owner=project.definition.principal,
            project_id=project.definition.project_id,
            expected_sequence=project.event_sequence,
            events=events,
        )

    def _require_project(
        self,
        query: QueryInvestigationProject,
    ) -> InvestigationProject:
        project = self.store.load(query.principal, query.project_id)
        if project is None:
            raise KeyError("investigation project not found")
        self._authorize(project, query.principal)
        return project

    @staticmethod
    def _authorize(
        project: InvestigationProject,
        principal: AuthenticatedPrincipal,
    ) -> None:
        if project.definition.principal != principal:
            raise PermissionError("investigation project belongs to another principal")

    def _enqueue(
        self,
        project: InvestigationProject,
        *,
        reason: str,
        defer_seconds: int = 0,
    ) -> None:
        self.queue.enqueue(
            queue="investigation",
            task_type="investigation_project",
            payload={
                "project_id": project.definition.project_id,
                "tenant_id": project.definition.principal.tenant_id,
                "user_id": project.definition.principal.user_id,
                "reason": reason,
            },
            idempotency_key=(
                f"investigation:{project.definition.project_id}:{project.event_sequence}:{reason}"
            ),
            max_attempts=5,
            due_at=(
                self.clock() + timedelta(seconds=defer_seconds)
                if defer_seconds > 0
                else None
            ),
        )

    @staticmethod
    def _latest_replan_request(project: InvestigationProject) -> ReplanRequest:
        # The store returns canonical events, but the aggregate only needs one
        # pending request at a time. The latest typed request owns revision scope.
        if project.pending_replan_requests:
            return project.pending_replan_requests[-1]
        raise RuntimeError("project has a pending replan digest but no typed request")

    @staticmethod
    def _admission_feedback_request(
        *,
        stage: str,
        trigger_ref: str,
        feedback: DecisionFeedback,
        affected_logical_subgoal_ids: tuple[str, ...] = (),
        revision_scope: tuple[str, ...] | None = None,
    ) -> ReplanRequest:
        effective_revision_scope = (
            feedback.revision_scope
            if revision_scope is None
            else revision_scope
        )
        return ReplanRequest(
            trigger_kind="admission_feedback",
            trigger_ref=trigger_ref,
            affected_logical_subgoal_ids=affected_logical_subgoal_ids,
            revision_scope=effective_revision_scope,
            decision_feedback=feedback,
            trigger_digest=canonical_digest({
                "stage": stage,
                "feedback": feedback.model_dump(mode="json"),
                "affected_logical_subgoal_ids": affected_logical_subgoal_ids,
                "revision_scope": effective_revision_scope,
            }),
        )

    @staticmethod
    def _feedback_retry_limit_reached(
        project: InvestigationProject,
        request: ReplanRequest,
    ) -> bool:
        equivalent_feedback_count = sum(
            existing.trigger_kind == "admission_feedback"
            and existing.trigger_digest == request.trigger_digest
            for existing in project.pending_replan_requests
        )
        return (
            equivalent_feedback_count
            >= project.definition.budget.same_feedback_revision_limit
        )


_ISO_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_ENGLISH_DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4}\b",
    re.IGNORECASE,
)


def _web_search_evidence_context(content: str) -> str:
    """Build a compact, lossless-for-verification view of Web search results."""
    try:
        payload = json.loads(content)
        results = payload["data"]["results"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return content
    if not isinstance(results, list):
        return content
    compact_results = []
    for result in results:
        if not isinstance(result, dict):
            continue
        title = str(result.get("title") or "")
        url = str(result.get("url") or "")
        snippet = str(result.get("snippet") or "")
        searchable = "\n".join((title, snippet))
        explicit_dates = tuple(dict.fromkeys((
            *_ISO_DATE_PATTERN.findall(searchable),
            *_ENGLISH_DATE_PATTERN.findall(searchable),
        )))
        compact_results.append({
            "title": title,
            "url": url,
            "host": (urlparse(url).hostname or "").lower(),
            "provider_published_at": result.get("published_at"),
            "explicit_dates_in_title_or_snippet": explicit_dates,
            "snippet": snippet,
        })
    return json.dumps(
        {"data": {"results": compact_results}, "tool": "web_search"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "ApproveInvestigationCommand",
    "CancelInvestigationProject",
    "CreateInvestigationProject",
    "GetInvestigationReport",
    "InvestigationProjectService",
    "ProcessInvestigationProject",
    "PauseInvestigationProject",
    "ProjectExecutionPolicy",
    "QueryInvestigationProject",
    "ResumeInvestigationProject",
    "SteerInvestigationProject",
]
