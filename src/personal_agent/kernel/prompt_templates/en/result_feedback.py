"""English answer, research, plan, and experiment feedback."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "conversation.answer.base_unavailable": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Select only the latest visible complete base draft.",
    ),
    "conversation.answer.operation_unavailable": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="This operation is not available in the current answer module.",
    ),
    "conversation.answer.assistant_message_invalid": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="An ordinary answer must come from a valid assistant message with no tool calls.",
    ),
    "conversation.answer.visible_body_missing": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The model has not returned a nonempty visible body; reasoning cannot serve as the answer.",
    ),
    "conversation.answer.citation_repair": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Correct the references or read more, then resubmit the complete answer; do not fabricate evidence.",
    ),
    "conversation.answer.research_writer_required": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Submit through research evidence selection and claims operations; an ordinary answer or revision cannot bypass the current writer.",
    ),
    "conversation.answer.research_revision_required": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="A research operation must select the current complete research revision.",
    ),
    "conversation.answer.research_body_rejected": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Submit through research evidence selection and claims operations; ordinary body text cannot bypass the current writer.",
    ),
    "conversation.answer.return_to_actions_repair": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Continue with the formally available actions; select again based on the current evidence, then submit the complete answer through the current research revision.",
    ),
    "conversation.answer.research_edit_repair": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Check the current complete revision, exact fragments, and visible references, then correct the arguments; the rejected action did not change the collection.",
    ),
    "conversation.answer.final_answer_missing": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Research progress has been saved, but no complete final answer has been submitted, so it cannot be delivered.",
    ),
    "conversation.answer.final_answer_repair": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Continue gathering evidence or submit final_answer through the current revision; use control_recheck_claims to change only the answer.",
    ),
    "conversation.answer.research_answer_not_approved": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Deliver only the exact answer in the current complete research revision, satisfying the verification contract configured for this run.",
    ),
    "conversation.answer.research_completion_repair": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Revise or add evidence through the current research revision, then resubmit; do not write a separate answer that bypasses the research.",
    ),
    "conversation.research.collection_exists": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Edit the existing collection locally against its current revision; it cannot be created again.",
    ),
    "conversation.research.base_ref_mismatch": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="base_ref must exactly match the current research_claims.resource_ref; the old revision was not modified.",
    ),
    "conversation.research.claim_unknown": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="claim_id does not belong to the current revision.",
    ),
    "conversation.research.last_claim": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The current revision's last claim cannot be deleted; retain at least one grounded claim.",
    ),
    "conversation.research.fragment_range_invalid": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Both fragment IDs must identify visible fragments of the current claim, with the start no later than the end; the current revision remains unchanged.",
    ),
    "conversation.research.claim_empty": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="A fragment revision cannot empty the entire claim.",
    ),
    "conversation.research.answer_segment_unknown": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="answer_segment_id must belong to the actual final answer of the current base_ref; the entire submission was not applied.",
    ),
    "conversation.research.final_references_unbound": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The final answer may reference only original text already bound to claims after this admission; the entire submission was not applied.",
    ),
    "conversation.research.final_answer_missing": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="No final answer has been submitted; the current research can be retained, but a complete answer must be generated before verification and completion.",
    ),
    "conversation.research.final_bound_coordinates": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The final answer may reference only actual coordinates already bound to this revision's claims.",
    ),
    "conversation.research.support_requirement_unknown": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="A missing requirement must reference a current frozen acceptance criterion ID.",
    ),
    "conversation.research.support_answer_unknown": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="A finding must identify a segment of the current final answer.",
    ),
    "conversation.research.support_fragment_invalid": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="A finding must bind an ordered fragment range within the same current claim.",
    ),
    "conversation.research.support_evidence_invalid": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="A finding may reference only returned evidence coordinates actually allowed for its category and target.",
    ),
    "conversation.plan.active_step_limit": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="A working plan may have at most one in_progress step.",
    ),
    "conversation.plan.active_step_repair": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Keep only the one step currently being advanced active; set the other remaining steps to pending.",
    ),
    "conversation.plan.step_binding_repair": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Omit step_id or set it to null for new steps; retain all current valid IDs and the responsibilities of bound steps. The entire plan remains unchanged.",
    ),
    "conversation.experiment.submission_missing": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="No complete report has been submitted, or feedback received after submission remains unresolved.",
    ),
    "conversation.experiment.submission_identity_mismatch": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The submitted report does not belong to the current task and principal.",
    ),
    "conversation.experiment.final_mismatch": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The final answer is not the current report submission.",
    ),
    "conversation.experiment.execution_unsettled": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="Python analysis still has an unconfirmed execution and cannot be delivered as complete.",
    ),
    "conversation.experiment.output_originals_missing": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The original Python analysis outputs cannot be restored, so the result cannot be delivered as complete.",
    ),
    "conversation.experiment.input_originals_missing": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="An original Python program, input, or execution manifest is missing.",
    ),
    "conversation.answer.citation_feedback": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="{error}\nSee the latest submitted_final for the complete submission and references for each segment.",
    ),
    "conversation.research.unselected_references": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="New research claim references must come from visible evidence coordinates selected this turn; coordinates not selected this turn: {unselected}.",
    ),
    "conversation.plan.step_binding_invalid": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The complete plan update was rejected: unknown IDs={unknown}; omitted steps={omitted}; changed responsibilities of bound steps={changed_bound}.",
    ),
    "conversation.experiment.citations_unbound": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The report references are not bound to actual sources: {error}",
    ),
}
