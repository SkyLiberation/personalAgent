"""CAS guards that create canonical runtime commit records."""

from __future__ import annotations

from personal_agent.runtime.contracts.commits import ControlCommit, TaskCompilationCommit
from personal_agent.runtime.contracts.control import ControlTurnState
from personal_agent.runtime.contracts.intake import TaskIntakeState
from personal_agent.runtime.contracts.task import TaskContract, TaskRuntimeProjection


class RuntimeCommitConflict(RuntimeError):
    pass


class TaskCompilationCommitter:
    def commit(
        self,
        intake: TaskIntakeState,
        task: TaskContract,
        runtime: TaskRuntimeProjection,
        *,
        expected_proposal_revision: int,
    ) -> tuple[TaskIntakeState, TaskCompilationCommit]:
        if intake.proposal_revision != expected_proposal_revision:
            raise RuntimeCommitConflict("task proposal revision changed")
        if intake.status not in {"analyzing", "awaiting_input"}:
            raise RuntimeCommitConflict("intake is not compilable")
        if runtime.task_id != task.task_id or runtime.task_revision != task.revision:
            raise RuntimeCommitConflict("initial runtime is not bound to compiled task revision")
        compiled = intake.model_copy(update={
            "status": "compiled",
            "compiled_task_ref": task.task_id,
            "interaction_request_ref": None,
        })
        return compiled, TaskCompilationCommit(
            intake_ref=intake.intake_id,
            expected_proposal_revision=expected_proposal_revision,
            task_ref=task.task_id,
            task_revision=task.revision,
            initial_runtime_ref=runtime.ledger_id,
            runtime_revision=runtime.revision,
            event_cursor=runtime.last_event_sequence,
        )


class ControlCommitter:
    def commit(
        self,
        control: ControlTurnState,
        runtime: TaskRuntimeProjection,
        *,
        admission_ref: str,
        admission_verdict: str,
        admission_proposal_ref: str,
        expected_task_revision: int,
        expected_event_cursor: int,
    ) -> ControlCommit:
        if runtime.task_revision != expected_task_revision:
            raise RuntimeCommitConflict("task revision changed before control commit")
        if runtime.last_event_sequence != expected_event_cursor:
            raise RuntimeCommitConflict("task event cursor changed before control commit")
        proposal = control.proposal
        command = control.accepted_command
        if proposal is None or command is None:
            raise RuntimeCommitConflict("control chain is incomplete")
        if admission_verdict != "accepted":
            raise RuntimeCommitConflict("denied proposal cannot be committed")
        if admission_proposal_ref != proposal.proposal_id:
            raise RuntimeCommitConflict("admission does not reference the proposal")
        if command.proposal_ref != proposal.proposal_id or command.admission_ref != admission_ref:
            raise RuntimeCommitConflict("control references do not form one chain")
        return ControlCommit(
            turn_ref=control.turn_id,
            proposal_ref=proposal.proposal_id,
            admission_ref=admission_ref,
            command_ref=command.command_id,
            expected_task_revision=expected_task_revision,
            expected_event_cursor=expected_event_cursor,
        )


__all__ = [
    "ControlCommitter", "RuntimeCommitConflict", "TaskCompilationCommitter",
]
