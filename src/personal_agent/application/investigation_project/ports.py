"""Ports required by the Investigation Project application service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from personal_agent.capabilities.inventory import RuntimeCapabilityInventory
from personal_agent.domain.investigation_project import (
    AcceptedPlanVersion,
    EvidenceRef,
    DisclosureManifest,
    ExecutionRef,
    InvestigationProject,
    InvestigationProjectDefinition,
    PlanProposal,
    ProjectEvent,
    ProjectUsage,
    ReplanRequest,
    SubGoalDefinitionVersion,
    SubGoalExecutionProposal,
    SubGoalVerificationAssessment,
)
from personal_agent.kernel.contracts.resource import GeneratedArtifactContent, ResourceRef
from personal_agent.kernel.contracts.scope import (
    ExecutionScope,
    AuthenticatedPrincipal,
)


T = TypeVar("T")


class ProjectAgentOutcomeUnknown(RuntimeError):
    """A child submission may exist, but no safe provider binding is known."""


@dataclass(frozen=True, slots=True)
class ModelDecision(Generic[T]):
    value: T
    usage: ProjectUsage


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    execution_ref: ExecutionRef
    evidence: tuple[EvidenceRef, ...]
    artifact_refs: tuple[ResourceRef, ...] = ()
    usage: ProjectUsage | None = None
    pending: bool = False
    provider_task_ref: str | None = None
    submission_key: str | None = None


@dataclass(frozen=True, slots=True)
class GeneratedContent:
    content: str
    content_digest: str
    evidence_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FinalVerificationResult:
    passed: bool
    feedback: str = ""


@dataclass(frozen=True, slots=True)
class EvidenceMaterial:
    reference: EvidenceRef
    content: str


class InvestigationProjectStorePort(Protocol):
    def create(self, definition: InvestigationProjectDefinition) -> InvestigationProject: ...

    def load(
        self,
        owner: AuthenticatedPrincipal,
        project_id: str,
    ) -> InvestigationProject | None: ...

    def append(
        self,
        *,
        owner: AuthenticatedPrincipal,
        project_id: str,
        expected_sequence: int,
        events: tuple[ProjectEvent, ...],
    ) -> InvestigationProject: ...

    def list_recoverable(
        self,
        *,
        limit: int = 100,
    ) -> tuple[InvestigationProject, ...]: ...


class CapabilitySnapshotPort(Protocol):
    def snapshot(self, owner: AuthenticatedPrincipal) -> RuntimeCapabilityInventory: ...

    def revision(self, inventory: RuntimeCapabilityInventory) -> str: ...


class InvestigationPlannerPort(Protocol):
    def propose_initial(
        self,
        definition: InvestigationProjectDefinition,
        *,
        based_on_event_sequence: int,
        repair_request: ReplanRequest | None,
        capabilities: RuntimeCapabilityInventory,
        capability_revision: str,
    ) -> ModelDecision[PlanProposal]: ...

    def propose_revision(
        self,
        project: InvestigationProject,
        request: ReplanRequest,
        *,
        evidence_material: tuple[EvidenceMaterial, ...],
        capabilities: RuntimeCapabilityInventory,
        capability_revision: str,
    ) -> ModelDecision[PlanProposal]: ...


class ExecutionProposerPort(Protocol):
    def propose(
        self,
        project: InvestigationProject,
        subgoal: SubGoalDefinitionVersion,
        *,
        evidence_material: tuple[EvidenceMaterial, ...],
        execution_scope: ExecutionScope,
        capabilities: RuntimeCapabilityInventory,
    ) -> ModelDecision[SubGoalExecutionProposal]: ...


class ProjectToolPort(Protocol):
    def execute(
        self,
        proposal: SubGoalExecutionProposal,
        *,
        execution_scope: ExecutionScope,
    ) -> ExecutionResult: ...


class ProjectAgentPort(Protocol):
    def submit_or_reconcile(
        self,
        proposal: SubGoalExecutionProposal,
        *,
        execution_scope: ExecutionScope,
        submission_key: str,
        authorization_digest: str | None = None,
        execution_command_digest: str | None = None,
    ) -> ExecutionResult: ...

    def cancel(
        self,
        agent_run_id: str,
        *,
        execution_scope: ExecutionScope,
    ) -> tuple[ResourceRef, ...]: ...


@dataclass(frozen=True, slots=True)
class DelegationPolicyDecision:
    allowed: bool
    requires_approval: bool
    authorization_digest: str
    reason: str = ""


class ProjectDelegationPolicyPort(Protocol):
    def evaluate(
        self,
        proposal: SubGoalExecutionProposal,
        *,
        execution_scope: ExecutionScope,
    ) -> DelegationPolicyDecision: ...


class DisclosureManifestPort(Protocol):
    def materialize(
        self,
        artifact_refs: tuple[ResourceRef, ...],
        *,
        owner: AuthenticatedPrincipal,
        execution_scope: ExecutionScope,
    ) -> DisclosureManifest: ...


class ProjectSynthesisPort(Protocol):
    def synthesize_subgoal(
        self,
        project: InvestigationProject,
        proposal: SubGoalExecutionProposal,
        *,
        evidence_material: tuple[EvidenceMaterial, ...],
        execution_scope: ExecutionScope,
    ) -> ModelDecision[GeneratedContent]: ...

    def synthesize_final(
        self,
        project: InvestigationProject,
        plan: AcceptedPlanVersion,
        *,
        evidence_material: tuple[EvidenceMaterial, ...],
        execution_scope: ExecutionScope,
    ) -> ModelDecision[GeneratedContent]: ...


class ProjectVerifierPort(Protocol):
    def verify_subgoal(
        self,
        project: InvestigationProject,
        subgoal: SubGoalDefinitionVersion,
        evidence: tuple[EvidenceRef, ...],
        *,
        evidence_material: tuple[EvidenceMaterial, ...],
        execution_scope: ExecutionScope,
    ) -> ModelDecision[SubGoalVerificationAssessment]: ...

    def verify_final(
        self,
        project: InvestigationProject,
        generated: GeneratedContent,
        *,
        evidence_material: tuple[EvidenceMaterial, ...],
        execution_scope: ExecutionScope,
    ) -> ModelDecision[FinalVerificationResult]: ...


class GeneratedArtifactWritePort(Protocol):
    def write_generated(
        self,
        *,
        owner: AuthenticatedPrincipal,
        execution_scope: ExecutionScope,
        producer_key: str,
        producer_ref: str,
        kind: str,
        content: str,
        content_digest: str,
        source_artifact_refs: tuple[ResourceRef, ...],
        evidence_refs: tuple[str, ...],
        limitations: tuple[str, ...] = (),
    ) -> ResourceRef: ...

    def read_generated(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> GeneratedArtifactContent: ...


__all__ = [
    "CapabilitySnapshotPort",
    "DelegationPolicyDecision",
    "DisclosureManifestPort",
    "EvidenceMaterial",
    "ExecutionProposerPort",
    "ExecutionResult",
    "FinalVerificationResult",
    "GeneratedArtifactWritePort",
    "GeneratedContent",
    "InvestigationPlannerPort",
    "InvestigationProjectStorePort",
    "ModelDecision",
    "ProjectAgentPort",
    "ProjectAgentOutcomeUnknown",
    "ProjectDelegationPolicyPort",
    "ProjectSynthesisPort",
    "ProjectToolPort",
    "ProjectVerifierPort",
]
