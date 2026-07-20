"""Admission boundary for model-proposed task semantics."""

from __future__ import annotations

from personal_agent.governance.contracts.admission import (
    DecisionFeedback,
    GovernanceSnapshotRef,
    StageAdmissionDecision,
)
from personal_agent.kernel.contracts.derivation import canonical_digest
from personal_agent.kernel.models import EntryInput
from personal_agent.planning.task_analyzer import (
    AcceptedTaskAnalysis,
    Goal,
    GoalRelation,
    TaskAnalysis,
    TaskAnalysisProvenanceRecord,
    TaskAnalysisProposal,
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
        if proposal.input_digest != task_analysis_input_digest(entry_input):
            reasons.append("task_analysis_input_digest_mismatch")
            rejected_fields.append("input_digest")
        payload = proposal.body.model_dump(mode="json")
        known_claims: dict[str, str] = {}
        for claim in proposal.body.grounding_claims:
            value = _field_value(payload, claim.output_field_ref)
            if value is None:
                reasons.append("task_analysis_grounding_field_unknown")
                rejected_fields.append(claim.output_field_ref)
                continue
            if claim.source_text not in entry_input.text:
                reasons.append("task_analysis_grounding_source_unknown")
                rejected_fields.append(claim.output_field_ref)
                continue
            if value != claim.source_text:
                reasons.append("task_analysis_grounding_identity_mismatch")
                rejected_fields.append(claim.output_field_ref)
                continue
            known_claims[claim.output_field_ref] = claim.source_text
        for field_ref in _user_explicit_field_refs(proposal):
            value = _field_value(payload, field_ref)
            if value is None or value not in entry_input.text:
                reasons.append("task_analysis_user_explicit_value_not_source")
                rejected_fields.append(field_ref)
            if field_ref not in known_claims:
                reasons.append("task_analysis_grounding_required")
                rejected_fields.append(field_ref)
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


def _field_value(payload: object, field_ref: str) -> str | None:
    current = payload
    for segment in field_ref.split("."):
        if isinstance(current, dict):
            current = current.get(segment)
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current if isinstance(current, str) else None


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
            if hint.origin == "user_explicit" and hint.user_required_provider:
                refs.append(f"goals.{goal_index}.resource_hints.{hint_index}.user_required_provider")
    for relation_index, relation in enumerate(proposal.body.relations):
        if relation.origin == "user_explicit":
            refs.append(f"relations.{relation_index}.rationale")
    return tuple(refs)


def _semantic_body(proposal: TaskAnalysisProposal) -> dict:
    return proposal.body.model_dump(mode="json", exclude={"grounding_claims"})


__all__ = [
    "AcceptedTaskAnalysisCompiler",
    "TaskAnalysisAdmission",
    "task_analysis_input_digest",
]
