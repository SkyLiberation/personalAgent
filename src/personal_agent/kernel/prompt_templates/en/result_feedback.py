"""English answer, research, plan, and experiment feedback."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "conversation.test_mode": PromptTranslation(
        source_version="v1-conversation-test-mode",
        version="v1-conversation-test-mode-en.1",
        template="This is an unattended test. When the available tools can obtain missing information, use them and continue. When further progress is impossible, use an allowed limitation or failure state and identify the exact gap.",
    ),
    "conversation.clarification.description": PromptTranslation(
        source_version="v1-clarification",
        version="v1-clarification-en.1",
        template="Ask the user one specific question and wait for a reply before continuing. Use this only when essential input cannot be obtained from existing information or available tools and requires the user to supply or decide it. The question is displayed directly to the user. Invoke this action alone.",
    ),
    "conversation.clarification.repair": PromptTranslation(
        source_version="v1-clarification",
        version="v1-clarification-en.1",
        template="If you need the user to supply information, invoke control_request_clarification alone with one nonempty question. If an available tool can obtain the information, invoke that tool.",
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
        source_version="v2-list-control",
        version="v2-list-control-en.1",
        template="Use a step_id from the current list for an existing step. Omit step_id for a new step. Keep the description of a bound step or add a new step.",
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
        template="Bash analysis still has an unconfirmed execution and cannot be delivered as complete.",
    ),
    "conversation.experiment.output_originals_missing": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="The original Bash analysis outputs cannot be restored, so the result cannot be delivered as complete.",
    ),
    "conversation.experiment.input_originals_missing": PromptTranslation(
        source_version="2026-10-27.v1",
        version="2026-10-27.en.v1",
        template="An original Bash program, input, or execution manifest is missing.",
    ),
    "conversation.plan.step_binding_invalid": PromptTranslation(
        source_version="v2-list-control",
        version="v2-list-control-en.1",
        template="The task list was not updated. Unknown step IDs: {unknown}. Steps with execution bindings whose descriptions changed: {changed_bound}.",
    ),
    "conversation.plan.goal_binding_invalid": PromptTranslation(
        source_version="v1", version="v1-en.1",
        template="Each unfinished plan step needs the IDs of the active goal items it serves. Revise the steps using the latest goal.",
    ),
}
