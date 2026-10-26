"""Replaceable answer writers; the Conversation loop owns calls and persistence.

Writers yield typed proposals/checks to that one loop. They never execute tools,
charge usage, write a Journal, or manufacture a verification pass.
"""

from collections.abc import Generator, Sequence
from dataclasses import dataclass

from pydantic import BaseModel
from copy import deepcopy

from personal_agent.capabilities.contracts.model import StructuredModelRequest, ModelActionDefinition, ModelAssistantMessage
from personal_agent.kernel.llm_schemas import model_tool_wire_name
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig
from personal_agent.kernel.contracts.resource import ResourceRef

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
            "提交完整用户正文；message 可直接使用 Markdown。references 只选当前可见文档行坐标。提交不代表核验或完成。")]
        submitted = next((item for item in reversed(inputs) if isinstance(item, SubmittedFinal)), None)
        if submitted is not None:
            schema = ReviseFinalArguments.model_json_schema()
            schema["properties"]["base_resource_id"]["enum"] = [submitted.resource_ref.resource_id]
            actions.append(self._action("revise_final", schema,
                "修订最新完整基稿。选择其资源ID，按1起始segment提交编辑；未改段由Runtime原样保留。"))
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
                raise ValueError("只能选择当前最新可见的完整基稿。")
            edits = tuple(FinalSegmentEdit(segment=edit.segment, operation=edit.operation, text=edit.text,
                references=tuple(ConversationEvidenceReference(evidence_id=ref) for ref in edit.references)) for edit in args.edits)
            return materialize_final_revision(FinalRevision(base_ref=current.resource_ref, edits=edits), inputs)
        raise ValueError("当前回答模块没有此操作。")

    def decode_assistant_message(self, message: ModelAssistantMessage | None, inputs, **conditions) -> FinalMessage:
        """Interpret the original visible body without inventing a tool call."""
        if message is None or message.call_ids:
            raise ValueError("普通回答须来自没有工具调用的合法 assistant 消息。")
        text = message.visible_text
        if text is None or not text.strip():
            raise ValueError("模型尚未返回非空可见正文；reasoning 不能作为回答。")
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

    @staticmethod
    def _citation_feedback(decision, inputs) -> DecisionFeedback | None:
        try:
            materialize_cited_draft(decision.segments, inputs)
        except CitationBindingError as error:
            return DecisionFeedback(
                action_id="answer-result", action_name="final_message", reason_code=error.reason_code,
                message=f"{error}\n完整提交及逐段引用见最新 submitted_final。",
                repairable_fields=("segments",),
                required_repair="修正引用或补读后重新提交完整回答，不要编造证据。",
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
            "逐项覆盖全部requirements，选择实际返回的引用并决定write、acquire或limit；来源出现不代表已决定写作。"))
        if selection is None or selection.next_step != "write":
            return tuple(actions)
        inherited = selected_citation_ids(tuple(ref for claim in current.claims for ref in claim.references), inputs) if current else frozenset()
        visible = tuple(item.model_copy(update={"citations": tuple(c for c in item.citations
                         if c.evidence_id in selected_ids or c.evidence_id in inherited)})
                        for item in materialize_citation_context(materialize_interaction_inputs(inputs)))
        operations = ((CreateClaims, ReturnToActions, StopResearch) if current is None else
            (ReviseClaimFragment, ReplaceClaimReferences, AddClaims, DeleteClaim, RecheckClaims, ReturnToActions, StopResearch))
        for operation in operations:
            name = operation.model_fields["kind"].annotation.__args__[0]
            schema = deepcopy(research_operation_schema(operation, current, visible))
            schema.get("properties", {}).pop("kind", None)
            schema["required"] = [field for field in schema.get("required", []) if field != "kind"]
            if "base_ref" in schema["properties"]:
                schema["properties"].pop("base_ref")
                schema["properties"]["base_resource_id"] = {"type": "string", "enum": [current.resource_ref.resource_id]}
                schema["required"] = ["base_resource_id" if field == "base_ref" else field for field in schema["required"]]
            actions.append(self._action(name, schema, "沿当前完整研究版本执行此操作；新增引用须来自本次有效选证，原文和版本由Runtime恢复。"))
        return tuple(actions)

    def decode_operation(self, invocation, inputs, **conditions):
        if self.uses_claims(inputs, **conditions) and (
            invocation.operation == "revise_final"
            or (invocation.operation == "submit_final" and invocation.arguments.get("disposition") == "answer")
        ):
            raise ValueError("当前须沿研究选证与claims操作提交；普通回答/修订不能绕过当前写作模块。")
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
                    raise ValueError("研究操作必须选择当前完整研究版本。")
                payload["base_ref"] = current.resource_ref
            return cls.model_validate({**payload, "kind": invocation.operation})
        return super().decode_operation(invocation, inputs, **conditions)

    def decode_assistant_message(self, message: ModelAssistantMessage | None, inputs, **conditions) -> FinalMessage:
        if self.uses_claims(inputs, **conditions):
            raise ValueError("当前须沿研究选证与 claims 操作提交；普通正文不能绕过当前写作模块。")
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
                required_repair="使用正式可用动作继续工作；根据当前证据重新选择，再沿当前研究版本提交完整回答。",
            )
            return AnswerResolution(None)
        try:
            claims = admit_claim_change(decision, inputs, reference, selected_ids)
        except (ValueError, CitationBindingError) as error:
            yield DecisionFeedback(
                action_id="research-admission", reason_code="research_edit_invalid",
                message=str(error), required_repair="核对当前完整版本、精确片段和可见引用后修正参数；被拒动作未改变集合。",
            )
            return AnswerResolution(None)
        yield claims
        if not claims.final_answer or not "".join(segment.text for segment in claims.final_answer).strip():
            yield DecisionFeedback(
                action_id="research-final", reason_code="final_answer_missing",
                message="研究进展已保存，但尚未提交完整最终回答，不能交付。",
                required_repair="继续取证或沿当前版本提交 final_answer；仅修改回答可用 control_recheck_claims。",
            )
            return AnswerResolution(None)
        if self.verification_enabled:
            checks = verification_steps(
                claims, tuple(inputs), messages, criteria,
                reuse_start_index=(len(inputs) if isinstance(decision, RecheckClaims) else reuse_start_index),
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
        current = (accepted_research(inputs, reuse_start_index=reuse_start_index)
                   if self.verification_enabled else current_claims(inputs))
        return current.final_answer if current is not None and current.final_answer else None

    def recovery_steps(self, *, inputs, messages, criteria, reuse_start_index):
        current = current_claims(inputs)
        if current is None or not current.final_answer:
            return None
        review = applicable_research_review(current, inputs, reuse_start_index=reuse_start_index)
        if self.verification_enabled and review is None:
            checks = verification_steps(current, tuple(inputs), messages, criteria,
                reuse_start_index=reuse_start_index)
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
            message="只能交付当前完整研究版本的确切回答，并满足本次装配的核验契约。",
            required_repair="沿当前研究版本修订或补证后重新提交，不能另写答案绕过研究。",
        )

    def needs_direct_verification(self, criteria, inputs) -> bool:
        return (super().needs_direct_verification(criteria, inputs)
                and current_claims(inputs) is None)
