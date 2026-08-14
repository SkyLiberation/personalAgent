"""Deterministic admission checks for semantic Project proposals."""

from __future__ import annotations

from collections import defaultdict, deque
import json
import re

from personal_agent.capabilities.inventory import RuntimeCapabilityInventory
from personal_agent.application.investigation_project.capability_matching import (
    contract_has_execution_path,
    matching_execution_inventory,
)
from personal_agent.application.investigation_project.ports import EvidenceMaterial
from personal_agent.domain.investigation_project import (
    AcceptedPlanVersion,
    DecisionFeedback,
    EvidenceAdmissionDecision,
    EvidenceRef,
    InvestigationProject,
    PlanProposal,
    SubGoalDefinitionVersion,
    SubGoalExecutionProposal,
    ToolExecutionOperation,
    canonical_digest,
)
from personal_agent.kernel.contracts.scope import ExecutionScope


class ProposalRejected(ValueError):
    def __init__(self, feedback: DecisionFeedback) -> None:
        super().__init__(feedback.reason)
        self.feedback = feedback


_URL_PATTERN = re.compile(r"https?://[^\s\]\)\"'<>]+")


def observed_url_locators(
    project: InvestigationProject,
    evidence_material: tuple[EvidenceMaterial, ...],
) -> tuple[str, ...]:
    """Return user-supplied or execution-observed URL facts."""
    visible_contract_parts = [project.definition.goal]
    visible_contract_parts.extend(
        f"{item.statement}\n{item.acceptance_contract}"
        for item in project.user_requirements.requirements
        if item.status == "active"
    )
    locators = list(_URL_PATTERN.findall("\n".join(visible_contract_parts)))
    for material in evidence_material:
        try:
            results = json.loads(material.content)["data"]["results"]
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(results, list):
            continue
        locators.extend(
            str(result["url"])
            for result in results
            if (
                isinstance(result, dict)
                and isinstance(result.get("url"), str)
                and result["url"].startswith(("http://", "https://"))
            )
        )
    return tuple(dict.fromkeys(locators))


def subgoal_definition_digest(subgoal: SubGoalDefinitionVersion) -> str:
    payload = {
        "logical_subgoal_id": subgoal.logical_subgoal_id,
        "subgoal_version": subgoal.subgoal_version,
        "supersedes_version": subgoal.supersedes_version,
        "objective": subgoal.objective,
        "depends_on": subgoal.depends_on,
        "required_output": subgoal.required_output,
        "capability_contract": subgoal.capability_contract.model_dump(mode="json"),
    }
    if subgoal.repairs_frozen_subgoals:
        payload["repairs_frozen_subgoals"] = tuple(
            item.model_dump(mode="json")
            for item in subgoal.repairs_frozen_subgoals
        )
    return canonical_digest(payload)


def plan_proposal_digest(proposal: PlanProposal) -> str:
    return canonical_digest(proposal)


def unverified_tool_execution_operations(
    project: InvestigationProject,
    *,
    subgoal_keys: set[tuple[str, int]] | None = None,
) -> tuple[ToolExecutionOperation, ...]:
    return tuple(
        proposal.operation
        for key, proposal in project.accepted_execution_proposals.items()
        if (
            (subgoal_keys is None or key in subgoal_keys)
            and
            key in project.execution_refs
            and key not in project.outcomes
            and proposal.operation.kind == "tool"
        )
    )


def frozen_subgoal_keys(
    project: InvestigationProject,
) -> set[tuple[str, int]]:
    """Return the canonical SubGoal versions bound by accepted execution facts."""
    return (
        set(project.outcomes)
        | set(project.execution_refs)
        | set(project.accepted_execution_proposals)
        | set(project.agent_runs)
    )


def repair_subgoal_logical_id(frozen_logical_subgoal_id: str) -> str:
    return f"{frozen_logical_subgoal_id}-repair"


