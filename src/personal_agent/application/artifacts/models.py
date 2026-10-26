"""Canonical immutable Artifact metadata, text edits and committed projections."""

from __future__ import annotations

from typing import Annotated, Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope

DRAFT_MAX_BYTES = 65_536
DRAFT_MAX_EDITS = 32
ArtifactPurpose = Literal["upload", "draft", "machine", "generated"]
ContentDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _ArtifactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def resolve_artifact_ref(
    resource_id: str,
    allowed_refs: tuple[ResourceRef, ...],
    *,
    principal: AuthenticatedPrincipal,
) -> ResourceRef:
    """Resolve a model's ID only within the caller's already authorized facts."""
    matches = tuple(dict.fromkeys(
        ref for ref in allowed_refs if ref.resource_id == resource_id
    ))
    if len(matches) != 1:
        raise PermissionError("文件ID不在当前可读集合中，或对应多个不同的确切引用。")
    ref = matches[0]
    if ref.resource_type != "artifact" or ref.owner != principal:
        raise PermissionError("文件ID不属于当前主体的Artifact。")
    return ref


def validate_display_filename(filename: str) -> str:
    """Names are export labels, never storage paths or HTTP header fragments."""
    if (
        not filename
        or len(filename) > 120
        or filename in {".", ".."}
        or filename != filename.strip()
        or any(
            ch in '/\\:<>"|?*' or unicodedata.category(ch).startswith("C")
            for ch in filename
        )
        or filename.endswith(".")
    ):
        raise ValueError(
            "filename must be a safe display name of at most 120 characters"
        )
    return filename


def validate_content_type(content_type: str | None) -> str | None:
    if content_type is not None and (
        not content_type
        or any(unicodedata.category(ch).startswith("C") for ch in content_type)
    ):
        raise ValueError("Artifact media type contains an invalid header separator")
    return content_type


class TextPosition(_ArtifactModel):
    line: int = Field(ge=1, strict=True)
    column: int = Field(ge=1, strict=True)


class TextRange(_ArtifactModel):
    start: TextPosition
    end: TextPosition


class TextEdit(_ArtifactModel):
    range: TextRange
    new_text: str


class CreateArtifact(_ArtifactModel):
    operation: Literal["create"]
    filename: str
    content_type: Literal["text/x-python", "application/json"]
    content: str

    _filename = field_validator("filename")(validate_display_filename)

    _content_type = field_validator("content_type")(validate_content_type)

    @model_validator(mode="after")
    def validate_draft(self) -> CreateArtifact:
        suffix = ".py" if self.content_type == "text/x-python" else ".json"
        if not self.filename.endswith(suffix):
            raise ValueError("draft filename does not match its media type")
        if len(self.content.encode("utf-8")) > DRAFT_MAX_BYTES:
            raise ValueError("draft exceeds the 65536-byte UTF-8 limit")
        return self


class PatchArtifact(_ArtifactModel):
    operation: Literal["patch"]
    base_resource_id: str = Field(min_length=1, description="当前可读草稿的resource_id；按该确切快照的行列范围修改。")
    edits: tuple[TextEdit, ...] = Field(min_length=1, max_length=DRAFT_MAX_EDITS)

    @model_validator(mode="after")
    def validate_added_bytes(self) -> PatchArtifact:
        if (
            sum(len(edit.new_text.encode("utf-8")) for edit in self.edits)
            > DRAFT_MAX_BYTES
        ):
            raise ValueError("patch additions exceed the 65536-byte UTF-8 limit")
        return self


ArtifactWriteRequest = Annotated[
    CreateArtifact | PatchArtifact, Field(discriminator="operation")
]


