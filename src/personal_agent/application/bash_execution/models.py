"""Immutable Bash requests, frozen execution identity and actual results."""

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
STDOUT_PREVIEW_CHARS = 4000
STDERR_PREVIEW_CHARS = 2000
BASH_SHARED_INPUTS_DIR = "/run/personal-agent-inputs"
BASH_RUNTIME_DIR = "/opt/personal-agent-runtime"
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


class BashModel(BaseModel):
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


def validate_execution_filename(name: str, *, allow_reserved: bool = False, prompts: PromptCatalog = DEFAULT_PROMPTS) -> str:
    if (
        not _FILENAME.fullmatch(name)
        or name in {".", ".."}
        or name.endswith(".")
        or name.split(".", 1)[0].casefold() in _DEVICES
        or (not allow_reserved and name.casefold() in _RESERVED)
    ):
        raise ValueError(prompts.render('bash_validation.filename'))
    return name


def validate_workspace_path(value: str, *, prompts: PromptCatalog = DEFAULT_PROMPTS) -> str:
    for part in value.split("/"):
        if (not part or part in {".", ".."} or len(part.encode("utf-8")) > 160
                or re.search(r'[\x00-\x1f<>:"\\|?*]', part) or part.endswith((".", " "))
                or part.split(".", 1)[0].casefold() in _DEVICES):
            raise ValueError(prompts.render("bash_validation.filename"))
    return value


class BashArgs(BashModel):
    command: str = Field(description=DEFAULT_PROMPTS.get("bash_execution.parameter.command").template)
    description: str = Field(min_length=1, max_length=512,
                             description=DEFAULT_PROMPTS.get("bash_execution.parameter.description").template)
    workdir: str = Field(default=".", max_length=256,
                         description=DEFAULT_PROMPTS.get("bash_execution.parameter.workdir").template)

    @field_validator("command")
    @classmethod
    def bounded_command(cls, command: str, info: ValidationInfo) -> str:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        if not command.strip() or "\x00" in command or len(command.encode("utf-8")) > PROGRAM_MAX_BYTES:
            raise ValueError(prompts.render("bash_validation.program_size"))
        return command

    @field_validator("workdir")
    @classmethod
    def relative_workdir(cls, workdir: str, info: ValidationInfo) -> str:
        if workdir == ".":
            return workdir
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        return validate_workspace_path(workdir, prompts=prompts)


class BashWorkspaceFile(BashModel):
    name: str
    resource_ref: ResourceRef


class BashExecutionLimits(BashModel):
    timeout_seconds: PositiveSeconds = 60
    memory_mb: PositiveInteger = 512
    cpus: PositiveSeconds = 1
    pids_limit: PositiveInteger = 64
    stdout_bytes: Annotated[int, Field(strict=True, gt=0, le=16 * 1024 * 1024)] = (
        16 * 1024 * 1024
    )
    stderr_bytes: Annotated[int, Field(strict=True, gt=0, le=64 * 1024)] = 64 * 1024
    scratch_mb: PositiveInteger = 32


class BashWorkspaceBinding(BashModel):
    """Deployment binding to the writable workspace of one MCP server."""

    mcp_server_id: Identifier
    volume_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    subdirectory: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    root: str = Field(pattern=r"^/workspace/(?:[A-Za-z0-9_-]+/)+[A-Za-z0-9_-]+$")
    runtime_volume_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    network_container_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class BashExecutionProfile(BashModel):
    authorized_principal: AuthenticatedPrincipal
    deployment_digest: Digest
    image_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    limits: BashExecutionLimits
    workspace: BashWorkspaceBinding | None = None


class BashExecutionAuthorization(BashModel):
    """Operator-owned permit for one foreground analysis conversation."""

    authorized_principal: AuthenticatedPrincipal
    conversation_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    expires_at: AwareDatetime
    turn_timeout_seconds: PositiveSeconds = 3600
    max_total_tokens: PositiveInteger
    max_execution_seconds: PositiveSeconds
    image_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    limits: BashExecutionLimits = Field(default_factory=BashExecutionLimits)
    workspace: BashWorkspaceBinding | None = None

    @property
    def authorization_digest(self) -> Digest:
        return canonical_digest(self.model_dump(mode="json", exclude_none=True))

    def execution_profile(self) -> BashExecutionProfile:
        return BashExecutionProfile(
            authorized_principal=self.authorized_principal,
            deployment_digest=self.authorization_digest,
            image_id=self.image_id,
            limits=self.limits,
            workspace=self.workspace,
        )


class BashInputIdentity(BashModel):
    name: str
    resource_ref: ResourceRef
    content_digest: Digest
    size_bytes: Annotated[int, Field(strict=True, ge=0)]

    @field_validator("name")
    @classmethod
    def safe_name(cls, name: str, info: ValidationInfo) -> str:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        return validate_workspace_path(name, prompts=prompts)


