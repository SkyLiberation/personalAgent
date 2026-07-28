"""Deterministic admission checks for semantic Project proposals."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from personal_agent.capabilities.inventory import RuntimeCapabilityInventory
from personal_agent.domain.investigation_project import (
    AcceptedPlanVersion,
    EvidenceAdmissionDecision,
    EvidenceRef,
    InvestigationProject,
    PlanProposal,
    SubGoalDefinitionVersion,
    SubGoalExecutionProposal,
    canonical_digest,
)
from personal_agent.kernel.contracts.scope import ExecutionScope


@dataclass(frozen=True, slots=True)
class DecisionFeedback:
    reason: str
    repairable_fields: tuple[str, ...] = ()
    immutable_fields: tuple[str, ...] = ()
    required_repair: str = ""
    revision_scope: tuple[str, ...] = ()
    disposition: str = "semantic_rejection"


class ProposalRejected(ValueError):
    def __init__(self, feedback: DecisionFeedback) -> None:
        super().__init__(feedback.reason)
        self.feedback = feedback


def subgoal_definition_digest(subgoal: SubGoalDefinitionVersion) -> str:
    return canonical_digest({
        "logical_subgoal_id": subgoal.logical_subgoal_id,
        "subgoal_version": subgoal.subgoal_version,
        "supersedes_version": subgoal.supersedes_version,
        "objective": subgoal.objective,
        "depends_on": subgoal.depends_on,
        "required_output": subgoal.required_output,
        "capability_contract": subgoal.capability_contract.model_dump(mode="json"),
    })


def plan_proposal_digest(proposal: PlanProposal) -> str:
    return canonical_digest(proposal)


class PlanAdmission:
    def accept(
        self,
        project: InvestigationProject,
        proposal: PlanProposal,
    ) -> AcceptedPlanVersion | None:
        if proposal.project_id != project.definition.project_id:
            self._reject("proposal project binding mismatch", immutable=("project_id",))
        if proposal.based_on_event_sequence != project.event_sequence:
            self._reject(
                "proposal is based on a stale project sequence",
                repairable=("based_on_event_sequence",),
            )
        self._validate_subgoals(proposal)
        self._validate_requirements(project, proposal)
        self._validate_frozen_boundary(project, proposal)
        digest = plan_proposal_digest(proposal)
        if project.accepted_plan and project.accepted_plan.plan_digest == digest:
            return None
        return AcceptedPlanVersion(
            plan_version=(project.accepted_plan.plan_version + 1 if project.accepted_plan else 1),
            proposal=proposal,
            plan_digest=digest,
        )

    def _validate_subgoals(self, proposal: PlanProposal) -> None:
        subgoals = {item.logical_subgoal_id: item for item in proposal.subgoals}
        if len(subgoals) != len(proposal.subgoals):
            self._reject("logical subgoal ids must be unique", repairable=("subgoals",))
        for subgoal in proposal.subgoals:
            if not subgoal.capability_contract.operation.strip():
                self._reject(
                    "subgoal capability contract requires an operation",
                    repairable=(subgoal.logical_subgoal_id,),
                )
            if subgoal.definition_digest != subgoal_definition_digest(subgoal):
                self._reject(
                    "subgoal definition digest mismatch",
                    repairable=(subgoal.logical_subgoal_id,),
                )
            unknown = set(subgoal.depends_on) - set(subgoals)
            if unknown:
                self._reject(
                    f"subgoal depends on unknown ids: {sorted(unknown)}",
                    repairable=(subgoal.logical_subgoal_id,),
                )
            if subgoal.logical_subgoal_id in subgoal.depends_on:
                self._reject(
                    "subgoal cannot depend on itself",
                    repairable=(subgoal.logical_subgoal_id,),
                )
        indegree = {item.logical_subgoal_id: 0 for item in proposal.subgoals}
        downstream: dict[str, list[str]] = defaultdict(list)
        for item in proposal.subgoals:
            for dependency in item.depends_on:
                indegree[item.logical_subgoal_id] += 1
                downstream[dependency].append(item.logical_subgoal_id)
        queue = deque(key for key, value in indegree.items() if value == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for child in downstream[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if visited != len(indegree):
            self._reject("plan dependencies must form a DAG", repairable=("subgoals",))

    def _validate_requirements(
        self,
        project: InvestigationProject,
        proposal: PlanProposal,
    ) -> None:
        required = {
            item.requirement_id
            for item in project.user_requirements.requirements
            if item.status == "active"
        }
        required.update(
            item.requirement_id
            for item in proposal.derived_requirements
            if item.completion_relevance == "required"
        )
        mapped = {item.requirement_id for item in proposal.requirement_mappings}
        missing = required - mapped
        if missing:
            self._reject(
                f"required requirements are not mapped: {sorted(missing)}",
                repairable=("requirement_mappings",),
                immutable=tuple(sorted(
                    item.requirement_id
                    for item in project.user_requirements.requirements
                )),
            )
        active_subgoals = {item.logical_subgoal_id for item in proposal.subgoals}
        for mapping in proposal.requirement_mappings:
            unknown = set(mapping.logical_subgoal_ids) - active_subgoals
            if unknown:
                self._reject(
                    f"requirement mapping references inactive subgoals: {sorted(unknown)}",
                    repairable=(mapping.requirement_id,),
                )

    def _validate_frozen_boundary(
        self,
        project: InvestigationProject,
        proposal: PlanProposal,
    ) -> None:
        if project.accepted_plan is None:
            return
        previous = {
            item.logical_subgoal_id: item
            for item in project.accepted_plan.proposal.subgoals
        }
        proposed = {item.logical_subgoal_id: item for item in proposal.subgoals}
        frozen_keys = (
            set(project.outcomes)
            | set(project.execution_refs)
            | set(project.accepted_execution_proposals)
            | set(project.agent_runs)
        )
        for logical_id, version in frozen_keys:
            old = previous.get(logical_id)
            new = proposed.get(logical_id)
            if old is None:
                continue
            if new is None or new.subgoal_version != version or new.definition_digest != old.definition_digest:
                self._reject(
                    "plan revision cannot overwrite frozen work",
                    immutable=(logical_id,),
                    revision_scope=tuple(
                        item.logical_subgoal_id
                        for item in proposal.subgoals
                        if item.logical_subgoal_id != logical_id
                    ),
                )
        for logical_id, new in proposed.items():
            old = previous.get(logical_id)
            if old is None:
                continue
            definition_changed = new.definition_digest != old.definition_digest
            if not definition_changed and (
                new.subgoal_version != old.subgoal_version
                or new.supersedes_version != old.supersedes_version
            ):
                self._reject(
                    "unchanged subgoal must retain logical id, version, and digest",
                    repairable=(logical_id,),
                )
            if definition_changed and (
                new.subgoal_version != old.subgoal_version + 1
                or new.supersedes_version != old.subgoal_version
            ):
                self._reject(
                    "changed subgoal must create the next version and supersede the old version",
                    repairable=(logical_id,),
                )

    @staticmethod
    def _reject(
        reason: str,
        *,
        repairable: tuple[str, ...] = (),
        immutable: tuple[str, ...] = (),
        revision_scope: tuple[str, ...] = (),
    ) -> None:
        raise ProposalRejected(DecisionFeedback(
            reason=reason,
            repairable_fields=repairable,
            immutable_fields=immutable,
            required_repair=reason,
            revision_scope=revision_scope,
        ))


class ExecutionProposalAdmission:
    def accept(
        self,
        project: InvestigationProject,
        subgoal: SubGoalDefinitionVersion,
        proposal: SubGoalExecutionProposal,
        *,
        execution_scope: ExecutionScope,
        capabilities: RuntimeCapabilityInventory,
    ) -> SubGoalExecutionProposal:
        plan = project.accepted_plan
        if plan is None:
            raise ProposalRejected(DecisionFeedback("project has no accepted plan"))
        expected = (
            project.definition.project_id,
            plan.plan_version,
            subgoal.logical_subgoal_id,
            subgoal.subgoal_version,
            project.event_sequence,
        )
        actual = (
            proposal.project_id,
            proposal.plan_version,
            proposal.logical_subgoal_id,
            proposal.subgoal_version,
            proposal.based_on_event_sequence,
        )
        if actual != expected:
            raise ProposalRejected(DecisionFeedback(
                "execution proposal binding is stale or mismatched",
                repairable_fields=("binding",),
                immutable_fields=("project_id", "plan_version", "logical_subgoal_id"),
            ))
        if proposal.proposal_digest != canonical_digest({
            "project_id": proposal.project_id,
            "plan_version": proposal.plan_version,
            "logical_subgoal_id": proposal.logical_subgoal_id,
            "subgoal_version": proposal.subgoal_version,
            "based_on_event_sequence": proposal.based_on_event_sequence,
            "proposal_id": proposal.proposal_id,
            "operation": proposal.operation.model_dump(mode="json"),
        }):
            raise ProposalRejected(DecisionFeedback(
                "execution proposal digest mismatch",
                repairable_fields=("proposal_digest",),
            ))
        if proposal.operation.kind not in subgoal.capability_contract.allowed_execution_kinds:
            raise ProposalRejected(DecisionFeedback(
                "execution kind is outside the accepted capability contract",
                repairable_fields=("operation",),
            ))
        if proposal.operation.kind == "tool":
            available = {
                item.tool_name
                for item in capabilities.local_tools
                if item.configuration_state == "enabled"
            } | {
                item.local_tool_name
                for item in capabilities.mcp_connectors
                if item.configuration_state == "enabled"
                and item.discovery_state == "discovered"
            }
            if proposal.operation.tool_name not in available:
                raise ProposalRejected(DecisionFeedback(
                    f"capability missing: {subgoal.capability_contract.operation}",
                    disposition="capability_missing",
                ))
        elif proposal.operation.kind == "agent":
            available_agents = {
                item.agent_id
                for item in capabilities.a2a_agents
                if item.implementation_present
                and item.configuration_state == "enabled"
                and item.discovery_state == "registered_profile"
            }
            if proposal.operation.agent_id not in available_agents:
                raise ProposalRejected(DecisionFeedback(
                    f"capability missing: {subgoal.capability_contract.operation}",
                    disposition="capability_missing",
                ))
        if execution_scope.project_id != project.definition.project_id:
            raise ProposalRejected(DecisionFeedback(
                "execution scope project binding mismatch",
                immutable_fields=("execution_scope",),
            ))
        return proposal


class EvidenceAdmission:
    def decide(
        self,
        project: InvestigationProject,
        evidence: EvidenceRef,
    ) -> EvidenceAdmissionDecision:
        known_execution = any(
            current.execution_id == evidence.execution_ref.execution_id
            and current.execution_digest == evidence.execution_ref.execution_digest
            for current in project.execution_refs.values()
        )
        scope_matches = (
            evidence.artifact_ref is None
            or evidence.artifact_ref.owner_scope == project.definition.security_scope
        )
        admitted = known_execution and scope_matches and bool(evidence.content_digest)
        reason = ""
        if not known_execution:
            reason = "execution ref is not committed by its owner"
        elif not scope_matches:
            reason = "artifact belongs to a different security scope"
        return EvidenceAdmissionDecision(
            evidence_ref=evidence,
            admitted=admitted,
            reason=reason,
        )


__all__ = [
    "DecisionFeedback",
    "EvidenceAdmission",
    "ExecutionProposalAdmission",
    "PlanAdmission",
    "ProposalRejected",
    "plan_proposal_digest",
    "subgoal_definition_digest",
]

