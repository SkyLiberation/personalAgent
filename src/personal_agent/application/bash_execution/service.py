"""Freeze model-selected bytes, dispatch once, and publish actual process output."""

from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.contracts.tool_runtime import accepted_tool_request_digest
from .models import (
    INPUT_MAX_BYTES,
    PROGRAM_MAX_BYTES,
    STDERR_PREVIEW_CHARS,
    STDOUT_PREVIEW_CHARS,
    BashArgs,
    BashBackendOutcome,
    BashExecutionCommand,
    BashExecutionFact,
    BashExecutionProfile,
    BashExecutionReceipt,
    BashInputContent,
    BashInputIdentity,
    BashInputManifest,
    BashJournalView,
    BashToolResult,
)
from .ports import BashArtifactPort, BashExecutionPort, BashJournalPort


class BashExecutionService:
    def __init__(
        self,
        *,
        artifacts: BashArtifactPort,
        journal: BashJournalPort,
        execution: BashExecutionPort,
        profile: BashExecutionProfile,
        prompts: PromptCatalog = DEFAULT_PROMPTS,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._prompts = prompts
        self.artifacts = artifacts
        self.journal = journal
        self.execution = execution
        self.profile = profile
        self.clock = clock

    def execute(
        self,
        arguments: BashArgs,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        request_digest: str,
    ) -> BashToolResult:
        if execution_scope.principal != self.profile.authorized_principal:
            raise PermissionError(self._prompts.render('bash_execution.authorization'))
        expected = accepted_tool_request_digest(
            execution_scope=execution_scope,
            action_id=action_id,
            tool_name="bash",
            arguments=arguments,
        )
        if request_digest != expected:
            raise PermissionError(self._prompts.render('bash_execution.request_digest'))
        view = self.journal.load_bash_execution(
            execution_scope=execution_scope,
            action_id=action_id,
            request_digest=request_digest,
            retain_task_workspace=self.profile.task_workspace is not None,
        )
        if (
            view.execution_scope != execution_scope
            or view.action_id != action_id
            or view.arguments != arguments
            or view.request_digest != request_digest
            or view.deployment_digest != self.profile.deployment_digest
        ):
            raise PermissionError(self._prompts.render('bash_execution.accepted_deployment'))
        if view.command is not None:
            self._validate_command(view.command, view)
        if view.receipt is not None and view.receipt.status != "unknown":
            if view.command is None:
                raise ValueError(self._prompts.render('bash_execution.receipt_command'))
            return self._response(view.receipt, execution_scope)
        command = view.command
        if command is None:
            if view.execution is not None or view.receipt is not None:
                raise ValueError(self._prompts.render('bash_execution.execution_command'))
            command = self._command(view)
            self.journal.bind_bash_command(
                execution_scope=execution_scope,
                action_id=action_id,
                command=command,
            )
        elif view.execution is None:
            self._validate_input_identities(command)
        if view.execution is not None:
            # Dispatching and terminal-without-receipt both resume the original
            # job. A missing capture must never trigger another computation.
            outcome = self.execution.reconcile(command)
            if view.execution.status not in {"dispatching", "unknown"}:
                original = view.execution
                if outcome.execution.output_available:
                    if outcome.execution != original:
                        raise ValueError(self._prompts.render('bash_execution.recovery_fact'))
                else:
                    # Reconciliation may lose a capture, but cannot erase an
                    # already committed exit code, OOM fact or actual runtime.
                    outcome = outcome.model_copy(
                        update={
                            "execution": original.model_copy(
                                update={"output_available": False}
                            )
                        }
                    )
        else:
            self.journal.record_bash_execution(
                execution_scope=execution_scope,
                action_id=action_id,
                fact=BashExecutionFact(status="dispatching", output_available=False),
            )
            outcome = self.execution.execute(
                command, lambda item: self._read_input(item, execution_scope), run_deadline_at=view.run_deadline_at,
            )
        if view.execution is None or view.execution.status in {
            "dispatching",
            "unknown",
        }:
            self.journal.record_bash_execution(
                execution_scope=execution_scope,
                action_id=action_id,
                fact=outcome.execution,
            )
        receipt = self._publish_outcome(command, outcome)
        self.journal.record_bash_result(
            execution_scope=execution_scope,
            action_id=action_id,
            receipt=receipt,
        )
        return self._response(receipt, execution_scope)

    def _input_identity(
        self, name: str, ref: ResourceRef, scope: ExecutionScope, *, max_bytes: int
    ) -> BashInputIdentity:
        if ref.resource_type != "artifact" or ref.owner != scope.principal:
            raise PermissionError(self._prompts.render('bash_execution.input_owner'))
        metadata = self.artifacts.describe_upload(
            ref,
            principal=scope.principal,
            owner=scope.principal,
        )
        if metadata.resource_ref != ref or metadata.size_bytes > max_bytes:
            raise ValueError(self._prompts.render('bash_execution.input_boundary'))
        return BashInputIdentity.model_validate({
            "name": name, "resource_ref": ref,
            "content_digest": metadata.content_digest, "size_bytes": metadata.size_bytes,
        }, context=self._prompts)

    def _read_input(self, identity: BashInputIdentity, scope: ExecutionScope) -> BashInputContent:
        stored, content = self.artifacts.read_upload(
            identity.resource_ref,
            principal=scope.principal,
            owner=scope.principal,
        )
        if stored.resource_ref != identity.resource_ref or stored.size_bytes != identity.size_bytes:
            raise ValueError(self._prompts.render('bash_execution.input_changed'))
        return BashInputContent.model_validate({
            **identity.model_dump(), "content": content,
        }, context=self._prompts)

    def _publish(
        self,
        scope: ExecutionScope,
        key: str,
        name: str,
        content: bytes,
        *,
        mime: str,
        sources: tuple[ResourceRef, ...] = (),
        limitations: tuple[str, ...] = (),
    ) -> ResourceRef:
        return self.artifacts.publish_machine(
            execution_scope=scope,
            producer_key=f"python-execution:{key}:{name}:{hashlib.sha256(content).hexdigest()}",
            producer_ref=key,
            filename=name,
            content_type=mime,
            file_bytes=content,
            kind="bash_execution",
            source_artifact_refs=tuple(dict.fromkeys(sources)),
            limitations=limitations,
        )

    def _command(self, view: BashJournalView) -> BashExecutionCommand:
        if (
            view.remaining_execution_seconds <= 0
            or self.clock() >= view.run_deadline_at
        ):
            raise TimeoutError(self._prompts.render('bash_execution.budget_exhausted'))
        scope = view.execution_scope
        content = view.arguments.command.encode("utf-8")
        program_ref = self._publish(
            scope,
            view.request_digest,
            "command.sh",
            content,
            mime="text/x-shellscript",
        )
        source = self._input_identity(
            "command.sh", program_ref, scope, max_bytes=PROGRAM_MAX_BYTES
        )
        inputs: list[BashInputIdentity] = []
        available = INPUT_MAX_BYTES
        for file in view.workspace_files:
            item = self._input_identity(file.name, file.resource_ref, scope, max_bytes=available)
            inputs.append(item)
            available -= item.size_bytes
        now = self.clock()
        reserved = min(
            self.profile.limits.timeout_seconds,
            view.remaining_execution_seconds,
            (view.run_deadline_at - now).total_seconds(),
        )
        if reserved <= 0:
            raise TimeoutError(self._prompts.render('bash_execution.input_budget_exhausted'))
        deadline = min(
            view.run_deadline_at,
            now + timedelta(microseconds=int(reserved * 1_000_000)),
        )
        reserved = (deadline - now).total_seconds()
        if reserved <= 0:
            raise TimeoutError(self._prompts.render('bash_execution.timer_resolution'))
        limits = self.profile.limits.model_copy(update={"timeout_seconds": reserved})
        fields = dict(
            execution_scope=scope,
            action_id=view.action_id,
            request_digest=view.request_digest,
            deployment_digest=view.deployment_digest,
            image_id=self.profile.image_id,
            limits=limits,
            program=source,
            inputs=tuple(inputs),
            workdir=view.arguments.workdir,
            accepted_at=now,
            deadline_at=deadline,
            reserved_seconds=reserved,
            task_workspace=view.task_workspace,
            workspace_file=view.arguments.workspace_file,
        )
        # Reparse the full payload so the digest uses exactly the persisted JSON
        # representation (including aware datetime and float serialization).
        provisional = BashExecutionCommand.model_construct(
            **fields, command_digest="0" * 64
        )
        return BashExecutionCommand.model_validate(
            {**fields, "command_digest": provisional.bound_digest()}, context=self._prompts,
        )

    def _validate_command(
        self, command: BashExecutionCommand, view: BashJournalView
    ) -> None:
        if (
            command.execution_scope != view.execution_scope
            or command.action_id != view.action_id
            or command.request_digest != view.request_digest
            or command.deployment_digest != view.deployment_digest
            or command.image_id != self.profile.image_id
            or command.deadline_at > view.run_deadline_at
            or command.limits.model_dump(exclude={"timeout_seconds"})
            != self.profile.limits.model_dump(exclude={"timeout_seconds"})
            or command.limits.timeout_seconds > self.profile.limits.timeout_seconds
            or command.workdir != view.arguments.workdir
            or command.task_workspace != view.task_workspace
            or command.workspace_file != view.arguments.workspace_file
        ):
            raise PermissionError(self._prompts.render('bash_execution.command_request'))
        expected = view.arguments.command.encode("utf-8")
        if command.program.content_digest != hashlib.sha256(
            expected
        ).hexdigest() or command.program.size_bytes != len(expected):
            raise ValueError(self._prompts.render('bash_execution.program_bytes'))

    def _validate_input_identities(self, command: BashExecutionCommand) -> None:
        for item in (command.program, *command.inputs):
            current = self._input_identity(
                item.name, item.resource_ref, command.execution_scope, max_bytes=item.size_bytes,
            )
            if current != item:
                raise ValueError(self._prompts.render('bash_execution.original_command'))

    def _publish_outcome(
        self, command: BashExecutionCommand, outcome: BashBackendOutcome
    ) -> BashExecutionReceipt:
        fact = outcome.execution
        if fact.status == "dispatching":
            raise ValueError(self._prompts.render('bash_execution.dispatching_result'))
        if (
            len(outcome.stdout) > command.limits.stdout_bytes
            or len(outcome.stderr) > command.limits.stderr_bytes
        ):
            raise ValueError(self._prompts.render('bash_execution.capture_budget'))
        sources = (
            command.program.resource_ref,
            *(item.resource_ref for item in command.inputs),
        )
        manifest = BashInputManifest(
            command_digest=command.command_digest,
            program=command.program,
            inputs=command.inputs,
            image_id=command.image_id,
            limits=command.limits,
        )
        manifest_ref = self._publish(
            command.execution_scope,
            command.command_digest,
            "input_manifest.json",
            (manifest.model_dump_json() + "\n").encode("utf-8"),
            mime="application/json",
            sources=sources,
        )
        limitations = []
        status = fact.status
        error = fact.error_code
        if fact.stdout_truncated:
            limitations.append(self._prompts.render('bash_execution.stdout_limit'))
        if fact.stderr_truncated:
            limitations.append(self._prompts.render('bash_execution.stderr_limit'))
        stdout_ref = stderr_ref = None
        if fact.output_available:
            for stream, content in (
                ("stdout", outcome.stdout),
                ("stderr", outcome.stderr),
            ):
                try:
                    content.decode("utf-8", errors="strict")
                    mime = "text/plain"
                except UnicodeDecodeError:
                    mime = "application/octet-stream"
                    limitations.append(
                        self._prompts.render('bash_execution.invalid_utf8', stream=stream)
                    )
                    if stream == "stdout" and status == "succeeded":
                        status, error = "invalid_output", "invalid_output"
                ref = self._publish(
                    command.execution_scope,
                    command.command_digest,
                    f"{stream}.{'txt' if mime == 'text/plain' else 'bin'}",
                    content,
                    mime=mime,
                    sources=(*sources, manifest_ref),
                    limitations=tuple(limitations),
                )
                if stream == "stdout":
                    stdout_ref = ref
                else:
                    stderr_ref = ref
        else:
            prompt = "bash_execution.task_workspace_unavailable" if error == "workspace_unavailable" else (
                "bash_execution.output_unavailable"
            )
            limitations.append(self._prompts.render(prompt))
            if status == "succeeded":
                status, error = "failed", "output_unavailable"
        return BashExecutionReceipt(
            action_id=command.action_id,
            command_digest=command.command_digest,
            status=status,
            program_ref=command.program.resource_ref,
            input_manifest_ref=manifest_ref,
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
            process_exit_code=fact.process_exit_code,
            elapsed_seconds=fact.elapsed_seconds,
            error_code=error,
            limits=command.limits,
            limitations=tuple(limitations),
        )

    def _response(
        self, receipt: BashExecutionReceipt, scope: ExecutionScope
    ) -> BashToolResult:
        previews: dict[str, str | int | None] = {}
        for stream, ref, limit, byte_limit in (
            (
                "stdout",
                receipt.stdout_ref,
                STDOUT_PREVIEW_CHARS,
                receipt.limits.stdout_bytes,
            ),
            (
                "stderr",
                receipt.stderr_ref,
                STDERR_PREVIEW_CHARS,
                receipt.limits.stderr_bytes,
            ),
        ):
            preview = omitted = None
            if ref is not None:
                content = self._read(
                    stream + ".txt", ref, scope, max_bytes=byte_limit
                ).content
                try:
                    text = content.decode("utf-8", errors="strict")
                    preview, omitted = text[:limit], max(0, len(text) - limit)
                except UnicodeDecodeError:
                    pass
            previews[f"{stream}_preview"] = preview
            previews[f"{stream}_omitted_chars"] = omitted
        return BashToolResult(
            receipt=receipt, limitations=receipt.limitations, **previews
        )
