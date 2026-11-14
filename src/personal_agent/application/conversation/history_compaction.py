"""Conversation-local history selection, immutable export and checkpoint activation."""
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from pydantic import ValidationError

from personal_agent.capabilities.contracts.model import (
    ModelActionDefinition, ModelAssistantMessage, ModelCapacityRefused, ModelInvocationUnavailable, StructuredModelRequest,
    StructuredModelResponse, StructuredOutputFailure, sealed_context_projection_ref,
)
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
from personal_agent.kernel.contracts.resource import ResourceRef

from .artifact_search import SearchActionOutputArguments
from .artifact_sources import input_resource_refs
from .citations import CitableInput
from .context_materialization import ARTIFACT_OUTPUT_CAPABILITIES, READ_ARTIFACT_CAPABILITY, artifact_read_actions
from .errors import ConversationOperationConflict
from .history_models import (
    HistoryCompactionCheckpoint, HistorySummary,
    VerificationHistoryCheckpoint, VerificationTurnCompaction,
)
from .journal import InMemoryInteractionJournal
from .models import ActionObservation, CommittedUsage, DecisionFeedback, InteractionTrace, ModelDecisionRecord
from .ports import InteractionArtifactPort
from .model_history import (
    active_history_checkpoint, decision_input_indices, history_summary_context, is_runtime_feedback, selected_analysis_turns,
    task_switch_input_indices,
)
from .history_compaction_source import (
    covered_observation_key, history_digest, main_decisions, render_history_run, run_source, select_coverage,
    snapshot_json, snapshot_result_positions,
)
from .analysis_tasks import task_message_indices
from .goal_maintenance import goal_context
from .verification_context import verification_prefix
from personal_agent.capabilities.contracts.verification import VerificationContext
from personal_agent.capabilities.contracts.verification_prompt import verification_judgment_text


# Keep source descriptions small even when a call includes a document body.
_MAX_SOURCE_ARGUMENT_CHARS = 512


@dataclass(frozen=True, slots=True)
class HistoryProjection:
    inputs: tuple[CitableInput, ...]
    summary: str
    recovery: str


@dataclass(frozen=True, slots=True)
class _ValidatedHistory:
    checkpoint: HistoryCompactionCheckpoint
    exported: list[dict]
    content: str


def _source_arguments(assistant: ModelAssistantMessage | None, action_id: str) -> str | None:
    if assistant is None:
        return None
    for call in assistant.payload.get("tool_calls") or ():
        if call["id"] == action_id:
            function = call.get("function")
            arguments = function.get("arguments") if isinstance(function, dict) else None
            if isinstance(arguments, str) and len(arguments) <= _MAX_SOURCE_ARGUMENT_CHARS:
                return arguments
            break
    return None


def _snapshot_search_keyword(content: str, snapshot_id: str, observation: ActionObservation) -> str | None:
    # The call ID also occurs in the assistant message. Match the receipt's JSON prefix.
    keyword = snapshot_json({"action_id": observation.action_id, "capability_id": observation.capability_id})[:-1]
    try:
        SearchActionOutputArguments(resource_id=snapshot_id, keyword=keyword)
    except ValidationError:
        return None
    matches = re.finditer(re.escape(keyword), content, flags=re.IGNORECASE)
    first = next(matches, None)
    return keyword if first is not None and next(matches, None) is None else None


def _digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def checkpoint_refs(trace: InteractionTrace, candidates: Sequence[InteractionTrace] = ()) -> tuple[ResourceRef, ...]:
    previous = selected_analysis_turns(trace, candidates)
    checkpoint = active_history_checkpoint(trace, previous)
    if checkpoint is None:
        return ()
    return (*checkpoint.prior_snapshot_refs, checkpoint.snapshot_ref)


def recorded_checkpoint_refs(sources: Sequence[InteractionTrace]) -> frozenset[ResourceRef]:
    """Identify history artifacts without granting model visibility."""
    return frozenset(ref for source in sources if source.history_compaction is not None
        for ref in (*source.history_compaction.prior_snapshot_refs, source.history_compaction.snapshot_ref))


