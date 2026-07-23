"""Admission boundary for model-proposed task semantics."""

from __future__ import annotations

import re
from uuid import UUID

from personal_agent.governance.contracts.admission import (
    DecisionFeedback,
    GovernanceSnapshotRef,
    StageAdmissionDecision,
)
from personal_agent.kernel.contracts.derivation import canonical_digest
from personal_agent.kernel.contracts.resource import MUTATING_OPERATIONS
from personal_agent.kernel.models import EntryInput
from personal_agent.planning.task_analyzer import (
    AcceptedTaskAnalysis,
    Goal,
    GoalRelation,
    TaskAnalysis,
    TaskAnalysisProvenanceRecord,
    TaskAnalysisProposal,
    task_analysis_field_value,
)


def task_analysis_input_digest(entry_input: EntryInput) -> str:
    return canonical_digest({
        "text": entry_input.text,
        "artifacts": [item.model_dump(mode="json") for item in entry_input.artifacts],
    })


class TaskAnalysisAdmission:
    def admit(
        self,
        entry_input: EntryInput,
        proposal: TaskAnalysisProposal,
        *,
        prior_proposal: TaskAnalysisProposal | None = None,
        revision_feedback: DecisionFeedback | None = None,
    ) -> StageAdmissionDecision:
        reasons: list[str] = []
        rejected_fields: list[str] = []
        if prior_proposal is not None or revision_feedback is not None:
            if prior_proposal is None or revision_feedback is None:
                reasons.append("task_analysis_revision_lineage_incomplete")
            else:
                if proposal.supersedes_proposal_ref != prior_proposal.proposal_id:
                    reasons.append("task_analysis_supersedes_mismatch")
                if proposal.revision_feedback_ref != revision_feedback.feedback_id:
                    reasons.append("task_analysis_feedback_ref_mismatch")
                if revision_feedback.revision_scope == "grounding_only" and (
                    _semantic_body(proposal) != _semantic_body(prior_proposal)
                ):
                    reasons.append("task_analysis_revision_scope_exceeded")
                if (
                    revision_feedback.revision_scope == "semantic_revision"
                    and "task_analysis_mutation_operation_required"
                    in revision_feedback.reason_codes
                    and not _read_only_mutation_revision_is_scoped(
                        prior_proposal,
                        proposal,
                        revision_feedback,
                    )
                ):
                    reasons.append("task_analysis_revision_scope_exceeded")
        if proposal.input_digest != task_analysis_input_digest(entry_input):
            reasons.append("task_analysis_input_digest_mismatch")
            rejected_fields.append("input_digest")
        payload = proposal.body.model_dump(mode="json")
        known_claims: dict[str, str] = {}
        for claim in proposal.body.grounding_claims:
            value = task_analysis_field_value(payload, claim.output_field_ref)
            if value is None:
                reasons.append("task_analysis_grounding_field_unknown")
                rejected_fields.append(claim.output_field_ref)
                continue
            if not _is_identity_source(entry_input, claim.source_text):
                reasons.append("task_analysis_grounding_source_unknown")
                rejected_fields.append(claim.output_field_ref)
                continue
            if value != claim.source_text:
                reasons.append("task_analysis_grounding_identity_mismatch")
                rejected_fields.append(claim.output_field_ref)
                continue
            known_claims[claim.output_field_ref] = claim.source_text
        for field_ref in _user_explicit_field_refs(proposal):
            value = task_analysis_field_value(payload, field_ref)
            if value is None or not _is_identity_source(entry_input, value):
                reasons.append("task_analysis_user_explicit_value_not_source")
                rejected_fields.append(field_ref)
            if field_ref not in known_claims:
                reasons.append("task_analysis_grounding_required")
                rejected_fields.append(field_ref)
        explicit_ids = _canonical_identity_values(entry_input.text)
        if explicit_ids:
            for goal_index, goal in enumerate(proposal.body.goals):
                delete_hints = [
                    (hint_index, hint)
                    for hint_index, hint in enumerate(goal.resource_hints)
                    if "delete" in hint.operations
                ]
                if not delete_hints:
                    continue
                if any(
                    hint.origin == "user_explicit" and hint.locator in explicit_ids
                    for _, hint in delete_hints
                ):
                    continue
                # Decision ownership: canonical identity extraction is a
                # closed-world input check. Admission can require the model to
                # preserve it, but cannot add the locator or choose a target.
                reasons.append("task_analysis_explicit_identity_required")
                if delete_hints:
                    rejected_fields.append(
                        f"goals.{goal_index}.resource_hints.{delete_hints[0][0]}.locator"
                    )
                else:
                    rejected_fields.append(f"goals.{goal_index}.resource_hints")
        artifact_ids = {item.artifact_id for item in entry_input.artifacts}
        if artifact_ids:
            for goal_index, goal in enumerate(proposal.body.goals):
                artifact_hints = [
                    (hint_index, hint)
                    for hint_index, hint in enumerate(goal.resource_hints)
                    if hint.semantic_domain == "artifact" and "read" in hint.operations
                ]
                if not artifact_hints:
                    continue
                if any(
                    hint.origin == "user_explicit" and hint.locator in artifact_ids
                    for _, hint in artifact_hints
                ):
                    continue
                # Decision ownership: EntryInput.artifacts owns attachment
                # identity. Admission requires an exact model-preserved id; it
                # never substitutes a filename/path or fills the locator.
                reasons.append("task_analysis_artifact_identity_required")
                rejected_fields.append(
                    f"goals.{goal_index}.resource_hints.{artifact_hints[0][0]}.locator"
                )
        for goal_index, goal in enumerate(proposal.body.goals):
            locators = {
                hint.locator for hint in goal.resource_hints if hint.locator is not None
            }
            for constraint_index, constraint in enumerate(goal.constraints):
                if constraint.description not in locators:
                    continue
                # Decision ownership: ResourceHint.locator is the canonical
                # owner of resource identity. Repeating the same identity in a
                # constraint creates a second semantic write surface, so
                # Admission rejects the Proposal instead of synchronizing it.
                reasons.append("task_analysis_duplicate_resource_identity")
                rejected_fields.append(
                    f"goals.{goal_index}.constraints.{constraint_index}"
                )
        for goal_index, goal in enumerate(proposal.body.goals):
            mutating = {
                str(operation)
                for hint in goal.resource_hints
                for operation in hint.operations
                if str(operation) in MUTATING_OPERATIONS
            }
            if (
                goal.result_contract == "external_state"
                or goal.side_effect_intent == "mutation"
            ) and not mutating:
                # Decision ownership: external-state classification has a
                # closed-world dependency on the model-proposed operations.
                # Admission rejects an impossible classification and asks the
                # model to revise; it does not rewrite the Goal or invent an
                # operation on the model's behalf.
                reasons.append("task_analysis_mutation_operation_required")
                rejected_fields.append(f"goals.{goal_index}")
            if mutating and (
                goal.result_contract != "external_state"
                or goal.side_effect_intent != "mutation"
            ):
                # Decision ownership: mutation classification is a
                # closed-world consequence of model-supplied operations.  The
                # admission boundary rejects the inconsistent proposal rather
                # than splitting Goals, adding a mutation flag, or choosing a
                # different operation on the model's behalf.
                reasons.append("task_analysis_mutation_contract_required")
                rejected_fields.append(f"goals.{goal_index}")
        reason_codes = tuple(dict.fromkeys(reasons))
        snapshot = GovernanceSnapshotRef(
            task_revision=1,
            runtime_revision=0,
            policy_revision="task-analysis-admission:v1",
        )
        if not reason_codes:
            return StageAdmissionDecision(
                stage="task_analysis",
                proposal_ref=proposal.proposal_id,
                verdict="accepted",
                snapshot=snapshot,
            )
        grounding_only = all("grounding" in item for item in reason_codes)
        feedback = DecisionFeedback(
            stage="task_analysis",
            rejected_proposal_ref=proposal.proposal_id,
            reason_codes=reason_codes,
            rejected_field_refs=tuple(dict.fromkeys(rejected_fields)),
            mutable_field_refs=("body.grounding_claims",) if grounding_only else ("body",),
            immutable_field_refs=("input_ref", "input_digest"),
            required_repairs=tuple(
                f"repair {field_ref}" for field_ref in dict.fromkeys(rejected_fields)
            ),
            revision_scope="grounding_only" if grounding_only else "semantic_revision",
            disposition=(
                "terminal"
                if "task_analysis_input_digest_mismatch" in reason_codes
                or proposal.revision_attempt >= 2
                else "revise_model"
            ),
            revision_budget_remaining=max(2 - proposal.revision_attempt, 0),
            governance_snapshot_ref="task-analysis-admission:v1",
            rejection_equivalence_hash=canonical_digest({
                "reasons": reason_codes,
                "fields": tuple(dict.fromkeys(rejected_fields)),
            }),
        )
        return StageAdmissionDecision(
            stage="task_analysis",
            proposal_ref=proposal.proposal_id,
            verdict="not_accepted",
            disposition=feedback.disposition,
            reason_codes=reason_codes,
            snapshot=snapshot,
            feedback=feedback,
        )


