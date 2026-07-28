"""Structured-model implementations of Project semantic decision ports."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.investigation_project.admission import (
    subgoal_definition_digest,
)
from personal_agent.application.investigation_project.ports import (
    GeneratedContent,
    ModelDecision,
)
from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.capabilities.inventory import RuntimeCapabilityInventory
from personal_agent.domain.investigation_project import (
    AgentExecutionOperation,
    CapabilityContract,
    DerivedRequirement,
    InvestigationProject,
    InvestigationProjectDefinition,
    PlanAssumption,
    PlanProposal,
    ProjectUsage,
    ReplanRequest,
    RequirementMapping,
    SubGoalDefinitionVersion,
    SubGoalExecutionProposal,
    SubGoalVerificationAssessment,
    SynthesisOperation,
    ToolExecutionOperation,
    UserInputOperation,
    canonical_digest,
    new_proposal_id,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _SubGoalDraft(_Model):
    logical_subgoal_id: str
    subgoal_version: int = Field(ge=1)
    supersedes_version: int | None = Field(default=None, ge=1)
    objective: str
    depends_on: tuple[str, ...] = ()
    required_output: str
    capability_contract: CapabilityContract


class _PlanDraft(_Model):
    assumptions: tuple[PlanAssumption, ...] = ()
    derived_requirements: tuple[DerivedRequirement, ...] = ()
    subgoals: tuple[_SubGoalDraft, ...]
    requirement_mappings: tuple[RequirementMapping, ...]


class _ToolOperationDraft(_Model):
    kind: Literal["tool"]
    tool_name: str
    typed_arguments: dict[str, Any]
    expected_artifact_type: str


class _AgentOperationDraft(_Model):
    kind: Literal["agent"]
    agent_id: str
    bounded_sub_goal: str
    context_artifact_refs: tuple[ResourceRef, ...] = ()
    expected_artifact_types: tuple[str, ...]
    token_budget: int = Field(ge=0)
    cost_budget: float = Field(ge=0)
    time_budget_seconds: int = Field(ge=1)


class _SynthesisOperationDraft(_Model):
    kind: Literal["synthesis"]
    input_artifact_refs: tuple[ResourceRef, ...] = ()
    requirement_refs: tuple[str, ...]
    output_contract: str


class _UserInputOperationDraft(_Model):
    kind: Literal["user_input"]
    question: str
    required_fields: tuple[str, ...] = ()


_OperationDraft = Annotated[
    _ToolOperationDraft
    | _AgentOperationDraft
    | _SynthesisOperationDraft
    | _UserInputOperationDraft,
    Field(discriminator="kind"),
]


class _ExecutionDraft(_Model):
    operation: _OperationDraft


class _ObservationDraft(_Model):
    statement: str
    evidence_refs: tuple[str, ...]
    contradicted_assumption_ids: tuple[str, ...] = ()
    affected_logical_subgoal_ids: tuple[str, ...] = ()


class _VerificationDraft(_Model):
    satisfied: bool
    evidence_refs: tuple[str, ...] = ()
    feedback: str = ""
    observations: tuple[_ObservationDraft, ...] = ()


class _GeneratedContentDraft(_Model):
    content: str
    evidence_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class _FinalVerificationDraft(_Model):
    passed: bool
    feedback: str = ""


def _inventory_payload(inventory: RuntimeCapabilityInventory) -> dict[str, Any]:
    return inventory.model_dump(mode="json")


def _usage(response, category) -> ProjectUsage:
    return ProjectUsage(
        category=category,
        reservation_id=f"model-port:{uuid4().hex[:16]}",
        tokens=max(0, int(response.total_tokens or 0)),
        estimated=response.total_tokens is None,
    )


def _request(
    *,
    operation: str,
    output_type,
    system: str,
    payload: dict[str, Any],
    max_tokens: int,
) -> StructuredModelRequest:
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        },
    ]
    return StructuredModelRequest(
        operation=operation,
        version="v1",
        messages=messages,
        output_type=output_type,
        context_projection_ref=sealed_context_projection_ref(
            purpose=operation,
            messages=messages,
        ),
        temperature=0,
        max_tokens=max_tokens,
    )


class StructuredInvestigationPlanner:
    def __init__(self, model: StructuredModelClient) -> None:
        self._model = model

    def propose_initial(
        self,
        definition: InvestigationProjectDefinition,
        *,
        based_on_event_sequence: int,
        capabilities: RuntimeCapabilityInventory,
        capability_revision: str,
    ) -> ModelDecision[PlanProposal]:
        response = self._model.generate(_request(
            operation="investigation_project_plan",
            output_type=_PlanDraft,
            system=(
                "You are the semantic Planner. Preserve every active user requirement. "
                "Return dynamic subgoals, dependencies, required outputs and capability "
                "contracts. Do not choose tools, agents, providers, authorization, state, "
                "or completion."
            ),
            payload={
                "project_id": definition.project_id,
                "goal": definition.goal,
                "user_requirements": definition.user_requirements.model_dump(mode="json"),
                "capabilities": _inventory_payload(capabilities),
                "capability_revision": capability_revision,
            },
            max_tokens=3000,
        ))
        proposal = self._materialize(
            response.value,
            project_id=definition.project_id,
            based_on_event_sequence=based_on_event_sequence,
            capability_revision=capability_revision,
            revision_reason="initial",
        )
        return ModelDecision(proposal, _usage(response, "planning"))

    def propose_revision(
        self,
        project: InvestigationProject,
        request: ReplanRequest,
        *,
        capabilities: RuntimeCapabilityInventory,
        capability_revision: str,
    ) -> ModelDecision[PlanProposal]:
        response = self._model.generate(_request(
            operation="investigation_project_replan",
            output_type=_PlanDraft,
            system=(
                "Revise only the allowed unfrozen Project scope. Reuse unchanged logical "
                "subgoal ids, versions and definitions; changed definitions increment the "
                "version and supersede the prior one. Never modify user requirements, "
                "completed outcomes, accepted executions, commands, or receipts."
            ),
            payload={
                "project": project.to_view().model_dump(mode="json"),
                "replan_request": request.model_dump(mode="json"),
                "capabilities": _inventory_payload(capabilities),
                "capability_revision": capability_revision,
            },
            max_tokens=3500,
        ))
        proposal = self._materialize(
            response.value,
            project_id=project.definition.project_id,
            based_on_event_sequence=project.event_sequence,
            capability_revision=capability_revision,
            revision_reason=request.request_id,
        )
        return ModelDecision(proposal, _usage(response, "planning"))

    @staticmethod
    def _materialize(
        draft: _PlanDraft,
        *,
        project_id: str,
        based_on_event_sequence: int,
        capability_revision: str,
        revision_reason: str,
    ) -> PlanProposal:
        subgoals = []
        for item in draft.subgoals:
            temporary = SubGoalDefinitionVersion(
                **item.model_dump(),
                definition_digest="0" * 64,
            )
            subgoals.append(temporary.model_copy(
                update={"definition_digest": subgoal_definition_digest(temporary)}
            ))
        return PlanProposal(
            project_id=project_id,
            based_on_event_sequence=based_on_event_sequence,
            capability_snapshot_revision=capability_revision,
            revision_reason=revision_reason,
            assumptions=draft.assumptions,
            derived_requirements=draft.derived_requirements,
            subgoals=tuple(subgoals),
            requirement_mappings=draft.requirement_mappings,
        )


class StructuredExecutionProposer:
    def __init__(self, model: StructuredModelClient) -> None:
        self._model = model

    def propose(
        self,
        project: InvestigationProject,
        subgoal: SubGoalDefinitionVersion,
        *,
        execution_scope: ExecutionScope,
        capabilities: RuntimeCapabilityInventory,
    ) -> ModelDecision[SubGoalExecutionProposal]:
        response = self._model.generate(_request(
            operation="investigation_subgoal_execution_proposal",
            output_type=_ExecutionDraft,
            system=(
                "Select one concrete operation from the supplied effective capabilities. "
                "Return its complete typed payload. Do not invent capabilities, modify the "
                "accepted subgoal, grant authorization, or claim execution/completion."
            ),
            payload={
                "project_goal": project.definition.goal,
                "subgoal": subgoal.model_dump(mode="json"),
                "admitted_evidence": [
                    item.model_dump(mode="json")
                    for item in project.admitted_evidence.values()
                ],
                "capabilities": _inventory_payload(capabilities),
                "execution_scope": execution_scope.model_dump(mode="json"),
            },
            max_tokens=1600,
        ))
        operation = _operation_from_draft(response.value.operation)
        proposal_id = new_proposal_id()
        binding = {
            "project_id": project.definition.project_id,
            "plan_version": project.accepted_plan.plan_version,
            "logical_subgoal_id": subgoal.logical_subgoal_id,
            "subgoal_version": subgoal.subgoal_version,
            "based_on_event_sequence": project.event_sequence,
            "proposal_id": proposal_id,
            "operation": operation.model_dump(mode="json"),
        }
        proposal = SubGoalExecutionProposal(
            **binding,
            proposal_digest=canonical_digest(binding),
        )
        return ModelDecision(proposal, _usage(response, "execution_proposal"))


class StructuredProjectVerifier:
    def __init__(self, model: StructuredModelClient) -> None:
        self._model = model

    def verify_subgoal(
        self,
        project: InvestigationProject,
        subgoal: SubGoalDefinitionVersion,
        evidence: tuple,
        *,
        execution_scope: ExecutionScope,
    ) -> ModelDecision[SubGoalVerificationAssessment]:
        response = self._model.generate(_request(
            operation="investigation_subgoal_verification",
            output_type=_VerificationDraft,
            system=(
                "Judge whether admitted evidence semantically satisfies the accepted "
                "subgoal and required output. Use only evidence ids supplied. Do not "
                "override execution facts or authorization."
            ),
            payload={
                "subgoal": subgoal.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "execution_scope": execution_scope.model_dump(mode="json"),
            },
            max_tokens=1000,
        ))
        value = response.value
        assessment_payload = {
            "logical_subgoal_id": subgoal.logical_subgoal_id,
            "subgoal_version": subgoal.subgoal_version,
            "satisfied": value.satisfied,
            "evidence_refs": value.evidence_refs,
            "feedback": value.feedback,
            "observations": [
                {
                    **item.model_dump(mode="python"),
                    "observation_digest": canonical_digest(item.model_dump(mode="json")),
                }
                for item in value.observations
            ],
        }
        assessment = SubGoalVerificationAssessment(
            **assessment_payload,
            assessment_digest=canonical_digest(assessment_payload),
        )
        return ModelDecision(assessment, _usage(response, "semantic_verification"))

    def verify_final(
        self,
        project: InvestigationProject,
        generated: GeneratedContent,
        *,
        execution_scope: ExecutionScope,
    ) -> ModelDecision[bool]:
        response = self._model.generate(_request(
            operation="investigation_final_report_verification",
            output_type=_FinalVerificationDraft,
            system=(
                "Verify that the report covers every active required contract, maps claims "
                "to admitted evidence, and states limitations. Return passed=false for any "
                "unsupported claim or missing required coverage."
            ),
            payload={
                "requirements": project.user_requirements.model_dump(mode="json"),
                "coverage": project.requirement_coverage(),
                "report": generated.content,
                "evidence_refs": generated.evidence_refs,
                "execution_scope": execution_scope.model_dump(mode="json"),
            },
            max_tokens=900,
        ))
        return ModelDecision(
            response.value.passed,
            _usage(response, "semantic_verification"),
        )


class StructuredProjectSynthesis:
    def __init__(self, model: StructuredModelClient) -> None:
        self._model = model

    def synthesize_subgoal(
        self,
        project: InvestigationProject,
        proposal: SubGoalExecutionProposal,
        *,
        execution_scope: ExecutionScope,
    ) -> ModelDecision[GeneratedContent]:
        response = self._model.generate(_request(
            operation="investigation_subgoal_synthesis",
            output_type=_GeneratedContentDraft,
            system=(
                "Synthesize the requested bounded output from admitted evidence only. "
                "Return every supporting evidence id and explicit limitations."
            ),
            payload={
                "operation": proposal.operation.model_dump(mode="json"),
                "admitted_evidence": [
                    item.model_dump(mode="json")
                    for item in project.admitted_evidence.values()
                ],
                "execution_scope": execution_scope.model_dump(mode="json"),
            },
            max_tokens=2200,
        ))
        generated = _generated(response.value)
        return ModelDecision(generated, _usage(response, "synthesis"))

    def synthesize_final(
        self,
        project: InvestigationProject,
        plan,
        *,
        execution_scope: ExecutionScope,
    ) -> ModelDecision[GeneratedContent]:
        response = self._model.generate(_request(
            operation="investigation_final_report_synthesis",
            output_type=_GeneratedContentDraft,
            system=(
                "Create the final investigation report. Cover every active required "
                "contract, cite only admitted evidence ids, preserve uncertainty, and "
                "include limitations. Do not claim completion."
            ),
            payload={
                "goal": project.definition.goal,
                "requirements": project.user_requirements.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json"),
                "outcomes": [
                    item.model_dump(mode="json")
                    for item in project.outcomes.values()
                ],
                "admitted_evidence": [
                    item.model_dump(mode="json")
                    for item in project.admitted_evidence.values()
                ],
                "execution_scope": execution_scope.model_dump(mode="json"),
            },
            max_tokens=4000,
        ))
        generated = _generated(response.value)
        return ModelDecision(generated, _usage(response, "synthesis"))


class UnavailableInvestigationModelPorts(
    StructuredInvestigationPlanner,
    StructuredExecutionProposer,
    StructuredProjectVerifier,
    StructuredProjectSynthesis,
):
    def __init__(self) -> None:
        pass

    def __getattribute__(self, name: str):
        if name.startswith("propose") or name.startswith("verify") or name.startswith("synthesize"):
            raise RuntimeError("structured model capability is not configured")
        return super().__getattribute__(name)


def _operation_from_draft(draft):
    payload = draft.model_dump(mode="python")
    return {
        "tool": ToolExecutionOperation,
        "agent": AgentExecutionOperation,
        "synthesis": SynthesisOperation,
        "user_input": UserInputOperation,
    }[draft.kind](**payload)


def _generated(value: _GeneratedContentDraft) -> GeneratedContent:
    return GeneratedContent(
        content=value.content,
        content_digest=canonical_digest({"content": value.content}),
        evidence_refs=value.evidence_refs,
        limitations=value.limitations,
    )


__all__ = [
    "StructuredExecutionProposer",
    "StructuredInvestigationPlanner",
    "StructuredProjectSynthesis",
    "StructuredProjectVerifier",
    "UnavailableInvestigationModelPorts",
]
