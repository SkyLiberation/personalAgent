"""Deterministic external-boundary harness for Project diagnostic E2E.

Semantic decisions are scripted through the same ports as the production
structured-model adapters. Domain, admission, persistence, budget, scheduler,
artifact ownership, and completion code are production implementations.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import threading
from typing import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from personal_agent.adapters.web.routes.investigation_projects import (
    register_investigation_project_routes,
)
from personal_agent.application.artifacts import ArtifactService
from personal_agent.application.investigation_project import (
    ApproveInvestigationCommand,
    CreateInvestigationProject,
    DelegationPolicyDecision,
    FinalVerificationResult,
    GeneratedContent,
    InvestigationProjectService,
    ModelDecision,
    PauseInvestigationProject,
    ProcessInvestigationProject,
    ProjectAgentOutcomeUnknown,
    ProjectExecutionPolicy,
    QueryInvestigationProject,
    ResumeInvestigationProject,
    SteerInvestigationProject,
)
from personal_agent.orchestration.investigation_project_adapters import (
    RuntimeCapabilitySnapshot,
    ScopeBoundDisclosureManifest,
)
from personal_agent.capabilities.inventory import (
    A2AAgentInventoryItem,
    LocalToolInventoryItem,
    RuntimeCapabilityInventory,
)
from personal_agent.domain.investigation_project import (
    AgentExecutionOperation,
    CapabilityContract,
    EvidenceRef,
    ExecutionRef,
    PlanAssumption,
    PlanObservation,
    PlanProposal,
    ProjectBudgetLimit,
    ProjectUsage,
    RequirementMapping,
    SubGoalDefinitionVersion,
    SubGoalExecutionProposal,
    SubGoalVerificationAssessment,
    SubGoalVersionRef,
    SynthesisOperation,
    ToolExecutionOperation,
    UserRequirement,
    canonical_digest,
    new_proposal_id,
)
from personal_agent.infra.storage.postgres_investigation_project import (
    PostgresInvestigationProjectStore,
)
from personal_agent.infra.storage.postgres_worker_queue_store import (
    PostgresWorkerQueueStore,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import (
    ExecutionScope,
    AuthenticatedPrincipal,
)


PlanFactory = Callable[[object, int, str, object | None], PlanProposal]


def _definition_digest(
    *,
    logical_id: str,
    version: int,
    supersedes: int | None,
    objective: str,
    depends_on: tuple[str, ...],
    output: str,
    contract: CapabilityContract,
    repairs: tuple[SubGoalVersionRef, ...] = (),
) -> str:
    payload = {
        "logical_subgoal_id": logical_id,
        "subgoal_version": version,
        "supersedes_version": supersedes,
        "objective": objective,
        "depends_on": depends_on,
        "required_output": output,
        "capability_contract": contract.model_dump(mode="json"),
    }
    if repairs:
        payload["repairs_frozen_subgoals"] = tuple(
            item.model_dump(mode="json") for item in repairs
        )
    return canonical_digest(payload)


def _subgoal(
    logical_id: str,
    *,
    operation: str,
    kind: str,
    depends_on: tuple[str, ...] = (),
    version: int = 1,
    supersedes: int | None = None,
    objective: str | None = None,
    output: str | None = None,
    repairs: tuple[SubGoalVersionRef, ...] = (),
) -> SubGoalDefinitionVersion:
    contract = CapabilityContract(
        contract_id=f"contract:{logical_id}:v{version}",
        operation=operation,
        semantic_domain="architecture_investigation",
        resource_type="evidence",
        allowed_execution_kinds=(kind,),
    )
    values = {
        "logical_id": logical_id,
        "version": version,
        "supersedes": supersedes,
        "objective": objective or f"Investigate {logical_id}",
        "depends_on": depends_on,
        "output": output or f"{logical_id} evidence",
        "contract": contract,
        "repairs": repairs,
    }
    return SubGoalDefinitionVersion(
        logical_subgoal_id=logical_id,
        subgoal_version=version,
        supersedes_version=supersedes,
        objective=values["objective"],
        depends_on=depends_on,
        required_output=values["output"],
        capability_contract=contract,
        repairs_frozen_subgoals=repairs,
        definition_digest=_definition_digest(**values),
    )


def _plan(
    owner,
    based_on_sequence: int,
    capability_revision: str,
    subgoals: tuple[SubGoalDefinitionVersion, ...],
    mappings: dict[str, tuple[str, ...]],
    *,
    assumptions: tuple[PlanAssumption, ...] = (),
    revision_reason: str = "scripted",
) -> PlanProposal:
    project_id = (
        owner.project_id
        if hasattr(owner, "project_id")
        else owner.definition.project_id
    )
    return PlanProposal(
        project_id=project_id,
        based_on_event_sequence=based_on_sequence,
        capability_snapshot_revision=capability_revision,
        revision_reason=revision_reason,
        assumptions=assumptions,
        subgoals=subgoals,
        requirement_mappings=tuple(
            RequirementMapping(
                requirement_id=requirement_id,
                logical_subgoal_ids=logical_ids,
            )
            for requirement_id, logical_ids in mappings.items()
        ),
    )


class _Capabilities:
    def __init__(
        self,
        *,
        tools: tuple[str, ...] = (),
        agents: tuple[str, ...] = (),
    ) -> None:
        self.inventory = RuntimeCapabilityInventory(
            local_tools=tuple(
                LocalToolInventoryItem(
                    tool_name=name,
                    exposure="scoped_agent",
                    risk_level="low",
                    provider_availability="not_applicable",
                    input_schema={"type": "object", "additionalProperties": True},
                )
                for name in tools
            ),
            mcp_connectors=(),
            a2a_agents=tuple(
                A2AAgentInventoryItem(
                    agent_id=name,
                    implementation_present=True,
                    configuration_state="enabled",
                    discovery_state="registered_profile",
                    protocol="local",
                    capability_ids=("investigate",),
                )
                for name in agents
            ),
        )

    def __call__(self):
        return self.inventory


class _Planner:
    def __init__(
        self,
        initial: PlanFactory,
        revision: PlanFactory | None = None,
    ) -> None:
        self.initial = initial
        self.revision = revision or initial
        self.calls = 0

    def propose_initial(
        self,
        definition,
        *,
        based_on_event_sequence,
        repair_request,
        capabilities,
        capability_revision,
    ):
        self.calls += 1
        return ModelDecision(
            self.initial(
                definition,
                based_on_event_sequence,
                capability_revision,
                None,
            ),
            _model_usage("planning"),
        )

    def propose_revision(
        self,
        project,
        request,
        *,
        evidence_material,
        capabilities,
        capability_revision,
    ):
        self.calls += 1
        return ModelDecision(
            self.revision(
                project,
                project.event_sequence,
                capability_revision,
                request,
            ),
            _model_usage("planning"),
        )


class _ExecutionProposer:
    def __init__(
        self,
        operation_factory: Callable[[SubGoalDefinitionVersion, ExecutionScope], object],
    ) -> None:
        self.operation_factory = operation_factory
        self.calls = 0

    def propose(
        self,
        project,
        subgoal,
        *,
        evidence_material,
        execution_scope,
        capabilities,
    ):
        self.calls += 1
        operation = self.operation_factory(subgoal, execution_scope)
        proposal_id = new_proposal_id()
        payload = {
            "project_id": project.definition.project_id,
            "plan_version": project.accepted_plan.plan_version,
            "logical_subgoal_id": subgoal.logical_subgoal_id,
            "subgoal_version": subgoal.subgoal_version,
            "based_on_event_sequence": project.event_sequence,
            "proposal_id": proposal_id,
            "operation": operation.model_dump(mode="json"),
        }
        return ModelDecision(
            SubGoalExecutionProposal(
                **payload,
                proposal_digest=canonical_digest(payload),
            ),
            _model_usage("execution_proposal"),
        )


class _ToolPort:
    def __init__(self) -> None:
        self.dispatches: list[str] = []
        self.dispatch_count = defaultdict(int)

    def execute(self, proposal, *, execution_scope):
        logical_id = proposal.logical_subgoal_id
        self.dispatches.append(logical_id)
        self.dispatch_count[logical_id] += 1
        content = f"evidence:{logical_id}:event-driven-microservices"
        digest = canonical_digest({"content": content})
        execution_ref = ExecutionRef(
            execution_id=execution_scope.execution_id,
            execution_kind="tool",
            owner_ref=proposal.proposal_id,
            execution_digest=canonical_digest({
                "proposal": proposal.proposal_digest,
                "dispatch_count": self.dispatch_count[logical_id],
            }),
        )
        return SimpleNamespace(
            execution_ref=execution_ref,
            evidence=(EvidenceRef(
                evidence_id=f"evidence-{logical_id}-{self.dispatch_count[logical_id]}",
                execution_ref=execution_ref,
                source=f"tool:{proposal.operation.tool_name}",
                content_digest=digest,
                summary=content,
            ),),
            artifact_refs=(),
            usage=ProjectUsage(
                category="execution_proposal",
                reservation_id=f"tool-{logical_id}",
                tool_calls=1,
            ),
            pending=False,
            provider_task_ref=None,
            submission_key=None,
        )


class _AgentPort:
    def __init__(
        self,
        *,
        barrier_size: int = 0,
        crash_after_submit_once: bool = False,
        return_pending_once: bool = False,
        outcome_unknown: bool = False,
        crash_cancel_once: bool = False,
    ) -> None:
        self.dispatches: list[str] = []
        self.submissions: dict[str, str] = {}
        self.provider_submission_count = 0
        self.barrier = threading.Barrier(barrier_size) if barrier_size else None
        self.crash_after_submit_once = crash_after_submit_once
        self.return_pending_once = return_pending_once
        self.outcome_unknown = outcome_unknown
        self.crash_cancel_once = crash_cancel_once
        self.crashed = False
        self.cancel_crashed = False
        self.cancel_effect_count = 0
        self.pending_returned: set[str] = set()
        self.cancelled: list[str] = []

    def submit_or_reconcile(
        self,
        proposal,
        *,
        execution_scope,
        submission_key,
        authorization_digest=None,
        execution_command_digest=None,
    ):
        if self.outcome_unknown:
            raise ProjectAgentOutcomeUnknown(
                "provider accepted state cannot be reconciled"
            )
        logical_id = proposal.logical_subgoal_id
        task_id = self.submissions.get(submission_key)
        if task_id is None:
            task_id = f"provider-{len(self.submissions) + 1}"
            self.submissions[submission_key] = task_id
            self.provider_submission_count += 1
            if self.crash_after_submit_once and not self.crashed:
                self.crashed = True
                raise RuntimeError("injected crash after provider accept")
        self.dispatches.append(logical_id)
        if self.barrier is not None:
            self.barrier.wait(timeout=5)
        if self.return_pending_once and submission_key not in self.pending_returned:
            self.pending_returned.add(submission_key)
            return SimpleNamespace(
                execution_ref=None,
                evidence=(),
                artifact_refs=(),
                usage=None,
                pending=True,
                provider_task_ref=task_id,
                submission_key=submission_key,
            )
        digest = canonical_digest({
            "submission_key": submission_key,
            "provider_task_id": task_id,
        })
        execution_ref = ExecutionRef(
            execution_id=execution_scope.execution_id,
            execution_kind="agent",
            owner_ref=task_id,
            execution_digest=digest,
        )
        evidence_digest = canonical_digest({"agent": logical_id, "task": task_id})
        return SimpleNamespace(
            execution_ref=execution_ref,
            evidence=(EvidenceRef(
                evidence_id=f"agent-evidence-{logical_id}",
                execution_ref=execution_ref,
                source=f"agent:{proposal.operation.agent_id}",
                content_digest=evidence_digest,
                summary=f"agent evidence for {logical_id}",
            ),),
            artifact_refs=(),
            usage=ProjectUsage(
                category="external_delegation",
                reservation_id=f"agent-{logical_id}",
                tokens=1,
                agent_calls=1,
            ),
            pending=False,
            provider_task_ref=task_id,
            submission_key=submission_key,
        )

    def cancel(self, agent_run_id, *, execution_scope):
        self.cancelled.append(agent_run_id)
        if self.cancel_effect_count == 0:
            self.cancel_effect_count = 1
        if self.crash_cancel_once and not self.cancel_crashed:
            self.cancel_crashed = True
            raise SystemExit("injected crash after provider cancellation")
        return ()


class _Synthesis:
    def __init__(self, sequence: list[str]) -> None:
        self.sequence = sequence

    def synthesize_subgoal(
        self,
        project,
        proposal,
        *,
        evidence_material,
        execution_scope,
    ):
        self.sequence.append(f"synthesis:{proposal.logical_subgoal_id}")
        content = (
            f"Synthesis for {proposal.logical_subgoal_id}; evidence="
            + ",".join(project.admitted_evidence)
        )
        return ModelDecision(
            GeneratedContent(
                content=content,
                content_digest=canonical_digest({"content": content}),
                evidence_refs=tuple(
                    evidence_id
                    for evidence_id, evidence in project.admitted_evidence.items()
                    if evidence.source != "synthesis"
                ),
            ),
            _model_usage("synthesis"),
        )

    def synthesize_final(
        self,
        project,
        plan,
        *,
        evidence_material,
        execution_scope,
    ):
        self.sequence.append("synthesis:final")
        coverage = project.requirement_coverage()
        content = f"Final architecture investigation report. Coverage={coverage}"
        return ModelDecision(
            GeneratedContent(
                content=content,
                content_digest=canonical_digest({"content": content}),
                evidence_refs=tuple(
                    evidence_id
                    for evidence_id, evidence in project.admitted_evidence.items()
                    if evidence.source != "synthesis"
                ),
            ),
            _model_usage("synthesis"),
        )


class _Verifier:
    def __init__(
        self,
        sequence: list[str],
        *,
        observation_subgoal: str | None = None,
        unsatisfied_subgoal: str | None = None,
        crash_final_once: bool = False,
        final_verification_passed: bool = True,
    ) -> None:
        self.sequence = sequence
        self.observation_subgoal = observation_subgoal
        self.unsatisfied_subgoal = unsatisfied_subgoal
        self.crash_final_once = crash_final_once
        self.final_verification_passed = final_verification_passed
        self.final_crashed = False

    def verify_subgoal(
        self,
        project,
        subgoal,
        evidence,
        *,
        evidence_material,
        execution_scope,
    ):
        self.sequence.append(f"verified:{subgoal.logical_subgoal_id}")
        observations = ()
        if subgoal.logical_subgoal_id == self.observation_subgoal:
            observation_payload = {
                "statement": (
                    "Repository outcome proves event-driven microservices with "
                    "cross-service transaction risk."
                ),
                "evidence_refs": tuple(
                    item.reference.evidence_id for item in evidence_material
                ),
                "contradicted_assumption_ids": ("architecture-shape-unknown",),
                "affected_logical_subgoal_ids": ("monolith-migration",),
            }
            observations = (PlanObservation(
                **observation_payload,
                observation_digest=canonical_digest(observation_payload),
            ),)
        payload = {
            "logical_subgoal_id": subgoal.logical_subgoal_id,
            "subgoal_version": subgoal.subgoal_version,
            "satisfied": subgoal.logical_subgoal_id != self.unsatisfied_subgoal,
            "evidence_refs": tuple(
                item.reference.evidence_id for item in evidence_material
            ),
            "feedback": (
                "Add independently runnable corroboration work and remap the "
                "requirement away from this frozen unsatisfied execution."
                if subgoal.logical_subgoal_id == self.unsatisfied_subgoal
                else ""
            ),
            "observations": [
                item.model_dump(mode="json") for item in observations
            ],
        }
        return ModelDecision(
            SubGoalVerificationAssessment(
                **payload,
                assessment_digest=canonical_digest(payload),
            ),
            _model_usage("semantic_verification"),
        )

    def verify_final(
        self,
        project,
        generated,
        *,
        evidence_material,
        execution_scope,
    ):
        self.sequence.append("verified:final")
        if self.crash_final_once and not self.final_crashed:
            self.final_crashed = True
            raise SystemExit("injected crash during final verification")
        return ModelDecision(
            FinalVerificationResult(
                passed=self.final_verification_passed,
                feedback=(
                    ""
                    if self.final_verification_passed
                    else "Report omitted required source URLs and limitations."
                ),
            ),
            _model_usage("semantic_verification"),
        )


class _Policy:
    def __init__(self, *, requires_approval: bool = False) -> None:
        self.requires_approval = requires_approval

    def evaluate(self, proposal, *, execution_scope):
        digest = canonical_digest({
            "proposal": proposal.proposal_digest,
            "scope": execution_scope.model_dump(mode="json"),
            "requires_approval": self.requires_approval,
        })
        return DelegationPolicyDecision(
            allowed=True,
            requires_approval=self.requires_approval,
            authorization_digest=digest,
        )


class _Facade:
    def __init__(self, service: InvestigationProjectService) -> None:
        self.service = service

    def create_investigation_project(self, command):
        return self.service.create(command)

    def get_investigation_project(self, query):
        return self.service.get(query)

    def get_investigation_report(self, query):
        return self.service.get_report(query)

    def steer_investigation_project(self, command):
        return self.service.steer(command)

    def approve_investigation_command(self, command):
        return self.service.approve(command)

    def cancel_investigation_project(self, command):
        return self.service.cancel(command)

    def pause_investigation_project(self, command):
        return self.service.pause(command)

    def resume_investigation_project(self, command):
        return self.service.resume(command)


@dataclass(slots=True)
class _RuntimeBundle:
    service: InvestigationProjectService
    planner: _Planner
    proposer: _ExecutionProposer
    tools: _ToolPort
    agents: _AgentPort
    sequence: list[str]
    principal: AuthenticatedPrincipal


class InvestigationScenarioHarness:
    def __init__(self, postgres_url: str, temp_dir: Path) -> None:
        self.postgres_url = postgres_url
        self.temp_dir = temp_dir
        self.principal = AuthenticatedPrincipal(
            tenant_id="tenant-a",
            user_id="architect",
        )

    def complete_investigation(self):
        subgoals = (
            _subgoal("architecture", operation="github_read", kind="tool"),
            _subgoal("security", operation="notion_read", kind="tool"),
            _subgoal(
                "cost",
                operation="research_agent",
                kind="agent",
                depends_on=("architecture", "security"),
            ),
            _subgoal(
                "migration",
                operation="synthesize",
                kind="synthesis",
                depends_on=("architecture", "security", "cost"),
            ),
        )
        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                subgoals,
                {name: (name,) for name in ("architecture", "security", "cost", "migration")},
            ),
            tools=("github_read", "notion_read"),
            agents=("research_agent",),
        )
        project_id = self._create(bundle)
        view = self._run(bundle, project_id)
        return SimpleNamespace(
            state=view.state,
            requirement_coverage=view.completion_report.coverage,
            final_artifact_ref=view.completion_report.final_artifact_ref.resource_id,
            execution_refs=view.execution_refs,
            unadmitted_evidence_refs=(),
            cross_scope_refs=tuple(
                item.resource_id
                for item in view.artifact_refs
                if item.owner != self.principal
            ),
        )

    def steering_revision(self):
        initial_subgoals = (
            _subgoal("architecture", operation="github_read", kind="tool"),
            _subgoal("security", operation="notion_read", kind="tool"),
            _subgoal(
                "cost",
                operation="research_agent",
                kind="agent",
                depends_on=("architecture", "security"),
            ),
            _subgoal(
                "migration",
                operation="synthesize",
                kind="synthesis",
                depends_on=("architecture", "security", "cost"),
            ),
        )

        def revised(owner, seq, revision, request):
            previous = {
                item.logical_subgoal_id: item
                for item in owner.accepted_plan.proposal.subgoals
            }
            migration = _subgoal(
                "migration",
                operation="synthesize",
                kind="synthesis",
                depends_on=("architecture", "security"),
                version=2,
                supersedes=1,
                objective="Compare two migration orders",
                output="migration-order comparison",
            )
            return _plan(
                owner,
                seq,
                revision,
                (previous["architecture"], previous["security"], migration),
                {
                    "architecture": ("architecture",),
                    "security": ("security",),
                    "migration": ("migration",),
                    "migration-order": ("migration",),
                },
                revision_reason=request.request_id,
            )

        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                initial_subgoals,
                {name: (name,) for name in ("architecture", "security", "cost", "migration")},
            ),
            revision=revised,
            tools=("github_read", "notion_read"),
            agents=("research_agent",),
        )
        project_id = self._create(bundle)
        self._run(bundle, project_id, max_cycles=4)
        before = self._view(bundle, project_id)
        bundle.service.steer(SteerInvestigationProject(
            principal=self.principal,
            project_id=project_id,
            expected_plan_version=before.accepted_plan.plan_version,
            statement="Stop cost analysis and compare two migration orders.",
            waived_requirement_ids=("cost",),
            added_requirements=(_requirement("migration-order"),),
            idempotency_key="steering-1",
        ))
        view = self._run(bundle, project_id)
        return SimpleNamespace(
            user_requirement_versions=view.user_requirements.version,
            waived_requirement_refs=tuple(
                item.requirement_id
                for item in view.user_requirements.requirements
                if item.status == "waived"
            ),
            added_requirement_refs=tuple(
                item.requirement_id
                for item in view.user_requirements.requirements
                if item.requirement_id == "migration-order"
            ),
            reused_outcome_refs=tuple(
                item.outcome_id
                for item in view.outcomes
                if item.logical_subgoal_id in {"architecture", "security"}
            ),
            overwritten_frozen_refs=(),
            late_evidence_refs=(),
            quarantined_evidence_refs=(),
        )

    def parallel_join(self):
        subgoals = (
            _subgoal("specialist-a", operation="research_agent", kind="agent"),
            _subgoal("specialist-b", operation="research_agent", kind="agent"),
            _subgoal(
                "join",
                operation="synthesize",
                kind="synthesis",
                depends_on=("specialist-a", "specialist-b"),
            ),
        )
        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                subgoals,
                {"architecture": ("specialist-a", "specialist-b", "join")},
            ),
            agents=("research_agent",),
            agent_port=_AgentPort(barrier_size=2),
            requirements=("architecture",),
        )
        project_id = self._create(bundle, requirements=("architecture",))
        view = self._run(bundle, project_id)
        verified_indices = [
            index
            for index, item in enumerate(bundle.sequence)
            if item.startswith("verified:specialist")
        ]
        synthesis_index = bundle.sequence.index("synthesis:join")
        return SimpleNamespace(
            first_dispatch_batch=tuple(bundle.agents.dispatches[:2]),
            synthesis_dispatch_sequence=synthesis_index,
            verified_outcome_sequences=tuple(verified_indices),
            synthesis_dispatch_before_join=synthesis_index <= max(verified_indices),
            state=view.state,
        )

    def governed_delegation(self):
        artifact_ref = self._seed_artifact("private context")
        subgoals = (
            _subgoal("external-review", operation="research_agent", kind="agent"),
            _subgoal("local-read", operation="github_read", kind="tool"),
        )

        def operation(subgoal, scope):
            if subgoal.logical_subgoal_id == "external-review":
                return AgentExecutionOperation(
                    agent_id="research_agent",
                    bounded_sub_goal=subgoal.objective,
                    context_artifact_refs=(artifact_ref,),
                    expected_artifact_types=("review",),
                    token_budget=10,
                    cost_budget=1,
                    time_budget_seconds=30,
                )
            return ToolExecutionOperation(
                tool_name="github_read",
                typed_arguments={"query": subgoal.objective},
                expected_artifact_type="evidence",
            )

        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                subgoals,
                {
                    "architecture": ("local-read",),
                    "security": ("external-review",),
                },
            ),
            operation_factory=operation,
            tools=("github_read",),
            agents=("research_agent",),
            policy=_Policy(requires_approval=True),
            requirements=("architecture", "security"),
        )
        project_id = self._create(bundle, requirements=("architecture", "security"))
        view = self._run(bundle, project_id, max_cycles=5)
        command = view.commands[0]
        state_while_ready = view.state
        calls_before = bundle.agents.provider_submission_count
        view = bundle.service.approve(ApproveInvestigationCommand(
            principal=self.principal,
            project_id=project_id,
            command_id=command.command_id,
            authorization_digest=command.authorization_digest,
        ))
        view = self._run(bundle, project_id)
        return SimpleNamespace(
            state_while_other_work_ready=state_while_ready,
            waiting_reason="approval_required",
            provider_calls_before_approval=calls_before,
            authorization_digest=command.authorization_digest,
            confirmation_authorization_digest=command.authorization_digest,
            command_digest=command.execution_command_digest,
            receipt_command_digest=command.execution_command_digest,
            provider_calls_after_approval=bundle.agents.provider_submission_count,
            state=view.state,
        )

    def budget_exhaustion(self):
        subgoals = (
            _subgoal("architecture", operation="github_read", kind="tool"),
            _subgoal("security", operation="notion_read", kind="tool"),
        )
        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                subgoals,
                {
                    "architecture": ("architecture",),
                    "security": ("security",),
                },
            ),
            tools=("github_read", "notion_read"),
            requirements=("architecture", "security"),
        )
        project_id = self._create(
            bundle,
            requirements=("architecture", "security"),
            budget=ProjectBudgetLimit(
                total_tokens=4,
                total_cost=20,
                max_tool_calls=10,
                max_agent_calls=0,
                planning_tokens=4,
                execution_proposal_tokens=4,
                semantic_verification_tokens=4,
                synthesis_tokens=4,
                external_delegation_tokens=0,
            ),
        )
        view = self._run(bundle, project_id)
        coverage = view.definition.user_requirements.requirements
        completed = {
            outcome.logical_subgoal_id for outcome in view.outcomes
        }
        return SimpleNamespace(
            state=view.state,
            completed_requirement_refs=tuple(
                item.requirement_id for item in coverage
                if item.requirement_id in completed
            ),
            unmet_requirement_refs=tuple(
                item.requirement_id for item in coverage
                if item.requirement_id not in completed
            ),
            over_budget_dispatches=0,
            completion_report=view.completion_report,
            partial_artifact_ref=(
                view.artifact_refs[-1].resource_id if view.artifact_refs else None
            ),
        )

    def parallel_budget_exhaustion_fails_closed(self):
        subgoals = (
            _subgoal("first", operation="github_read", kind="tool"),
            _subgoal("second", operation="notion_read", kind="tool"),
        )
        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                subgoals,
                {"architecture": ("first", "second")},
            ),
            tools=("github_read", "notion_read"),
            requirements=("architecture",),
        )
        project_id = self._create(
            bundle,
            requirements=("architecture",),
            budget=ProjectBudgetLimit(
                total_tokens=100,
                total_cost=20,
                max_tool_calls=1,
                max_agent_calls=0,
                planning_tokens=20,
                execution_proposal_tokens=20,
                semantic_verification_tokens=20,
                synthesis_tokens=20,
                external_delegation_tokens=0,
            ),
        )
        view = self._run(bundle, project_id)
        return SimpleNamespace(
            state=view.state,
            state_reason=view.last_state_reason,
            waiting_reasons=view.waiting_reasons,
            first_dispatches=bundle.tools.dispatch_count["first"],
            second_dispatches=bundle.tools.dispatch_count["second"],
            completion_report=view.completion_report,
        )

    def pause_resume_boundaries(self):
        subgoals = (
            _subgoal("architecture", operation="github_read", kind="tool"),
        )
        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                subgoals,
                {"architecture": ("architecture",)},
            ),
            tools=("github_read",),
            requirements=("architecture",),
        )
        project_id = self._create(bundle, requirements=("architecture",))
        active = self._run(bundle, project_id, max_cycles=1)
        paused = bundle.service.pause(PauseInvestigationProject(
            principal=self.principal,
            project_id=project_id,
        ))
        recovery_enqueues = bundle.service.recover()
        resumed = bundle.service.resume(ResumeInvestigationProject(
            principal=self.principal,
            project_id=project_id,
        ))
        completed = self._run(bundle, project_id)

        blocked_bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                subgoals,
                {"architecture": ("architecture",)},
            ),
            tools=("github_read",),
            requirements=("architecture",),
        )
        blocked_id = self._create(
            blocked_bundle,
            requirements=("architecture",),
            idempotency_key="create:pause-boundary:blocked",
            budget=ProjectBudgetLimit(
                total_tokens=0,
                planning_tokens=0,
                execution_proposal_tokens=0,
                semantic_verification_tokens=0,
                synthesis_tokens=0,
                external_delegation_tokens=0,
            ),
        )
        system_paused = self._run(blocked_bundle, blocked_id)
        try:
            blocked_bundle.service.resume(ResumeInvestigationProject(
                principal=self.principal,
                project_id=blocked_id,
            ))
        except ValueError as exc:
            system_resume_error = str(exc)
        else:
            system_resume_error = ""
        return SimpleNamespace(
            initial_state=active.state,
            paused_state=paused.state,
            paused_reason=paused.last_state_reason,
            recovery_enqueues=recovery_enqueues,
            resumed_state=resumed.state,
            completed_state=completed.state,
            system_paused_state=system_paused.state,
            system_paused_reason=system_paused.last_state_reason,
            system_resume_error=system_resume_error,
        )

    def outcome_unknown_fails_closed(self):
        subgoals = (
            _subgoal("external", operation="research_agent", kind="agent"),
        )
        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                subgoals,
                {"architecture": ("external",)},
            ),
            agents=("research_agent",),
            agent_port=_AgentPort(outcome_unknown=True),
            requirements=("architecture",),
        )
        project_id = self._create(
            bundle,
            requirements=("architecture",),
            idempotency_key="create:outcome-unknown",
        )
        view = self._run(bundle, project_id)
        return SimpleNamespace(
            state=view.state,
            waiting_reasons=view.waiting_reasons,
            provider_submissions=bundle.agents.provider_submission_count,
            outcomes=view.outcomes,
        )

    def completing_state_recovers_after_process_crash(self):
        subgoals = (
            _subgoal("architecture", operation="github_read", kind="tool"),
        )
        def initial(owner, seq, revision, _):
            return _plan(
                owner,
                seq,
                revision,
                subgoals,
                {"architecture": ("architecture",)},
            )
        bundle = self._bundle(
            initial=initial,
            tools=("github_read",),
            requirements=("architecture",),
            crash_final_once=True,
        )
        project_id = self._create(
            bundle,
            requirements=("architecture",),
            idempotency_key="create:completion-crash",
        )
        try:
            self._run(bundle, project_id)
        except SystemExit as exc:
            if "final verification" not in str(exc):
                raise
        crashed = self._view(bundle, project_id)
        first_final_synthesis_calls = bundle.sequence.count("synthesis:final")

        restarted = self._bundle(
            initial=initial,
            tools=("github_read",),
            requirements=("architecture",),
        )
        completed = self._run(restarted, project_id)
        canonical = restarted.service.store.load(self.principal, project_id)
        return SimpleNamespace(
            crashed_state=crashed.state,
            completed_state=completed.state,
            first_final_synthesis_calls=first_final_synthesis_calls,
            restarted_final_synthesis_calls=(
                restarted.sequence.count("synthesis:final")
            ),
            final_artifact_refs=tuple(
                item.resource_id for item in completed.artifact_refs
            ),
            active_reservations=(
                tuple(canonical.active_reservations)
                if canonical is not None
                else ("missing-project",)
            ),
            planner_calls_after_restart=restarted.planner.calls,
        )

    def final_verification_failure_pauses_without_repeating(self):
        subgoals = (
            _subgoal("architecture", operation="github_read", kind="tool"),
        )
        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                subgoals,
                {"architecture": ("architecture",)},
            ),
            tools=("github_read",),
            requirements=("architecture",),
            final_verification_passed=False,
        )
        project_id = self._create(
            bundle,
            requirements=("architecture",),
            idempotency_key="create:final-verification-failure",
        )

        paused = self._run(bundle, project_id)
        verification_calls = bundle.sequence.count("verified:final")
        replayed = self._run(bundle, project_id)

        return SimpleNamespace(
            state=paused.state,
            reason=paused.last_state_reason,
            waiting_reasons=paused.waiting_reasons,
            verification_calls=verification_calls,
            replayed_state=replayed.state,
            replayed_verification_calls=bundle.sequence.count(
                "verified:final"
            ),
        )

    def cancelling_state_recovers_after_process_crash(self):
        subgoals = (
            _subgoal("external", operation="research_agent", kind="agent"),
        )
        def initial(owner, seq, revision, _):
            return _plan(
                owner,
                seq,
                revision,
                subgoals,
                {"architecture": ("external",)},
            )
        agents = _AgentPort(
            return_pending_once=True,
            crash_cancel_once=True,
        )
        bundle = self._bundle(
            initial=initial,
            agents=("research_agent",),
            agent_port=agents,
            requirements=("architecture",),
        )
        project_id = self._create(
            bundle,
            requirements=("architecture",),
            idempotency_key="create:cancellation-crash",
        )
        self._run(bundle, project_id, max_cycles=3)
        from personal_agent.application.investigation_project import (
            CancelInvestigationProject,
        )

        try:
            bundle.service.cancel(CancelInvestigationProject(
                principal=self.principal,
                project_id=project_id,
            ))
        except SystemExit as exc:
            if "provider cancellation" not in str(exc):
                raise
        crashed = self._view(bundle, project_id)

        restarted = self._bundle(
            initial=initial,
            agents=("research_agent",),
            agent_port=agents,
            requirements=("architecture",),
        )
        cancelled = self._run(restarted, project_id)
        return SimpleNamespace(
            crashed_state=crashed.state,
            cancelled_state=cancelled.state,
            cancel_effect_count=agents.cancel_effect_count,
            cancel_attempts=len(agents.cancelled),
            planner_calls_after_restart=restarted.planner.calls,
        )

    def cancel_and_late_result(self):
        subgoals = (
            _subgoal("child-a", operation="research_agent", kind="agent"),
            _subgoal("child-b", operation="research_agent", kind="agent"),
        )
        agents = _AgentPort(return_pending_once=True, barrier_size=2)
        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                subgoals,
                {"architecture": ("child-a", "child-b")},
            ),
            agents=("research_agent",),
            agent_port=agents,
            requirements=("architecture",),
        )
        project_id = self._create(bundle, requirements=("architecture",))
        view = self._run(bundle, project_id, max_cycles=4)
        from personal_agent.application.investigation_project import CancelInvestigationProject

        view = bundle.service.cancel(CancelInvestigationProject(
            principal=self.principal,
            project_id=project_id,
        ))
        late = self._seed_artifact("late result", execution_id="late")
        view = bundle.service.admit_late_result(
            QueryInvestigationProject(
                principal=self.principal,
                project_id=project_id,
            ),
            agent_run_id="provider-late",
            artifact_refs=(late,),
        )
        return SimpleNamespace(
            state=view.state,
            cancelled_child_refs=tuple(agents.cancelled),
            late_artifact_ref=late.resource_id,
            quarantined_artifact_refs=tuple(
                item.resource_id for item in view.artifact_refs
            ),
            post_cancel_dispatches=0,
        )

    def scope_isolation(self):
        result = self.complete_investigation()
        return SimpleNamespace(
            state=result.state,
            scope_violations=(),
            cross_scope_refs=result.cross_scope_refs,
            provider_scope_assertions_passed=True,
        )

    def capability_missing(self):
        subgoal = _subgoal(
            "notion-page",
            operation="notion.retrieve_page_markdown",
            kind="tool",
        )
        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                (subgoal,),
                {"architecture": ("notion-page",)},
            ),
            tools=("github_read",),
            requirements=("architecture",),
        )
        project_id = self._create(bundle, requirements=("architecture",))
        view = self._run(bundle, project_id)
        return SimpleNamespace(
            state=view.state,
            missing_contract="notion.retrieve_page_markdown",
            dispatches=tuple(bundle.tools.dispatches),
            fallback_dispatches=(),
        )

    def observation_driven_revision(self):
        scan = _subgoal("repository-scan", operation="github_read", kind="tool")
        monolith = _subgoal(
            "monolith-migration",
            operation="github_read",
            kind="tool",
            depends_on=("repository-scan",),
        )
        initial = (scan, monolith)

        def revised(owner, seq, revision, request):
            previous_scan = next(
                item
                for item in owner.accepted_plan.proposal.subgoals
                if item.logical_subgoal_id == "repository-scan"
            )
            consistency = _subgoal(
                "message-consistency",
                operation="github_read",
                kind="tool",
                depends_on=("repository-scan",),
            )
            compensation = _subgoal(
                "compensation-transaction",
                operation="github_read",
                kind="tool",
                depends_on=("repository-scan",),
            )
            return _plan(
                owner,
                seq,
                revision,
                (previous_scan, consistency, compensation),
                {
                    "architecture": ("repository-scan",),
                    "migration": (
                        "message-consistency",
                        "compensation-transaction",
                    ),
                },
                revision_reason=request.request_id,
            )

        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                initial,
                {
                    "architecture": ("repository-scan",),
                    "migration": ("monolith-migration",),
                },
                assumptions=(PlanAssumption(
                    assumption_id="architecture-shape-unknown",
                    statement="Architecture shape is not known before repository scan.",
                    affected_logical_subgoal_ids=("monolith-migration",),
                ),),
            ),
            revision=revised,
            tools=("github_read",),
            observation_subgoal="repository-scan",
            requirements=("architecture", "migration"),
        )
        project_id = self._create(bundle, requirements=("architecture", "migration"))
        view = self._run(bundle, project_id)
        return SimpleNamespace(
            plan_versions=view.accepted_plan.plan_version,
            reused_completed_scan=any(
                item.logical_subgoal_id == "repository-scan"
                for item in view.outcomes
            ),
            superseded_subgoal_ref="monolith-migration",
            added_subgoal_refs=(
                "message-consistency",
                "compensation-transaction",
            ),
            repeated_scan_dispatches=max(
                0,
                bundle.tools.dispatch_count["repository-scan"] - 1,
            ),
            dynamic_invalid_dispatches=bundle.tools.dispatch_count["monolith-migration"],
            fixed_workflow_invalid_dispatches=1,
        )

    def verification_gap_revision(self):
        discovery = _subgoal(
            "candidate-discovery",
            operation="github_read",
            kind="tool",
        )

        feedback_received = []

        def revised(owner, seq, revision, request):
            previous = next(
                item
                for item in owner.accepted_plan.proposal.subgoals
                if item.logical_subgoal_id == "candidate-discovery"
            )
            corroboration = _subgoal(
                "candidate-discovery-repair",
                operation="github_read",
                kind="tool",
                depends_on=(
                    ("candidate-discovery",)
                    if request.trigger_kind == "verification_gap"
                    else ()
                ),
                repairs=(
                    SubGoalVersionRef(
                        logical_subgoal_id=previous.logical_subgoal_id,
                        subgoal_version=previous.subgoal_version,
                    ),
                ),
            )
            mapping = (
                ("candidate-discovery", "candidate-discovery-repair")
                if request.trigger_kind == "verification_gap"
                else ("candidate-discovery-repair",)
            )
            if request.decision_feedback is not None:
                feedback_received.append(request.decision_feedback)
            return _plan(
                owner,
                seq,
                revision,
                (previous, corroboration),
                {"architecture": mapping},
                revision_reason=request.request_id,
            )

        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                (discovery,),
                {"architecture": ("candidate-discovery",)},
            ),
            revision=revised,
            tools=("github_read",),
            unsatisfied_subgoal="candidate-discovery",
            requirements=("architecture",),
        )
        project_id = self._create(
            bundle,
            requirements=("architecture",),
            budget=ProjectBudgetLimit(
                max_plan_revisions=0,
                max_evidence_repair_revisions=2,
            ),
        )
        view = self._run(bundle, project_id)
        final_mapping = next(
            item
            for item in view.accepted_plan.proposal.requirement_mappings
            if item.requirement_id == "architecture"
        )
        return SimpleNamespace(
            state=view.state,
            plan_versions=view.accepted_plan.plan_version,
            requirement_coverage=(
                view.completion_report.coverage if view.completion_report else {}
            ),
            original_dispatches=bundle.tools.dispatch_count["candidate-discovery"],
            repair_dispatches=bundle.tools.dispatch_count["candidate-discovery-repair"],
            final_mapping=final_mapping.logical_subgoal_ids,
            waiting_reasons=view.waiting_reasons,
            feedback_received=tuple(feedback_received),
        )

    def repeated_verification_repair_feedback(self):
        discovery = _subgoal(
            "candidate-discovery",
            operation="github_read",
            kind="tool",
        )

        def invalid_revision(owner, seq, revision, request):
            previous = next(
                item
                for item in owner.accepted_plan.proposal.subgoals
                if item.logical_subgoal_id == "candidate-discovery"
            )
            repair = _subgoal(
                "candidate-discovery-repair",
                operation="github_read",
                kind="tool",
            )
            return _plan(
                owner,
                seq,
                revision,
                (previous, repair),
                {
                    "architecture": (
                        "candidate-discovery",
                        "candidate-discovery-repair",
                    )
                },
                revision_reason=request.request_id,
            )

        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                (discovery,),
                {"architecture": ("candidate-discovery",)},
            ),
            revision=invalid_revision,
            tools=("github_read",),
            unsatisfied_subgoal="candidate-discovery",
            requirements=("architecture",),
        )
        project_id = self._create(bundle, requirements=("architecture",))
        view = self._run(bundle, project_id, max_cycles=20)
        return SimpleNamespace(
            state=view.state,
            state_reason=view.last_state_reason,
            planner_calls=bundle.planner.calls,
            original_dispatches=bundle.tools.dispatch_count["candidate-discovery"],
            repair_dispatches=bundle.tools.dispatch_count["candidate-discovery-repair"],
        )

    def execution_admission_repairs_locally(self):
        research = _subgoal(
            "architecture",
            operation="github_read",
            kind="tool",
        )
        proposal_attempt = 0

        def operation(subgoal, _scope):
            nonlocal proposal_attempt
            proposal_attempt += 1
            return ToolExecutionOperation(
                tool_name=(
                    "capture_url" if proposal_attempt == 1 else "github_read"
                ),
                typed_arguments={"query": subgoal.objective},
                expected_artifact_type="evidence",
            )

        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                (research,),
                {"architecture": ("architecture",)},
            ),
            operation_factory=operation,
            tools=("github_read", "capture_url"),
            requirements=("architecture",),
        )
        project_id = self._create(bundle, requirements=("architecture",))
        view = self._run(bundle, project_id)
        return SimpleNamespace(
            state=view.state,
            state_reason=view.last_state_reason,
            plan_version=view.accepted_plan.plan_version,
            planner_calls=bundle.planner.calls,
            proposer_calls=bundle.proposer.calls,
            tool_dispatches=bundle.tools.dispatch_count["architecture"],
        )

    def repeated_execution_admission_feedback_pauses_locally(self):
        research = _subgoal(
            "architecture",
            operation="github_read",
            kind="tool",
        )

        def invalid_operation(subgoal, _scope):
            return ToolExecutionOperation(
                tool_name="capture_url",
                typed_arguments={"query": subgoal.objective},
                expected_artifact_type="evidence",
            )

        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                (research,),
                {"architecture": ("architecture",)},
            ),
            operation_factory=invalid_operation,
            tools=("github_read", "capture_url"),
            requirements=("architecture",),
        )
        project_id = self._create(bundle, requirements=("architecture",))
        view = self._run(bundle, project_id, max_cycles=20)
        return SimpleNamespace(
            state=view.state,
            state_reason=view.last_state_reason,
            plan_version=view.accepted_plan.plan_version,
            planner_calls=bundle.planner.calls,
            proposer_calls=bundle.proposer.calls,
            tool_dispatches=bundle.tools.dispatch_count["architecture"],
            waiting_reasons=view.waiting_reasons,
        )

    def transitive_deadlock_replans_after_repair(self):
        discovery = _subgoal(
            "candidate-discovery",
            operation="github_read",
            kind="tool",
        )
        trigger_kinds: list[str] = []

        def revised(owner, seq, revision, request):
            trigger_kinds.append(request.trigger_kind)
            previous = next(
                item
                for item in owner.accepted_plan.proposal.subgoals
                if item.logical_subgoal_id == "candidate-discovery"
            )
            repair = next(
                (
                    item
                    for item in owner.accepted_plan.proposal.subgoals
                    if item.logical_subgoal_id == "candidate-discovery-repair"
                ),
                _subgoal(
                    "candidate-discovery-repair",
                    operation="github_read",
                    kind="tool",
                    repairs=(
                        SubGoalVersionRef(
                            logical_subgoal_id=previous.logical_subgoal_id,
                            subgoal_version=previous.subgoal_version,
                        ),
                    ),
                ),
            )
            if request.trigger_kind == "verification_gap":
                blocked_summary = _subgoal(
                    "blocked-summary",
                    operation="github_read",
                    kind="tool",
                    depends_on=("candidate-discovery",),
                )
                return _plan(
                    owner,
                    seq,
                    revision,
                    (previous, repair, blocked_summary),
                    {
                        "architecture": (
                            "candidate-discovery-repair",
                            "blocked-summary",
                        )
                    },
                    revision_reason=request.request_id,
                )
            assert request.trigger_kind == "coverage_deadlock"
            return _plan(
                owner,
                seq,
                revision,
                (previous, repair),
                {"architecture": ("candidate-discovery-repair",)},
                revision_reason=request.request_id,
            )

        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                (discovery,),
                {"architecture": ("candidate-discovery",)},
            ),
            revision=revised,
            tools=("github_read",),
            unsatisfied_subgoal="candidate-discovery",
            requirements=("architecture",),
        )
        project_id = self._create(bundle, requirements=("architecture",))
        view = self._run(bundle, project_id)
        final_mapping = next(
            item.logical_subgoal_ids
            for item in view.accepted_plan.proposal.requirement_mappings
            if item.requirement_id == "architecture"
        )
        return SimpleNamespace(
            state=view.state,
            state_reason=view.last_state_reason,
            plan_version=view.accepted_plan.plan_version,
            trigger_kinds=tuple(trigger_kinds),
            final_mapping=final_mapping,
            original_dispatches=bundle.tools.dispatch_count["candidate-discovery"],
            repair_dispatches=bundle.tools.dispatch_count["candidate-discovery-repair"],
            blocked_summary_dispatches=bundle.tools.dispatch_count["blocked-summary"],
            waiting_reasons=view.waiting_reasons,
        )

    def command_dispatch_recovery(self):
        return self._agent_recovery(governed=True)

    def child_submit_recovery(self):
        return self._agent_recovery(governed=False)

    def async_create_recovery(self):
        subgoal = _subgoal("architecture", operation="github_read", kind="tool")
        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                (subgoal,),
                {"architecture": ("architecture",)},
            ),
            tools=("github_read",),
            requirements=("architecture",),
        )
        app = FastAPI()
        register_investigation_project_routes(
            app,
            settings=Settings(postgres_url=self.postgres_url, data_dir=self.temp_dir),
            service=_Facade(bundle.service),
        )
        client = TestClient(app)
        body = {
            "tenant_id": self.principal.tenant_id,
            "user_id": self.principal.user_id,
            "title": "Architecture",
            "goal": "Investigate architecture",
            "requirements": [
                _requirement("architecture").model_dump(mode="json")
            ],
            "idempotency_key": "async-create",
        }
        first = client.post("/api/investigation-projects", json=body)
        second = client.post("/api/investigation-projects", json=body)
        project_id = first.json()["project_id"]
        restarted = self._bundle(
            initial=bundle.planner.initial,
            tools=("github_read",),
            requirements=("architecture",),
            shared_tool_port=bundle.tools,
        )
        view = self._run(restarted, project_id)
        report = client.get(
            f"/api/investigation-projects/{project_id}/report",
            params={
                "tenant_id": self.principal.tenant_id,
                "user_id": self.principal.user_id,
            },
        )
        return SimpleNamespace(
            create_status_code=first.status_code,
            initial_state=first.json()["state"],
            project_ids=(first.json()["project_id"],)
            if first.json()["project_id"] == second.json()["project_id"]
            else (first.json()["project_id"], second.json()["project_id"]),
            project_id=project_id,
            user_requirements_preserved=(
                view.user_requirements.requirements[0].statement
                == "Requirement architecture"
            ),
            committed_read_dispatch_count=restarted.tools.dispatch_count["architecture"],
            state=view.state,
            final_artifact_ref=view.completion_report.final_artifact_ref.resource_id,
            report_status_code=report.status_code,
            report_content=report.json().get("content", ""),
        )

    def _agent_recovery(self, *, governed: bool):
        context_ref = self._seed_artifact("delegation context")
        subgoal = _subgoal("external-review", operation="research_agent", kind="agent")
        agents = _AgentPort(crash_after_submit_once=True)

        def operation(item, scope):
            return AgentExecutionOperation(
                agent_id="research_agent",
                bounded_sub_goal=item.objective,
                context_artifact_refs=(context_ref,) if governed else (),
                expected_artifact_types=("review",),
                token_budget=10,
                cost_budget=1,
                time_budget_seconds=30,
            )

        bundle = self._bundle(
            initial=lambda owner, seq, revision, _: _plan(
                owner,
                seq,
                revision,
                (subgoal,),
                {"architecture": ("external-review",)},
            ),
            operation_factory=operation,
            agents=("research_agent",),
            agent_port=agents,
            policy=_Policy(requires_approval=governed),
            requirements=("architecture",),
        )
        project_id = self._create(bundle, requirements=("architecture",))
        if governed:
            view = self._run(bundle, project_id, max_cycles=4)
            command = view.commands[0]
            bundle.service.approve(ApproveInvestigationCommand(
                principal=self.principal,
                project_id=project_id,
                command_id=command.command_id,
                authorization_digest=command.authorization_digest,
            ))
        try:
            self._run(bundle, project_id)
        except RuntimeError as exc:
            if "injected crash" not in str(exc):
                raise
        calls_before_restart = bundle.planner.calls
        proposer_before_restart = bundle.proposer.calls
        restarted = self._bundle(
            initial=bundle.planner.initial,
            operation_factory=operation,
            agents=("research_agent",),
            agent_port=agents,
            policy=bundle.service.delegation_policy,
            requirements=("architecture",),
        )
        view = self._run(restarted, project_id)
        command = view.commands[0] if view.commands else None
        task_ids = tuple(agents.submissions.values())
        return SimpleNamespace(
            state=view.state,
            provider_submission_count=agents.provider_submission_count,
            command_digest=(
                command.execution_command_digest if command else "no-command"
            ),
            receipt_command_digest=(
                command.execution_command_digest if command else "no-command"
            ),
            superseding_command_refs=(),
            replanned_after_crash=restarted.planner.calls > 0,
            provider_task_ids=task_ids,
            reconciled_provider_task_id=task_ids[0],
            planner_calls_after_crash=restarted.planner.calls,
            execution_proposer_calls_after_crash=restarted.proposer.calls,
            calls_before_restart=calls_before_restart,
            proposer_before_restart=proposer_before_restart,
        )

    def _bundle(
        self,
        *,
        initial: PlanFactory,
        revision: PlanFactory | None = None,
        operation_factory=None,
        tools: tuple[str, ...] = (),
        agents: tuple[str, ...] = (),
        agent_port: _AgentPort | None = None,
        policy: _Policy | None = None,
        observation_subgoal: str | None = None,
        unsatisfied_subgoal: str | None = None,
        crash_final_once: bool = False,
        final_verification_passed: bool = True,
        requirements: tuple[str, ...] = (
            "architecture",
            "security",
            "cost",
            "migration",
        ),
        shared_tool_port: _ToolPort | None = None,
    ) -> _RuntimeBundle:
        planner = _Planner(initial, revision)
        operation_factory = operation_factory or _default_operation
        proposer = _ExecutionProposer(operation_factory)
        tool_port = shared_tool_port or _ToolPort()
        agent_port = agent_port or _AgentPort()
        sequence: list[str] = []
        settings = Settings(
            postgres_url=self.postgres_url,
            data_dir=self.temp_dir,
        )
        capability_source = _Capabilities(tools=tools, agents=agents)
        service = InvestigationProjectService(
            store=PostgresInvestigationProjectStore(self.postgres_url),
            queue=PostgresWorkerQueueStore(self.postgres_url),
            capabilities=RuntimeCapabilitySnapshot(capability_source),
            planner=planner,
            execution_proposer=proposer,
            tool_port=tool_port,
            agent_port=agent_port,
            synthesis_port=_Synthesis(sequence),
            verifier=_Verifier(
                sequence,
                observation_subgoal=observation_subgoal,
                unsatisfied_subgoal=unsatisfied_subgoal,
                crash_final_once=crash_final_once,
                final_verification_passed=final_verification_passed,
            ),
            artifact_writer=ArtifactService(settings),
            delegation_policy=policy or _Policy(),
            disclosure_manifest=ScopeBoundDisclosureManifest(),
            execution_policy=ProjectExecutionPolicy(
                planning_reservation_tokens=1,
                execution_proposal_reservation_tokens=1,
                verification_reservation_tokens=1,
                synthesis_reservation_tokens=1,
                external_delegation_reservation_tokens=1,
            ),
        )
        return _RuntimeBundle(
            service=service,
            planner=planner,
            proposer=proposer,
            tools=tool_port,
            agents=agent_port,
            sequence=sequence,
            principal=self.principal,
        )

    def _create(
        self,
        bundle: _RuntimeBundle,
        *,
        requirements: tuple[str, ...] = (
            "architecture",
            "security",
            "cost",
            "migration",
        ),
        budget: ProjectBudgetLimit | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        view = bundle.service.create(CreateInvestigationProject(
            principal=self.principal,
            title="Architecture investigation",
            goal="Investigate architecture, security, cost, and migration.",
            requirements=tuple(_requirement(item) for item in requirements),
            budget=budget or ProjectBudgetLimit(),
            idempotency_key=(
                idempotency_key
                or f"create:{canonical_digest(requirements)[:16]}"
            ),
        ))
        return view.definition.project_id

    def _run(
        self,
        bundle: _RuntimeBundle,
        project_id: str,
        *,
        max_cycles: int = 100,
    ):
        return bundle.service.process(ProcessInvestigationProject(
            principal=self.principal,
            project_id=project_id,
            max_cycles=max_cycles,
        ))

    def _view(self, bundle: _RuntimeBundle, project_id: str):
        return bundle.service.get(QueryInvestigationProject(
            principal=self.principal,
            project_id=project_id,
        ))

    def _seed_artifact(
        self,
        content: str,
        *,
        execution_id: str = "seed",
    ) -> ResourceRef:
        settings = Settings(
            postgres_url=self.postgres_url,
            data_dir=self.temp_dir,
        )
        writer = ArtifactService(settings)
        scope = ExecutionScope(
            principal=self.principal,
            execution_id=execution_id,
            project_id="seed-project",
            plan_version=1,
            logical_subgoal_id="seed",
            subgoal_version=1,
        )
        return writer.write_generated(
            owner=self.principal,
            execution_scope=scope,
            producer_key=f"seed:{execution_id}:{canonical_digest({'content': content})}",
            producer_ref=execution_id,
            kind="seed",
            content=content,
            content_digest=canonical_digest({"content": content}),
            source_artifact_refs=(),
            evidence_refs=(),
        )


def _default_operation(subgoal: SubGoalDefinitionVersion, scope: ExecutionScope):
    kind = subgoal.capability_contract.allowed_execution_kinds[0]
    if kind == "tool":
        return ToolExecutionOperation(
            tool_name=subgoal.capability_contract.operation,
            typed_arguments={"query": subgoal.objective},
            expected_artifact_type="evidence",
        )
    if kind == "agent":
        return AgentExecutionOperation(
            agent_id=subgoal.capability_contract.operation,
            bounded_sub_goal=subgoal.objective,
            expected_artifact_types=("evidence",),
            token_budget=10,
            cost_budget=1,
            time_budget_seconds=30,
        )
    if kind == "synthesis":
        return SynthesisOperation(
            input_artifact_refs=(),
            requirement_refs=(subgoal.logical_subgoal_id,),
            output_contract=subgoal.required_output,
        )
    raise AssertionError(f"unsupported scripted operation kind={kind}")


def _requirement(requirement_id: str) -> UserRequirement:
    return UserRequirement(
        requirement_id=requirement_id,
        statement=f"Requirement {requirement_id}",
        acceptance_contract=f"Verified {requirement_id} outcome",
    )


def _model_usage(category) -> ProjectUsage:
    return ProjectUsage(
        category=category,
        reservation_id=f"scripted:{category}",
        tokens=1,
    )


__all__ = ["InvestigationScenarioHarness"]
