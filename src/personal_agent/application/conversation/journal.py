"""Conversation execution facts and their durable snapshot projection."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from collections.abc import Callable
from threading import RLock
from uuid import uuid4

from pydantic import ValidationError
from personal_agent.capabilities.contracts.model import (
    ModelInvocationContinuation, ModelInvocationUnavailable, ModelResponseRecord,
)

from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.evidence import EvidenceItem
from personal_agent.kernel.contracts.tool_runtime import accepted_tool_request_digest
from personal_agent.application.artifacts.models import ArtifactWriteReceipt
from personal_agent.application.retrieval_experiment.models import (
    ExperimentToolArgs,
    ExperimentRecord,
    ExperimentCommand,
    ExperimentExecutionFact,
    ExperimentActionReceipt,
    ExperimentJournalView,
)
from personal_agent.application.bash_execution.models import (
    canonical_digest,
    BashArgs,
    BashExecutionCommand,
    BashExecutionFact,
    BashExecutionReceipt,
    BashTaskWorkspaceAccess,
    BashWorkspaceFile,
    validate_workspace_path,
    BashJournalView,
)
from personal_agent.application.artifacts.models import artifact_file_path
from .artifact_sources import trace_resource_refs
from .analysis_tasks import select_goal_task
from .tool_requests import WriteArtifactArgs

from .errors import ConversationOperationNotFound, ConversationOperationConflict
from .goal_changes import GoalPatchRejected, apply_goal_patch
from .goal_maintenance import admit_goal_maintenance, current_analysis_goal
from .goal_models import (
    SUBMIT_GOAL_PATCH, AnalysisGoalRef, GoalMaintenanceInvocation, GoalPatchProposal, goal_verification_action_id,
)
from .verification_admission import observed_receipts, INTERACTION_VERIFICATION_CAPABILITY
from .journal_lock import exclusive_run_lock
from .model_history import validate_decision_extension, prior_analysis_turns, selected_analysis_turns
from .workspace_changes import validate_workspace_progress
from .models import (
    ActionGoalBinding, ActionGoalReview, ActionObservation,
    CommittedUsage,
    ConversationWorkingPlan, SessionId,
    InteractionTrace,
    AcceptedArtifactToolRequest,
    AcceptedExperimentToolRequest,
    AcceptedBashToolRequest,
    MCPWriteDispatch, RunExecutionBudget,
    ModelDecisionRecord, StoredModelRequest, ModelRequestReference, ModelResponseReference,
)


def session_lock_key(principal: AuthenticatedPrincipal, session_id: SessionId) -> str:
    return canonical_digest({"principal": principal.model_dump(mode="json"),
                             "conversation_id": session_id})


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
        with self.exclusive_run(scope.execution_id):
            return self._begin_model_invocation(scope, request)

    def _begin_model_invocation(self, scope, request):
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
        step_no = None
        if request.kind == "tool_calling":
            step_no = next((record.step_no for record in reversed(trace.model_decisions)
                            if record.step_no is not None), 0) + 1
        record = ModelDecisionRecord(invocation_id=invocation_id, operation=request.operation,
            request=reference, input_start=len(trace.inputs), step_no=step_no)
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
            self._write_response_original(scope.execution_id, response.invocation_id, sequence, text)
            reference = ModelResponseReference(invocation_id=response.invocation_id, attempt_id=response.attempt_id,
                sequence=sequence, content_digest=sha256(text.encode("utf-8")).hexdigest())
            records[index] = invocation.model_copy(update={"response_refs": (*invocation.response_refs, reference)})
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
            recoverable_transport = (previous.step_no is not None
                and isinstance(failure, ModelInvocationUnavailable) and failure.retryable)
            records[index] = previous.model_copy(update={
                "assistant": response.assistant_message if response is not None else previous.assistant,
                "protocol_exchanges": response.protocol_exchanges if response is not None else previous.protocol_exchanges,
                "status": "decoded" if failure is None else "invalid" if previous.response_refs else "failed",
                "diagnostics": str(failure)[:2000] if failure is not None else None,
                "consumed": failure is not None and not previous.response_refs and not recoverable_transport})
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

    def _write_response_original(self, run_ref: str, invocation_id: str, sequence: int, text: str) -> None:
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

    def exclusive_session(self, *, principal: AuthenticatedPrincipal, session_id: SessionId):
        key = session_lock_key(principal, session_id)
        return exclusive_run_lock(f"memory:{id(self)}:conversation:{key}", None)

    @staticmethod
    def _validate_run_ref(run_ref: str) -> None:
        if not re.fullmatch(r"(?:turn|irun)_[A-Za-z0-9_-]+", run_ref):
            raise ValueError("invalid conversation turn reference")

    def put(
        self, trace: InteractionTrace, *, expected_revision: int | None = None
    ) -> None:
        with self.exclusive_run(trace.interaction_run_ref):
            previous = self.get(trace.interaction_run_ref)
            self._check_revision(trace, previous, expected_revision)
            with self._lock:
                self._traces[trace.interaction_run_ref] = trace

    def _check_revision(self, trace, previous, expected_revision):
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
            or previous.bash_authorization_digest != trace.bash_authorization_digest
            or previous.answer_protocol_version != trace.answer_protocol_version
            or previous.answer_result_binding != trace.answer_result_binding
            or previous.feature_flags_binding != trace.feature_flags_binding
            or previous.run_deadline_at != trace.run_deadline_at
            or previous.max_execution_seconds != trace.max_execution_seconds
        ):
            raise ConversationOperationConflict(
                "interaction journal input binding changed"
            )
        if previous is not None:
            validate_decision_extension(previous, trace)
            validate_workspace_progress(previous.workspace_changes, trace.workspace_changes)
            if trace.action_goal_reviews[:len(previous.action_goal_reviews)] != previous.action_goal_reviews:
                raise ConversationOperationConflict("action goal reviews are immutable")
            if trace.goal_operations[:len(previous.goal_operations)] != previous.goal_operations:
                raise ConversationOperationConflict("accepted goal operations are immutable")
            new_operations = trace.goal_operations[len(previous.goal_operations):]
            if len(new_operations) > 1:
                raise ConversationOperationConflict("one goal operation may be committed per decision")
            for operation in new_operations:
                caller = next((item for item in trace.model_decisions
                               if item.step_no == operation.decision_turn), None)
                if (operation.run_ref != trace.interaction_run_ref or caller is None or caller.assistant is None
                        or operation.call_id not in caller.assistant.call_ids
                        or not any(item.call_id == operation.call_id
                                   and item.operation == ("read_current_goal" if operation.operation == "read" else "maintain_goal")
                                   and item.status == "accepted" for item in caller.dispositions)):
                    raise ConversationOperationConflict("goal operation is not bound to an accepted native call")
                if operation.operation != "read":
                    self._check_goal_commit(previous, operation, caller)
                    reference = operation.verification_ref
                    if not trace.feature_flags_binding.goal_verification:
                        if reference is not None:
                            raise ConversationOperationConflict("未启用目标核验的操作不能绑定通过回执")
                        continue
                    expected = goal_verification_action_id(operation.run_ref, operation.decision_turn, operation.call_id)
                    observation = next((item for item in trace.inputs
                        if isinstance(item, ActionObservation) and item.action_id == expected), None)
                    receipts = observed_receipts((observation,) if observation is not None else (),
                        capability_names=frozenset({INTERACTION_VERIFICATION_CAPABILITY}))
                    if (reference is None or reference.kind != "tool_result" or reference.action_id != expected
                            or len(receipts) != 1 or receipts[0].checked_kind != "goal"
                            or receipts[0].verdict != "passed"
                            or receipts[0].verified_draft != operation.verification_text()):
                        raise ConversationOperationConflict("goal operation lacks its exact passed verification")
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
                    or current.goal_ref != accepted.goal_ref
                ):
                    raise ConversationOperationConflict(
                        "accepted tool request is immutable"
                    )

    def _check_goal_commit(self, previous, operation, caller):
        call = next((call for call in caller.assistant.payload.get("tool_calls", ())
                     if call.get("id") == operation.call_id), None)
        function = call.get("function", {}) if call else {}
        if operation.patch is None or function.get("name") != SUBMIT_GOAL_PATCH:
            raise ConversationOperationConflict("goal update must carry its original patch")
        try:
            original = GoalPatchProposal.model_validate_json(function["arguments"]).to_patch()
        except (KeyError, ValidationError) as error:
            raise ConversationOperationConflict("original goal patch is invalid") from error
        if original != operation.patch:
            raise ConversationOperationConflict("goal operation differs from the submitted patch")
        branch = prior_analysis_turns(previous, self.task_traces(previous))
        try:
            task = select_goal_task(operation.patch, previous, branch)
            candidate = apply_goal_patch(operation.patch, previous, task.current, previous=task.previous)
        except GoalPatchRejected as error:
            raise ConversationOperationConflict(f"goal patch commit rejected: {error.reason}") from error
        expected = admit_goal_maintenance(
            GoalMaintenanceInvocation(call_id=operation.call_id, arguments=operation.patch),
            trace=previous, current=task.current, candidate=candidate, verification_ref=operation.verification_ref,
        )
        if operation != expected:
            raise ConversationOperationConflict("goal snapshot differs from its version-bound patch")

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

    def record_action_goal_reviews(self, scope: ExecutionScope, reviews: tuple[ActionGoalReview, ...]) -> None:
        def record(latest):
            known = {item.binding.action_id for item in latest.action_goal_reviews}
            if known.intersection(item.binding.action_id for item in reviews):
                raise ConversationOperationConflict("action goal review already exists")
            return latest.model_copy(update={
                "revision": latest.revision + 1,
                "action_goal_reviews": (*latest.action_goal_reviews, *reviews),
            })
        self.update(scope, record)

    def begin_mcp_write_dispatch(
        self, scope: ExecutionScope, dispatch: MCPWriteDispatch, *, replaying_model_response: bool,
    ) -> bool:
        if scope.task_id != dispatch.action_id:
            raise ConversationOperationConflict("MCP write dispatch is bound to another action")
        registered = False

        def record(latest: InteractionTrace) -> InteractionTrace:
            nonlocal registered
            previous = latest.mcp_write_dispatches
            existing = next((item for item in previous or () if item.action_id == dispatch.action_id), None)
            if existing is not None:
                if existing != dispatch:
                    raise ConversationOperationConflict("MCP write dispatch already has a different binding")
                return latest
            if previous is None and replaying_model_response:
                return latest
            registered = True
            return latest.model_copy(update={
                "revision": latest.revision + 1,
                "mcp_write_dispatches": (*(previous or ()), dispatch),
            })

        self.update(scope, record)
        return registered

    def accept_tool_request(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        arguments: WriteArtifactArgs | ExperimentToolArgs | BashArgs,
        plan_step_id: str | None,
        action_goal_binding: ActionGoalBinding | None = None,
        goal_ref: AnalysisGoalRef | None = None,
    ):
        if isinstance(arguments, WriteArtifactArgs):
            tool_name, request_type = "write_artifact", AcceptedArtifactToolRequest
        elif isinstance(arguments, ExperimentToolArgs):
            tool_name, request_type = "retrieval_experiment", AcceptedExperimentToolRequest
        elif isinstance(arguments, BashArgs):
            tool_name, request_type = "bash", AcceptedBashToolRequest
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
            goal_ref=goal_ref,
        )
        if execution_scope.task_id != action_id:
            raise PermissionError("accepted action identity does not match its scope")

        def accept(latest):
            self.check_tool_goal(latest, request)
            review = next((item for item in latest.action_goal_reviews if item.binding.action_id == action_id), None)
            if review is not None or action_goal_binding is not None:
                if (review is None or review.binding != action_goal_binding
                        or review.binding.request_digest != request.request_digest
                        or review.judgment.verdict == "conflict"):
                    raise ConversationOperationConflict("tool acceptance differs from its action goal review")
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
                        or previous.goal_ref != request.goal_ref
                ):
                    raise ConversationOperationConflict(
                        "action_id is already bound to a different accepted request"
                    )
                return latest
            if tool_name in {"retrieval_experiment", "bash"} and (
                (latest.deployment_digest if tool_name == "retrieval_experiment"
                 else latest.bash_profile_digest) is None
                or latest.run_deadline_at is None
                or latest.max_execution_seconds is None
            ):
                raise PermissionError(
                    "当前运行没有绑定获准的执行配置、截止和额度"
                )
            accepted = request
            if isinstance(request, AcceptedBashToolRequest):
                workspace_files = self.bash_workspace_files(latest)
                if review is not None and tuple(file.resource_ref for file in workspace_files) != review.binding.input_refs:
                    raise ConversationOperationConflict("Bash workspace changed after action goal review")
                accepted = request.model_copy(update={"workspace_files": workspace_files})
            return latest.model_copy(
                update={
                    "revision": latest.revision + 1,
                    "accepted_tool_requests": (*latest.accepted_tool_requests, accepted),
                }
            )

        updated = self.update(execution_scope, accept)
        return next(
            item
            for item in updated.accepted_tool_requests
            if item.action_id == action_id
        )

    def check_tool_goal(self, trace, request) -> None:
        if request.goal_ref is None:
            return
        history = selected_analysis_turns(trace, self.task_traces(trace))
        current = current_analysis_goal(trace, history)
        if current is None or current.reference != request.goal_ref:
            raise ConversationOperationConflict("tool request is bound to an obsolete goal")
        if current.execution_control is not None and current.execution_control.mode != "running":
            raise ConversationOperationConflict("current execution control disallows tool writes")
        if request.plan_step_id is not None and not any(
            step.step_id == request.plan_step_id and step.status == "in_progress"
            for step in (trace.working_plan.steps if trace.working_plan is not None else ())
        ):
            raise ConversationOperationConflict("tool request is bound to an inactive plan step")

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

    def session_runs(self, *, principal: AuthenticatedPrincipal, session_id: SessionId) -> tuple[InteractionTrace, ...]:
        with self._lock:
            candidates = tuple(self._traces.values())
        return tuple(sorted((trace for trace in candidates
                             if trace.principal == principal and trace.conversation_id == session_id),
                            key=lambda trace: (len(trace.messages), trace.interaction_run_ref)))

    def last_turn(self, *, principal: AuthenticatedPrincipal, session_id: SessionId) -> InteractionTrace | None:
        turns = self.session_runs(principal=principal, session_id=session_id)
        return turns[-1] if turns else None

    def analysis_traces(self, trace: InteractionTrace) -> tuple[InteractionTrace, ...]:
        if trace.bash_authorization_digest is None:
            return (trace,)
        candidates = tuple(item for item in self.session_runs(principal=trace.principal, session_id=trace.conversation_id)
                           if item.bash_authorization_digest is not None)
        if any(item.bash_authorization_digest != trace.bash_authorization_digest for item in candidates):
            raise PermissionError("同一分析对话不能更换授权身份并重置额度")
        if not any(item.interaction_run_ref == trace.interaction_run_ref for item in candidates):
            raise ConversationOperationNotFound("分析运行尚未提交至Journal")
        return candidates

    def _history_candidates(self, trace: InteractionTrace) -> tuple[InteractionTrace, ...]:
        return tuple(item for item in self.session_runs(principal=trace.principal, session_id=trace.conversation_id)
                     if len(item.messages) <= len(trace.messages))

    def task_traces(self, trace: InteractionTrace) -> tuple[InteractionTrace, ...]:
        """Ordered predecessors and the current turn within the original execution binding."""
        if trace.bash_authorization_digest is not None:
            self.analysis_traces(trace)
        candidates = self._history_candidates(trace)
        return tuple(item for item in candidates if (
            item.bash_authorization_digest == trace.bash_authorization_digest
            and item.deployment_digest == trace.deployment_digest
            and item.answer_protocol_version == trace.answer_protocol_version
            and item.answer_result_binding == trace.answer_result_binding
            and item.feature_flags_binding == trace.feature_flags_binding
        ))

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
        sources = (*selected_analysis_turns(trace, self.task_traces(trace)), trace)
        return tuple(dict.fromkeys(ref for item in sources
                                   for ref in trace_resource_refs(
                                       item, include_goal_drafts=item.interaction_run_ref == trace.interaction_run_ref)))

    def bash_workspace_files(self, trace: InteractionTrace) -> tuple[BashWorkspaceFile, ...]:
        sources = (*selected_analysis_turns(trace, self.task_traces(trace)), trace)
        attachment_refs = {ref for source in sources for ref in source.input_artifact_refs}
        names = {item.resource.resource_ref: item.resource.filename for source in sources
                 for item in source.inputs if item.kind == "artifact_source"
                 and item.resource.resource_ref in attachment_refs}
        paths = {}
        counts = {}
        for ref in self.readable_resource_refs(trace):
            path = artifact_file_path(ref)
            if ref in names:
                try:
                    path = validate_workspace_path(f"attachments/{names[ref]}")
                except ValueError:
                    pass
            paths[ref] = path
            key = path.casefold()
            counts[key] = counts.get(key, 0) + 1
        return tuple(BashWorkspaceFile(
            name=path if counts[path.casefold()] == 1 else f"versions/{ref.resource_id}/{ref.revision}/{path.rsplit('/', 1)[-1]}",
            resource_ref=ref,
        ) for ref, path in paths.items())

    def task_observations(self, previous: tuple[InteractionTrace, ...]) -> tuple[ActionObservation, ...]:
        """Recover owned tool observations for the selected task."""
        observations: list[ActionObservation] = []
        for source in previous:
            owned = {item.action_id for item in source.accepted_tool_requests}
            owned.update(call_id for decision in source.model_decisions
                         if decision.assistant is not None
                         for call_id in decision.assistant.call_ids)
            observations.extend(item for item in source.inputs if isinstance(item, ActionObservation)
                                and item.action_id in owned)
        return tuple(observations)

    def execution_budget(self, trace: InteractionTrace) -> RunExecutionBudget:
        """Both execution consumers derive allowance from the same committed facts."""
        consumed = 0.0
        unsettled: list[str] = []
        records = ((source, record) for source in self.analysis_traces(trace)
                   for record in (*source.experiment_records, *(item for item in source.accepted_tool_requests
                                   if isinstance(item, AcceptedBashToolRequest))))
        for source, record in records:
            if record.command is None:
                continue
            fact = record.execution
            if fact is None or fact.status in {"dispatching", "unknown"}:
                consumed += record.command.reserved_seconds
                unsettled.append(f"{source.interaction_run_ref}:{record.action_id}"
                                 if trace.bash_authorization_digest is not None else record.action_id)
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

    def load_bash_execution(
        self, *, execution_scope: ExecutionScope, action_id: str, request_digest: str,
        retain_task_workspace: bool = False,
    ) -> BashJournalView:
        trace = self.get(execution_scope.execution_id)
        if (trace is None or trace.principal != execution_scope.principal
                or trace.conversation_id != execution_scope.thread_id):
            raise PermissionError("Bash journal scope mismatch")
        accepted = self._accepted(trace, execution_scope, action_id, request_digest)
        if (not isinstance(accepted, AcceptedBashToolRequest)
                or trace.bash_profile_digest is None or trace.run_deadline_at is None
                or trace.max_execution_seconds is None):
            raise PermissionError("Bash execution is not authorized for this run")
        if accepted.execution is None:
            self.check_tool_goal(trace, accepted)
        workspace = accepted.command.task_workspace if accepted.command is not None else (
            self._bash_task_workspace(trace) if retain_task_workspace else None
        )
        return BashJournalView(
            execution_scope=execution_scope, action_id=action_id,
            arguments=accepted.arguments, request_digest=request_digest,
            deployment_digest=trace.bash_profile_digest, workspace_files=accepted.workspace_files,
            run_deadline_at=trace.run_deadline_at,
            remaining_execution_seconds=self.execution_budget(trace).remaining_seconds,
            command=accepted.command, execution=accepted.execution, receipt=accepted.receipt,
            task_workspace=workspace,
        )

    def _bash_task_workspace(self, trace: InteractionTrace) -> BashTaskWorkspaceAccess:
        candidates = self.task_traces(trace)
        selected = selected_analysis_turns(trace, candidates)
        goal = current_analysis_goal(trace, selected)
        first = trace.first_goal_operation
        selection = first.patch.task if first is not None and first.patch is not None else None
        if (goal is None or goal.goal.goal_id is None
                or (selection is not None and selection.action == "side_question")):
            raise PermissionError("Bash task workspace requires an accepted analysis task")
        return BashTaskWorkspaceAccess(
            task_id=goal.goal.goal_id,
            predecessor_turn_ids=tuple(
                item.interaction_run_ref for item in prior_analysis_turns(trace, candidates)
            ),
        )

    def _update_bash(self, scope: ExecutionScope, action_id: str, change) -> None:
        def update(trace):
            accepted = self._accepted(trace, scope, action_id)
            if not isinstance(accepted, AcceptedBashToolRequest):
                raise PermissionError("accepted request is not Bash execution")
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

    def bind_bash_command(
        self, *, execution_scope: ExecutionScope, action_id: str,
        command: BashExecutionCommand,
    ) -> None:
        def bind(trace, accepted):
            if accepted.command is not None:
                if accepted.command != command:
                    raise ConversationOperationConflict("Bash command already differs")
                return accepted
            self.check_tool_goal(trace, accepted)
            if (command.execution_scope != execution_scope or command.action_id != action_id
                    or command.request_digest != accepted.request_digest
                    or command.deployment_digest != trace.bash_profile_digest
                    or trace.run_deadline_at is None or command.deadline_at > trace.run_deadline_at):
                raise PermissionError("Bash command binding mismatch")
            workspace_files = tuple(BashWorkspaceFile(name=item.name, resource_ref=item.resource_ref) for item in command.inputs)
            if (workspace_files != accepted.workspace_files or command.workdir != accepted.arguments.workdir
                    or command.workspace_file != accepted.arguments.workspace_file):
                raise PermissionError("Bash command changed the authorized workspace")
            if command.task_workspace is not None and command.task_workspace != self._bash_task_workspace(trace):
                raise PermissionError("Bash task workspace binding changed")
            code = accepted.arguments.command.encode("utf-8")
            if (command.program.content_digest != sha256(code).hexdigest()
                    or command.program.size_bytes != len(code)):
                raise PermissionError("Bash command changed accepted program")
            budget = self.execution_budget(trace)
            if any(item != action_id for item in budget.unsettled_action_ids):
                raise PermissionError("reconcile the pending execution before starting another")
            if command.reserved_seconds > budget.remaining_seconds:
                raise PermissionError("shared execution allowance exhausted")
            return accepted.model_copy(update={"command": command, "workspace_files": ()})
        self._update_bash(execution_scope, action_id, bind)

    def record_bash_execution(
        self, *, execution_scope: ExecutionScope, action_id: str,
        fact: BashExecutionFact,
    ) -> None:
        def record(trace, accepted):
            if accepted.command is None:
                raise PermissionError("Bash execution requires its frozen command")
            if (accepted.execution is not None
                    and accepted.execution.status not in {"dispatching", "unknown"}):
                if accepted.execution != fact:
                    raise ConversationOperationConflict("Bash terminal cannot change")
                return accepted
            return accepted.model_copy(update={"execution": fact})
        self._update_bash(execution_scope, action_id, record)

    def record_bash_result(
        self, *, execution_scope: ExecutionScope, action_id: str,
        receipt: BashExecutionReceipt,
    ) -> None:
        def record(trace, accepted):
            command, fact = accepted.command, accepted.execution
            if (command is None or fact is None or receipt.action_id != action_id
                    or receipt.command_digest != command.command_digest
                    or receipt.program_ref != command.program.resource_ref
                    or receipt.process_exit_code != fact.process_exit_code
                    or receipt.elapsed_seconds != fact.elapsed_seconds
                    or receipt.limits != command.limits):
                raise PermissionError("Bash receipt is not bound to actual execution")
            protocol_failure = fact.status == "succeeded" and (
                receipt.status == "invalid_output" or (
                    receipt.status == "failed" and receipt.error_code == "output_unavailable"
                    and receipt.stdout_ref is None and receipt.stderr_ref is None
                )
            )
            if receipt.status != fact.status and not protocol_failure:
                raise ValueError("Bash receipt contradicts process status")
            refs = (receipt.program_ref, receipt.input_manifest_ref,
                    *((receipt.stdout_ref,) if receipt.stdout_ref else ()),
                    *((receipt.stderr_ref,) if receipt.stderr_ref else ()))
            if any(ref.owner != execution_scope.principal or ref.resource_type != "artifact"
                   for ref in refs):
                raise PermissionError("Bash output reference scope mismatch")
            if accepted.receipt is not None and accepted.receipt.status != "unknown":
                if accepted.receipt != receipt:
                    raise ConversationOperationConflict("Bash receipt already differs")
                return accepted
            return accepted.model_copy(update={"receipt": receipt})
        self._update_bash(execution_scope, action_id, record)

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
        traces = self.session_runs(principal=principal, session_id=conversation_id)
        candidates = [trace for trace in traces if trace.working_plan is not None]
        if not candidates:
            return None
        latest = max(candidates, key=lambda trace: trace.working_plan.revision)
        return latest.working_plan

    def plan_result_delivered(
        self,
        working_plan: ConversationWorkingPlan,
        *,
        principal: AuthenticatedPrincipal,
        session_id: SessionId,
    ) -> bool:
        """Read the existing accepted answer; step progress is not delivery evidence."""
        return any(
            trace.working_plan is not None
            and trace.working_plan.plan_id == working_plan.plan_id
            and trace.final_message is not None
            and trace.final_message.disposition == "answer"
            for trace in self.session_runs(principal=principal, session_id=session_id)
        )

    def conversation_evidence_refs(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> tuple[str, ...]:
        """Project scoped URL evidence produced by successful execution facts."""

        traces = self.session_runs(principal=principal, session_id=conversation_id)
        refs: dict[str, str] = {}
        for trace in sorted(traces, key=lambda item: item.interaction_run_ref):
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

__all__ = [
    "ConversationOperationNotFound",
    "InMemoryInteractionJournal",
]
