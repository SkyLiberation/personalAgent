"""Freeze model-selected bytes, dispatch once, and publish actual process output."""

from __future__ import annotations

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
    ExecutePythonArgs,
    PythonBackendOutcome,
    PythonExecutionCommand,
    PythonExecutionFact,
    PythonExecutionProfile,
    PythonExecutionReceipt,
    PythonInputContent,
    PythonInputManifest,
    PythonJournalView,
    PythonToolResult,
    canonical_digest,
)
from .ports import PythonArtifactPort, PythonExecutionPort, PythonJournalPort


class PythonExecutionService:
    def __init__(
        self,
        *,
        artifacts: PythonArtifactPort,
        journal: PythonJournalPort,
        execution: PythonExecutionPort,
        profile: PythonExecutionProfile,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.artifacts = artifacts
        self.journal = journal
        self.execution = execution
        self.profile = profile
        self.clock = clock

    def execute(
        self,
        arguments: ExecutePythonArgs,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        request_digest: str,
    ) -> PythonToolResult:
        if execution_scope.principal != self.profile.authorized_principal:
            raise PermissionError("本主体未获Python执行部署授权")
        expected = accepted_tool_request_digest(
            execution_scope=execution_scope,
            action_id=action_id,
            tool_name="execute_python",
            arguments=arguments,
        )
        if request_digest != expected:
            raise PermissionError("Python请求与已接受摘要不同")
        view = self.journal.load_python_execution(
            execution_scope=execution_scope,
            action_id=action_id,
            request_digest=request_digest,
        )
        if (
            view.execution_scope != execution_scope
            or view.action_id != action_id
            or view.arguments != arguments
            or view.request_digest != request_digest
            or view.deployment_digest != self.profile.deployment_digest
        ):
            raise PermissionError("Python请求未被本run按当前部署接受")
        if view.command is not None:
            self._validate_command(view.command, view)
        if view.receipt is not None and view.receipt.status != "unknown":
            if view.command is None:
                raise ValueError("Python回执缺少冻结Command")
            self.execution.cleanup(view.command)
            return self._response(view.receipt, execution_scope)
        command = view.command
        if command is None:
            if view.execution is not None or view.receipt is not None:
                raise ValueError("Python执行记录缺少冻结Command")
            command, inputs = self._command(view)
            self.journal.bind_python_command(
                execution_scope=execution_scope,
                action_id=action_id,
                command=command,
            )
        elif view.execution is None:
            inputs = self._restore_inputs(command, view)
        if view.execution is not None:
            # Dispatching and terminal-without-receipt both resume the original
            # job. A missing capture must never trigger another computation.
            outcome = self.execution.reconcile(command)
            if view.execution.status not in {"dispatching", "unknown"}:
                original = view.execution
                if outcome.execution.output_available:
                    if outcome.execution != original:
                        raise ValueError("Python恢复结果与已保存进程事实不同")
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
            self.journal.record_python_execution(
                execution_scope=execution_scope,
                action_id=action_id,
                fact=PythonExecutionFact(status="dispatching", output_available=False),
            )
            outcome = self.execution.execute(command, inputs)
        if view.execution is None or view.execution.status in {
            "dispatching",
            "unknown",
        }:
            self.journal.record_python_execution(
                execution_scope=execution_scope,
                action_id=action_id,
                fact=outcome.execution,
            )
        receipt = self._publish_outcome(command, outcome)
        self.journal.record_python_result(
            execution_scope=execution_scope,
            action_id=action_id,
            receipt=receipt,
        )
        if receipt.status != "unknown":
            self.execution.cleanup(command)
        return self._response(receipt, execution_scope)

    def _read(
        self, name: str, ref: ResourceRef, scope: ExecutionScope, *, max_bytes: int
    ) -> PythonInputContent:
        if ref.resource_type != "artifact" or ref.owner != scope.principal:
            raise PermissionError("Python只能读取本主体的确切Artifact")
        metadata = self.artifacts.resource_item(
            ref,
            principal=scope.principal,
            owner=scope.principal,
        )
        if metadata.resource_ref != ref or metadata.size_bytes > max_bytes:
            raise ValueError("Python输入身份或字节长度超过边界")
        stored, content = self.artifacts.read_upload(
            ref,
            principal=scope.principal,
            owner=scope.principal,
        )
        if stored.resource_ref != ref or stored.size_bytes != metadata.size_bytes:
            raise ValueError("Python读取期间Artifact身份发生变化")
        return PythonInputContent(
            name=name,
            resource_ref=ref,
            content_digest=metadata.content_digest,
            size_bytes=metadata.size_bytes,
            content=content,
        )

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
            kind="python_execution",
            source_artifact_refs=tuple(dict.fromkeys(sources)),
            limitations=limitations,
        )

    def _require_arguments(self, view: PythonJournalView) -> None:
        refs = [item.resource_ref for item in view.arguments.input_files]
        if view.arguments.program_ref is not None:
            refs.append(view.arguments.program_ref)
        if any(ref not in view.allowed_refs for ref in refs):
            raise PermissionError("Python程序或输入不属于当前合法可读集合")

    def _command(
        self, view: PythonJournalView
    ) -> tuple[PythonExecutionCommand, tuple[PythonInputContent, ...]]:
        self._require_arguments(view)
        if (
            view.remaining_execution_seconds <= 0
            or self.clock() >= view.run_deadline_at
        ):
            raise TimeoutError("当前run执行额度或绝对截止已耗尽")
        scope = view.execution_scope
        if view.arguments.code is not None:
            content = view.arguments.code.encode("utf-8")
            program_ref = self._publish(
                scope,
                view.request_digest,
                "program.py",
                content,
                mime="text/x-python",
            )
        else:
            program_ref = view.arguments.program_ref
            if program_ref is None:
                raise ValueError("Python请求缺少程序来源")
        source = self._read(
            "program.py", program_ref, scope, max_bytes=PROGRAM_MAX_BYTES
        )
        # Source files are UTF-8; compilation and program correctness belong to
        # the real interpreter and its output rather than an admission heuristic.
        source.content.decode("utf-8", errors="strict")
        inputs: list[PythonInputContent] = []
        available = INPUT_MAX_BYTES
        for binding in view.arguments.input_files:
            item = self._read(
                binding.name, binding.resource_ref, scope, max_bytes=available
            )
            inputs.append(item)
            available -= item.size_bytes
        now = self.clock()
        reserved = min(
            self.profile.limits.timeout_seconds,
            view.remaining_execution_seconds,
            (view.run_deadline_at - now).total_seconds(),
        )
        if reserved <= 0:
            raise TimeoutError("准备Python输入时当前run截止或额度已耗尽")
        deadline = min(
            view.run_deadline_at,
            now + timedelta(microseconds=int(reserved * 1_000_000)),
        )
        reserved = (deadline - now).total_seconds()
        if reserved <= 0:
            raise TimeoutError("Python剩余额度低于执行时钟精度")
        limits = self.profile.limits.model_copy(update={"timeout_seconds": reserved})
        fields = dict(
            execution_scope=scope,
            action_id=view.action_id,
            request_digest=view.request_digest,
            deployment_digest=view.deployment_digest,
            image_id=self.profile.image_id,
            limits=limits,
            program=source.identity(),
            inputs=tuple(item.identity() for item in inputs),
            accepted_at=now,
            deadline_at=deadline,
            reserved_seconds=reserved,
        )
        # Reparse the full payload so the digest uses exactly the persisted JSON
        # representation (including aware datetime and float serialization).
        provisional = PythonExecutionCommand.model_construct(
            **fields, command_digest="0" * 64
        )
        command = PythonExecutionCommand(
            **fields,
            command_digest=canonical_digest(
                provisional.model_dump(mode="json", exclude={"command_digest"})
            ),
        )
        return command, (source, *inputs)

    def _validate_command(
        self, command: PythonExecutionCommand, view: PythonJournalView
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
            or tuple((item.name, item.resource_ref) for item in command.inputs)
            != tuple((item.name, item.resource_ref) for item in view.arguments.input_files)
        ):
            raise PermissionError("冻结Python Command与已接受请求或部署不同")
        if view.arguments.code is not None:
            expected = view.arguments.code.encode("utf-8")
            if command.program.content_digest != hashlib.sha256(
                expected
            ).hexdigest() or command.program.size_bytes != len(expected):
                raise ValueError("冻结Python程序与已接受inline原字节不同")
        elif command.program.resource_ref != view.arguments.program_ref:
            raise ValueError("冻结Python程序引用与已接受请求不同")

    def _restore_inputs(
        self, command: PythonExecutionCommand, view: PythonJournalView
    ) -> tuple[PythonInputContent, ...]:
        self._require_arguments(view)
        contents = tuple(
            self._read(
                item.name,
                item.resource_ref,
                view.execution_scope,
                max_bytes=item.size_bytes,
            )
            for item in (command.program, *command.inputs)
        )
        if tuple(item.identity() for item in contents) != (
            command.program,
            *command.inputs,
        ):
            raise ValueError("Python原件与冻结Command不同")
        return contents

    def _publish_outcome(
        self, command: PythonExecutionCommand, outcome: PythonBackendOutcome
    ) -> PythonExecutionReceipt:
        fact = outcome.execution
        if fact.status == "dispatching":
            raise ValueError("执行器不能以dispatching作为执行结果")
        if (
            len(outcome.stdout) > command.limits.stdout_bytes
            or len(outcome.stderr) > command.limits.stderr_bytes
        ):
            raise ValueError("执行器返回超过冻结捕获额度的字节")
        sources = (
            command.program.resource_ref,
            *(item.resource_ref for item in command.inputs),
        )
        manifest = PythonInputManifest(
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
            limitations.append("stdout已达到捕获限制；原件只包含实际捕获字节。")
        if fact.stderr_truncated:
            limitations.append("stderr已达到捕获限制；原件只包含实际捕获字节。")
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
                        f"{stream}含无效UTF-8；保留捕获原字节，不提供文本预览。"
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
            limitations.append(
                "原作业输出不可恢复；未重新运行程序，不能按空输出来解释。"
            )
            if status == "succeeded":
                status, error = "failed", "output_unavailable"
        return PythonExecutionReceipt(
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
        self, receipt: PythonExecutionReceipt, scope: ExecutionScope
    ) -> PythonToolResult:
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
        return PythonToolResult(
            receipt=receipt, limitations=receipt.limitations, **previews
        )
