"""Conversation-local history selection, immutable export and checkpoint activation."""
from collections.abc import Callable, Sequence
from hashlib import sha256
import json

from personal_agent.capabilities.contracts.model import (
    ModelCapacityRefused, ModelInvocationUnavailable, StructuredModelRequest,
    StructuredModelResponse, StructuredOutputFailure, sealed_context_projection_ref,
)
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.prompts import get_prompt
from personal_agent.kernel.contracts.resource import ResourceRef

from .citations import CitableInput
from .errors import ConversationOperationConflict
from .history_models import HistoryCompactionCheckpoint, HistoryItemKey, HistorySummary
from .journal import InMemoryInteractionJournal
from .models import ActionObservation, CommittedUsage, DecisionFeedback, InteractionInput, InteractionTrace
from .ports import InteractionArtifactPort


def _digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def item_key(item: InteractionInput) -> HistoryItemKey | None:
    if isinstance(item, (ActionObservation, DecisionFeedback)):
        return HistoryItemKey(kind=item.kind, action_id=item.action_id,
                              decision_turn=getattr(item, "decision_turn", None))
    return None


def checkpoint_refs(trace: InteractionTrace) -> tuple[ResourceRef, ...]:
    checkpoint = trace.history_compaction
    return (checkpoint.snapshot_ref,) if checkpoint else ()