class BashInputContent(BashInputIdentity):
    content: bytes

    @model_validator(mode="after")
    def verified_bytes(self, info: ValidationInfo) -> BashInputContent:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        if (
            len(self.content) != self.size_bytes
            or hashlib.sha256(self.content).hexdigest() != self.content_digest
        ):
            raise ValueError(prompts.render('bash_validation.input_bytes'))
        return self

    def identity(self) -> BashInputIdentity:
        return BashInputIdentity(**self.model_dump(exclude={"content"}))


class BashExecutionCommand(BashModel):
    execution_scope: ExecutionScope
    action_id: Identifier
    request_digest: Digest
    deployment_digest: Digest
    image_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    limits: BashExecutionLimits
    program: BashInputIdentity
    inputs: tuple[BashInputIdentity, ...]
    workdir: str
    accepted_at: AwareDatetime
    deadline_at: AwareDatetime
    reserved_seconds: PositiveSeconds
    command_digest: Digest

    @model_validator(mode="after")
    def validate_command(self, info: ValidationInfo) -> BashExecutionCommand:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        if self.deadline_at <= self.accepted_at:
            raise ValueError(prompts.render('bash_validation.deadline'))
        if (
            self.reserved_seconds > self.limits.timeout_seconds
            or self.reserved_seconds
            > (self.deadline_at - self.accepted_at).total_seconds()
        ):
            raise ValueError(prompts.render('bash_validation.reservation'))
        if (
            self.program.name != "command.sh"
            or self.program.size_bytes > PROGRAM_MAX_BYTES
        ):
            raise ValueError(prompts.render('bash_validation.program_identity'))
        names = [item.name.casefold() for item in self.inputs]
        if self.workdir != ".":
            validate_workspace_path(self.workdir, prompts=prompts)
        if (
            len(names) != len(set(names))
            or sum(item.size_bytes for item in self.inputs) > INPUT_MAX_BYTES
        ):
            raise ValueError(prompts.render('bash_validation.input_total'))
        if any(
            item.resource_ref.owner != self.execution_scope.principal
            or item.resource_ref.resource_type != "artifact"
            for item in (self.program, *self.inputs)
        ):
            raise ValueError(prompts.render('bash_validation.input_owner'))
        if self.command_digest != canonical_digest(
            self.model_dump(mode="json", exclude={"command_digest"})
        ):
            raise ValueError(prompts.render('bash_validation.command_digest'))
        return self


class BashExecutionFact(BashModel):
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


class BashExecutionReceipt(BashModel):
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
    limits: BashExecutionLimits
    limitations: tuple[str, ...] = ()


class BashJournalView(BashModel):
    execution_scope: ExecutionScope
    action_id: Identifier
    arguments: BashArgs
    request_digest: Digest
    deployment_digest: Digest
    workspace_files: tuple[BashWorkspaceFile, ...]
    run_deadline_at: AwareDatetime
    remaining_execution_seconds: Seconds
    command: BashExecutionCommand | None = None
    execution: BashExecutionFact | None = None
    receipt: BashExecutionReceipt | None = None


class BashBackendOutcome(BashModel):
    execution: BashExecutionFact
    stdout: bytes
    stderr: bytes


class BashInputManifest(BashModel):
    command_digest: Digest
    program: BashInputIdentity
    inputs: tuple[BashInputIdentity, ...]
    image_id: str
    limits: BashExecutionLimits


class BashToolResult(BashModel):
    receipt: BashExecutionReceipt
    stdout_preview: str | None = Field(default=None, max_length=STDOUT_PREVIEW_CHARS)
    stderr_preview: str | None = Field(default=None, max_length=STDERR_PREVIEW_CHARS)
    stdout_omitted_chars: int | None = Field(default=None, ge=0)
    stderr_omitted_chars: int | None = Field(default=None, ge=0)
    limitations: tuple[str, ...] = ()

    def shell_output(self) -> str:
        parts = [self.stdout_preview] if self.stdout_preview else []
        if self.stdout_omitted_chars:
            parts.append("[stdout truncated]")
        if self.stderr_preview:
            parts.append(f"[stderr]\n{self.stderr_preview}")
        if self.stderr_omitted_chars:
            parts.append("[stderr truncated]")
        if self.receipt.status not in {"failed", "succeeded"} or self.receipt.process_exit_code is None:
            parts.append(f"[{self.receipt.status}]")
        if self.receipt.process_exit_code is not None:
            parts.append(f"[exit code: {self.receipt.process_exit_code}]")
        return "\n".join(parts)
