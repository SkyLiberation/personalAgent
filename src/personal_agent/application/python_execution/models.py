"""Immutable Python requests, frozen execution identity and actual results."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope
from personal_agent.kernel.prompts import get_prompt

PROGRAM_MAX_BYTES = 128 * 1024
INPUT_MAX_BYTES = 64 * 1024 * 1024
INPUT_MAX_COUNT = 32
STDOUT_PREVIEW_CHARS = 4000
STDERR_PREVIEW_CHARS = 2000
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1)]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveSeconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]
PositiveInteger = Annotated[int, Field(strict=True, gt=0)]
ProcessStatus = Literal[
    "dispatching", "succeeded", "failed", "timed_out", "output_limit", "unknown"
]
ResultStatus = Literal[
    "succeeded", "failed", "timed_out", "output_limit", "unknown", "invalid_output"
]
ErrorCode = Literal[
    "execution_failed",
    "deadline",
    "output_limit",
    "backend_unknown",
    "invalid_output",
    "output_unavailable",
    "oom",
]
_FILENAME = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
_DEVICES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)}
)
_RESERVED = frozenset({"program.py", "input_manifest.json"})


class PythonModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def validate_python_filename(name: str, *, allow_reserved: bool = False) -> str:
    if (
        not _FILENAME.fullmatch(name)
        or name in {".", ".."}
        or name.endswith(".")
        or name.split(".", 1)[0].casefold() in _DEVICES
        or (not allow_reserved and name.casefold() in _RESERVED)
    ):
        raise ValueError("输入必须是合法、非保留的1—64字符ASCII平面文件名")
    return name


class PythonInputBinding(PythonModel):
    name: str = Field(
        description=get_prompt("python_execution.parameter.input_name").template
    )
    resource_ref: ResourceRef = Field(
        description=get_prompt("python_execution.parameter.input_resource_ref").template
    )

    @field_validator("name")
    @classmethod
    def safe_name(cls, name: str) -> str:
        return validate_python_filename(name)


class ExecutePythonArgs(PythonModel):
    code: str | None = Field(
        description=get_prompt("python_execution.parameter.code").template
    )
    program_ref: ResourceRef | None = Field(
        description=get_prompt("python_execution.parameter.program_ref").template
    )
    input_files: tuple[PythonInputBinding, ...] = Field(
        max_length=INPUT_MAX_COUNT,
        description=get_prompt("python_execution.parameter.input_files").template,
    )

    @field_validator("code")
    @classmethod
    def bounded_code(cls, code: str | None) -> str | None:
        if code is not None and len(code.encode("utf-8")) > PROGRAM_MAX_BYTES:
            raise ValueError("Python程序超过128 KiB")
        return code

    @model_validator(mode="after")
    def valid_source_and_names(self) -> ExecutePythonArgs:
        if (self.code is None) == (self.program_ref is None):
            raise ValueError("code与program_ref必须恰好一项不是null")
        names = [item.name.casefold() for item in self.input_files]
        if len(names) != len(set(names)):
            raise ValueError("输入文件名不能重复或仅大小写不同")
        return self


class PythonExecutionLimits(PythonModel):
    timeout_seconds: PositiveSeconds = 60
    memory_mb: PositiveInteger = 512
    cpus: PositiveSeconds = 1
    pids_limit: PositiveInteger = 64
    stdout_bytes: Annotated[int, Field(strict=True, gt=0, le=16 * 1024 * 1024)] = (
        16 * 1024 * 1024
    )
    stderr_bytes: Annotated[int, Field(strict=True, gt=0, le=64 * 1024)] = 64 * 1024
    scratch_mb: PositiveInteger = 32


class PythonExecutionProfile(PythonModel):
    authorized_principal: AuthenticatedPrincipal
    deployment_digest: Digest
    image_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    limits: PythonExecutionLimits


class PythonInputIdentity(PythonModel):
    name: str
    resource_ref: ResourceRef
    content_digest: Digest
    size_bytes: Annotated[int, Field(strict=True, ge=0)]

    @field_validator("name")
    @classmethod
    def safe_name(cls, name: str) -> str:
        return validate_python_filename(name, allow_reserved=True)


class PythonInputContent(PythonInputIdentity):
    content: bytes

    @model_validator(mode="after")
    def verified_bytes(self) -> PythonInputContent:
        if (
            len(self.content) != self.size_bytes
            or hashlib.sha256(self.content).hexdigest() != self.content_digest
        ):
            raise ValueError("Python输入长度或原字节摘要不符")
        return self

    def identity(self) -> PythonInputIdentity:
        return PythonInputIdentity(**self.model_dump(exclude={"content"}))


class PythonExecutionCommand(PythonModel):
    execution_scope: ExecutionScope
    action_id: Identifier
    request_digest: Digest
    deployment_digest: Digest
    image_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    limits: PythonExecutionLimits
    program: PythonInputIdentity
    inputs: tuple[PythonInputIdentity, ...] = Field(max_length=INPUT_MAX_COUNT)
    accepted_at: AwareDatetime
    deadline_at: AwareDatetime
    reserved_seconds: PositiveSeconds
    command_digest: Digest

    @model_validator(mode="after")
    def validate_command(self) -> PythonExecutionCommand:
        if self.deadline_at <= self.accepted_at:
            raise ValueError("Python deadline必须晚于接受时间")
        if (
            self.reserved_seconds > self.limits.timeout_seconds
            or self.reserved_seconds
            > (self.deadline_at - self.accepted_at).total_seconds()
        ):
            raise ValueError("Python预留超过冻结限额或deadline")
        if (
            self.program.name != "program.py"
            or self.program.size_bytes > PROGRAM_MAX_BYTES
        ):
            raise ValueError("Python程序身份或长度不合法")
        names = [validate_python_filename(item.name).casefold() for item in self.inputs]
        if (
            len(names) != len(set(names))
            or sum(item.size_bytes for item in self.inputs) > INPUT_MAX_BYTES
        ):
            raise ValueError("Python输入重复或超过64 MiB")
        if any(
            item.resource_ref.owner != self.execution_scope.principal
            or item.resource_ref.resource_type != "artifact"
            for item in (self.program, *self.inputs)
        ):
            raise ValueError("Python Command只绑定本主体的Artifact")
        if self.command_digest != canonical_digest(
            self.model_dump(mode="json", exclude={"command_digest"})
        ):
            raise ValueError("Python Command摘要不一致")
        return self


class PythonExecutionFact(PythonModel):
    status: ProcessStatus
    process_exit_code: int | None = None
    elapsed_seconds: Seconds | None = None
    container_id: str | None = None
    image_id: str | None = None
    oom_killed: bool | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    output_available: bool = True
    error_code: ErrorCode | None = None


class PythonExecutionReceipt(PythonModel):
    action_id: Identifier
    command_digest: Digest
    status: ResultStatus
    program_ref: ResourceRef
    input_manifest_ref: ResourceRef
    stdout_ref: ResourceRef | None = None
    stderr_ref: ResourceRef | None = None
    process_exit_code: int | None = None
    elapsed_seconds: Seconds | None = None
    error_code: ErrorCode | None = None
    limits: PythonExecutionLimits
    limitations: tuple[str, ...] = ()


class PythonJournalView(PythonModel):
    execution_scope: ExecutionScope
    action_id: Identifier
    arguments: ExecutePythonArgs
    request_digest: Digest
    deployment_digest: Digest
    allowed_refs: tuple[ResourceRef, ...]
    run_deadline_at: AwareDatetime
    remaining_execution_seconds: Seconds
    command: PythonExecutionCommand | None = None
    execution: PythonExecutionFact | None = None
    receipt: PythonExecutionReceipt | None = None


class PythonBackendOutcome(PythonModel):
    execution: PythonExecutionFact
    stdout: bytes
    stderr: bytes


class PythonInputManifest(PythonModel):
    command_digest: Digest
    program: PythonInputIdentity
    inputs: tuple[PythonInputIdentity, ...]
    image_id: str
    limits: PythonExecutionLimits


class PythonToolResult(PythonModel):
    receipt: PythonExecutionReceipt
    stdout_preview: str | None = Field(default=None, max_length=STDOUT_PREVIEW_CHARS)
    stderr_preview: str | None = Field(default=None, max_length=STDERR_PREVIEW_CHARS)
    stdout_omitted_chars: int | None = Field(default=None, ge=0)
    stderr_omitted_chars: int | None = Field(default=None, ge=0)
    limitations: tuple[str, ...] = ()