class ArtifactRecord(_ArtifactModel):
    resource_ref: ResourceRef
    filename: str
    content_type: str | None
    source_type: str
    size_bytes: int = Field(ge=0)
    storage_name: str
    created_by_principal_id: str = Field(min_length=1)
    artifact_kind: str = Field(min_length=1)
    content_digest: ContentDigest
    # Absence records an historical unknown, never the current caller's scope.
    purpose: ArtifactPurpose | None = None
    execution_scope: ExecutionScope | None = None
    producer_key: str | None = None
    producer_ref: str | None = None
    source_artifact_refs: tuple[ResourceRef, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    _filename = field_validator("filename")(validate_display_filename)
    _content_type = field_validator("content_type")(validate_content_type)

    @model_validator(mode="after")
    def validate_identity(self) -> ArtifactRecord:
        if (
            self.resource_ref.resource_type != "artifact"
            or self.resource_ref.revision != 1
        ):
            raise ValueError("Artifact records require an immutable artifact revision")
        if self.created_by_principal_id != self.resource_ref.owner.principal_id:
            raise ValueError("Artifact creator does not match its owner")
        if (
            self.execution_scope
            and self.execution_scope.principal != self.resource_ref.owner
        ):
            raise ValueError("Artifact execution scope does not match its owner")
        if (
            self.purpose in {"draft", "machine", "generated"}
            and self.execution_scope is None
        ):
            raise ValueError(
                "new generated Artifacts require their actual execution scope"
            )
        if any(
            ref.owner != self.resource_ref.owner for ref in self.source_artifact_refs
        ):
            raise ValueError("Artifact source is cross-scope")
        if (
            not self.storage_name
            or self.storage_name in {".", ".."}
            or any(ch in self.storage_name for ch in "/\\:")
            or any(unicodedata.category(ch).startswith("C") for ch in self.storage_name)
        ):
            raise ValueError("Artifact storage name must be a local basename")
        return self


class ArtifactTextSnapshot(_ArtifactModel):
    record: ArtifactRecord
    content: str
    eof_position: TextPosition

    @property
    def resource_ref(self) -> ResourceRef:
        return self.record.resource_ref

    @property
    def content_digest(self) -> str:
        return self.record.content_digest


class ArtifactWriteReceipt(_ArtifactModel):
    resource_ref: ResourceRef
    filename: str
    content_type: str
    size_bytes: int = Field(ge=0)
    content_digest: ContentDigest
    source_artifact_refs: tuple[ResourceRef, ...] = ()
    edits_applied: int = Field(default=0, ge=0, le=DRAFT_MAX_EDITS)


class ArtifactResourceItem(_ArtifactModel):
    """User download projection; the Web boundary supplies the download route."""

    resource_ref: ResourceRef
    filename: str
    content_type: str | None
    size_bytes: int = Field(ge=0)
    content_digest: ContentDigest


class GeneratedArtifactPublication(_ArtifactModel):
    operation: Literal["generated"] = "generated"
    kind: str = Field(min_length=1)
    content: str
    content_digest: ContentDigest
    source_artifact_refs: tuple[ResourceRef, ...]
    evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...] = ()


class MachineArtifactPublication(_ArtifactModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, ser_json_bytes="base64", val_json_bytes="base64"
    )
    operation: Literal["machine"] = "machine"
    filename: str
    content_type: str = Field(min_length=1)
    file_bytes: bytes
    kind: str = Field(min_length=1)
    source_artifact_refs: tuple[ResourceRef, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    _filename = field_validator("filename")(validate_display_filename)
    _content_type = field_validator("content_type")(validate_content_type)


AcceptedArtifactRequest = Annotated[
    CreateArtifact
    | PatchArtifact
    | GeneratedArtifactPublication
    | MachineArtifactPublication,
    Field(discriminator="operation"),
]


class ArtifactProducerBinding(_ArtifactModel):
    """Immutable accepted request; canonical metadata owns the committed result."""

    producer_key: str = Field(min_length=1)
    producer_ref: str = Field(min_length=1)
    execution_scope: ExecutionScope
    purpose: Literal["draft", "machine", "generated"]
    request: AcceptedArtifactRequest

    @model_validator(mode="after")
    def validate_purpose(self) -> ArtifactProducerBinding:
        expected = (
            "draft"
            if self.request.operation in {"create", "patch"}
            else self.request.operation
        )
        if self.purpose != expected:
            raise ValueError(
                "accepted Artifact request does not match its producer purpose"
            )
        return self