class HistoryCompactor:
    """The journal owns facts and usage; this collaborator owns only their input view."""

    def __init__(self, *, journal: InMemoryInteractionJournal,
                 artifacts: InteractionArtifactPort,
                 generate: Callable[[StructuredModelRequest[HistorySummary], str], StructuredModelResponse[HistorySummary]],
                 record_usage: Callable[[CommittedUsage, StructuredModelResponse], CommittedUsage],
                 prompts: PromptCatalog = DEFAULT_PROMPTS) -> None:
        self.journal, self.artifacts = journal, artifacts
        self.generate, self.record_usage = generate, record_usage
        self._prompts = prompts

    def project_verification(
        self, run_ref: str, context: VerificationContext, checkpoint: VerificationHistoryCheckpoint | None,
        *, previous_turns: tuple[InteractionTrace, ...],
    ) -> VerificationContext:
        if checkpoint is None:
            return context
        if checkpoint.kind != context.kind:
            raise ConversationOperationConflict("verification summary belongs to another responsibility")
        trace = self.journal.get(run_ref)
        allowed_runs = {source.interaction_run_ref for source in (*previous_turns, trace)}
        turns = list(context.turns)
        seen = set()
        for item in checkpoint.turns:
            if item.user_turn in seen or item.user_turn > len(turns) or item.summary_run_ref not in allowed_runs:
                raise ConversationOperationConflict("verification summary belongs to another history")
            seen.add(item.user_turn)
            source = turns[item.user_turn - 1]
            if item.covered_events > len(source.events):
                raise ConversationOperationConflict("verification summary source range changed")
            text = verification_prefix(source, item.covered_events, kind=context.kind)
            if sha256(text.encode()).hexdigest() != item.source_digest:
                raise ConversationOperationConflict("verification summary source changed")
            snapshot = self.artifacts.read_snapshot(item.snapshot_ref, principal=trace.principal, owner=trace.principal)
            if snapshot.content != text or snapshot.content_digest != item.source_digest:
                raise ConversationOperationConflict("verification summary snapshot changed")
            summary_trace = self.journal.get(item.summary_run_ref)
            if not any(record.invocation_id == item.model_invocation_id and record.response_refs
                       and record.status == "decoded" for record in summary_trace.model_decisions):
                raise ConversationOperationConflict("verification summary has no completed model response")
            turns[item.user_turn - 1] = source.model_copy(update={
                "summary": item.working_summary, "events": source.events[item.covered_events:]})
        return context.model_copy(update={"turns": tuple(turns)})

    def compact_verification(
        self, run_ref: str, context: VerificationContext, previous: VerificationHistoryCheckpoint | None,
        *, previous_turns: tuple[InteractionTrace, ...], task_id: str | None,
    ) -> VerificationHistoryCheckpoint:
        trace = self.journal.get(run_ref)
        if previous is not None and previous.kind != context.kind:
            raise ConversationOperationConflict("verification summary belongs to another responsibility")
        existing = {item.user_turn: item for item in previous.turns} if previous else {}
        sources = (*previous_turns, trace)
        target = None
        for turn in context.turns:
            # The whole current user turn, including unresolved feedback, stays verbatim.
            source = sources[turn.user_turn - 1]
            if source.final_message is None or source.final_message.disposition != "answer":
                continue
            if not turn.events or turn.events[-1].verdict is None or turn.events[-1].verdict.verdict != "passed":
                continue
            end = len(turn.events)
            while end and turn.events[end - 1].verdict is None:
                end -= 1
            old = existing.get(turn.user_turn)
            if end > (old.covered_events if old else 0):
                target = turn, end, old
                break
        if target is None:
            raise ConversationOperationConflict("verification history has no safe prefix to compact")
        turn, end, old = target
        text = verification_prefix(turn, end, kind=context.kind)
        digest = sha256(text.encode()).hexdigest()
        scope = ExecutionScope(principal=trace.principal, execution_id=run_ref,
            thread_id=trace.conversation_id, task_id=f"{context.kind}_verification_history")
        reference = self.artifacts.write_generated(owner=trace.principal, execution_scope=scope,
            producer_key=f"verification-history:{digest}", producer_ref=f"{run_ref}:{turn.user_turn}:{end}",
            kind="conversation_history", content=text, content_digest=digest,
            source_artifact_refs=(), evidence_refs=(),
            limitations=(self._prompts.get("conversation.history.snapshot_limitation").template,))
        prompt = self._prompts.get(f"conversation.{context.kind}_verification_history_compaction")
        parts = []
        if turn.question is not None:
            parts.append(self._prompts.render("interaction_verification.history.user_turn",
                number=turn.user_turn, question=turn.question))
        if old is not None:
            parts.append(self._prompts.render("conversation.context.history_previous_summary", summary=old.working_summary))
        for item in turn.events[old.covered_events if old else 0:end]:
            parts.append(self._prompts.render("conversation.context.history_verification_entry",
                submission_id=item.submission_id, text=item.content))
            if item.verdict is not None:
                parts.append(self._prompts.render("interaction_verification.history.judgment",
                    submission_id=item.submission_id, judgment=verification_judgment_text(item.verdict, prompts=self._prompts)))
        system = prompt.template
        if context.kind == "goal":
            system += "\n\n" + self._prompts.get("conversation.goal.snapshot_fields").template
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": "\n\n".join(parts)}]
        request = StructuredModelRequest(operation=f"conversation_{context.kind}_verification_history_compaction",
            version=prompt.version, consumer_key=f"verification-summary:{run_ref}:{digest}",
            messages=messages, output_type=HistorySummary, output_transport="native_tool", max_tokens=8192,
            context_projection_ref=sealed_context_projection_ref(purpose="verification_history", messages=messages))
        try:
            response = self.generate(request, run_ref)
        except (ModelInvocationUnavailable, StructuredOutputFailure) as error:
            self.record_failure(run_ref, error)
            raise
        paid = self.record_response(run_ref, response)
        summary = HistorySummary.model_validate(response.value).working_summary.strip()
        if not summary or len(summary) >= len(text) or not response.response_records:
            raise ConversationOperationConflict("verification summary is incomplete or did not reduce input")
        if paid.messages != trace.messages or paid.goal_operations != trace.goal_operations:
            raise ConversationOperationConflict("verification state changed during compaction")
        item = VerificationTurnCompaction(user_turn=turn.user_turn, covered_events=end,
            source_digest=digest, snapshot_ref=reference, working_summary=summary,
            model_invocation_id=response.response_records[-1].invocation_id, summary_run_ref=run_ref)
        existing[turn.user_turn] = item
        checkpoint = VerificationHistoryCheckpoint(kind=context.kind, prompt_version=prompt.version, task_id=task_id,
            turns=tuple(existing[key] for key in sorted(existing)))
        self.journal.update(scope, lambda current: current.model_copy(update={
            "revision": current.revision + 1,
            "verification_history_compactions": (*(
                item for item in current.verification_history_compactions if item.kind != context.kind), checkpoint),
            "model_decisions": tuple(record.model_copy(update={"consumed": True})
                if record.invocation_id == item.model_invocation_id else record for record in current.model_decisions)}))
        return checkpoint

    def _sources(self, trace: InteractionTrace) -> tuple[InteractionTrace, ...]:
        return (*selected_analysis_turns(trace, self.journal.task_traces(trace)), trace)

    def has_safe_prefix(self, run_ref: str) -> bool:
        trace = self.journal.get(run_ref)
        previous = self.validate(trace)
        coverage = select_coverage(self._sources(trace), previous)
        return bool(coverage and (previous is None or coverage != previous.sources))

    def validate(self, trace: InteractionTrace,
                 candidate: HistoryCompactionCheckpoint | None = None) -> HistoryCompactionCheckpoint | None:
        validated = self._validated_history(trace, candidate)
        return validated.checkpoint if validated is not None else None

    def _validated_history(
        self, trace: InteractionTrace, candidate: HistoryCompactionCheckpoint | None,
    ) -> _ValidatedHistory | None:
        sources = self._sources(trace)
        checkpoint = candidate or active_history_checkpoint(trace, sources[:-1])
        if checkpoint is None:
            return None
        by_run = {source.interaction_run_ref: source for source in sources}
        if (checkpoint.run_ref not in by_run or checkpoint.snapshot_ref.owner != trace.principal
                or checkpoint.source_revision > by_run[checkpoint.run_ref].revision):
            raise ConversationOperationConflict(self._prompts.render("conversation.history.source_invalid"))
        if len({item.run_ref for item in checkpoint.sources}) != len(checkpoint.sources):
            raise ConversationOperationConflict(self._prompts.render("conversation.history.coverage_invalid"))
        exported = []
        for item in checkpoint.sources:
            source = by_run.get(item.run_ref)
            if source is None or not any(record.turn_index == item.through_turn for record in main_decisions(source)):
                raise ConversationOperationConflict(self._prompts.render("conversation.history.decision_missing"))
            if item.includes_final and source.final_message is None:
                raise ConversationOperationConflict(self._prompts.render("conversation.history.source_invalid"))
            content = run_source(source, item.through_turn, item.includes_final)
            if history_digest(content) != item.source_digest:
                raise ConversationOperationConflict(self._prompts.render("conversation.history.source_changed"))
            exported.append(content)
        if history_digest(exported) != checkpoint.source_digest:
            raise ConversationOperationConflict(self._prompts.render("conversation.history.source_changed"))
        snapshot = self.artifacts.read_snapshot(checkpoint.snapshot_ref,
            principal=trace.principal, owner=trace.principal)
        if (sha256(snapshot.content.encode("utf-8")).hexdigest() != checkpoint.snapshot_digest
                or snapshot.content_digest != checkpoint.snapshot_digest
                or json.loads(snapshot.content) != exported):
            raise ConversationOperationConflict(self._prompts.render("conversation.history.snapshot_digest_invalid"))
        return _ValidatedHistory(checkpoint, exported, snapshot.content)

    def _summary_context(self, checkpoint: HistoryCompactionCheckpoint) -> str:
        return history_summary_context(checkpoint, self._prompts)

    def project_messages(self, trace: InteractionTrace, messages: list[dict],
                         candidate: HistoryCompactionCheckpoint | None = None) -> list[dict]:
        checkpoint = self.validate(trace, candidate)
        if checkpoint is None:
            return messages
        turns = self._sources(trace)
        sources = {source.interaction_run_ref: source for source in turns}
        indices = task_message_indices(trace, turns[:-1])
        has_partial_tail = not checkpoint.sources[-1].includes_final
        completed = [item for item in checkpoint.sources if item.includes_final]
        result = [dict(message) for message in messages]
        for item in completed:
            original = len(sources[item.run_ref].messages)
            index = indices.index(original) + 1
            if index >= len(result) or result[index]["role"] != "assistant":
                raise ConversationOperationConflict(self._prompts.render("conversation.history.source_invalid"))
            result[index]["content"] = (self._summary_context(checkpoint)
                if not has_partial_tail and item == completed[-1]
                else self._prompts.get("conversation.history.covered_answer").template)
        return result

    def project(self, trace: InteractionTrace, visible: Sequence[CitableInput],
                *, protected_citations: frozenset[str] = frozenset(),
                candidate: HistoryCompactionCheckpoint | None = None,
                actions: Sequence[ModelActionDefinition] = ()) -> HistoryProjection:
        validated = self._validated_history(trace, candidate)
        if validated is None:
            return HistoryProjection(inputs=tuple(visible), summary="", recovery="")
        checkpoint = validated.checkpoint
        snapshot_id = checkpoint.snapshot_ref.resource_id
        snapshot_readers = artifact_read_actions(snapshot_id, actions)
        sources = self._sources(trace)
        coverage = {item.run_ref: item for item in checkpoint.sources}
        covered: dict[tuple, tuple[str, ModelDecisionRecord, int]] = {}
        protected = set()
        recent = main_decisions(trace)[-2:]
        for record in recent:
            protected.update(covered_observation_key(trace.inputs[index])
                             for index in decision_input_indices(trace, record))
        for source in sources:
            item = coverage.get(source.interaction_run_ref)
            if item is None:
                continue
            for record in main_decisions(source):
                if record.turn_index > item.through_turn:
                    continue
                for ordinal, index in enumerate(decision_input_indices(source, record)):
                    observation = source.inputs[index]
                    if source.interaction_run_ref == trace.interaction_run_ref or not is_runtime_feedback(observation):
                        covered[covered_observation_key(observation)] = (source.interaction_run_ref, record, ordinal)
        excluded = {covered_observation_key(trace.inputs[index])
                    for index in task_switch_input_indices(trace)
                    if isinstance(trace.inputs[index], (ActionObservation, DecisionFeedback))}
        result = []
        artifact_sources = []
        positions = snapshot_result_positions(validated.content, validated.exported) if snapshot_readers else {}
        snapshot_reader = next((action for action in snapshot_readers if action.target_name == READ_ARTIFACT_CAPABILITY), None)
        for item in visible:
            observation = item.observation
            key = covered_observation_key(observation) if isinstance(observation, (ActionObservation, DecisionFeedback)) else None
            if key in excluded:
                continue
            cited = any(citation.evidence_id in protected_citations for citation in item.citations)
            if key not in covered or cited or key in protected:
                result.append(item)
                continue
            if not actions or not isinstance(observation, ActionObservation):
                continue
            run_ref, record, ordinal = covered[key]
            refs = input_resource_refs((observation,))
            position = positions.get((run_ref, record.turn_index, ordinal))
            if (not refs and (position is None or not item.citations
                              or observation.capability_id in ARTIFACT_OUTPUT_CAPABILITIES)):
                continue
            arguments = _source_arguments(record.assistant, observation.action_id)
            argument_context = (self._prompts.render("conversation.context.history_arguments", arguments=arguments)
                                if arguments is not None else "")
            source = dict(run_ref=run_ref, turn=record.turn_index, action_id=observation.action_id,
                          source_tool=observation.capability_id)
            for ref in refs:
                readers = artifact_read_actions(ref.resource_id, actions)
                if readers:
                    artifact_sources.append(self._prompts.render("conversation.context.history_artifact",
                        **source, resource_id=ref.resource_id,
                        readers=", ".join(reader.name for reader in readers), arguments=argument_context))
            if refs or position is None:
                continue
            label = self._prompts.render("conversation.context.history_source", **source)
            if snapshot_reader is not None:
                artifact_sources.append(self._prompts.render("conversation.context.history_inline_read",
                    source=label, resource_id=snapshot_id, reader=snapshot_reader.name,
                    line=position.line, column=position.column, arguments=argument_context))
                continue
            keyword = _snapshot_search_keyword(validated.content, snapshot_id, observation)
            if keyword is not None:
                artifact_sources.append(self._prompts.render("conversation.context.history_inline_search",
                    source=label, resource_id=snapshot_id, reader=snapshot_readers[0].name,
                    keyword=keyword, arguments=argument_context))

        if snapshot_readers:
            artifact_sources.append(self._prompts.render("conversation.context.history_snapshot",
                resource_id=snapshot_id, readers=", ".join(reader.name for reader in snapshot_readers)))
        recovery = (self._prompts.render("conversation.history.result_locations", locations="\n".join(artifact_sources))
                    if artifact_sources else "")
        return HistoryProjection(inputs=tuple(result), summary=self._summary_context(checkpoint), recovery=recovery)

    def record_response(self, run_ref: str, response: StructuredModelResponse) -> InteractionTrace:
        trace = self.journal.get(run_ref)
        scope = ExecutionScope(principal=trace.principal, execution_id=run_ref,
                               thread_id=trace.conversation_id, task_id="history_context")
        return self.journal.update(scope, lambda latest: latest.model_copy(update={
            "revision": latest.revision + 1,
            "usage": self.record_usage(latest.usage, response),
        }))

    def record_failure(self, run_ref: str, error: Exception) -> None:
        responses = (*getattr(error, "prior_responses", ()),
                     *((error.response,) if getattr(error, "response", None) is not None else ()))
        for response in responses:
            self.record_response(run_ref, response)
        if isinstance(error, ModelInvocationUnavailable):
            trace = self.journal.get(run_ref)
            scope = ExecutionScope(principal=trace.principal, execution_id=run_ref,
                                   thread_id=trace.conversation_id, task_id="history_context")
            self.journal.update(scope, lambda current: current.model_copy(update={
                "revision": current.revision + 1,
                "usage": current.usage.model_copy(update={"provider_usage_complete": False}),
            }))
        error.response = None
        error.prior_responses = ()

    def compact(self, run_ref: str, *, verify_reduction: Callable[[HistoryCompactionCheckpoint], None] | None = None,
                ) -> HistoryCompactionCheckpoint:
        trace = self.journal.get(run_ref)
        sources = self._sources(trace)
        previous = self.validate(trace)
        coverage = select_coverage(sources, previous)
        if not coverage or (previous is not None and coverage == previous.sources):
            raise ValueError(self._prompts.render("conversation.history.no_closed_progress"))
        old = {item.run_ref: item for item in previous.sources} if previous else {}
        by_run = {source.interaction_run_ref: source for source in sources}
        exported = [run_source(by_run[item.run_ref], item.through_turn, item.includes_final) for item in coverage]
        new_history = "\n\n".join(render_history_run(by_run[item.run_ref], item,
            after_turn=old[item.run_ref].through_turn if item.run_ref in old else 0, prompts=self._prompts)
            for item in coverage if item != old.get(item.run_ref))
        source_digest = history_digest(exported)
        text = snapshot_json(exported)
        content_digest = sha256(text.encode("utf-8")).hexdigest()
        scope = ExecutionScope(principal=trace.principal, execution_id=run_ref,
            thread_id=trace.conversation_id, task_id="history_context")
        snapshot_ref = self.artifacts.write_generated(owner=trace.principal, execution_scope=scope,
            producer_key=f"history:{run_ref}:{source_digest}", producer_ref=f"{run_ref}:history:{source_digest}",
            kind="conversation_history", content=text, content_digest=content_digest,
            source_artifact_refs=(), evidence_refs=(),
            limitations=(self._prompts.get("conversation.history.snapshot_limitation").template,))
        snapshot = self.artifacts.read_snapshot(snapshot_ref, principal=trace.principal, owner=trace.principal)
        if snapshot.content != text or snapshot.content_digest != content_digest:
            raise ConversationOperationConflict(self._prompts.render("conversation.history.export_incomplete"))
        prompt = self._prompts.get("conversation.history_compaction")
        delivery = self._prompts.get("conversation.context.history.delivered"
            if trace.final_message is not None else "conversation.context.history.partial").template
        contents = self._prompts.render("conversation.context.history_input",
            question=trace.messages[-1].content,
            goal=goal_context(trace, sources[:-1], prompts=self._prompts),
            delivery=delivery, history=new_history, snapshot_id=snapshot_ref.resource_id)
        if previous is not None:
            contents = self._prompts.render("conversation.context.history_previous_summary",
                summary=previous.working_summary) + "\n\n" + contents
        system = prompt.template
        version = prompt.version
        snapshot_prompt = self._prompts.get("conversation.goal.snapshot_fields")
        system += "\n\n" + snapshot_prompt.template
        version += "+" + snapshot_prompt.version
        messages = [{"role": "system", "content": system}, {"role": "user", "content": contents}]
        request = StructuredModelRequest(operation="conversation_history_compaction", version=version,
            consumer_key="conversation:history_compaction", messages=messages, output_type=HistorySummary,
            output_transport="native_tool", max_tokens=8192,
            context_projection_ref=sealed_context_projection_ref(purpose="conversation_history_compaction", messages=messages),
            metadata={"component": "conversation_history", "prompt_name": prompt.name})
        try:
            response = self.generate(request, run_ref)
        except (ModelCapacityRefused, ModelInvocationUnavailable, StructuredOutputFailure) as error:
            self.record_failure(run_ref, error)
            raise
        paid = self.record_response(run_ref, response)
        summary = HistorySummary.model_validate(response.value).working_summary.strip()
        choices = (response.raw_response or {}).get("choices", ()) or ()
        original_size = len(json.dumps(new_history, ensure_ascii=True)) + len(
            json.dumps(previous.working_summary if previous else "", ensure_ascii=True))
        if (not summary or len(json.dumps(summary, ensure_ascii=True)) >= original_size
                or any(choice.get("finish_reason") == "length" for choice in choices)):
            raise ValueError(self._prompts.render("conversation.history.summary_incomplete"))
        if select_coverage(self._sources(paid), previous) != coverage or paid.history_compaction != trace.history_compaction:
            raise ConversationOperationConflict(self._prompts.render("conversation.history.source_changed"))
        checkpoint = HistoryCompactionCheckpoint(run_ref=run_ref, source_revision=trace.revision,
            source_digest=source_digest, sources=coverage, snapshot_ref=snapshot_ref,
            snapshot_digest=content_digest, working_summary=summary, prompt_version=version,
            prior_snapshot_refs=tuple(dict.fromkeys((*previous.prior_snapshot_refs, previous.snapshot_ref))) if previous else (),
            model=response.model, response_id=(response.raw_response or {}).get("id"),
            response_digest=_digest({"content": response.content, "model": response.model,
                                     "response_id": (response.raw_response or {}).get("id")}),
            previous_checkpoint_digest=_digest(previous.model_dump(mode="json")) if previous else None)
        if verify_reduction is not None:
            verify_reduction(checkpoint)
        def activate(current):
            if current.revision != paid.revision or current.history_compaction != trace.history_compaction:
                raise ConversationOperationConflict(self._prompts.render("conversation.history.activation_conflict"))
            return current.model_copy(update={"revision": current.revision + 1, "history_compaction": checkpoint,
                "model_decisions": tuple(record.model_copy(update={"consumed": True})
                    if record.operation == request.operation and record.status == "decoded" else record
                    for record in current.model_decisions)})
        self.journal.update(scope, activate)
        return checkpoint