def execution_evidence_subgoal_keys(
    project: InvestigationProject,
    subgoal: SubGoalDefinitionVersion,
) -> set[tuple[str, int]]:
    """Derive the exact dependency/repair execution boundary for a SubGoal."""
    active_by_id = {
        item.logical_subgoal_id: item
        for item in project.active_plan_subgoals
    }
    active_by_key = {
        (item.logical_subgoal_id, item.subgoal_version): item
        for item in project.active_plan_subgoals
    }
    pending_keys = [
        (item.logical_subgoal_id, item.subgoal_version)
        for item in subgoal.repairs_frozen_subgoals
    ]
    pending_keys.extend(
        (
            active_by_id[logical_id].logical_subgoal_id,
            active_by_id[logical_id].subgoal_version,
        )
        for logical_id in subgoal.depends_on
        if logical_id in active_by_id
    )
    scoped_keys: set[tuple[str, int]] = set()
    while pending_keys:
        key = pending_keys.pop()
        if key in scoped_keys:
            continue
        scoped_keys.add(key)
        related = active_by_key.get(key)
        if related is None:
            continue
        pending_keys.extend(
            (
                repair_ref.logical_subgoal_id,
                repair_ref.subgoal_version,
            )
            for repair_ref in related.repairs_frozen_subgoals
        )
        pending_keys.extend(
            (
                active_by_id[logical_id].logical_subgoal_id,
                active_by_id[logical_id].subgoal_version,
            )
            for logical_id in related.depends_on
            if logical_id in active_by_id
        )
    return scoped_keys


