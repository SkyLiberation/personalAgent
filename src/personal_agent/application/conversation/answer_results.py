"""Decode and validate Conversation answer submissions."""

from dataclasses import dataclass, field

from copy import deepcopy

from personal_agent.capabilities.contracts.model import ModelActionDefinition, ModelAssistantMessage
from personal_agent.kernel.llm_schemas import model_tool_wire_name
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig
from personal_agent.kernel.feature_flags import FeatureFlags
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from personal_agent.capabilities.contracts.verification import ConversationEvidenceReference

from .citations import CitationBindingError, materialize_cited_draft
from .models import (
    AnswerResultInvocation, ConversationAnswerSegment, DecisionFeedback, FinalMessage,
    InteractionInput, SubmitFinalArguments,
)


@dataclass(frozen=True)
class DirectAnswerResult:
    config: AnswerResultConfig
    feature_flags: FeatureFlags = field(default_factory=FeatureFlags, kw_only=True)
    prompts: PromptCatalog = field(default=DEFAULT_PROMPTS, kw_only=True)

    @property
    def verification_enabled(self) -> bool:
        return self.feature_flags.answer_verification

    def action_definitions(self) -> tuple[ModelActionDefinition, ...]:
        return (ModelActionDefinition(
            name=model_tool_wire_name("control_submit_final"),
            kind="answer_result",
            target_name="submit_final",
            description=self.prompts.get("conversation.answer.submit_description").template,
            input_schema=SubmitFinalArguments.model_json_schema(),
            strict=False,
        ),)

    @staticmethod
    def without_normal_answer(action: ModelActionDefinition) -> ModelActionDefinition:
        schema = deepcopy(action.input_schema)
        disposition = schema["properties"]["disposition"]
        disposition["enum"] = [state for state in disposition["enum"] if state != "answer"]
        return action.model_copy(update={"input_schema": schema})

    def decode_operation(self, invocation: AnswerResultInvocation) -> FinalMessage:
        if invocation.operation == "submit_final":
            args = SubmitFinalArguments.model_validate(invocation.arguments)
            return FinalMessage(disposition=args.disposition, segments=(ConversationAnswerSegment(
                text=args.message, references=tuple(ConversationEvidenceReference(evidence_id=ref) for ref in args.references)),))
        raise ValueError(self.prompts.render("conversation.answer.operation_unavailable"))

    def decode_assistant_message(self, message: ModelAssistantMessage | None) -> FinalMessage:
        """Interpret the original visible body without inventing a tool call."""
        if message is None or message.call_ids:
            raise ValueError(self.prompts.render("conversation.answer.assistant_message_invalid"))
        text = message.visible_text
        if text is None or not text.strip():
            raise ValueError(self.prompts.render("conversation.answer.visible_body_missing"))
        return FinalMessage(disposition="answer", segments=(ConversationAnswerSegment(text=text),))

    def validate_final(
        self, decision: FinalMessage, inputs: tuple[InteractionInput, ...],
    ) -> DecisionFeedback | None:
        try:
            materialize_cited_draft(decision.segments, inputs, prompts=self.prompts)
        except CitationBindingError as error:
            return DecisionFeedback(
                action_id="answer-result", action_name="final_message", reason_code=error.reason_code,
                message=self.prompts.render("conversation.answer.citation_feedback", error=error),
                repairable_fields=("segments",),
                required_repair=self.prompts.render("conversation.answer.citation_repair"),
            )
        return None
