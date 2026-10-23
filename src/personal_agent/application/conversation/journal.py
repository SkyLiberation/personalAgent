"""Conversation execution facts and their durable snapshot projection."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import ValidationError

from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope
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
from personal_agent.application.python_execution.models import (
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
from .models import (
    ActionObservation,
    ConversationWorkingPlan,
    InteractionTrace,
    AcceptedArtifactToolRequest,
    AcceptedExperimentToolRequest,
    AcceptedPythonToolRequest,
    RunExecutionBudget,
)


logger = logging.getLogger(__name__)


class InMemoryInteractionJournal:
    """Append-only execution facts used to rebuild transient interaction context."""

    def __init__(self) -> None:
        self._traces: dict[str, InteractionTrace] = {}
        self._lock = RLock()

    def exclusive_run(self, run_ref: str):
        self._validate_run_ref(run_ref)
        return exclusive_run_lock(f"memory:{id(self)}:{run_ref}", None)

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
            or previous.run_deadline_at != trace.run_deadline_at
            or previous.max_execution_seconds != trace.max_execution_seconds
        ):
            raise ConversationOperationConflict(
                "interaction journal input binding changed"
            )
        if previous is not None:
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
                latest.deployment_digest is None
                or latest.run_deadline_at is None
                or latest.max_execution_seconds is None
            ):
                raise PermissionError(
                    "this interaction has no authorized experiment deployment"
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

    @staticmethod
    def execution_budget(trace: InteractionTrace) -> RunExecutionBudget:
        """Both execution consumers derive allowance from the same committed facts."""
        consumed = 0.0
        unsettled: list[str] = []
        records = (*trace.experiment_records, *(
            item for item in trace.accepted_tool_requests
            if isinstance(item, AcceptedPythonToolRequest)
        ))
        for record in records:
            if record.command is None:
                continue
            fact = record.execution
            if fact is None or fact.status in {"dispatching", "unknown"}:
                consumed += record.command.reserved_seconds
                unsettled.append(record.action_id)
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
                or trace.deployment_digest is None or trace.run_deadline_at is None
                or trace.max_execution_seconds is None):
            raise PermissionError("Python execution is not authorized for this run")
        return PythonJournalView(
            execution_scope=execution_scope, action_id=action_id,
            arguments=accepted.arguments, request_digest=request_digest,
            deployment_digest=trace.deployment_digest, allowed_refs=trace_resource_refs(trace),
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
                    or command.deployment_digest != trace.deployment_digest
                    or trace.run_deadline_at is None or command.deadline_at > trace.run_deadline_at):
                raise PermissionError("Python command binding mismatch")
            if tuple((item.name, item.resource_ref) for item in command.inputs) != tuple(
                    (item.name, item.resource_ref) for item in accepted.arguments.input_files):
                raise PermissionError("Python command changed accepted input bindings")
            if (accepted.arguments.program_ref is not None
                    and command.program.resource_ref != accepted.arguments.program_ref):
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
