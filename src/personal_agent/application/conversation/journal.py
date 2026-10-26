"""Conversation execution facts and their durable snapshot projection."""

from __future__ import annotations

import json
import logging
import os
import re
from hashlib import sha256
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import ValidationError
from personal_agent.capabilities.contracts.model import ModelInvocationContinuation, ModelResponseRecord

from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.evidence import EvidenceItem
from personal_agent.kernel.contracts.tool_runtime import accepted_tool_request_digest
from personal_agent.application.artifacts.models import ArtifactWriteReceipt, resolve_artifact_ref
from personal_agent.application.retrieval_experiment.models import (
    ExperimentToolArgs,
    ExperimentRecord,
    ExperimentCommand,
    ExperimentExecutionFact,
    ExperimentActionReceipt,
    ExperimentJournalView,
)
from personal_agent.application.python_execution.models import (
    canonical_digest,
    ExecutePythonArgs,
    PythonExecutionCommand,
    PythonExecutionFact,
    PythonExecutionReceipt,
    PythonJournalView,
)
from .artifact_sources import trace_resource_refs
from .tool_requests import WriteArtifactArgs

from .errors import ConversationOperationNotFound, ConversationOperationConflict
from .journal_lock import exclusive_run_lock
from .model_history import validate_decision_extension
from .models import (
    ActionObservation,
    CommittedUsage,
    ConversationWorkingPlan,
    InteractionTrace,
    AcceptedArtifactToolRequest,
    AcceptedExperimentToolRequest,
    AcceptedPythonToolRequest,
    RunExecutionBudget,
    ModelDecisionRecord, StoredModelRequest, ModelRequestReference, ModelResponseReference,
)


logger = logging.getLogger(__name__)


