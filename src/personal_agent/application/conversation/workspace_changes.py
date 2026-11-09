"""Conversation-owned commands for changes to one explicitly bound workspace."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_agent.kernel.contracts.derivation import canonical_digest
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope

from .errors import ConversationOperationConflict, ConversationOperationNotFound

if TYPE_CHECKING:
    from .journal import InMemoryInteractionJournal
    from .models import InteractionTrace

WORKSPACE_CHANGES = "prepare_workspace_changes"
Decision = Literal["approve", "reject"]
Outcome = Literal["applied", "blocked", "unknown"]
ReceiptStatus = Literal["applied", "blocked", "unknown", "rejected"]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
PathArgument = Annotated[str, Field(min_length=1, max_length=1024)]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateDirectory(_Record):
    kind: Literal["create_directory"]
    path: PathArgument


class MoveFile(_Record):
    kind: Literal["move_file"]
    source: PathArgument
    destination: PathArgument


WorkspaceChange = Annotated[CreateDirectory | MoveFile, Field(discriminator="kind")]


class WorkspaceChangeArguments(_Record):
    changes: tuple[WorkspaceChange, ...] = Field(min_length=1, max_length=64)


class WorkspaceChangeCommand(_Record):
    scope: ExecutionScope
    binding_digest: Digest
    arguments: WorkspaceChangeArguments
    decision_turn: int = Field(ge=1)
    plan_step_id: str | None = None

    @model_validator(mode="after")
    def require_call_scope(self):
        if self.scope.thread_id is None or self.scope.task_id is None:
            raise ValueError("工作区命令必须绑定原会话和动作")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self)


class WorkspaceChangeReceipt(_Record):
    command_digest: Digest
    status: ReceiptStatus
    outcomes: tuple[Outcome, ...]


class WorkspaceChangeOperation(_Record):
    command: WorkspaceChangeCommand
    outcomes: tuple[Outcome, ...] = ()
    dispatching: bool = False
    receipt: WorkspaceChangeReceipt | None = None

    @model_validator(mode="after")
    def require_consistent_progress(self):
        count = len(self.command.arguments.changes)
        if len(self.outcomes) > count or (self.dispatching and len(self.outcomes) >= count):
            raise ValueError("工作区执行进度超出批准清单")
        if self.receipt is not None and (
            self.dispatching or self.receipt.outcomes != self.outcomes
            or self.receipt.command_digest != self.command.digest
        ):
            raise ValueError("工作区回执与命令或进度不一致")
        return self


class WorkspaceChangeConfirmation(_Record):
    kind: Literal["workspace_changes"] = "workspace_changes"
    command_digest: Digest
    changes: tuple[WorkspaceChange, ...]


class WorkspaceChangeBinding(_Record):
    principal: AuthenticatedPrincipal
    conversation_id: str
    root: PathArgument
    digest: Digest

    @field_validator("root")
    @classmethod
    def valid_root(cls, value: str) -> str:
        return _canonical_path(value)


class WorkspaceChangePort(Protocol):
    def permitted(self, kind: Literal["create_directory", "move_file"], scope: ExecutionScope) -> bool: ...

    def dispatch(self, change: WorkspaceChange, scope: ExecutionScope) -> Outcome: ...


def _canonical_path(value: str) -> str:
    path = PurePosixPath(value)
    if (path.anchor != "/" or len(path.parts) < 2 or path.as_posix() != value
            or ".." in path.parts or "\\" in value or any(ord(c) < 32 for c in value)):
        raise ValueError("工作区路径必须是规范的 POSIX 绝对路径")
    return value


def _receipt_evidence(command: WorkspaceChangeCommand, receipt: WorkspaceChangeReceipt) -> list[str]:
    labels = {"applied": "执行成功", "blocked": "策略阻止", "unknown": "结果未知"}
    evidence = []
    for change, outcome in zip(command.arguments.changes, receipt.outcomes):
        action = (f"建目录 {change.path}" if isinstance(change, CreateDirectory)
                  else f"移动 {change.source} → {change.destination}")
        evidence.append(f"{labels[outcome]} · {action}")
    return evidence


def validate_workspace_progress(
    previous: tuple[WorkspaceChangeOperation, ...], current: tuple[WorkspaceChangeOperation, ...],
) -> None:
    if len(current) < len(previous):
        raise ConversationOperationConflict("工作区确认记录不可删除")
    for old, new in zip(previous, current):
        if (new.command != old.command or new.outcomes[:len(old.outcomes)] != old.outcomes
                or (old.receipt is not None and old != new)):
            raise ConversationOperationConflict("工作区命令、既有执行进度和终态不可改写")


class WorkspaceChangeService:
    def __init__(
        self, binding: WorkspaceChangeBinding, port: WorkspaceChangePort,
        journal: InMemoryInteractionJournal,
    ) -> None:
        self.binding = binding
        self._port = port
        self._journal = journal

    def visible(self, trace: InteractionTrace, source_platform: str) -> bool:
        if (source_platform != "web" or trace.principal != self.binding.principal
                or trace.conversation_id != self.binding.conversation_id):
            return False
        scope = ExecutionScope(principal=trace.principal, execution_id=trace.interaction_run_ref,
                               thread_id=trace.conversation_id)
        return all(self._port.permitted(kind, scope) for kind in ("create_directory", "move_file"))

    def prepare(
        self, trace: InteractionTrace, *, source_platform: str, action_id: str,
        arguments: WorkspaceChangeArguments, plan_step_id: str | None,
    ) -> WorkspaceChangeOperation:
        if not self.visible(trace, source_platform):
            raise PermissionError("此会话没有工作区变更权限")
        root = PurePosixPath(self.binding.root)
        changed: set[WorkspaceChange] = set()
        for change in arguments.changes:
            paths = (change.path,) if isinstance(change, CreateDirectory) else (change.source, change.destination)
            for path in paths:
                value = PurePosixPath(_canonical_path(path))
                if value == root or not value.is_relative_to(root):
                    raise ValueError("变更路径必须位于授权工作区内")
            if len(paths) != len(set(paths)) or change in changed:
                raise ValueError("工作区清单含重复操作或相同源目标")
            changed.add(change)
        traces = self._journal.conversation_traces(trace.conversation_id, trace.principal)
        for previous in traces:
            for operation in previous.workspace_changes:
                if operation.command.binding_digest != self.binding.digest:
                    continue
                if operation.receipt is None or operation.receipt.status == "unknown":
                    raise ConversationOperationConflict("已有未完成或结果未知的工作区变更")
                if (previous.interaction_run_ref == trace.interaction_run_ref
                        and operation.command.arguments == arguments):
                    raise ConversationOperationConflict("相同工作区清单已有决定与回执")
        command = WorkspaceChangeCommand(
            scope=ExecutionScope(principal=trace.principal, execution_id=trace.interaction_run_ref,
                                 thread_id=trace.conversation_id, task_id=action_id),
            binding_digest=self.binding.digest,
            arguments=arguments,
            decision_turn=trace.usage.model_turns,
            plan_step_id=plan_step_id,
        )
        return WorkspaceChangeOperation(command=command)

    def store(self, operation: WorkspaceChangeOperation) -> None:
        self._journal.update(operation.command.scope, lambda trace: trace.model_copy(update={
            "revision": trace.revision + 1,
            "workspace_changes": (*trace.workspace_changes, operation),
            "usage": trace.usage.model_copy(update={"tool_calls": trace.usage.tool_calls + 1}),
        }))

    def decide(
        self, trace: InteractionTrace, *, digest: str, decision: Decision,
    ) -> WorkspaceChangeReceipt:
        operation = next((item for item in trace.workspace_changes if item.command.digest == digest), None)
        if operation is None:
            raise ConversationOperationNotFound("工作区命令不存在")
        if operation.receipt is not None:
            if (decision == "reject") != (operation.receipt.status == "rejected"):
                raise ConversationOperationConflict("工作区命令已有不同的决定")
            return operation.receipt
        if decision == "reject":
            if operation.dispatching or operation.outcomes:
                raise ConversationOperationConflict("工作区命令已经开始执行")
            return self._finish(operation, "rejected", ())
        if operation.dispatching:
            return self._finish(operation, "unknown", (*operation.outcomes, "unknown"))
        if operation.command.binding_digest != self.binding.digest:
            raise ConversationOperationConflict("工作区部署已变化")
        changes = operation.command.arguments.changes
        start = len(operation.outcomes)
        for index in range(start, len(changes)):
            change = changes[index]
            scope = operation.command.scope.model_copy(update={"task_id": f"{operation.command.scope.task_id}:{index}"})
            if not self._port.permitted(change.kind, scope):
                return self._finish(operation, "blocked", (*operation.outcomes, "blocked"))
            operation = operation.model_copy(update={"dispatching": True})
            self._persist(operation)
            outcome = self._port.dispatch(change, scope)
            operation = operation.model_copy(update={
                "dispatching": False, "outcomes": (*operation.outcomes, outcome),
            })
            if outcome != "applied" or index + 1 == len(changes):
                return self._finish(operation, outcome, operation.outcomes)
            self._persist(operation)
        raise AssertionError("approved workspace changes must be nonempty")

    def _finish(
        self, operation: WorkspaceChangeOperation, status: ReceiptStatus, outcomes: tuple[Outcome, ...],
    ) -> WorkspaceChangeReceipt:
        receipt = WorkspaceChangeReceipt(command_digest=operation.command.digest, status=status, outcomes=outcomes)
        self._persist(operation.model_copy(update={
            "outcomes": outcomes, "dispatching": False, "receipt": receipt,
        }))
        return receipt

    def _persist(self, operation: WorkspaceChangeOperation) -> None:
        from .models import ActionObservation

        command = operation.command
        def update(trace):
            updates = {
                "revision": trace.revision + 1,
                "workspace_changes": tuple(
                    operation if item.command == command else item for item in trace.workspace_changes
                ),
            }
            receipt = operation.receipt
            if receipt is not None:
                updates.update(
                    inputs=(*trace.inputs, ActionObservation(
                        kind="tool_result", action_id=command.scope.task_id, capability_id=WORKSPACE_CHANGES,
                        status="succeeded" if receipt.status == "applied" else "failed",
                        plan_step_id=command.plan_step_id, execution_request_digest=command.digest,
                        payload={"receipt": receipt.model_dump(mode="json"),
                                 "execution_facts": _receipt_evidence(command, receipt)},
                    )),
                    execution_order=(*trace.execution_order, command.scope.task_id),
                    model_decisions=tuple(
                        record.model_copy(update={"consumed": True}) if record.turn_index == command.decision_turn
                        else record for record in trace.model_decisions
                    ),
                )
            return trace.model_copy(update=updates)
        self._journal.update(command.scope, update)
