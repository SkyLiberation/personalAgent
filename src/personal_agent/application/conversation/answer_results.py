"""Normalize Conversation answers and explicit turn status reports."""

from dataclasses import dataclass, field

from personal_agent.capabilities.contracts.model import ModelActionDefinition, ModelAssistantMessage
from personal_agent.kernel.llm_schemas import model_tool_wire_name
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig
from personal_agent.kernel.feature_flags import FeatureFlags
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .models import (
    AnswerResultInvocation, ConversationAnswerSegment, FinalMessage, ReportTurnStatusArguments,
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
            name=model_tool_wire_name("control_report_turn_status"),
            kind="answer_result",
            target_name="report_turn_status",
            description=self.prompts.get("conversation.answer.report_status_description").template,
            input_schema=ReportTurnStatusArguments.model_json_schema(),
            strict=False,
        ),)

    def decode_operation(self, invocation: AnswerResultInvocation) -> FinalMessage:
        if invocation.operation != "report_turn_status":
            raise ValueError(self.prompts.render("conversation.answer.operation_unavailable"))
        args = ReportTurnStatusArguments.model_validate(invocation.arguments)
        return FinalMessage(disposition=args.disposition, segments=(ConversationAnswerSegment(text=args.message),))

    def decode_assistant_message(self, message: ModelAssistantMessage | None) -> FinalMessage:
        """Interpret the original visible body without inventing a tool call."""
        if message is None or message.call_ids:
            raise ValueError(self.prompts.render("conversation.answer.assistant_message_invalid"))
        text = message.visible_text
        if text is None or not text.strip():
            raise ValueError(self.prompts.render("conversation.answer.visible_body_missing"))
        return FinalMessage(disposition="answer", segments=(ConversationAnswerSegment(text=text),))
