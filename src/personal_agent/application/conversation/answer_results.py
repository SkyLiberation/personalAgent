"""Replaceable answer writers; the Conversation loop owns calls and persistence.

Writers yield typed proposals/checks to that one loop. They never execute tools,
charge usage, write a Journal, or manufacture a verification pass.
"""

from collections.abc import Generator, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel
from copy import deepcopy

from personal_agent.capabilities.contracts.model import StructuredModelRequest, ModelActionDefinition, ModelAssistantMessage
from personal_agent.kernel.llm_schemas import model_tool_wire_name
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .citations import CitationBindingError, materialize_cited_draft, materialize_citation_context, selected_citation_ids
from .context_materialization import materialize_interaction_inputs
from .final_revisions import materialize_final_revision
from .models import (
    ConversationAnswerSegment, ConversationMessage, DecisionFeedback, FinalMessage,
    InteractionInput, ReviewCriteria, SubmitFinalArguments, ReviseFinalArguments,
    FinalRevision, FinalSegmentEdit, SubmittedFinal, ResearchEvidenceSelection, InitialResearchEvidenceSelection,
)
from .research import (
    AddClaims, CreateClaims, DeleteClaim, RecheckClaims, ReplaceClaimReferences,
    ReturnToActions, ReviseClaimFragment, StopResearch, accepted_research,
    admit_claim_change, current_claims, in_research_mode, verification_steps, research_operation_schema, applicable_research_review,
)


ClaimSubmission = (
    CreateClaims | ReviseClaimFragment | ReplaceClaimReferences | AddClaims
    | DeleteClaim | RecheckClaims | ReturnToActions | StopResearch
)
_CLAIM_SUBMISSION_TYPES = (
    CreateClaims, ReviseClaimFragment, ReplaceClaimReferences, AddClaims,
    DeleteClaim, RecheckClaims, ReturnToActions, StopResearch,
)


@dataclass(frozen=True)
class AnswerResolution:
    final: FinalMessage | None


AnswerStep = StructuredModelRequest | InteractionInput


@dataclass(frozen=True)
class DirectAnswerResult:
    config: AnswerResultConfig
    prompts: PromptCatalog = field(default=DEFAULT_PROMPTS, kw_only=True)

    @property
    def verification_enabled(self) -> bool:
        return self.config.verification == "required"

    @property
    def delivery_prompt_name(self) -> str:
        return "conversation.answer.direct.delivery"

    def uses_claims(self, inputs, **conditions) -> bool:
        return False

    def action_definitions(self, inputs, **conditions) -> tuple[ModelActionDefinition, ...]:
        actions = [self._action("submit_final", SubmitFinalArguments.model_json_schema(),
            self.prompts.get("conversation.answer.submit_description").template)]
        submitted = next((item for item in reversed(inputs) if isinstance(item, SubmittedFinal)), None)
        if submitted is not None:
            schema = ReviseFinalArguments.model_json_schema()
            schema["properties"]["base_resource_id"]["enum"] = [submitted.resource_ref.resource_id]
            actions.append(self._action("revise_final", schema,
                self.prompts.get("conversation.answer.revise_description").template))
        return tuple(actions)

    @staticmethod
    def _action(name, schema, description):
        schema = deepcopy(schema)
        definitions = schema.pop("$defs", {})
        reachable = set()
        def visit(value):
            if isinstance(value, dict):
                ref = value.get("$ref", "")
                if ref.startswith("#/$defs/"):
                    key = ref.split("/")[-1]
                    if key not in reachable:
                        reachable.add(key)
                        visit(definitions[key])
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)
        visit(schema)
        if reachable:
            schema["$defs"] = {key: value for key, value in definitions.items() if key in reachable}
        return ModelActionDefinition(name=model_tool_wire_name("control_" + name), kind="answer_result",
            target_name=name, description=description, input_schema=schema, strict=False)

    def decode_operation(self, invocation, inputs, **conditions):
        from personal_agent.capabilities.contracts.verification import ConversationEvidenceReference
        if invocation.operation == "submit_final":
            args = SubmitFinalArguments.model_validate(invocation.arguments)
            return FinalMessage(disposition=args.disposition, segments=(ConversationAnswerSegment(
                text=args.message, references=tuple(ConversationEvidenceReference(evidence_id=ref) for ref in args.references)),))
        if invocation.operation == "revise_final":
            args = ReviseFinalArguments.model_validate(invocation.arguments)
            current = next((item for item in reversed(inputs) if isinstance(item, SubmittedFinal)), None)
            if current is None or current.resource_ref.resource_id != args.base_resource_id:
                raise ValueError(self.prompts.render("conversation.answer.base_unavailable"))
            edits = tuple(FinalSegmentEdit(segment=edit.segment, operation=edit.operation, text=edit.text,
                references=tuple(ConversationEvidenceReference(evidence_id=ref) for ref in edit.references)) for edit in args.edits)
            return materialize_final_revision(
                FinalRevision(base_ref=current.resource_ref, edits=edits), inputs,
                prompts=self.prompts,
            )
        raise ValueError(self.prompts.render("conversation.answer.operation_unavailable"))

    def decode_assistant_message(self, message: ModelAssistantMessage | None, inputs, **conditions) -> FinalMessage:
        """Interpret the original visible body without inventing a tool call."""
        if message is None or message.call_ids:
            raise ValueError(self.prompts.render("conversation.answer.assistant_message_invalid"))
        text = message.visible_text
        if text is None or not text.strip():
            raise ValueError(self.prompts.render("conversation.answer.visible_body_missing"))
        return FinalMessage(disposition="answer", segments=(ConversationAnswerSegment(text=text),))

    def handles_submission(self, decision: object) -> bool:
        return isinstance(decision, FinalMessage)

    def submission_steps(
        self, decision: FinalMessage | ClaimSubmission, *, inputs: list[InteractionInput],
        messages: Sequence[ConversationMessage], criteria: ReviewCriteria,
        reference: ResourceRef, selected_ids: frozenset[str], reuse_start_index: int,
    ) -> Generator[AnswerStep, BaseModel | None, AnswerResolution]:
        if not isinstance(decision, FinalMessage):
            raise ValueError("直接回答模块只接收 FinalMessage")
        yield from ()
        return AnswerResolution(decision)

    def validate_final(self, decision, inputs, *, reuse_start_index: int, requires_review: bool, experiment_run: bool) -> DecisionFeedback | None:
        if current_claims(inputs) is not None:
            raise ValueError("直接回答模块不能消费另一个 writer 的 claim 状态")
        return self._citation_feedback(decision, inputs)

    def _citation_feedback(self, decision, inputs) -> DecisionFeedback | None:
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

    def needs_direct_verification(self, criteria, inputs) -> bool:
        return self.verification_enabled and criteria.requires_review