class AcceptedTaskAnalysisCompiler:
    def compile(
        self,
        proposal: TaskAnalysisProposal,
        admission: StageAdmissionDecision,
    ) -> AcceptedTaskAnalysis:
        if admission.verdict != "accepted" or admission.proposal_ref != proposal.proposal_id:
            raise ValueError("only the admitted task-analysis proposal can be accepted")
        body = proposal.body
        clarification = body.clarification
        analysis = TaskAnalysis(
            user_goal=body.user_goal,
            outcome=body.outcome,
            goals=[Goal(
                goal_id=f"goal_{index}",
                description=draft.description,
                result_contract=draft.result_contract,
                success_criteria=draft.success_criteria,
                constraints=draft.constraints,
                side_effect_intent=draft.side_effect_intent,
                evidence_requirement=draft.evidence_requirement,
                resource_hints=draft.resource_hints,
            ) for index, draft in enumerate(body.goals, start=1)],
            relations=[GoalRelation(
                predecessor_goal_id=f"goal_{relation.predecessor}",
                successor_goal_id=f"goal_{relation.successor}",
                kind=relation.kind,
                origin=relation.origin,
                rationale=relation.rationale,
            ) for relation in body.relations],
            missing_information=(clarification.missing_information if clarification else []),
            clarification_prompt=(clarification.prompt if clarification else ""),
            rejection_reason=body.rejection_reason or "",
            error=proposal.control_error,
        )
        return AcceptedTaskAnalysis(
            proposal_ref=proposal.proposal_id,
            admission_ref=admission.admission_id,
            input_ref=proposal.input_ref,
            input_digest=proposal.input_digest,
            analysis=analysis,
            grounding_records=tuple(TaskAnalysisProvenanceRecord(
                source_ref=proposal.input_ref,
                source_digest=canonical_digest(claim.source_text),
                output_field_ref=claim.output_field_ref,
                output_digest=canonical_digest(claim.source_text),
            ) for claim in body.grounding_claims),
        )


