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
    'conversation.service.artifact_unread': PromptTranslation(
        source_version='v1', version='en.v1',
        template='This turn cannot end as `{disposition}` while the omitted portion of original `{resource_id}` is unread.',
    ),
    'conversation.service.artifact_refetch': PromptTranslation(
        source_version='v1', version='en.v1',
        template='The same request already produced offloaded original `{resource_id}`. Fetching it again cannot show the omitted content.',
    ),
    'conversation.service.artifact_repair_read': PromptTranslation(
        source_version='v1', version='en.v1',
        template='Use `{tool}` with `resource_id` set to `{resource_id}` and choose a relevant `start_line`.',
    ),
    'conversation.service.artifact_repair_search': PromptTranslation(
        source_version='v1', version='en.v1',
        template='Use `{tool}` with `resource_id` set to `{resource_id}` and a `keyword` to locate relevant content.',
    ),
    'conversation.service.artifact_repair_unavailable': PromptTranslation(
        source_version='v1', version='en.v1',
        template='No declared read or search action accepts original `{resource_id}` in this request.',
    ),
    'conversation.service.historical_source_rejected': PromptTranslation(
        source_version='2026-11-06.v2',
        version="2026-11-06.en.v2",
        template='Historical original `{resource_id}` is readable as working context and is ineligible as source-verification material.',
    ),
    'conversation.service.duplicate_call_id': PromptTranslation(
        source_version='v1', version='en.v1',
        template='Call identity `{call_id}` is bound to an earlier committed operation. The duplicate did not execute.',
    ),
    'conversation.service.duplicate_call_repair': PromptTranslation(
        source_version='v1', version='en.v1',
        template='Use the committed result first. If a new operation is necessary, issue a new valid call. The native tool protocol binds its identity.',
    ),
    'conversation.knowledge.exclusive': PromptTranslation(
        source_version='v1', version='en.v1',
        template="This batch contained {count} actions. The knowledge operation requires its own confirmation proposal. No action in the batch executed.",
    ),
    'conversation.knowledge.exclusive_repair': PromptTranslation(
        source_version='v1', version='en.v1',
        template="Reissue this knowledge operation by itself and wait for the user to confirm the exact proposal.",
    ),
    'conversation.knowledge.save_unavailable': PromptTranslation(
        source_version='v1', version='en.v1',
        template="Governed knowledge saving is unavailable in this deployment.",
    ),
    'conversation.knowledge.save_unavailable_repair': PromptTranslation(
        source_version='v1', version='en.v1',
        template="Explain that saving is currently unavailable and preserve the user's original content and intent.",
    ),
    'conversation.knowledge.delete_unavailable': PromptTranslation(
        source_version='v1', version='en.v1',
        template="This deployment cannot look up the target or prepare a deletion for confirmation.",
    ),
    'conversation.knowledge.delete_unavailable_repair': PromptTranslation(
        source_version='v1', version='en.v1',
        template="Explain that deletion cannot currently be prepared.",
    ),
    'conversation.knowledge.source_repeated': PromptTranslation(
        source_version='v1', version='en.v1',
        template="selections[{position}] repeats source message {index}. Select each user message at most once.",
    ),
    'conversation.knowledge.source_not_user': PromptTranslation(
        source_version='v1', version='en.v1',
        template="selections[{position}] sets source_message_index to {index}, which does not identify a user message.",
    ),
    'conversation.knowledge.source_span_invalid': PromptTranslation(
        source_version='v1', version='en.v1',
        template="The text_span in selections[{position}] is blank or does not match a contiguous span in message {index}.",
    ),
    'conversation.knowledge.source_repair': PromptTranslation(
        source_version='v1', version='en.v1',
        template="Eligible user message indexes are {indexes}. Select one exact nonblank span per message, excluding save or confirmation instructions. Ask the user for the source if none is available.",
    ),
    'conversation.knowledge.delete_target_missing': PromptTranslation(
        source_version='v1', version='en.v1',
        template="Knowledge ID {target_id} was not found among the current user's eligible deletion targets.",
    ),
    'conversation.knowledge.delete_target_stop': PromptTranslation(
        source_version='v1', version='en.v1',
        template="There is no target that can be confirmed in this request. Explain the limitation or clarify the target with the user. Preserve existing knowledge.",
    ),
    'conversation.knowledge.delete_target_retry': PromptTranslation(
        source_version='v1', version='en.v1',
        template="Call `{inventory_tool}` to obtain the inventory. If a returned `knowledge_item_id` matches the user's target, issue `{delete_tool}` alone to prepare confirmation. Explain or clarify if no item matches.",
    ),
    'conversation.knowledge.delete_target_reuse': PromptTranslation(
        source_version='v1', version='en.v1',
        template='Use the inventory already returned in this interaction. If a listed `knowledge_item_id` matches the user’s target, call `{delete_tool}` alone to prepare confirmation. Otherwise explain the limitation or clarify the target.',
    ),
    'conversation.knowledge.inventory_already_returned': PromptTranslation(
        source_version='v1', version='en.v1',
        template='This interaction already returned a successful personal knowledge inventory.',
    ),
    'conversation.knowledge.inventory_reuse': PromptTranslation(
        source_version='v1', version='en.v1',
        template='Continue using the inventory already returned. If it lacks the required item, explain the limitation or clarify the target.',
    ),
    'conversation.knowledge.arguments_repair': PromptTranslation(
        source_version='v1', version='en.v1',
        template="Correct the arguments using the validation details, preserving the target and scope requested by the user.",
    ),
    'conversation.knowledge.operation_repair': PromptTranslation(
        source_version='v1', version='en.v1',
        template="Explain why the operation did not start. Clarify missing business input with the user while preserving the original goal.",
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