class HistoryCompactor:
    """The journal owns facts and usage; this collaborator owns only their input view."""

    def __init__(self, *, journal: InMemoryInteractionJournal,
                 artifacts: InteractionArtifactPort,
                 generate: Callable[[StructuredModelRequest[HistorySummary]], StructuredModelResponse[HistorySummary]],
                 admit: Callable[[str, CommittedUsage], None],
                 record_usage: Callable[[CommittedUsage, StructuredModelResponse], CommittedUsage]) -> None:
        self.journal, self.artifacts = journal, artifacts
        self.generate, self.admit, self.record_usage = generate, admit, record_usage

    @staticmethod
    def _source(trace: InteractionTrace, end: int) -> list:
        return [item.model_dump(mode="json") for item in trace.inputs[:end]]

    def validate(self, trace: InteractionTrace) -> HistoryCompactionCheckpoint | None:
        checkpoint = trace.history_compaction
        if checkpoint is None:
            return None
        if (checkpoint.run_ref != trace.interaction_run_ref
                or checkpoint.source_revision > trace.revision
                or checkpoint.source_end > len(trace.inputs)
                or checkpoint.snapshot_ref.owner != trace.principal
                or _digest(self._source(trace, checkpoint.source_end)) != checkpoint.source_digest):
            raise ValueError("历史摘要的原始来源或主体已失效。")
        snapshot = self.artifacts.read_snapshot(checkpoint.snapshot_ref,
                            principal=trace.principal, owner=trace.principal)
        if (snapshot.content_digest != checkpoint.snapshot_digest
                or sha256(snapshot.content.encode("utf-8")).hexdigest() != checkpoint.snapshot_digest):
            raise ValueError("历史原件快照摘要不一致。")
        keys = {item_key(item) for item in trace.inputs[:checkpoint.source_end]}
        if len(set(checkpoint.covered_items)) != len(checkpoint.covered_items) or not set(checkpoint.covered_items) <= keys:
            raise ValueError("历史摘要覆盖无效或重复条目。")
        return checkpoint

    def project(self, trace: InteractionTrace, visible: Sequence[CitableInput],
                *, protected_citations: frozenset[str] = frozenset()) -> tuple[tuple[CitableInput, ...], str]:
        checkpoint = self.validate(trace)
        if checkpoint is None:
            return tuple(visible), ""
        covered = set(checkpoint.covered_items)
        result = tuple(item for item in visible
                       if item_key(item.observation) not in covered
                       or any(citation.evidence_id in protected_citations for citation in item.citations))
        facts = [{"action_id": item.action_id, "capability_id": item.capability_id,
                  "status": item.status}
                 for item in trace.inputs if isinstance(item, ActionObservation)]
        context = json.dumps({
            "explanation": "派生工作摘要，只帮助继续任务；不是执行、来源或批准事实。原件可用 read_artifact／search_action_output 读取；历史快照不是论文来源。当前目标、工作清单、原稿和额度仍以本次独立输入为准。",
            "working_summary": checkpoint.working_summary,
            "history_snapshot_ref": checkpoint.snapshot_ref.model_dump(mode="json"),
            "source_range": [0, checkpoint.source_end], "execution_status_facts": facts,
            "experiment_records": [record.model_dump(mode="json") for record in trace.experiment_records],
        }, ensure_ascii=False)
        return result, context

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

    def compact(self, run_ref: str) -> HistoryCompactionCheckpoint:
        trace = self.journal.get(run_ref)
        previous = self.validate(trace)
        old_keys = set(previous.covered_items) if previous else set()
        observations = [index for index, item in enumerate(trace.inputs) if isinstance(item, ActionObservation)]
        latest_feedback = next((index for index in range(len(trace.inputs) - 1, -1, -1)
                                if isinstance(trace.inputs[index], DecisionFeedback)), None)
        latest_verification = next((index for index in range(len(trace.inputs) - 1, -1, -1)
                                    if isinstance(trace.inputs[index], ActionObservation)
                                    and trace.inputs[index].capability_id == "verify_interaction_draft"), None)
        boundary = observations[-1] if observations else 0
        pending = {item.action_id for item in trace.accepted_tool_requests
                   if item.tool_name == "write_artifact" and item.receipt is None and item.failure is None}
        pending.update(item.action_id for item in trace.experiment_records
                       if item.receipt is None or item.receipt.status == "unknown")
        pending.update(item.action_id for item in trace.accepted_tool_requests
                       if item.tool_name == "execute_python"
                       and (item.receipt is None or item.receipt.status == "unknown"))
        choices = [(index, item_key(item)) for index, item in enumerate(trace.inputs[:boundary])
                   if item_key(item) is not None and item_key(item) not in old_keys
                   and index not in (latest_feedback, latest_verification)
                   and not (isinstance(item, ActionObservation)
                            and (item.status == "running" or item.action_id in pending))]
        if not choices:
            raise ValueError("没有新的闭合旧历史可压缩，已停止无进展的重复压缩。")
        prompt = get_prompt("conversation.history_compaction")
        while choices:
            self.admit(run_ref, self.journal.get(run_ref).usage)
            end = max(previous.source_end if previous else 0, choices[-1][0] + 1)
            source = self._source(trace, end)
            source_digest = _digest(source)
            text = "\n".join(json.dumps({"input_index": index, "input": item}, ensure_ascii=False)
                             for index, item in enumerate(source))
            content_digest = sha256(text.encode("utf-8")).hexdigest()
            scope = ExecutionScope(principal=trace.principal, execution_id=run_ref,
                                   thread_id=trace.conversation_id, task_id="history_context")
            snapshot_ref = self.artifacts.write_generated(owner=trace.principal, execution_scope=scope,
                producer_key=f"history:{run_ref}:{source_digest}", producer_ref=f"{run_ref}:inputs:0:{end}:{source_digest}",
                kind="conversation_history", content=text, content_digest=content_digest,
                source_artifact_refs=(), evidence_refs=(), limitations=("运行历史原件，不是外部证据。",))
            exported = self.artifacts.read_snapshot(snapshot_ref, principal=trace.principal, owner=trace.principal)
            if exported.content != text or exported.content_digest != content_digest:
                raise ValueError("历史原件导出不完整，不能让原历史退出输入。")
            messages = [{"role": "system", "content": prompt.template}, {"role": "user", "content": json.dumps({
                "previous_summary": previous.working_summary if previous else None,
                "snapshot_ref": snapshot_ref.model_dump(mode="json"),
                "new_closed_history": [trace.inputs[index].model_dump(mode="json") for index, _ in choices],
            }, ensure_ascii=False)}]
            request = StructuredModelRequest(operation="conversation_history_compaction", version=prompt.version,
                messages=messages, output_type=HistorySummary, max_tokens=8192,
                extra_body={"thinking": {"type": "disabled"}},
                context_projection_ref=sealed_context_projection_ref(purpose="conversation_history_compaction", messages=messages),
                metadata={"component": "conversation_history", "prompt_name": prompt.name})
            try:
                response = self.generate(request)
            except ModelCapacityRefused as error:
                if error.response is not None or getattr(error, "prior_responses", ()):
                    self.record_failure(run_ref, error)
                    raise
                if error.reason_code != "context_capacity_exceeded" or len(choices) == 1:
                    raise
                choices = choices[:len(choices) // 2]
                continue
            except (ModelInvocationUnavailable, StructuredOutputFailure) as error:
                self.record_failure(run_ref, error)
                raise
            paid = self.record_response(run_ref, response)
            self.admit(run_ref, paid.usage)
            summary = HistorySummary.model_validate(response.value).working_summary.strip()
            raw = response.raw_response
            choices_out = getattr(raw, "choices", ()) or ()
            if not summary or any(getattr(choice, "finish_reason", None) == "length" for choice in choices_out):
                raise ValueError("历史摘要为空或被截断，未激活。")
            if self._source(paid, end) != source or paid.history_compaction != previous:
                raise ConversationOperationConflict("摘要期间历史或检查点已变化，费用保留但不覆盖新状态。")
            checkpoint = HistoryCompactionCheckpoint(run_ref=run_ref, source_revision=trace.revision,
                source_end=end, source_digest=source_digest, covered_items=tuple(sorted(
                    old_keys | {key for _, key in choices}, key=lambda key: (key.kind, key.action_id, key.decision_turn or 0))),
                snapshot_ref=snapshot_ref, snapshot_digest=content_digest, working_summary=summary,
                prompt_version=prompt.version, model=response.model, response_id=getattr(raw, "id", None),
                response_digest=_digest({"content": response.content, "model": response.model,
                                         "response_id": getattr(raw, "id", None)}),
                previous_checkpoint_digest=_digest(previous.model_dump(mode="json")) if previous else None)
            def activate(current):
                if current.revision != paid.revision or current.history_compaction != previous:
                    raise ConversationOperationConflict("历史摘要激活时 Journal revision 冲突。")
                return current.model_copy(update={"revision": current.revision + 1, "history_compaction": checkpoint})
            self.journal.update(scope, activate)
            return checkpoint
        raise ValueError("历史摘要没有安全覆盖区间。")