class PlanAdmission:
    def accept(
        self,
        project: InvestigationProject,
        proposal: PlanProposal,
        *,
        capabilities: RuntimeCapabilityInventory,
    ) -> AcceptedPlanVersion | None:
        if proposal.project_id != project.definition.project_id:
            self._reject("proposal project binding mismatch", immutable=("project_id",))
        if proposal.based_on_event_sequence != project.event_sequence:
            self._reject(
                "proposal is based on a stale project sequence",
                repairable=("based_on_event_sequence",),
            )
        self._validate_subgoals(proposal)
        self._validate_capabilities(proposal, capabilities)
        self._validate_requirements(project, proposal)
        self._validate_frozen_boundary(project, proposal)
        self._validate_repair_lineage(project, proposal)
        self._validate_revision_progress(project, proposal)
        digest = plan_proposal_digest(proposal)
        if project.accepted_plan and project.accepted_plan.plan_digest == digest:
            return None
        return AcceptedPlanVersion(
            plan_version=(project.accepted_plan.plan_version + 1 if project.accepted_plan else 1),
            proposal=proposal,
            plan_digest=digest,
        )

    def _validate_capabilities(
        self,
        proposal: PlanProposal,
        capabilities: RuntimeCapabilityInventory,
    ) -> None:
        for subgoal in proposal.subgoals:
            if subgoal.capability_contract.semantic_domain.strip().lower() in {
                "verification",
                "semantic_verification",
            }:
                self._reject(
                    "Project semantic verification is owned by the automatic "
                    "Verifier and cannot be a Plan SubGoal; model a user-visible "
                    "analysis or report output instead",
                    repairable=(subgoal.logical_subgoal_id,),
                )
            if not contract_has_execution_path(
                capabilities,
                subgoal.capability_contract,
            ):
                self._reject(
                    "subgoal capability contract has no equivalent executable "
                    "capability; use supplied capability dimensions or synthesis: "
                    f"{subgoal.logical_subgoal_id}="
                    f"{subgoal.capability_contract.model_dump(mode='json')}",
                    repairable=(subgoal.logical_subgoal_id,),
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
        user_requirement_ids = {
            item.requirement_id
            for item in project.user_requirements.requirements
            if item.status == "active"
        }
        derived_requirement_ids = [
            item.requirement_id for item in proposal.derived_requirements
        ]
        if len(set(derived_requirement_ids)) != len(derived_requirement_ids):
            self._reject(
                "derived requirement ids must be unique",
                repairable=("derived_requirements",),
            )
        collisions = user_requirement_ids.intersection(
            derived_requirement_ids
        )
        if collisions:
            self._reject(
                "derived requirements cannot reuse user requirement ids: "
                f"{sorted(collisions)}",
                repairable=("derived_requirements",),
                immutable=tuple(sorted(collisions)),
            )
        required = set(user_requirement_ids)
        required.update(
            item.requirement_id
            for item in proposal.derived_requirements
            if item.completion_relevance == "required"
        )
        mapped = {item.requirement_id for item in proposal.requirement_mappings}
        if len(mapped) != len(proposal.requirement_mappings):
            self._reject(
                "requirement mapping ids must be unique",
                repairable=("requirement_mappings",),
            )
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
        for logical_id, version in frozen_subgoal_keys(project):
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

    def _validate_repair_lineage(
        self,
        project: InvestigationProject,
        proposal: PlanProposal,
    ) -> None:
        frozen = frozen_subgoal_keys(project)
        repairable_frozen = {
            key
            for key, waiting_reason in project.waiting_reasons.items()
            if waiting_reason.reason == "verification_repair"
        }
        previous_repair_keys = {
            item.logical_subgoal_id: {
                (
                    repair_ref.logical_subgoal_id,
                    repair_ref.subgoal_version,
                )
                for repair_ref in item.repairs_frozen_subgoals
            }
            for item in (
                project.accepted_plan.proposal.subgoals
                if project.accepted_plan is not None
                else ()
            )
        }
        for subgoal in proposal.subgoals:
            repair_keys = {
                (item.logical_subgoal_id, item.subgoal_version)
                for item in subgoal.repairs_frozen_subgoals
            }
            if not repair_keys:
                continue
            if len(repair_keys) != 1:
                self._reject(
                    "each repair subgoal must own exactly one frozen gap",
                    repairable=(subgoal.logical_subgoal_id,),
                )
            repaired_logical_id, _ = next(iter(repair_keys))
            expected_logical_id = repair_subgoal_logical_id(
                repaired_logical_id
            )
            if subgoal.logical_subgoal_id != expected_logical_id:
                self._reject(
                    "repair logical subgoal identity is deterministic; expected "
                    f"{expected_logical_id!r}",
                    repairable=(subgoal.logical_subgoal_id,),
                    immutable=(repaired_logical_id,),
                )
            if project.accepted_plan is None:
                self._reject(
                    "initial plan subgoals cannot claim frozen repair lineage",
                    repairable=(subgoal.logical_subgoal_id,),
                )
            unknown = repair_keys - frozen
            if unknown:
                self._reject(
                    "repair lineage references work outside the frozen execution "
                    f"boundary: {sorted(unknown)}",
                    repairable=(subgoal.logical_subgoal_id,),
                    immutable=tuple(sorted(item[0] for item in frozen)),
                )
            newly_claimed_repair_keys = repair_keys - previous_repair_keys.get(
                subgoal.logical_subgoal_id,
                set(),
            )
            non_repair_gaps = newly_claimed_repair_keys - repairable_frozen
            if non_repair_gaps:
                self._reject(
                    "repair lineage must reference an active frozen verification "
                    f"gap: {sorted(non_repair_gaps)}",
                    repairable=(subgoal.logical_subgoal_id,),
                )
        if project.accepted_plan is None:
            return
        previous_mappings = {
            item.requirement_id: item.logical_subgoal_ids
            for item in project.accepted_plan.proposal.requirement_mappings
        }
        proposed_mappings = {
            item.requirement_id: item.logical_subgoal_ids
            for item in proposal.requirement_mappings
        }
        proposed_by_id = {
            item.logical_subgoal_id: item for item in proposal.subgoals
        }
        active_requirement_ids = {
            item.requirement_id
            for item in project.user_requirements.requirements
            if item.status == "active"
        }
        active_requirement_ids.update(
            item.requirement_id
            for item in proposal.derived_requirements
            if item.completion_relevance == "required"
        )
        for gap_key in repairable_frozen:
            gap_id, _ = gap_key
            affected_requirements = {
                requirement_id
                for requirement_id, logical_ids in previous_mappings.items()
                if (
                    requirement_id in active_requirement_ids
                    and gap_id in logical_ids
                )
            }
            for requirement_id in affected_requirements:
                replacements = proposed_mappings.get(requirement_id, ())
                if gap_id in replacements:
                    continue
                if not any(
                    gap_key
                    in {
                        (
                            repair_ref.logical_subgoal_id,
                            repair_ref.subgoal_version,
                        )
                        for repair_ref in proposed_by_id[
                            replacement_id
                        ].repairs_frozen_subgoals
                    }
                    for replacement_id in replacements
                    if replacement_id in proposed_by_id
                ):
                    self._reject(
                        "requirement mapping replaced a frozen verification gap "
                        "without canonical repair lineage",
                        repairable=(requirement_id, "subgoals"),
                        immutable=(gap_id,),
                    )

    def _validate_revision_progress(
        self,
        project: InvestigationProject,
        proposal: PlanProposal,
    ) -> None:
        if project.accepted_plan is None:
            return

        proposed = {
            item.logical_subgoal_id: item for item in proposal.subgoals
        }
        satisfied_keys = {
            key for key, outcome in project.outcomes.items()
            if outcome.assessment.satisfied
        }
        frozen_unsatisfied = {
            logical_id
            for logical_id, version in project.execution_refs
            if (
                (logical_id, version) not in satisfied_keys
                and logical_id in proposed
                and proposed[logical_id].subgoal_version == version
            )
        }
        required_ids = {
            item.requirement_id
            for item in project.user_requirements.requirements
            if item.status == "active"
        }
        required_ids.update(
            item.requirement_id
            for item in proposal.derived_requirements
            if item.completion_relevance == "required"
        )
        impossible_mappings = {
            mapping.requirement_id: tuple(
                logical_id
                for logical_id in mapping.logical_subgoal_ids
                if logical_id in frozen_unsatisfied
            )
            for mapping in proposal.requirement_mappings
            if mapping.requirement_id in required_ids
            and frozen_unsatisfied.intersection(mapping.logical_subgoal_ids)
        }
        if impossible_mappings:
            immutable = tuple(sorted({
                logical_id
                for logical_ids in impossible_mappings.values()
                for logical_id in logical_ids
            }))
            self._reject(
                "required requirement mapping cannot depend on a frozen unsatisfied "
                "execution; retain frozen facts, add independently runnable repair "
                "work, and remap the requirement to its outcome",
                repairable=("subgoals", "requirement_mappings"),
                immutable=immutable,
                revision_scope=tuple(
                    item.logical_subgoal_id
                    for item in proposal.subgoals
                    if item.logical_subgoal_id not in immutable
                ),
            )

        completed_ids = {
            logical_id
            for logical_id, version in satisfied_keys
            if (
                logical_id in proposed
                and proposed[logical_id].subgoal_version == version
            )
        }
        occupied_keys = (
            set(project.outcomes)
            | set(project.execution_refs)
            | set(project.waiting_reasons)
            | set(project.accepted_execution_proposals)
        )
        runnable = any(
            (
                (item.logical_subgoal_id, item.subgoal_version) not in occupied_keys
                and all(dependency in completed_ids for dependency in item.depends_on)
            )
            for item in proposal.subgoals
        )
        required_complete = all(
            all(
                any(
                    outcome.logical_subgoal_id == logical_id
                    and outcome.assessment.satisfied
                    for outcome in project.outcomes.values()
                )
                for logical_id in mapping.logical_subgoal_ids
            )
            for mapping in proposal.requirement_mappings
            if mapping.requirement_id in required_ids
        )
        if not runnable and not required_complete:
            self._reject(
                "plan revision leaves required work without a runnable subgoal; add "
                "independently runnable repair work without replaying frozen execution",
                repairable=("subgoals", "requirement_mappings"),
                immutable=tuple(sorted(frozen_unsatisfied)),
                revision_scope=tuple(
                    item.logical_subgoal_id
                    for item in proposal.subgoals
                    if item.logical_subgoal_id not in frozen_unsatisfied
                ),
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
        observed_url_locators: tuple[str, ...] = (),
    ) -> SubGoalExecutionProposal:
        plan = project.accepted_plan
        if plan is None:
            raise ProposalRejected(DecisionFeedback(
                reason="project has no accepted plan",
            ))
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
                reason="execution proposal binding is stale or mismatched",
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
                reason="execution proposal digest mismatch",
                repairable_fields=("proposal_digest",),
            ))
        if proposal.operation.kind not in subgoal.capability_contract.allowed_execution_kinds:
            raise ProposalRejected(DecisionFeedback(
                reason="execution kind is outside the accepted capability contract",
                repairable_fields=("operation",),
            ))
        if proposal.operation.kind == "tool":
            matching = matching_execution_inventory(
                capabilities,
                subgoal.capability_contract,
            )
            available = {
                item.tool_name
                for item in matching.local_tools
            } | {
                item.local_tool_name
                for item in matching.mcp_connectors
            }
            if proposal.operation.tool_name not in available:
                if available:
                    raise ProposalRejected(DecisionFeedback(
                        reason=(
                            "selected Tool is outside the accepted SubGoal "
                            "capability contract"
                        ),
                        repairable_fields=("operation",),
                        immutable_fields=(
                            "project_id",
                            "plan_version",
                            "logical_subgoal_id",
                        ),
                        required_repair=(
                            "Select one of the deterministically matched Tool "
                            f"capabilities: {sorted(available)}"
                        ),
                        revision_scope=(subgoal.logical_subgoal_id,),
                    ))
                raise ProposalRejected(DecisionFeedback(
                    reason=(
                        f"capability missing: "
                        f"{subgoal.capability_contract.operation}"
                    ),
                    disposition="capability_missing",
                ))
            if (
                proposal.operation.tool_name == "capture_url"
                and observed_url_locators
                and proposal.operation.typed_arguments.get("url")
                not in observed_url_locators
            ):
                raise ProposalRejected(DecisionFeedback(
                    reason="capture URL was not observed in user input or execution evidence",
                    repairable_fields=("operation",),
                    immutable_fields=(
                        "project_id",
                        "plan_version",
                        "logical_subgoal_id",
                    ),
                    required_repair=(
                        "Select a URL from the deterministically observed locator set."
                    ),
                    revision_scope=(subgoal.logical_subgoal_id,),
                ))
            operation_digest = canonical_digest(
                proposal.operation.model_dump(mode="json")
            )
            if any(
                canonical_digest(item.model_dump(mode="json"))
                == operation_digest
                for item in unverified_tool_execution_operations(project)
            ):
                raise ProposalRejected(DecisionFeedback(
                    reason=(
                        "execution proposal repeats an exact Tool operation whose prior "
                        "execution did not produce a verified SubGoal outcome"
                    ),
                    repairable_fields=("operation",),
                    immutable_fields=(
                        "project_id",
                        "plan_version",
                        "logical_subgoal_id",
                    ),
                    required_repair=(
                        "Choose different arguments or a different admitted capability "
                        "that can address the verification gap without replaying the "
                        "semantically insufficient execution."
                    ),
                    revision_scope=(subgoal.logical_subgoal_id,),
                ))
        elif proposal.operation.kind == "agent":
            available_agents = {
                item.agent_id
                for item in matching_execution_inventory(
                    capabilities,
                    subgoal.capability_contract,
                ).a2a_agents
            }
            if proposal.operation.agent_id not in available_agents:
                raise ProposalRejected(DecisionFeedback(
                    reason=(
                        f"capability missing: "
                        f"{subgoal.capability_contract.operation}"
                    ),
                    disposition="capability_missing",
                ))
        if execution_scope.project_id != project.definition.project_id:
            raise ProposalRejected(DecisionFeedback(
                reason="execution scope project binding mismatch",
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
            or evidence.artifact_ref.owner == project.definition.principal
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
    "execution_evidence_subgoal_keys",
    "frozen_subgoal_keys",
    "observed_url_locators",
    "plan_proposal_digest",
    "repair_subgoal_logical_id",
    "subgoal_definition_digest",
    "unverified_tool_execution_operations",
]