def _is_identity_source(entry_input: EntryInput, value: str) -> bool:
    return value in entry_input.text or value in {
        artifact.artifact_id for artifact in entry_input.artifacts
    }


def _user_explicit_field_refs(proposal: TaskAnalysisProposal) -> tuple[str, ...]:
    refs: list[str] = []
    for goal_index, goal in enumerate(proposal.body.goals):
        for criterion_index, criterion in enumerate(goal.success_criteria):
            if criterion.origin == "user_explicit":
                refs.append(f"goals.{goal_index}.success_criteria.{criterion_index}.description")
        for constraint_index, constraint in enumerate(goal.constraints):
            if constraint.origin == "user_explicit":
                refs.append(f"goals.{goal_index}.constraints.{constraint_index}.description")
        for hint_index, hint in enumerate(goal.resource_hints):
            if hint.origin == "user_explicit" and hint.locator:
                refs.append(f"goals.{goal_index}.resource_hints.{hint_index}.locator")
            if hint.origin == "user_explicit" and hint.user_required_provider:
                refs.append(f"goals.{goal_index}.resource_hints.{hint_index}.user_required_provider")
    for relation_index, relation in enumerate(proposal.body.relations):
        if relation.origin == "user_explicit":
            refs.append(f"relations.{relation_index}.rationale")
    return tuple(refs)


def _semantic_body(proposal: TaskAnalysisProposal) -> dict:
    return proposal.body.model_dump(mode="json", exclude={"grounding_claims"})


def _read_only_mutation_revision_is_scoped(
    prior: TaskAnalysisProposal,
    revised: TaskAnalysisProposal,
    feedback: DecisionFeedback,
) -> bool:
    before = _semantic_body(prior)
    after = _semantic_body(revised)
    allowed_goal_indexes = {
        int(match.group(1))
        for field_ref in feedback.rejected_field_refs
        if (match := re.fullmatch(r"goals\.(\d+)", field_ref)) is not None
    }
    if not allowed_goal_indexes:
        return False
    before_goals = before.get("goals")
    after_goals = after.get("goals")
    if not isinstance(before_goals, list) or not isinstance(after_goals, list):
        return False
    if len(before_goals) != len(after_goals):
        return False
    for index in allowed_goal_indexes:
        if index >= len(before_goals):
            return False
        for goal in (before_goals[index], after_goals[index]):
            if not isinstance(goal, dict):
                return False
            goal.pop("result_contract", None)
            goal.pop("side_effect_intent", None)
    return before == after


_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _canonical_identity_values(text: str) -> frozenset[str]:
    values: set[str] = set()
    for candidate in _UUID_PATTERN.findall(text):
        try:
            values.add(str(UUID(candidate)))
        except ValueError:
            continue
    return frozenset(values)


__all__ = [
    "AcceptedTaskAnalysisCompiler",
    "TaskAnalysisAdmission",
    "task_analysis_input_digest",
]
