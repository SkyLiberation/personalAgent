"""English mirrors of conversation runtime feedback and terminal explanations."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    'conversation.service.experiment_restore_validation_unavailable': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Experiment completion validation is unavailable; the completed answer cannot be restored.',
    ),
    'conversation.service.experiment_delivery_restore_unavailable': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The experiment delivery service is unavailable; the report submission cannot be restored.',
    ),
    'conversation.service.run_deadline_limitation': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template="This task's runtime limit has been reached. Committed artifacts are preserved; unfinished work does not count as complete delivery.",
    ),
    'conversation.service.repeated_invalid_actions': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The model repeatedly submitted the same kind of invalid action, so this interaction stopped safely. None of the rejected actions were executed.',
    ),
    'conversation.service.research_selection_coverage_repair': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Cover every requirement exactly once, linking only current claims and returned references. This selection was not accepted.',
    ),
    'conversation.service.research_selection_evidence_repair': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Use currently allowed tools to address the gaps, then select evidence again after obtaining new evidence.',
    ),
    'conversation.service.experiment_delivery_check_unavailable': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The experiment delivery service is unavailable; the report submission cannot be checked.',
    ),
    'conversation.service.plan_review_ready': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The plan is ready. Work will continue after you adjust or confirm it.',
    ),
    'conversation.service.experiment_completion_repair': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template="Continue execution or complete this task's results according to the actual gaps. Existing experiments and drafts are preserved; rewriting the report alone cannot establish completion.",
    ),
    'conversation.service.experiment_validation_unavailable': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Experiment completion validation is unavailable; the answer cannot be completed.',
    ),
    'conversation.service.experiment_incomplete_prefix': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Experiment delivery is still incomplete: ',
    ),
    'conversation.service.artifact_unavailable': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The committed original is currently unavailable: {resource}. It was not re-executed or replaced.',
    ),
    'conversation.service.artifact_unavailable_repair': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Continue using the originals that remain available, or state the missing material honestly. The original may be read again after it is restored; do not guess its contents.',
    ),
    'conversation.service.knowledge_delete_confirmation': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Please confirm whether to delete this knowledge item. No deletion will occur before confirmation.',
    ),
    'conversation.service.knowledge_delete_rejected': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Deletion was cancelled; the knowledge item is unchanged.',
    ),
    'conversation.service.knowledge_deleted': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The knowledge item was deleted.',
    ),
    'conversation.service.intent_request_incomplete': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The research-intent model call did not complete. Known usage has been preserved.',
    ),
    'conversation.service.intent_protocol_invalid': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The structured research-intent output did not satisfy the protocol. Known usage has been preserved.',
    ),
    'conversation.service.background_unavailable': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Background tasks that continue after this response ends, or can be queried or adjusted later, are not currently supported. No background work was started. You can continue the work in the current conversation.',
    ),
    'conversation.service.rejected_draft_details': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='{error}\nSee the latest submitted_final for the complete rejected draft and its per-segment references.',
    ),
    'conversation.service.citation_repair': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Correct the references or read the missing material, then resubmit the draft with its corresponding references. Do not fabricate evidence.',
    ),
    'conversation.service.verification_budget_exhausted': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The tool-call budget is exhausted; no new verification has started.',
    ),
    'conversation.service.answer_result_repair': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Submit complete visible body text or a valid native operation according to the current answer module. This body text was not accepted.',
    ),
    'conversation.service.final_operation_repair': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Correct the operation using its current Schema and an allowed base-draft ID. This complete operation was not applied.',
    ),
    'conversation.service.model_deadline_exceeded': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template="This task's runtime limit has been reached; no new work can start. Committed results are preserved.",
    ),
    'conversation.service.model_budget_exhausted': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template="Known model usage has reached this task's allowance; no new work can start. Committed results are preserved.",
    ),
    'conversation.service.unsettled_execution': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='This analysis task still has unsettled tool executions; restore their execution state first.',
    ),
    'conversation.service.model_capacity_missing': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The execution configuration lacks a capacity profile matching the current model. This model call has not started.',
    ),
    'conversation.service.history_summary_incomplete': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The history summary did not complete. Original records and incurred usage are preserved.',
    ),
    'conversation.service.history_summary_inactive': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The history summary was not activated: {failure}',
    ),
    'conversation.service.model_journal_incomplete': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Model-call recording or recovery did not complete. Saved originals and actual usage are preserved.',
    ),
    'conversation.service.model_request_failed': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The model request did not obtain a usable response.',
    ),
    'conversation.service.model_output_invalid': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The model output does not satisfy the current interaction contract.',
    ),
    'conversation.service.model_response_record_incomplete': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The model response was not fully recorded. Saved originals and actual usage are preserved.',
    ),
    'conversation.service.model_capacity_refused': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template="The current model request exceeds its declared capacity boundary, or the deployment's capacity information does not match the actual request. This call was stopped.",
    ),
    'conversation.service.historical_source_rejected': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Historical originals may be read only as working context, not as source-verification material.',
    ),
    'conversation.service.historical_source_repair': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Use read_artifact or search_action_output to read the historical original.',
    ),
    'conversation.service.execution_permission_missing': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='This task has no bound execution permission for that tool.',
    ),
    'conversation.service.execution_permission_repair': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Use capabilities available to this task, or explain that an authorized execution environment is missing.',
    ),
    'conversation.service.resource_reference_not_allowed': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template="Only exact resource references supplied by this task's inputs or committed receipts may be read.",
    ),
    'conversation.service.resource_reference_repair': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='Use a resource_id supplied by current inputs or committed receipts.',
    ),
    'conversation.service.read_request_too_long': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The read parameters are too long to echo completely and provide continuation parameters within the output budget. Shorten the literal keyword.',
    ),
    'conversation.service.experiment_mutation_deadline': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='The experiment runtime limit has been reached; no new mutation call can be dispatched.',
    ),
    'conversation.service.execution_budget_limitation': PromptTranslation(
        source_version='2026-10-27.v1',
        version="2026-10-27.en.v1",
        template='This interaction has reached its execution budget; no substitute answer was generated. Increase the budget to continue from committed results.',
    ),
}
