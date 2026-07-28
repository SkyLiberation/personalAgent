"""Application use cases and durable execution loop for Investigation Projects."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.investigation_project.admission import (
    EvidenceAdmission,
    ExecutionProposalAdmission,
    PlanAdmission,
    ProposalRejected,
)
from personal_agent.application.investigation_project.budget import (
    BudgetExceeded,
    CompletionGate,
    ProjectBudgetLedger,
)
from personal_agent.application.investigation_project.ports import (
    CapabilitySnapshotPort,
    DisclosureManifestPort,
    GeneratedArtifactWritePort,
    GeneratedContent,
    InvestigationPlannerPort,
    InvestigationProjectStorePort,
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
    EvidenceAdmissionCommittedData,
    EvidenceRef,
    ExecutionCommittedData,
    ExecutionProposalAcceptedData,
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
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope, SecurityScope


class ApplicationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateInvestigationProject(ApplicationModel):
    principal: AuthenticatedPrincipal
    security_scope: SecurityScope
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    requirements: tuple[UserRequirement, ...] = Field(min_length=1)
    budget: ProjectBudgetLimit = Field(default_factory=ProjectBudgetLimit)
    idempotency_key: str = Field(min_length=1)


class QueryInvestigationProject(ApplicationModel):
    principal: AuthenticatedPrincipal
    security_scope: SecurityScope
    project_id: str = Field(min_length=1)


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


class InvestigationProjectService:
    """Coordinates typed semantic ports while Project remains the state owner."""

    def __init__(
        self,
        *,
        store: InvestigationProjectStorePort,
        queue: WorkerQueuePort,
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
        if command.principal.tenant_id != command.security_scope.tenant_id:
            raise PermissionError("principal tenant does not match security scope")
        requirement_ids = [item.requirement_id for item in command.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("user requirement ids must be unique")
        definition = InvestigationProjectDefinition(
            principal=command.principal,
            security_scope=command.security_scope,
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
            project = self._process_once(project)
            if project.event_sequence == before or project.is_terminal or project.state == "paused":
                break
        if not project.is_terminal and project.state != "paused":
            self._enqueue(project, reason=f"continue:{project.event_sequence}")
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
            if artifact_ref.owner_scope != project.definition.security_scope:
                raise PermissionError("late artifact belongs to another scope")
        return self._append(project, LateResultQuarantinedData(
            agent_run_id=agent_run_id,
            artifact_refs=artifact_refs,
        )).to_view()

    def _process_once(self, project: InvestigationProject) -> InvestigationProject:
        if project.is_terminal or project.state == "paused":
            return project
        if project.state == "cancelling":
            return self._finish_cancellation(project)
        if project.state == "completing":
            return self._complete(project)
        if project.state == "planning":
            return self._plan(project, revision=None)
        if project.replan_request_digests:
            request = self._latest_replan_request(project)
            return self._plan(project, revision=request)
        ready = project.ready_subgoals()
        if ready:
            return self._propose_execution(project, ready[0])
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
            return self._complete(project)
        return self._derive_blocked_state(project)

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
    ) -> InvestigationProject:
        prepared: list[tuple[SubGoalExecutionProposal, ExecutionScope, ProjectUsage, object]] = []
        for proposal in proposals:
            operation = proposal.operation
            scope = self._execution_scope(
                project,
                proposal.logical_subgoal_id,
                proposal.subgoal_version,
                proposal.proposal_id,
            )
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
        for item, result in zip(prepared, results, strict=True):
            proposal, scope, reservation, _ = item
            if isinstance(result, Exception):
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
        return project

    def _plan(
        self,
        project: InvestigationProject,
        *,
        revision: ReplanRequest | None,
    ) -> InvestigationProject:
        if (
            revision is not None
            and project.accepted_plan is not None
            and project.accepted_plan.plan_version
            >= project.definition.budget.max_plan_revisions + 1
        ):
            return self._pause_with_wait(
                project,
                logical_subgoal_id="planning",
                subgoal_version=1,
                reason="budget_exhausted",
                authority="user",
                detail="maximum plan revisions reached",
            )
        inventory = self.capabilities.snapshot(project.definition.security_scope)
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
                    capabilities=inventory,
                    capability_revision=capability_revision,
                )
                if revision is not None
                else self.planner.propose_initial(
                    project.definition,
                    based_on_event_sequence=project.event_sequence,
                    capabilities=inventory,
                    capability_revision=capability_revision,
                )
            )
            accepted = self.plan_admission.accept(project, decision.value)
        except ProposalRejected as exc:
            project = self._release(project, reservation)
            request = ReplanRequest(
                trigger_kind="admission_feedback",
                trigger_ref=f"plan-admission:{project.event_sequence}",
                revision_scope=exc.feedback.revision_scope,
                trigger_digest=canonical_digest({
                    "reason": exc.feedback.reason,
                    "sequence": project.event_sequence,
                }),
            )
            if request.trigger_digest in project.replan_request_digests:
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
        inventory = self.capabilities.snapshot(project.definition.security_scope)
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
        try:
            decision = self.execution_proposer.propose(
                project,
                subgoal,
                execution_scope=scope,
                capabilities=inventory,
            )
            accepted = self.execution_admission.accept(
                project,
                subgoal,
                decision.value,
                execution_scope=scope,
                capabilities=inventory,
            )
        except ProposalRejected as exc:
            project = self._release(project, reservation)
            if exc.feedback.disposition == "capability_missing":
                return self._pause_if_globally_blocked(self._append(
                    project,
                    WaitingReasonSetData(waiting_reason=WaitingReason(
                        logical_subgoal_id=subgoal.logical_subgoal_id,
                        subgoal_version=subgoal.subgoal_version,
                        reason="capability_missing",
                        recovery_authority="provider",
                        detail=exc.feedback.reason,
                    )),
                ))
            request = ReplanRequest(
                trigger_kind="admission_feedback",
                trigger_ref=f"execution-admission:{project.event_sequence}",
                affected_logical_subgoal_ids=(subgoal.logical_subgoal_id,),
                revision_scope=(subgoal.logical_subgoal_id,),
                trigger_digest=canonical_digest({
                    "reason": exc.feedback.reason,
                    "subgoal": subgoal.logical_subgoal_id,
                }),
            )
            return self._append(project, ReplanRequestedData(request=request))
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
    ) -> InvestigationProject:
        operation = proposal.operation
        scope = self._execution_scope(
            project,
            proposal.logical_subgoal_id,
            proposal.subgoal_version,
            proposal.proposal_id,
        )
        if operation.kind == "user_input":
            return self._pause_if_globally_blocked(self._append(
                project,
                WaitingReasonSetData(waiting_reason=WaitingReason(
                    logical_subgoal_id=proposal.logical_subgoal_id,
                    subgoal_version=proposal.subgoal_version,
                    reason="user_input_required",
                    recovery_authority="user",
                    detail=operation.question,
                )),
            ))
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
            return self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="budget_exhausted",
                authority="user",
                detail=str(exc),
            )
        try:
            result = (
                self.tool_port.execute(proposal, execution_scope=scope)
                if operation.kind == "tool"
                else self._execute_synthesis(project, proposal, scope)
            )
        except Exception as exc:
            project = self._release(project, reservation)
            return self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="provider_unavailable",
                authority="provider",
                detail=f"{type(exc).__name__}: {exc}",
            )
        return self._commit_execution(project, proposal, result, reservation, scope)

    def _dispatch_agent(
        self,
        project: InvestigationProject,
        proposal: SubGoalExecutionProposal,
        operation: AgentExecutionOperation,
        scope: ExecutionScope,
    ) -> InvestigationProject:
        decision = self.delegation_policy.evaluate(proposal, execution_scope=scope)
        if not decision.allowed:
            return self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="capability_missing",
                authority="user",
                detail=decision.reason or "external delegation denied",
            )
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
                security_scope=project.definition.security_scope,
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
                security_scope=project.definition.security_scope,
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
            return self._pause_if_globally_blocked(project)
        if decision.requires_approval and command is not None and not command.approved:
            return project
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
            return self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="budget_exhausted",
                authority="user",
                detail=str(exc),
            )
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
        except ProjectAgentOutcomeUnknown as exc:
            project = self._release(project, reservation)
            return self._pause_with_wait(
                project,
                logical_subgoal_id=proposal.logical_subgoal_id,
                subgoal_version=proposal.subgoal_version,
                reason="outcome_unknown",
                authority="provider",
                detail=str(exc),
            )
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
            return self._append(project, *data)
        return self._commit_execution(project, proposal, result, reservation, scope)

    def _execute_synthesis(
        self,
        project: InvestigationProject,
        proposal: SubGoalExecutionProposal,
        scope: ExecutionScope,
    ) -> ExecutionResult:
        decision = self.synthesis_port.synthesize_subgoal(
            project,
            proposal,
            execution_scope=scope,
        )
        producer_key = canonical_digest({
            "project_id": project.definition.project_id,
            "plan_version": proposal.plan_version,
            "logical_subgoal_id": proposal.logical_subgoal_id,
            "subgoal_version": proposal.subgoal_version,
            "proposal_digest": proposal.proposal_digest,
        })
        artifact_ref = self.artifact_writer.write_generated(
            security_scope=project.definition.security_scope,
            execution_scope=scope,
            producer_key=producer_key,
            producer_ref=proposal.proposal_id,
            kind="subgoal_synthesis",
            content=decision.value.content,
            content_digest=decision.value.content_digest,
            source_artifact_refs=proposal.operation.input_artifact_refs,
            evidence_refs=decision.value.evidence_refs,
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
            admitted,
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
                    execution_scope=scope,
                )
                source_artifacts = tuple(
                    artifact
                    for outcome in project.outcomes.values()
                    for artifact in outcome.artifact_refs
                )
                artifact_ref = self.artifact_writer.write_generated(
                    security_scope=project.definition.security_scope,
                    execution_scope=scope,
                    producer_key=producer_key,
                    producer_ref=project.accepted_plan.plan_digest,
                    kind="final_report",
                    content=decision.value.content,
                    content_digest=decision.value.content_digest,
                    source_artifact_refs=source_artifacts,
                    evidence_refs=decision.value.evidence_refs,
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
                    security_scope=project.definition.security_scope,
                )
                generated = GeneratedContent(
                    content=stored.content,
                    content_digest=stored.content_digest,
                    evidence_refs=stored.evidence_refs,
                    limitations=stored.limitations,
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
        if not verified.value:
            project = self._append(
                project,
                StateChangedData(
                    from_state="completing",
                    to_state="active",
                    reason="final_verification_failed",
                ),
            )
            return project
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
        dispatchable = any(
            key not in project.execution_refs
            and key not in project.outcomes
            and key not in project.waiting_reasons
            for key in project.accepted_execution_proposals
        )
        if (
            project.waiting_reasons
            and not project.ready_subgoals()
            and not dispatchable
        ):
            return self._append(project, StateChangedData(
                from_state="active",
                to_state="paused",
                reason="all_remaining_required_work_waiting",
            ))
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
                security_scope=project.definition.security_scope,
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
            security_scope=project.definition.security_scope,
            principal_id=project.definition.principal.principal_id,
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
            security_scope=project.definition.security_scope,
            project_id=project.definition.project_id,
            expected_sequence=project.event_sequence,
            events=events,
        )

    def _require_project(
        self,
        query: QueryInvestigationProject,
    ) -> InvestigationProject:
        project = self.store.load(query.security_scope, query.project_id)
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

    def _enqueue(self, project: InvestigationProject, *, reason: str) -> None:
        self.queue.enqueue(
            queue="investigation",
            task_type="investigation_project",
            payload={
                "project_id": project.definition.project_id,
                "tenant_id": project.definition.security_scope.tenant_id,
                "workspace_id": project.definition.security_scope.workspace_id,
                "user_id": project.definition.principal.user_id,
                "reason": reason,
            },
            idempotency_key=(
                f"investigation:{project.definition.project_id}:{project.event_sequence}:{reason}"
            ),
            max_attempts=5,
        )

    @staticmethod
    def _latest_replan_request(project: InvestigationProject) -> ReplanRequest:
        # The store returns canonical events, but the aggregate only needs one
        # pending request at a time. The latest typed request owns revision scope.
        if project.pending_replan_requests:
            return project.pending_replan_requests[-1]
        raise RuntimeError("project has a pending replan digest but no typed request")


__all__ = [
    "ApproveInvestigationCommand",
    "CancelInvestigationProject",
    "CreateInvestigationProject",
    "InvestigationProjectService",
    "ProcessInvestigationProject",
    "PauseInvestigationProject",
    "ProjectExecutionPolicy",
    "QueryInvestigationProject",
    "ResumeInvestigationProject",
    "SteerInvestigationProject",
]