@dataclass(frozen=True)
class ClaimAnswerResult(DirectAnswerResult):
    @property
    def delivery_prompt_name(self) -> str:
        return "conversation.research_delivery_policy"

    def uses_claims(self, inputs, **conditions) -> bool:
        return in_research_mode(inputs, **conditions)

    def action_definitions(self, inputs, *, selection=None, selected_ids=frozenset(), **conditions):
        actions = list(super().action_definitions(inputs, **conditions))
        if not self.uses_claims(inputs, **conditions):
            return tuple(actions)
        # Ordinary answer/revision cannot become a second entrance to this writer.
        actions = [action for action in actions if action.target_name != "revise_final"]
        for index, action in enumerate(actions):
            if action.target_name == "submit_final":
                schema = deepcopy(action.input_schema)
                schema["properties"]["disposition"]["enum"] = ["clarification_required", "limitation", "failed"]
                actions[index] = action.model_copy(update={"input_schema": schema})
        current = current_claims(inputs)
        selection_type = InitialResearchEvidenceSelection if current is None else ResearchEvidenceSelection
        actions.append(self._action("select_research_evidence", selection_type.model_json_schema(),
            self.prompts.get("conversation.answer.select_evidence_description").template))
        if selection is None or selection.next_step != "write":
            return tuple(actions)
        inherited = selected_citation_ids(tuple(ref for claim in current.claims for ref in claim.references), inputs, prompts=self.prompts) if current else frozenset()
        visible = tuple(item.model_copy(update={"citations": tuple(c for c in item.citations
                         if c.evidence_id in selected_ids or c.evidence_id in inherited)})
                        for item in materialize_citation_context(materialize_interaction_inputs(inputs)))
        operations = ((CreateClaims, ReturnToActions, StopResearch) if current is None else
            (ReviseClaimFragment, ReplaceClaimReferences, AddClaims, DeleteClaim, RecheckClaims, ReturnToActions, StopResearch))
        for operation in operations:
            name = operation.model_fields["kind"].annotation.__args__[0]
            schema = deepcopy(research_operation_schema(operation, current, visible, prompts=self.prompts))
            schema.get("properties", {}).pop("kind", None)
            schema["required"] = [field for field in schema.get("required", []) if field != "kind"]
            if "base_ref" in schema["properties"]:
                schema["properties"].pop("base_ref")
                schema["properties"]["base_resource_id"] = {"type": "string", "enum": [current.resource_ref.resource_id]}
                schema["required"] = ["base_resource_id" if field == "base_ref" else field for field in schema["required"]]
            actions.append(self._action(name, schema, self.prompts.get("conversation.answer.research_operation_description").template))
        return tuple(actions)

    def decode_operation(self, invocation, inputs, **conditions):
        if self.uses_claims(inputs, **conditions) and (
            invocation.operation == "revise_final"
            or (invocation.operation == "submit_final" and invocation.arguments.get("disposition") == "answer")
        ):
            raise ValueError(self.prompts.render("conversation.answer.research_writer_required"))
        if invocation.operation == "select_research_evidence":
            cls = InitialResearchEvidenceSelection if current_claims(inputs) is None else ResearchEvidenceSelection
            return cls.model_validate(invocation.arguments)
        for cls in _CLAIM_SUBMISSION_TYPES:
            if cls.model_fields["kind"].annotation.__args__[0] != invocation.operation:
                continue
            payload = dict(invocation.arguments)
            if "base_ref" in cls.model_fields:
                current = current_claims(inputs)
                if current is None or payload.pop("base_resource_id", None) != current.resource_ref.resource_id:
                    raise ValueError(self.prompts.render("conversation.answer.research_revision_required"))
                payload["base_ref"] = current.resource_ref
            return cls.model_validate({**payload, "kind": invocation.operation})
        return super().decode_operation(invocation, inputs, **conditions)

    def decode_assistant_message(self, message: ModelAssistantMessage | None, inputs, **conditions) -> FinalMessage:
        if self.uses_claims(inputs, **conditions):
            raise ValueError(self.prompts.render("conversation.answer.research_body_rejected"))
        return super().decode_assistant_message(message, inputs, **conditions)

    def handles_submission(self, decision: object) -> bool:
        return isinstance(decision, (FinalMessage, *_CLAIM_SUBMISSION_TYPES))

    def submission_steps(
        self, decision: FinalMessage | ClaimSubmission, *, inputs: list[InteractionInput],
        messages: Sequence[ConversationMessage], criteria: ReviewCriteria,
        reference: ResourceRef, selected_ids: frozenset[str], reuse_start_index: int,
    ) -> Generator[AnswerStep, BaseModel | None, AnswerResolution]:
        if isinstance(decision, FinalMessage):
            return AnswerResolution(decision)
        if isinstance(decision, StopResearch):
            return AnswerResolution(FinalMessage(disposition="limitation", segments=(
                ConversationAnswerSegment(text=decision.reason),
            )))
        if isinstance(decision, ReturnToActions):
            yield DecisionFeedback(
                action_id="research-return", reason_code="research_needs_evidence",
                message=decision.reason,
                required_repair=self.prompts.render("conversation.answer.return_to_actions_repair"),
            )
            return AnswerResolution(None)
        try:
            claims = admit_claim_change(decision, inputs, reference, selected_ids, prompts=self.prompts)
        except (ValueError, CitationBindingError) as error:
            yield DecisionFeedback(
                action_id="research-admission", reason_code="research_edit_invalid",
                message=str(error), required_repair=self.prompts.render("conversation.answer.research_edit_repair"),
            )
            return AnswerResolution(None)
        yield claims
        if not claims.final_answer or not "".join(segment.text for segment in claims.final_answer).strip():
            yield DecisionFeedback(
                action_id="research-final", reason_code="final_answer_missing",
                message=self.prompts.render("conversation.answer.final_answer_missing"),
                required_repair=self.prompts.render("conversation.answer.final_answer_repair"),
            )
            return AnswerResolution(None)
        if self.verification_enabled:
            checks = verification_steps(
                claims, tuple(inputs), messages, criteria,
                reuse_start_index=(len(inputs) if isinstance(decision, RecheckClaims) else reuse_start_index),
                prompts=self.prompts,
            )
            response = None
            while True:
                try:
                    step = checks.send(response)
                except StopIteration:
                    break
                response = yield step
        answer = self._current_answer(inputs, reuse_start_index=reuse_start_index)
        return AnswerResolution(
            FinalMessage(disposition="answer", segments=answer) if answer is not None else None,
        )

    def _current_answer(self, inputs, *, reuse_start_index: int):
        current = (accepted_research(inputs, reuse_start_index=reuse_start_index, prompts=self.prompts)
                   if self.verification_enabled else current_claims(inputs))
        return current.final_answer if current is not None and current.final_answer else None

    def recovery_steps(self, *, inputs, messages, criteria, reuse_start_index):
        current = current_claims(inputs)
        if current is None or not current.final_answer:
            return None
        review = applicable_research_review(current, inputs, reuse_start_index=reuse_start_index, prompts=self.prompts)
        if self.verification_enabled and review is None:
            checks = verification_steps(current, tuple(inputs), messages, criteria,
                reuse_start_index=reuse_start_index, prompts=self.prompts)
            response = None
            while True:
                try:
                    step = checks.send(response)
                except StopIteration:
                    break
                response = yield step
        answer = self._current_answer(inputs, reuse_start_index=reuse_start_index)
        return FinalMessage(disposition="answer", segments=answer) if answer is not None else None

    def validate_final(self, decision, inputs, *, reuse_start_index: int, requires_review: bool, experiment_run: bool) -> DecisionFeedback | None:
        feedback = self._citation_feedback(decision, inputs)
        if feedback is not None:
            return feedback
        if decision.disposition != "answer" or not self.uses_claims(inputs,
                requires_review=requires_review, experiment_run=experiment_run):
            return None
        if decision.segments == self._current_answer(inputs, reuse_start_index=reuse_start_index):
            return None
        return DecisionFeedback(
            action_id="research-completion", reason_code="research_answer_not_approved",
            message=self.prompts.render("conversation.answer.research_answer_not_approved"),
            required_repair=self.prompts.render("conversation.answer.research_completion_repair"),
        )

    def needs_direct_verification(self, criteria, inputs) -> bool:
        return (super().needs_direct_verification(criteria, inputs)
                and current_claims(inputs) is None)
