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
    ValidationInfo,
    field_validator,
    model_validator,
)

from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
from personal_agent.kernel.prompt_registry import PromptCatalog

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


def validate_python_filename(name: str, *, allow_reserved: bool = False, prompts: PromptCatalog = DEFAULT_PROMPTS) -> str:
    if (
        not _FILENAME.fullmatch(name)
        or name in {".", ".."}
        or name.endswith(".")
        or name.split(".", 1)[0].casefold() in _DEVICES
        or (not allow_reserved and name.casefold() in _RESERVED)
    ):
        raise ValueError(prompts.render('python_validation.filename'))
    return name


class PythonInputBinding(PythonModel):
    name: str = Field(
        description=DEFAULT_PROMPTS.get("python_execution.parameter.input_name").template
    )
    resource_id: str = Field(
        min_length=1,
        description=DEFAULT_PROMPTS.get("python_execution.parameter.input_resource_id").template
    )

    @field_validator("name")
    @classmethod
    def safe_name(cls, name: str, info: ValidationInfo) -> str:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        return validate_python_filename(name, prompts=prompts)


class ExecutePythonArgs(PythonModel):
    code: str = Field(
        description=DEFAULT_PROMPTS.get("python_execution.parameter.code").template
    )
    input_files: tuple[PythonInputBinding, ...] = Field(
        default=(),
        max_length=INPUT_MAX_COUNT,
        description=DEFAULT_PROMPTS.get("python_execution.parameter.input_files").template,
    )

    @field_validator("code")
    @classmethod
    def bounded_code(cls, code: str, info: ValidationInfo) -> str:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        if len(code.encode("utf-8")) > PROGRAM_MAX_BYTES:
            raise ValueError(prompts.render('python_validation.program_size'))
        return code

    @model_validator(mode="after")
    def valid_names(self, info: ValidationInfo) -> ExecutePythonArgs:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        names = [item.name.casefold() for item in self.input_files]
        if len(names) != len(set(names)):
            raise ValueError(prompts.render('python_validation.input_names'))
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


class PythonExecutionAuthorization(PythonModel):
    """Operator-owned permit for one foreground analysis conversation."""

    authorized_principal: AuthenticatedPrincipal
    conversation_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    expires_at: AwareDatetime
    turn_timeout_seconds: PositiveSeconds = 3600
    max_total_tokens: PositiveInteger
    max_execution_seconds: PositiveSeconds
    image_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    limits: PythonExecutionLimits = Field(default_factory=PythonExecutionLimits)

    @property
    def authorization_digest(self) -> Digest:
        return canonical_digest(self.model_dump(mode="json"))

    def execution_profile(self) -> PythonExecutionProfile:
        return PythonExecutionProfile(
            authorized_principal=self.authorized_principal,
            deployment_digest=self.authorization_digest,
            image_id=self.image_id,
            limits=self.limits,
        )


class PythonInputIdentity(PythonModel):
    name: str
    resource_ref: ResourceRef
    content_digest: Digest
    size_bytes: Annotated[int, Field(strict=True, ge=0)]

    @field_validator("name")
    @classmethod
    def safe_name(cls, name: str, info: ValidationInfo) -> str:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        return validate_python_filename(name, allow_reserved=True, prompts=prompts)


class PythonInputContent(PythonInputIdentity):
    content: bytes

    @model_validator(mode="after")
    def verified_bytes(self, info: ValidationInfo) -> PythonInputContent:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        if (
            len(self.content) != self.size_bytes
            or hashlib.sha256(self.content).hexdigest() != self.content_digest
        ):
            raise ValueError(prompts.render('python_validation.input_bytes'))
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
    def validate_command(self, info: ValidationInfo) -> PythonExecutionCommand:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        if self.deadline_at <= self.accepted_at:
            raise ValueError(prompts.render('python_validation.deadline'))
        if (
            self.reserved_seconds > self.limits.timeout_seconds
            or self.reserved_seconds
            > (self.deadline_at - self.accepted_at).total_seconds()
        ):
            raise ValueError(prompts.render('python_validation.reservation'))
        if (
            self.program.name != "program.py"
            or self.program.size_bytes > PROGRAM_MAX_BYTES
        ):
            raise ValueError(prompts.render('python_validation.program_identity'))
        names = [validate_python_filename(item.name, prompts=prompts).casefold() for item in self.inputs]
        if (
            len(names) != len(set(names))
            or sum(item.size_bytes for item in self.inputs) > INPUT_MAX_BYTES
        ):
            raise ValueError(prompts.render('python_validation.input_total'))
        if any(
            item.resource_ref.owner != self.execution_scope.principal
            or item.resource_ref.resource_type != "artifact"
            for item in (self.program, *self.inputs)
        ):
            raise ValueError(prompts.render('python_validation.input_owner'))
        if self.command_digest != canonical_digest(
            self.model_dump(mode="json", exclude={"command_digest"})
        ):
            raise ValueError(prompts.render('python_validation.command_digest'))
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