class InMemoryInteractionJournal:
    """Append-only execution facts used to rebuild transient interaction context."""

    def __init__(self) -> None:
        self._traces: dict[str, InteractionTrace] = {}
        self._lock = RLock()
        self._model_request_originals: dict[tuple[str, str], str] = {}
        self._model_response_originals: dict[tuple[str, str], list[str]] = {}

    def recover_model_response_originals(self, scope):
        """Account complete orphan tail originals before admission of new work."""
        trace = self.get(scope.execution_id)
        if trace is None:
            raise ConversationOperationNotFound("interaction run not found")
        if trace.principal != scope.principal or trace.conversation_id != scope.thread_id:
            raise PermissionError("interaction journal scope mismatch")
        for record in trace.model_decisions:
            if record.consumed:
                continue
            for original in self._response_originals(scope.execution_id, record.invocation_id):
                self.record_model_response(scope, original)
        return self.get(scope.execution_id)

    def begin_model_invocation(self, scope, request):
        """Persist original request and stable identity before any paid send."""
        trace = self.get(scope.execution_id)
        if trace is None:
            raise ConversationOperationNotFound("interaction run not found")
        if trace.principal != scope.principal or trace.conversation_id != scope.thread_id:
            raise PermissionError("interaction journal scope mismatch")
        pending = next((record for record in reversed(trace.model_decisions)
                        if not record.consumed and record.operation == request.operation
                        and record.request.consumer_key == request.consumer_key), None)
        if pending is not None:
            stored = self.model_request(scope.execution_id, pending)
            if (request.kind != stored.kind or request.max_output_repairs != stored.max_output_repairs
                    or request.output_transport != stored.output_transport or request.response_format != stored.response_format):
                raise ConversationOperationConflict("未消费模型调用的当前输出策略或修复额度已变化")
            # Recover complete sequenced originals written before a crashed Trace commit.
            for observed in self._response_originals(scope.execution_id, pending.invocation_id):
                self.record_model_response(scope, observed)
            pending = next(record for record in self.get(scope.execution_id).model_decisions
                           if record.invocation_id == pending.invocation_id)
            original = self.model_request(scope.execution_id, pending).restore(request.output_type)
            return original, ModelInvocationContinuation.for_request(original,
                invocation_id=pending.invocation_id, response_records=self.model_response_records(scope.execution_id, pending))
        invocation_id = uuid4().hex
        stored = StoredModelRequest.from_request(request)
        text = stored.model_dump_json()
        self._write_request_original(scope.execution_id, invocation_id, text)
        reference = ModelRequestReference(invocation_id=invocation_id, operation=request.operation,
            request_digest=stored.request_digest, content_digest=sha256(text.encode("utf-8")).hexdigest(),
            context_projection_ref=stored.context_projection_ref, consumer_key=stored.consumer_key,
            output_type_name=stored.output_type_name,
            output_schema_digest=canonical_digest(stored.output_schema) if stored.output_schema is not None else None, max_output_repairs=stored.max_output_repairs,
            kind=stored.kind)
        record = ModelDecisionRecord(invocation_id=invocation_id, operation=request.operation,
            request=reference, input_start=len(trace.inputs),
            turn_index=None)
        self.update(scope, lambda current: current.model_copy(update={"revision": current.revision + 1,
            "model_decisions": (*current.model_decisions, record)}))
        return request, ModelInvocationContinuation.for_request(request, invocation_id=invocation_id)

    def record_model_response(self, scope, response: ModelResponseRecord):
        """Commit each actual attempt once, before the Adapter decodes it."""
        def append(trace):
            records = list(trace.model_decisions)
            index = next((i for i, item in enumerate(records) if item.invocation_id == response.invocation_id), None)
            if index is None:
                raise ConversationOperationConflict("模型原响应缺少已存调用绑定")
            invocation = records[index]
            if (response.operation != invocation.operation or response.request_digest != invocation.request.request_digest
                    or response.context_projection_ref != invocation.request.context_projection_ref):
                raise ConversationOperationConflict("模型原响应绑定与已存原请求不一致")
            existing_ref = next((item for record in records for item in record.response_refs
                                 if item.attempt_id == response.attempt_id), None)
            if existing_ref is not None and existing_ref.invocation_id != response.invocation_id:
                raise ConversationOperationConflict("模型attempt身份已属于另一调用")
            existing = self._response_originals(scope.execution_id, response.invocation_id)[existing_ref.sequence] if existing_ref is not None else None
            if existing is not None:
                if existing != response:
                    raise ConversationOperationConflict("同一模型attempt原件不可改写")
                return trace
            sequence = len(invocation.response_refs)
            text = response.model_dump_json()
            self._write_response_original(scope.execution_id, response.invocation_id, sequence, response.attempt_id, text)
            reference = ModelResponseReference(invocation_id=response.invocation_id, attempt_id=response.attempt_id,
                sequence=sequence, content_digest=sha256(text.encode("utf-8")).hexdigest())
            records[index] = invocation.model_copy(update={"response_refs": (*invocation.response_refs, reference),
                "turn_index": invocation.turn_index or (trace.usage.model_turns + 1 if invocation.request.kind == "tool_calling" else None)})
            usage = trace.usage
            complete = (usage.provider_usage_complete and response.input_tokens is not None
                        and response.output_tokens is not None and usage.model_calls is not None
                        and usage.input_tokens is not None and usage.output_tokens is not None)
            total = response.total_tokens
            if total is None:
                total = (response.input_tokens or 0) + (response.output_tokens or 0)
            usage = usage.model_copy(update={"provider_usage_complete": complete,
                "model_calls": usage.model_calls + 1 if complete else None,
                "input_tokens": usage.input_tokens + response.input_tokens if complete else None,
                "output_tokens": usage.output_tokens + response.output_tokens if complete else None,
                "total_tokens": usage.total_tokens + total})
            return trace.model_copy(update={"revision": trace.revision + 1,
                "model_decisions": tuple(records), "usage": usage})
        return self.update(scope, append)

    def finish_model_invocation(self, scope, invocation_id, *, response=None, failure=None):
        def finish(trace):
            records = list(trace.model_decisions)
            index = next(i for i, item in enumerate(records) if item.invocation_id == invocation_id)
            previous = records[index]
            if response is not None:
                originals = self.model_response_records(scope.execution_id, previous)
                if tuple(response.response_records) != originals:
                    raise ConversationOperationConflict("解码结果未绑定当前完整响应原件序列")
            records[index] = previous.model_copy(update={
                "assistant": response.assistant_message if response is not None else previous.assistant,
                "protocol_exchanges": response.protocol_exchanges if response is not None else previous.protocol_exchanges,
                "status": "decoded" if failure is None else "invalid" if previous.response_refs else "failed",
                "diagnostics": str(failure)[:2000] if failure is not None else None,
                "consumed": failure is not None and not previous.response_refs})
            return trace.model_copy(update={"revision": trace.revision + 1, "model_decisions": tuple(records)})
        return self.update(scope, finish)

    def _write_request_original(self, run_ref, invocation_id, text):
        key = (run_ref, invocation_id)
        existing = self._model_request_originals.get(key)
        if existing is not None and existing != text:
            raise ConversationOperationConflict("模型原请求不可改写")
        self._model_request_originals[key] = text

    def _read_request_original(self, run_ref, invocation_id):
        return self._model_request_originals[(run_ref, invocation_id)]

    def _write_response_original(self, run_ref, invocation_id, sequence, attempt_id, text):
        originals = self._model_response_originals.setdefault((run_ref, invocation_id), [])
        if sequence < len(originals):
            if originals[sequence] != text:
                raise ConversationOperationConflict("模型响应序号原件冲突")
        elif sequence == len(originals):
            originals.append(text)
        else:
            raise ConversationOperationConflict("模型响应原件序号不连续")

    def _response_originals(self, run_ref, invocation_id):
        return tuple(ModelResponseRecord.model_validate_json(text)
            for text in self._model_response_originals.get((run_ref, invocation_id), ()))

    def model_request(self, run_ref, record):
        text = self._read_request_original(run_ref, record.invocation_id)
        if sha256(text.encode("utf-8")).hexdigest() != record.request.content_digest:
            raise ConversationOperationConflict("模型原请求引用摘要不匹配")
        stored = StoredModelRequest.model_validate_json(text)
        if (stored.request_digest != record.request.request_digest or stored.operation != record.operation
                or stored.consumer_key != record.request.consumer_key
                or (canonical_digest(stored.output_schema) if stored.output_schema is not None else None) != record.request.output_schema_digest):
            raise ConversationOperationConflict("模型原请求绑定不匹配")
        return stored

    def model_response_records(self, run_ref, record):
        originals = self._response_originals(run_ref, record.invocation_id)
        if len(originals) < len(record.response_refs):
            raise ConversationOperationConflict("已提交模型响应原件缺失")
        result = []
        for index, reference in enumerate(record.response_refs):
            original = originals[index]
            text = original.model_dump_json()
            if (reference.sequence != index or reference.invocation_id != record.invocation_id
                    or original.attempt_id != reference.attempt_id
                    or sha256(text.encode("utf-8")).hexdigest() != reference.content_digest):
                raise ConversationOperationConflict("模型响应原件引用或序号不匹配")
            if (original.invocation_id != record.invocation_id or original.operation != record.operation
                    or original.request_digest != record.request.request_digest
                    or original.context_projection_ref != record.request.context_projection_ref):
                raise ConversationOperationConflict("模型响应原件请求绑定不匹配")
            result.append(original)
        if record.assistant is not None and result:
            allowed = (result[-1],) if record.consumed else result
            if not any(record.assistant == original.assistant_message for original in allowed):
                raise ConversationOperationConflict("模型assistant投影与响应原件不一致")
        return tuple(result)

    def exclusive_run(self, run_ref: str):
        self._validate_run_ref(run_ref)
        return exclusive_run_lock(f"memory:{id(self)}:{run_ref}", None)

    def exclusive_conversation(self, conversation_id: str, principal: AuthenticatedPrincipal):
        key = canonical_digest({"principal": principal.model_dump(mode="json"),
                                "conversation_id": conversation_id})
        return exclusive_run_lock(f"memory:{id(self)}:conversation:{key}", None)

    @staticmethod
    def _validate_run_ref(run_ref: str) -> None:
        if not re.fullmatch(r"irun_[A-Za-z0-9_-]+", run_ref):
            raise ValueError("invalid interaction run reference")

    def put(
        self, trace: InteractionTrace, *, expected_revision: int | None = None
    ) -> None:
        with self.exclusive_run(trace.interaction_run_ref):
            previous = self.get(trace.interaction_run_ref)
            self._check_revision(trace, previous, expected_revision)
            with self._lock:
                self._traces[trace.interaction_run_ref] = trace

    @staticmethod
    def _check_revision(trace, previous, expected_revision):
        if previous == trace:
            return
        expected = (
            trace.revision - 1 if expected_revision is None else expected_revision
        )
        if (
            previous.revision if previous else 0
        ) != expected or trace.revision != expected + 1:
            raise ConversationOperationConflict("interaction journal revision changed")
        if previous is not None and (
            previous.principal != trace.principal
            or previous.conversation_id != trace.conversation_id
            or previous.messages != trace.messages
            or previous.input_artifact_refs != trace.input_artifact_refs
            or previous.deployment_digest != trace.deployment_digest
            or previous.python_authorization_digest != trace.python_authorization_digest
            or previous.answer_result_binding != trace.answer_result_binding
            or previous.run_deadline_at != trace.run_deadline_at
            or previous.max_execution_seconds != trace.max_execution_seconds
        ):
            raise ConversationOperationConflict(
                "interaction journal input binding changed"
            )
        if previous is not None:
            validate_decision_extension(previous, trace)
            for accepted in previous.accepted_tool_requests:
                current = next(
                    (
                        item
                        for item in trace.accepted_tool_requests
                        if item.action_id == accepted.action_id
                    ),
                    None,
                )
                if current is None or (
                    current.execution_scope != accepted.execution_scope
                    or current.tool_name != accepted.tool_name
                    or current.arguments != accepted.arguments
                    or current.request_digest != accepted.request_digest
                    or current.plan_step_id != accepted.plan_step_id
                ):
                    raise ConversationOperationConflict(
                        "accepted tool request is immutable"
                    )

    def update(
        self,
        execution_scope: ExecutionScope,
        change: Callable[[InteractionTrace], InteractionTrace],
    ) -> InteractionTrace:
        with self.exclusive_run(execution_scope.execution_id):
            latest = self.get(execution_scope.execution_id)
            if latest is None:
                raise ConversationOperationNotFound("interaction run not found")
            if (
                latest.principal != execution_scope.principal
                or latest.conversation_id != execution_scope.thread_id
            ):
                raise PermissionError("interaction journal scope mismatch")
            updated = change(latest)
            if updated == latest:
                return latest
            updated = InteractionTrace.model_validate(updated.model_dump(mode="python"))
            self.put(updated, expected_revision=latest.revision)
            return updated

    def get(self, interaction_run_ref: str) -> InteractionTrace | None:
        self._validate_run_ref(interaction_run_ref)
        with self._lock:
            return self._traces.get(interaction_run_ref)

    def accept_tool_request(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        arguments: WriteArtifactArgs | ExperimentToolArgs | ExecutePythonArgs,
        plan_step_id: str | None,
    ):
        if isinstance(arguments, WriteArtifactArgs):
            tool_name, request_type = "write_artifact", AcceptedArtifactToolRequest
        elif isinstance(arguments, ExperimentToolArgs):
            tool_name, request_type = "retrieval_experiment", AcceptedExperimentToolRequest
        elif isinstance(arguments, ExecutePythonArgs):
            tool_name, request_type = "execute_python", AcceptedPythonToolRequest
        else:
            raise TypeError("unsupported accepted tool request")
        request = request_type(
            action_id=action_id,
            execution_scope=execution_scope,
            arguments=arguments,
            request_digest=accepted_tool_request_digest(
                execution_scope=execution_scope,
                action_id=action_id,
                tool_name=tool_name,
                arguments=arguments,
            ),
            plan_step_id=plan_step_id,
        )
        if execution_scope.task_id != action_id:
            raise PermissionError("accepted action identity does not match its scope")

        def accept(latest):
            previous = next(
                (
                    item
                    for item in latest.accepted_tool_requests
                    if item.action_id == action_id
                ),
                None,
            )
            if previous is not None:
                if (
                    previous.execution_scope != request.execution_scope
                    or previous.tool_name != request.tool_name
                    or previous.arguments != request.arguments
                    or previous.request_digest != request.request_digest
                    or previous.plan_step_id != request.plan_step_id
                ):
                    raise ConversationOperationConflict(
                        "action_id is already bound to a different accepted request"
                    )
                return latest
            if tool_name in {"retrieval_experiment", "execute_python"} and (
                (latest.deployment_digest if tool_name == "retrieval_experiment"
                 else latest.python_profile_digest) is None
                or latest.run_deadline_at is None
                or latest.max_execution_seconds is None
            ):
                raise PermissionError(
                    "当前运行没有绑定获准的执行配置、截止和额度"
                )
            return latest.model_copy(
                update={
                    "revision": latest.revision + 1,
                    "accepted_tool_requests": (*latest.accepted_tool_requests, request),
                }
            )

        updated = self.update(execution_scope, accept)
        return next(
            item
            for item in updated.accepted_tool_requests
            if item.action_id == action_id
        )

    @staticmethod
    def _accepted(trace, scope, action_id, request_digest=None):
        accepted = next(
            (
                item
                for item in trace.accepted_tool_requests
                if item.action_id == action_id
            ),
            None,
        )
        if (
            accepted is None
            or accepted.execution_scope != scope
            or scope.task_id != action_id
            or request_digest is not None
            and accepted.request_digest != request_digest
        ):
            raise PermissionError(
                "tool request has not been accepted in this exact scope"
            )
        expected = accepted_tool_request_digest(
            execution_scope=scope,
            action_id=action_id,
            tool_name=accepted.tool_name,
            arguments=accepted.arguments,
        )
        if expected != accepted.request_digest:
            raise PermissionError("accepted tool request digest is inconsistent")
        return accepted

    def record_artifact_result(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        receipt: ArtifactWriteReceipt | None = None,
        failure: ActionObservation | None = None,
    ) -> None:
        def record(latest):
            accepted = self._accepted(latest, execution_scope, action_id)
            if not isinstance(accepted, AcceptedArtifactToolRequest) or (
                receipt is None
            ) == (failure is None):
                raise ValueError(
                    "Artifact result requires exactly one receipt or failure"
                )
            if accepted.receipt is not None or accepted.failure is not None:
                if accepted.receipt != receipt or accepted.failure != failure:
                    raise ConversationOperationConflict(
                        "accepted Artifact outcome already differs"
                    )
                return latest
            if receipt is not None and (
                receipt.resource_ref.owner != execution_scope.principal
                or receipt.resource_ref.resource_type != "artifact"
            ):
                raise PermissionError("Artifact receipt scope mismatch")
            if failure is not None and (
                failure.action_id != action_id
                or failure.status != "failed"
                or failure.capability_id != "write_artifact"
            ):
                raise ValueError("Artifact failure is not bound to the accepted action")
            updated = accepted.model_copy(
                update={"receipt": receipt, "failure": failure}
            )
            return latest.model_copy(
                update={
                    "revision": latest.revision + 1,
                    "accepted_tool_requests": tuple(
                        updated if item.action_id == action_id else item
                        for item in latest.accepted_tool_requests
                    ),
                }
            )

        self.update(execution_scope, record)

    def load(
        self, *, execution_scope: ExecutionScope, action_id: str, request_digest: str
    ) -> ExperimentJournalView:
        trace = self.get(execution_scope.execution_id)
        if (
            trace is None
            or trace.principal != execution_scope.principal
            or trace.conversation_id != execution_scope.thread_id
        ):
            raise PermissionError("experiment journal scope mismatch")
        accepted = self._accepted(trace, execution_scope, action_id, request_digest)
        if (
            not isinstance(accepted, AcceptedExperimentToolRequest)
            or trace.deployment_digest is None
            or trace.run_deadline_at is None
            or trace.max_execution_seconds is None
        ):
            raise PermissionError("experiment deployment is not bound to this run")
        budget = self.execution_budget(trace)
        return ExperimentJournalView(
            execution_scope=execution_scope,
            action_id=action_id,
            action=accepted.arguments.action,
            request_digest=request_digest,
            deployment_digest=trace.deployment_digest,
            allowed_artifact_refs=trace_resource_refs(trace),
            run_deadline_at=trace.run_deadline_at,
            remaining_execution_seconds=budget.remaining_seconds,
            records=trace.experiment_records,
        )

    def conversation_traces(
        self, conversation_id: str, principal: AuthenticatedPrincipal,
    ) -> tuple[InteractionTrace, ...]:
        with self._lock:
            candidates = tuple(self._traces.values())
        return tuple(sorted((trace for trace in candidates
                             if trace.conversation_id == conversation_id and trace.principal == principal),
                            key=lambda trace: (len(trace.messages), trace.interaction_run_ref)))

    def analysis_traces(self, trace: InteractionTrace) -> tuple[InteractionTrace, ...]:
        if trace.python_authorization_digest is None:
            return (trace,)
        candidates = tuple(item for item in self.conversation_traces(trace.conversation_id, trace.principal)
                           if item.python_authorization_digest is not None)
        if any(item.python_authorization_digest != trace.python_authorization_digest for item in candidates):
            raise PermissionError("同一分析对话不能更换授权身份并重置额度")
        if not any(item.interaction_run_ref == trace.interaction_run_ref for item in candidates):
            raise ConversationOperationNotFound("分析运行尚未提交至Journal")
        return candidates

    def conversation_usage(self, trace: InteractionTrace) -> CommittedUsage:
        usages = tuple(item.usage for item in self.analysis_traces(trace))
        complete = all(item.provider_usage_complete for item in usages)
        return CommittedUsage(
            provider_usage_complete=complete,
            model_calls=sum(item.model_calls for item in usages) if all(item.model_calls is not None for item in usages) else None,
            input_tokens=sum(item.input_tokens for item in usages) if all(item.input_tokens is not None for item in usages) else None,
            output_tokens=sum(item.output_tokens for item in usages) if all(item.output_tokens is not None for item in usages) else None,
            total_tokens=sum(item.total_tokens for item in usages),
            model_turns=sum(item.model_turns for item in usages),
            tool_calls=sum(item.tool_calls for item in usages),
            agent_calls=sum(item.agent_calls for item in usages),
        )

    def readable_resource_refs(self, trace: InteractionTrace) -> tuple[ResourceRef, ...]:
        return tuple(dict.fromkeys(ref for item in self.analysis_traces(trace)
                                   for ref in trace_resource_refs(item)))

    def analysis_observations(self, trace: InteractionTrace) -> tuple[ActionObservation, ...]:
        observations: list[ActionObservation] = []
        for source in self.analysis_traces(trace):
            if source.interaction_run_ref == trace.interaction_run_ref:
                continue
            owned = {item.action_id for item in source.accepted_tool_requests
                     if item.tool_name in {"execute_python", "write_artifact"}}
            observations.extend(item for item in source.inputs if isinstance(item, ActionObservation)
                                and item.action_id in owned and item.status == "succeeded"
                                and item.capability_id in {"execute_python", "write_artifact"})
        return tuple(observations)

    def execution_budget(self, trace: InteractionTrace) -> RunExecutionBudget:
        """Both execution consumers derive allowance from the same committed facts."""
        consumed = 0.0
        unsettled: list[str] = []
        records = ((source, record) for source in self.analysis_traces(trace)
                   for record in (*source.experiment_records, *(item for item in source.accepted_tool_requests
                                   if isinstance(item, AcceptedPythonToolRequest))))
        for source, record in records:
            if record.command is None:
                continue
            fact = record.execution
            if fact is None or fact.status in {"dispatching", "unknown"}:
                consumed += record.command.reserved_seconds
                unsettled.append(f"{source.interaction_run_ref}:{record.action_id}"
                                 if trace.python_authorization_digest is not None else record.action_id)
            else:
                consumed += (
                    fact.elapsed_seconds if fact.elapsed_seconds is not None
                    else record.command.reserved_seconds
                )
        return RunExecutionBudget(
            consumed_seconds=consumed,
            remaining_seconds=max(0.0, (trace.max_execution_seconds or 0.0) - consumed),
            unsettled_action_ids=tuple(unsettled),
        )

    def load_python_execution(
        self, *, execution_scope: ExecutionScope, action_id: str, request_digest: str
    ) -> PythonJournalView:
        trace = self.get(execution_scope.execution_id)
        if (trace is None or trace.principal != execution_scope.principal
                or trace.conversation_id != execution_scope.thread_id):
            raise PermissionError("Python journal scope mismatch")
        accepted = self._accepted(trace, execution_scope, action_id, request_digest)
        if (not isinstance(accepted, AcceptedPythonToolRequest)
                or trace.python_profile_digest is None or trace.run_deadline_at is None
                or trace.max_execution_seconds is None):
            raise PermissionError("Python execution is not authorized for this run")
        return PythonJournalView(
            execution_scope=execution_scope, action_id=action_id,
            arguments=accepted.arguments, request_digest=request_digest,
            deployment_digest=trace.python_profile_digest, allowed_refs=self.readable_resource_refs(trace),
            run_deadline_at=trace.run_deadline_at,
            remaining_execution_seconds=self.execution_budget(trace).remaining_seconds,
            command=accepted.command, execution=accepted.execution, receipt=accepted.receipt,
        )

    def _update_python(self, scope: ExecutionScope, action_id: str, change) -> None:
        def update(trace):
            accepted = self._accepted(trace, scope, action_id)
            if not isinstance(accepted, AcceptedPythonToolRequest):
                raise PermissionError("accepted request is not Python execution")
            updated = change(trace, accepted)
            if updated == accepted:
                return trace
            return trace.model_copy(update={
                "revision": trace.revision + 1,
                "accepted_tool_requests": tuple(
                    updated if item.action_id == action_id else item
                    for item in trace.accepted_tool_requests
                ),
            })
        self.update(scope, update)

    def bind_python_command(
        self, *, execution_scope: ExecutionScope, action_id: str,
        command: PythonExecutionCommand,
    ) -> None:
        def bind(trace, accepted):
            if accepted.command is not None:
                if accepted.command != command:
                    raise ConversationOperationConflict("Python command already differs")
                return accepted
            if (command.execution_scope != execution_scope or command.action_id != action_id
                    or command.request_digest != accepted.request_digest
                    or command.deployment_digest != trace.python_profile_digest
                    or trace.run_deadline_at is None or command.deadline_at > trace.run_deadline_at):
                raise PermissionError("Python command binding mismatch")
            if tuple((item.name, item.resource_ref) for item in command.inputs) != tuple(
                    (item.name, resolve_artifact_ref(
                        item.resource_id, self.readable_resource_refs(trace), principal=trace.principal
                    )) for item in accepted.arguments.input_files):
                raise PermissionError("Python command changed accepted input bindings")
            code = accepted.arguments.code.encode("utf-8")
            if (command.program.content_digest != sha256(code).hexdigest()
                    or command.program.size_bytes != len(code)):
                raise PermissionError("Python command changed accepted program")
            budget = self.execution_budget(trace)
            if any(item != action_id for item in budget.unsettled_action_ids):
                raise PermissionError("reconcile the pending execution before starting another")
            if command.reserved_seconds > budget.remaining_seconds:
                raise PermissionError("shared execution allowance exhausted")
            return accepted.model_copy(update={"command": command})
        self._update_python(execution_scope, action_id, bind)

    def record_python_execution(
        self, *, execution_scope: ExecutionScope, action_id: str,
        fact: PythonExecutionFact,
    ) -> None:
        def record(trace, accepted):
            if accepted.command is None:
                raise PermissionError("Python execution requires its frozen command")
            if (accepted.execution is not None
                    and accepted.execution.status not in {"dispatching", "unknown"}):
                if accepted.execution != fact:
                    raise ConversationOperationConflict("Python terminal cannot change")
                return accepted
            return accepted.model_copy(update={"execution": fact})
        self._update_python(execution_scope, action_id, record)

    def record_python_result(
        self, *, execution_scope: ExecutionScope, action_id: str,
        receipt: PythonExecutionReceipt,
    ) -> None:
        def record(trace, accepted):
            command, fact = accepted.command, accepted.execution
            if (command is None or fact is None or receipt.action_id != action_id
                    or receipt.command_digest != command.command_digest
                    or receipt.program_ref != command.program.resource_ref
                    or receipt.process_exit_code != fact.process_exit_code
                    or receipt.elapsed_seconds != fact.elapsed_seconds
                    or receipt.limits != command.limits):
                raise PermissionError("Python receipt is not bound to actual execution")
            protocol_failure = fact.status == "succeeded" and (
                receipt.status == "invalid_output" or (
                    receipt.status == "failed" and receipt.error_code == "output_unavailable"
                    and receipt.stdout_ref is None and receipt.stderr_ref is None
                )
            )
            if receipt.status != fact.status and not protocol_failure:
                raise ValueError("Python receipt contradicts process status")
            refs = (receipt.program_ref, receipt.input_manifest_ref,
                    *((receipt.stdout_ref,) if receipt.stdout_ref else ()),
                    *((receipt.stderr_ref,) if receipt.stderr_ref else ()))
            if any(ref.owner != execution_scope.principal or ref.resource_type != "artifact"
                   for ref in refs):
                raise PermissionError("Python output reference scope mismatch")
            if accepted.receipt is not None and accepted.receipt.status != "unknown":
                if accepted.receipt != receipt:
                    raise ConversationOperationConflict("Python receipt already differs")
                return accepted
            return accepted.model_copy(update={"receipt": receipt})
        self._update_python(execution_scope, action_id, record)

    def _update_experiment(self, scope, action_id, change):
        def update(latest):
            accepted = self._accepted(latest, scope, action_id)
            if not isinstance(accepted, AcceptedExperimentToolRequest):
                raise PermissionError("accepted request is not an experiment")
            previous = next(
                (
                    item
                    for item in latest.experiment_records
                    if item.action_id == action_id
                ),
                ExperimentRecord(
                    action_id=action_id, request_digest=accepted.request_digest
                ),
            )
            updated = change(latest, accepted, previous)
            if updated == previous and previous in latest.experiment_records:
                return latest
            records = tuple(
                item
                for item in latest.experiment_records
                if item.action_id != action_id
            ) + (updated,)
            return latest.model_copy(
                update={"revision": latest.revision + 1, "experiment_records": records}
            )

        self.update(scope, update)

    def bind_command(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        command: ExperimentCommand,
    ) -> None:
        def bind(trace, accepted, previous):
            if previous.command is not None:
                if previous.command != command:
                    raise ConversationOperationConflict(
                        "experiment command already differs"
                    )
                return previous
            if (
                command.execution_scope != execution_scope
                or command.action_id != action_id
                or command.request_digest != accepted.request_digest
                or command.deployment_digest != trace.deployment_digest
                or trace.run_deadline_at is None
                or command.deadline_at > trace.run_deadline_at
            ):
                raise PermissionError("experiment command binding mismatch")
            view = self.load(
                execution_scope=execution_scope,
                action_id=action_id,
                request_digest=accepted.request_digest,
            )
            if command.reserved_seconds > view.remaining_execution_seconds:
                raise PermissionError("experiment execution allowance exhausted")
            if any(item != action_id for item in self.execution_budget(trace).unsettled_action_ids):
                raise PermissionError("reconcile the pending execution before starting another")
            return previous.model_copy(update={"command": command})

        self._update_experiment(execution_scope, action_id, bind)

    def record_execution(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        fact: ExperimentExecutionFact,
    ) -> None:
        def record(trace, accepted, previous):
            if previous.command is None:
                raise PermissionError("execution requires its accepted command")
            if previous.execution is not None and previous.execution.status not in {
                "dispatching",
                "unknown",
            }:
                if previous.execution != fact:
                    raise ConversationOperationConflict(
                        "confirmed experiment terminal cannot change"
                    )
                return previous
            return previous.model_copy(update={"execution": fact})

        self._update_experiment(execution_scope, action_id, record)

    def record_result(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        receipt: ExperimentActionReceipt,
    ) -> None:
        def record(trace, accepted, previous):
            if receipt.operation != accepted.arguments.action.operation:
                raise ValueError("experiment receipt operation mismatch")
            if previous.receipt is not None and previous.receipt.status != "unknown":
                if previous.receipt != receipt:
                    raise ConversationOperationConflict(
                        "confirmed experiment receipt cannot change"
                    )
                return previous
            if receipt.operation != "freeze" and (
                previous.execution is None
                or previous.execution.status != receipt.status
            ):
                raise ValueError(
                    "experiment receipt does not match actual execution status"
                )
            refs = (
                *receipt.result_refs,
                *receipt.diagnostic_refs,
                *((receipt.frozen_ref,) if receipt.frozen_ref else ()),
            )
            if any(
                ref.owner != execution_scope.principal
                or ref.resource_type != "artifact"
                for ref in refs
            ):
                raise PermissionError(
                    "experiment receipt contains an unauthorized reference"
                )
            return previous.model_copy(update={"receipt": receipt})

        self._update_experiment(execution_scope, action_id, record)

    def working_plan(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> ConversationWorkingPlan | None:
        with self._lock:
            traces = tuple(self._traces.values())
        candidates = [
            trace
            for trace in traces
            if trace.conversation_id == conversation_id
            and trace.principal == principal
            and trace.working_plan is not None
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda trace: trace.working_plan.revision)
        return latest.working_plan

    def plan_result_delivered(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
        working_plan: ConversationWorkingPlan,
    ) -> bool:
        """Read the existing accepted answer; step progress is not delivery evidence."""
        with self._lock:
            return any(
                trace.conversation_id == conversation_id
                and trace.principal == principal
                and trace.working_plan is not None
                and trace.working_plan.plan_id == working_plan.plan_id
                and trace.final_message is not None
                and trace.final_message.disposition == "answer"
                for trace in self._traces.values()
            )

    def working_plan_observations(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
        working_plan: ConversationWorkingPlan,
    ) -> tuple[ActionObservation, ...]:
        """Project committed execution facts for the current foreground plan."""

        with self._lock:
            traces = tuple(self._traces.values())
        candidates = sorted(
            (
                trace
                for trace in traces
                if trace.conversation_id == conversation_id
                and trace.principal == principal
                and trace.working_plan is not None
                and trace.working_plan.plan_id == working_plan.plan_id
            ),
            key=lambda trace: (
                trace.working_plan.revision,
                trace.interaction_run_ref,
            ),
        )
        observations: list[ActionObservation] = []
        seen: set[tuple[str, str]] = set()
        for trace in candidates:
            for item in trace.inputs:
                if (
                    not isinstance(item, ActionObservation)
                    or item.status != "succeeded"
                ):
                    continue
                key = (item.capability_id, item.action_id)
                if key in seen:
                    continue
                seen.add(key)
                observations.append(item)
        return tuple(observations)

    def conversation_evidence_refs(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> tuple[str, ...]:
        """Project scoped URL evidence produced by successful execution facts."""

        with self._lock:
            traces = tuple(self._traces.values())
        refs: dict[str, str] = {}
        for trace in sorted(traces, key=lambda item: item.interaction_run_ref):
            if trace.conversation_id != conversation_id or trace.principal != principal:
                continue
            for observation in trace.inputs:
                if (
                    not isinstance(observation, ActionObservation)
                    or observation.status != "succeeded"
                ):
                    continue
                evidence_items = observation.payload.get("evidence", ())
                if not isinstance(evidence_items, list):
                    continue
                for payload in evidence_items:
                    try:
                        evidence = EvidenceItem.model_validate(payload)
                    except ValidationError:
                        continue
                    if not evidence.url or evidence.url in refs:
                        continue
                    refs[evidence.url] = json.dumps(
                        {"title": evidence.title, "url": evidence.url},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
        return tuple(refs.values())


class FileInteractionJournal(InMemoryInteractionJournal):
    """Durable append-only snapshots of committed interaction facts."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _original_directory(self, run_ref, invocation_id):
        self._validate_run_ref(run_ref)
        if not re.fullmatch(r"[0-9a-f]{32}", invocation_id):
            raise ConversationOperationConflict("模型调用原件身份不合法")
        return self._root / run_ref / "model_invocations" / invocation_id

    @staticmethod
    def _write_immutable_original(target, text):
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = text.encode("utf-8")
        if target.exists():
            if target.read_bytes() != raw:
                raise ConversationOperationConflict("模型原件已存在且内容冲突")
            return
        temporary = target.parent / f".{uuid4().hex[:12]}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _write_request_original(self, run_ref, invocation_id, text):
        self._write_immutable_original(self._original_directory(run_ref, invocation_id) / "request.json", text)

    def _read_request_original(self, run_ref, invocation_id):
        return (self._original_directory(run_ref, invocation_id) / "request.json").read_text(encoding="utf-8")

    def _write_response_original(self, run_ref, invocation_id, sequence, attempt_id, text):
        directory = self._original_directory(run_ref, invocation_id)
        existing = list(directory.glob(f"{sequence:06d}.*.response.json"))
        target = directory / f"{sequence:06d}.{attempt_id}.response.json"
        if existing and (len(existing) != 1 or existing[0] != target):
            raise ConversationOperationConflict("模型响应原件序号冲突")
        self._write_immutable_original(target, text)

    def _response_originals(self, run_ref, invocation_id):
        directory = self._original_directory(run_ref, invocation_id)
        result = []
        attempts = set()
        for index, path in enumerate(sorted(directory.glob("*.response.json"))):
            match = re.fullmatch(r"([0-9]{6})\.([0-9a-f]{32})\.response\.json", path.name)
            if match is None or int(match[1]) != index or match[2] in attempts:
                raise ConversationOperationConflict("模型响应原件序号重复或不连续")
            record = ModelResponseRecord.model_validate_json(path.read_text(encoding="utf-8"))
            if record.invocation_id != invocation_id or record.attempt_id != match[2]:
                raise ConversationOperationConflict("模型响应原件身份与文件绑定不匹配")
            attempts.add(record.attempt_id)
            result.append(record)
        return tuple(result)

    def exclusive_conversation(self, conversation_id: str, principal: AuthenticatedPrincipal):
        key = canonical_digest({"principal": principal.model_dump(mode="json"),
                                "conversation_id": conversation_id})
        root = self._root.resolve()
        return exclusive_run_lock(f"file:{os.path.normcase(str(root))}:conversation:{key}",
                                  root.parent / "conversation_locks" / f"{key}.lock")

    def conversation_traces(
        self, conversation_id: str, principal: AuthenticatedPrincipal,
    ) -> tuple[InteractionTrace, ...]:
        for run_dir in sorted(path for path in self._root.iterdir() if path.is_dir()):
            self.get(run_dir.name)
        return super().conversation_traces(conversation_id, principal)

    def exclusive_run(self, run_ref: str):
        self._validate_run_ref(run_ref)
        root = self._root.resolve()
        return exclusive_run_lock(
            f"file:{os.path.normcase(str(root))}:{run_ref}",
            root / run_ref / ".writer.lock",
        )

    def put(
        self, trace: InteractionTrace, *, expected_revision: int | None = None
    ) -> None:
        with self.exclusive_run(trace.interaction_run_ref):
            previous = self.get(trace.interaction_run_ref)
            self._check_revision(trace, previous, expected_revision)
            if previous == trace:
                return
            run_dir = self._root / trace.interaction_run_ref
            run_dir.mkdir(parents=True, exist_ok=True)
            target = run_dir / f"{trace.revision:04d}.json"
            if target.exists():
                raise ConversationOperationConflict(
                    "interaction snapshot already exists with different contents"
                )
            temporary = run_dir / f".{trace.revision:04d}.{uuid4().hex}.tmp"
            try:
                with temporary.open("xb") as stream:
                    stream.write(trace.model_dump_json(indent=2).encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            with self._lock:
                self._traces[trace.interaction_run_ref] = trace

    def get(self, interaction_run_ref: str) -> InteractionTrace | None:
        self._validate_run_ref(interaction_run_ref)
        run_dir = self._root / interaction_run_ref
        snapshots = sorted(run_dir.glob("*.json")) if run_dir.exists() else []
        if not snapshots:
            return None
        try:
            trace = InteractionTrace.model_validate_json(
                snapshots[-1].read_text(encoding="utf-8")
            )
        except ValidationError as error:
            missing_principal = any(
                tuple(item.get("loc", ())) == ("principal",)
                and item.get("type") == "missing"
                for item in error.errors()
            )
            if not missing_principal:
                raise
            logger.warning(
                "interaction.journal.unscoped | %s",
                json.dumps(
                    {"run_id": interaction_run_ref, "disposition": "quarantined"},
                    sort_keys=True,
                ),
            )
            raise ConversationOperationNotFound(
                "interaction run has no trustworthy owner scope"
            ) from error
        with self._lock:
            self._traces[interaction_run_ref] = trace
        return trace

    def working_plan(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> ConversationWorkingPlan | None:
        for run_dir in sorted(path for path in self._root.iterdir() if path.is_dir()):
            self.get(run_dir.name)
        return super().working_plan(conversation_id, principal)

    def plan_result_delivered(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
        working_plan: ConversationWorkingPlan,
    ) -> bool:
        for run_dir in sorted(path for path in self._root.iterdir() if path.is_dir()):
            self.get(run_dir.name)
        return super().plan_result_delivered(conversation_id, principal, working_plan)

    def working_plan_observations(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
        working_plan: ConversationWorkingPlan,
    ) -> tuple[ActionObservation, ...]:
        for run_dir in sorted(path for path in self._root.iterdir() if path.is_dir()):
            self.get(run_dir.name)
        return super().working_plan_observations(
            conversation_id,
            principal,
            working_plan,
        )

    def conversation_evidence_refs(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> tuple[str, ...]:
        for run_dir in sorted(path for path in self._root.iterdir() if path.is_dir()):
            self.get(run_dir.name)
        return super().conversation_evidence_refs(conversation_id, principal)


__all__ = [
    "ConversationOperationNotFound",
    "FileInteractionJournal",
    "InMemoryInteractionJournal",
]
