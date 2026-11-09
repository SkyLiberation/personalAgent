"""Conversation-local history selection, immutable export and checkpoint activation."""
from collections.abc import Callable, Sequence
from hashlib import sha256
import json

from personal_agent.capabilities.contracts.model import (
    ModelCapacityRefused, ModelInvocationUnavailable, StructuredModelRequest,
    StructuredModelResponse, StructuredOutputFailure, sealed_context_projection_ref,
)
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
from personal_agent.kernel.contracts.resource import ResourceRef

from .citations import CitableInput
from .errors import ConversationOperationConflict
from .history_models import (
    HistoryCompactionCheckpoint, HistorySummary,
    VerificationHistoryCheckpoint, VerificationTurnCompaction,
)
from .journal import InMemoryInteractionJournal
from .models import ActionObservation, CommittedUsage, DecisionFeedback, InteractionTrace
from .ports import InteractionArtifactPort
from .model_history import (
    active_history_checkpoint, decision_input_indices, history_summary_context, is_runtime_feedback, prior_analysis_turns,
)
from .history_compaction_source import (
    covered_observation_key, history_digest, main_decisions, run_source, select_coverage,
)
from .goal_maintenance import goal_context
from .verification_context import verification_prefix
from personal_agent.capabilities.contracts.verification import VerificationContext


def _digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def checkpoint_refs(trace: InteractionTrace, candidates: Sequence[InteractionTrace] = ()) -> tuple[ResourceRef, ...]:
    sources = (*prior_analysis_turns(trace, candidates), trace)
    return tuple(dict.fromkeys(ref for source in sources if source.history_compaction is not None
        for ref in (*source.history_compaction.prior_snapshot_refs, source.history_compaction.snapshot_ref)))


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
    ) -> VerificationContext:
        if checkpoint is None:
            return context
        if checkpoint.kind != context.kind:
            raise ConversationOperationConflict("verification summary belongs to another responsibility")
        trace = self.journal.get(run_ref)
        allowed_runs = {source.interaction_run_ref for source in (
            *prior_analysis_turns(trace, self.journal.analysis_traces(trace)), trace)}
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
    ) -> VerificationHistoryCheckpoint:
        trace = self.journal.get(run_ref)
        if previous is not None and previous.kind != context.kind:
            raise ConversationOperationConflict("verification summary belongs to another responsibility")
        existing = {item.user_turn: item for item in previous.turns} if previous else {}
        sources = (*prior_analysis_turns(trace, self.journal.analysis_traces(trace)), trace)
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
        payload = {
            "previous_summary": old.working_summary if old else None,
            "new_events": [item.model_dump(mode="json") for item in turn.events[old.covered_events if old else 0:end]],
        }
        if turn.question is not None:
            payload = {"user_question": turn.question, **payload}
        messages = [{"role": "system", "content": prompt.template},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
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
        checkpoint = VerificationHistoryCheckpoint(kind=context.kind, prompt_version=prompt.version,
            turns=tuple(existing[key] for key in sorted(existing)))
        self.journal.update(scope, lambda current: current.model_copy(update={
            "revision": current.revision + 1,
            "verification_history_compactions": (*(
                item for item in current.verification_history_compactions if item.kind != context.kind), checkpoint),
            "model_decisions": tuple(record.model_copy(update={"consumed": True})
                if record.invocation_id == item.model_invocation_id else record for record in current.model_decisions)}))
        return checkpoint

    def _sources(self, trace: InteractionTrace) -> tuple[InteractionTrace, ...]:
        return (*prior_analysis_turns(trace, self.journal.analysis_traces(trace)), trace)

    def has_safe_prefix(self, run_ref: str) -> bool:
        trace = self.journal.get(run_ref)
        previous = self.validate(trace)
        coverage = select_coverage(self._sources(trace), previous)
        return bool(coverage and (previous is None or coverage != previous.sources))

    def validate(self, trace: InteractionTrace,
                 candidate: HistoryCompactionCheckpoint | None = None) -> HistoryCompactionCheckpoint | None:
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
        return checkpoint

    def _summary_context(self, checkpoint: HistoryCompactionCheckpoint) -> str:
        return history_summary_context(checkpoint, self._prompts)

    def project_messages(self, trace: InteractionTrace, messages: list[dict],
                         candidate: HistoryCompactionCheckpoint | None = None) -> list[dict]:
        checkpoint = self.validate(trace, candidate)
        if checkpoint is None:
            return messages
        sources = {source.interaction_run_ref: source for source in self._sources(trace)}
        has_partial_tail = not checkpoint.sources[-1].includes_final
        completed = [item for item in checkpoint.sources if item.includes_final]
        result = [dict(message) for message in messages]
        for item in completed:
            index = len(sources[item.run_ref].messages) + 1  # stable system prefix, then conversation
            if index >= len(result) or result[index]["role"] != "assistant":
                raise ConversationOperationConflict(self._prompts.render("conversation.history.source_invalid"))
            result[index]["content"] = (self._summary_context(checkpoint)
                if not has_partial_tail and item == completed[-1]
                else self._prompts.render("conversation.history.covered_answer", resource_id=checkpoint.snapshot_ref.resource_id))
        return result

    def project(self, trace: InteractionTrace, visible: Sequence[CitableInput],
                *, protected_citations: frozenset[str] = frozenset(),
                candidate: HistoryCompactionCheckpoint | None = None) -> tuple[tuple[CitableInput, ...], str]:
        checkpoint = self.validate(trace, candidate)
        sources = self._sources(trace)
        coverage = {item.run_ref: item for item in checkpoint.sources} if checkpoint else {}
        covered = set()
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
                for index in decision_input_indices(source, record):
                    observation = source.inputs[index]
                    if source.interaction_run_ref == trace.interaction_run_ref or not is_runtime_feedback(observation):
                        covered.add(covered_observation_key(observation))
        result = []
        for item in visible:
            observation = item.observation
            key = covered_observation_key(observation) if isinstance(observation, (ActionObservation, DecisionFeedback)) else None
            cited = any(citation.evidence_id in protected_citations for citation in item.citations)
            if key in covered and not cited and key not in protected:
                continue
            result.append(item)
        context = self._summary_context(checkpoint) if checkpoint else ""
        return tuple(result), context

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
        new_history = [run_source(by_run[item.run_ref], item.through_turn, item.includes_final,
            after_turn=old[item.run_ref].through_turn if item.run_ref in old else 0)
            for item in coverage if item != old.get(item.run_ref)]
        source_digest = history_digest(exported)
        text = json.dumps(exported, ensure_ascii=False, sort_keys=True)
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
        messages = [{"role": "system", "content": prompt.template}, {"role": "user", "content": json.dumps({
            "previous_summary": previous.working_summary if previous else None,
            "current_user_request": trace.messages[-1].content,
            "current_goal": goal_context(trace, sources[:-1], prompts=self._prompts),
            "current_turn_delivered": trace.final_message is not None,
            "new_closed_interactions": new_history,
            "snapshot_ref": snapshot_ref.model_dump(mode="json"),
        }, ensure_ascii=False)}]
        request = StructuredModelRequest(operation="conversation_history_compaction", version=prompt.version,
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
            snapshot_digest=content_digest, working_summary=summary, prompt_version=prompt.version,
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
