from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from pydantic import TypeAdapter

from personal_agent.application.capture.utils import (
    normalize_upload_filename,
    source_type_from_upload,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import create_prompt_catalog
from personal_agent.kernel.contracts.resource import (
    GeneratedArtifactContent,
    ResourceRef,
)
from personal_agent.kernel.contracts.scope import ExecutionScope, AuthenticatedPrincipal

from .models import (
    ArtifactProducerBinding,
    ArtifactRecord,
    ArtifactResourceItem,
    ArtifactTextSnapshot,
    ArtifactWriteReceipt,
    ArtifactWriteRequest,
    CreateArtifact,
    DRAFT_MAX_BYTES,
    DRAFT_SUFFIXES,
    GeneratedArtifactPublication,
    MachineArtifactPublication,
    TOOL_OUTPUT_ID_PATTERN,
    resolve_artifact_file,
    supports_text_snapshot,
    tool_output_directory,
    validate_display_filename,
)
from .storage import exclusive_artifact_lock, install_immutable
from .text_coordinates import TextCoordinates


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    resource_ref: ResourceRef
    filename: str
    content_type: str | None
    source_type: str
    size_bytes: int
    storage_path: Path


@dataclass(frozen=True, slots=True)
class _PreparedDraft:
    binding: ArtifactProducerBinding
    record: ArtifactRecord
    file_bytes: bytes
    edits_applied: int


class ArtifactService:
    """Owns immutable Artifact bytes, metadata and accepted producer requests."""

    def __init__(self, settings: Settings, *, prompts: PromptCatalog | None = None) -> None:
        self.settings = settings
        self._prompts = prompts if prompts is not None else create_prompt_catalog(settings.prompt_language)

    def save_upload(
        self,
        *,
        filename: str,
        content_type: str | None,
        file_bytes: bytes,
        uploads_dir: Path,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> ResourceRef:
        _authorize_principal(principal, owner)
        normalized = validate_display_filename(normalize_upload_filename(filename))
        canonical_root = self.settings.data_dir / "uploads"
        if uploads_dir.resolve() != canonical_root.resolve():
            raise ValueError(
                "uploads_dir must be the canonical Artifact upload directory"
            )
        identity = _canonical_bytes(
            {
                "owner": owner.model_dump(mode="json"),
                "filename": normalized,
                "content_type": content_type,
                "content_digest": _digest(file_bytes),
            }
        )
        artifact_id = f"art_{_digest(identity)[:32]}"
        resource_ref = ResourceRef(
            resource_id=artifact_id, resource_type="artifact", owner=owner
        )
        record = ArtifactRecord(
            resource_ref=resource_ref,
            filename=normalized,
            content_type=content_type,
            source_type=source_type_from_upload(normalized, content_type),
            size_bytes=len(file_bytes),
            storage_name=f"{artifact_id}.bin",
            created_by_principal_id=principal.principal_id,
            artifact_kind="upload",
            content_digest=_digest(file_bytes),
            purpose="upload",
        )
        canonical_root.mkdir(parents=True, exist_ok=True)
        with exclusive_artifact_lock(canonical_root / f".{artifact_id}.lock"):
            self._commit_record(canonical_root, record, file_bytes)
        return resource_ref

    def _load_record(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> tuple[ArtifactRecord, Path]:
        _authorize_principal(principal, owner)
        if resource_ref.resource_type != "artifact" or resource_ref.owner != owner:
            raise PermissionError(
                "Artifact reference is outside the authenticated owner"
            )
        if resource_ref.revision != 1:
            raise ValueError("Artifact revision does not exist")
        sidecar = self._sidecar(resource_ref.resource_id)
        record = ArtifactRecord.model_validate_json(sidecar.read_bytes())
        if record.resource_ref != resource_ref:
            raise PermissionError(
                "Artifact reference does not match its canonical record"
            )
        storage_path = (sidecar.parent / record.storage_name).resolve()
        if storage_path.parent != sidecar.parent.resolve():
            raise PermissionError(
                "Artifact storage path escapes its canonical directory"
            )
        return record, storage_path

    def _read_verified(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> tuple[ArtifactRecord, Path, bytes]:
        record, path = self._load_record(resource_ref, principal=principal, owner=owner)
        content = path.read_bytes()
        if (
            len(content) != record.size_bytes
            or _digest(content) != record.content_digest
        ):
            raise RuntimeError(
                "InvariantViolation: Artifact bytes differ from canonical metadata"
            )
        return record, path, content

    def resolve(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> StoredArtifact:
        record, path, _ = self._read_verified(
            resource_ref, principal=principal, owner=owner
        )
        return _stored_artifact(record, path)

    def read_upload(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> tuple[StoredArtifact, bytes]:
        record, path, content = self._read_verified(
            resource_ref, principal=principal, owner=owner
        )
        return _stored_artifact(record, path), content

    def read_snapshot(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> ArtifactTextSnapshot:
        record, _, content_bytes = self._read_verified(
            resource_ref, principal=principal, owner=owner
        )
        if not supports_text_snapshot(record.content_type):
            raise ValueError("Artifact is not directly readable UTF-8 text")
        content = content_bytes.decode("utf-8", errors="strict")
        return ArtifactTextSnapshot(
            record=record,
            content=content,
            eof_position=TextCoordinates(content).eof_position,
        )

    def read_limitations(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> tuple[str, ...]:
        record, _, _ = self._read_verified(
            resource_ref, principal=principal, owner=owner
        )
        return record.limitations

    def read_text(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> str:
        return self.read_snapshot(
            resource_ref, principal=principal, owner=owner
        ).content

    def resource_item(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> ArtifactResourceItem:
        record, _, _ = self._read_verified(
            resource_ref, principal=principal, owner=owner
        )
        return self._resource_item(record)

    def describe_upload(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> ArtifactResourceItem:
        """Authorize a reference and read its identity before materializing bytes."""
        record, path = self._load_record(resource_ref, principal=principal, owner=owner)
        if not path.is_file() or path.stat().st_size != record.size_bytes:
            raise RuntimeError("InvariantViolation: Artifact is missing or differs from canonical size")
        return self._resource_item(record)

    @staticmethod
    def _resource_item(record: ArtifactRecord) -> ArtifactResourceItem:
        return ArtifactResourceItem(
            resource_ref=record.resource_ref,
            filename=record.filename,
            content_type=record.content_type,
            size_bytes=record.size_bytes,
            content_digest=record.content_digest,
        )

    def write_draft(
        self,
        *,
        execution_scope: ExecutionScope,
        tool_call_id: str,
        request: ArtifactWriteRequest,
        allowed_resource_refs: tuple[ResourceRef, ...],
    ) -> ArtifactWriteReceipt:
        """Trusted Gateway values bind identity; the request contains model choices."""
        prepared = self._prepare_draft(
            execution_scope=execution_scope,
            tool_call_id=tool_call_id,
            request=request,
            allowed_resource_refs=allowed_resource_refs,
        )
        self._commit_publication(prepared.binding, prepared.record, prepared.file_bytes)
        return _draft_receipt(prepared.record, prepared.edits_applied)

    def recover_draft(
        self,
        *,
        execution_scope: ExecutionScope,
        tool_call_id: str,
        request: ArtifactWriteRequest,
        allowed_resource_refs: tuple[ResourceRef, ...],
    ) -> ArtifactWriteReceipt | None:
        """Read an already committed draft without completing a partial write."""
        prepared = self._prepare_draft(
            execution_scope=execution_scope,
            tool_call_id=tool_call_id,
            request=request,
            allowed_resource_refs=allowed_resource_refs,
        )
        root, producer_path, lock_path = self._producer_paths(prepared.binding)
        if not lock_path.exists():
            if producer_path.exists():
                raise RuntimeError(
                    "InvariantViolation: Artifact producer lock is missing"
                )
            return None
        with exclusive_artifact_lock(lock_path, create=False):
            if not _producer_binding_exists(producer_path, prepared.binding):
                return None
            metadata_path = root / f"{prepared.record.resource_ref.resource_id}.json"
            if not metadata_path.exists():
                return None
            try:
                record, _, file_bytes = self._read_verified(
                    prepared.record.resource_ref,
                    principal=execution_scope.principal,
                    owner=execution_scope.principal,
                )
            except FileNotFoundError:
                return None
            if record != prepared.record or file_bytes != prepared.file_bytes:
                raise RuntimeError(
                    "InvariantViolation: committed Artifact differs from its producer request"
                )
        return _draft_receipt(record, prepared.edits_applied)

    def _prepare_draft(
        self,
        *,
        execution_scope: ExecutionScope,
        tool_call_id: str,
        request: ArtifactWriteRequest,
        allowed_resource_refs: tuple[ResourceRef, ...],
    ) -> _PreparedDraft:
        if not isinstance(execution_scope, ExecutionScope):
            raise TypeError("write_draft requires a trusted typed ExecutionScope")
        if not tool_call_id:
            raise ValueError("write_draft requires a stable tool_call_id")
        request = TypeAdapter(ArtifactWriteRequest).validate_python(request)
        source_refs: tuple[ResourceRef, ...] = ()
        edits_applied = 0
        if isinstance(request, CreateArtifact):
            filename, content_type, content = (
                request.filename,
                request.content_type,
                request.content,
            )
        else:
            base_ref = resolve_artifact_file(
                request.file_path, allowed_resource_refs,
                principal=execution_scope.principal, prompts=self._prompts,
            )
            base = self.read_snapshot(
                base_ref,
                principal=execution_scope.principal,
                owner=execution_scope.principal,
            )
            if (
                base.record.purpose != "draft"
                or base.record.execution_scope is None
                or base.record.execution_scope.execution_id
                != execution_scope.execution_id
                or base.record.execution_scope.thread_id != execution_scope.thread_id
            ):
                raise PermissionError(
                    "edit target is not a draft from this task execution"
                )
            filename = base.record.filename
            content_type = base.record.content_type
            if content_type not in DRAFT_SUFFIXES:
                raise ValueError("edit target is not a supported text draft")
            edited, edits_applied = request.replace(
                base.content.encode("utf-8"), max_bytes=DRAFT_MAX_BYTES,
            )
            content = edited.decode("utf-8")
            source_refs = (base_ref,)
        binding = ArtifactProducerBinding(
            producer_key=f"draft:{execution_scope.execution_id}:{tool_call_id}",
            producer_ref=tool_call_id,
            execution_scope=execution_scope,
            purpose="draft",
            request=request,
        )
        file_bytes = content.encode("utf-8")
        record = self._publication_record(
            binding=binding,
            filename=filename,
            content_type=content_type,
            file_bytes=file_bytes,
            kind="draft",
            source_artifact_refs=source_refs,
        )
        return _PreparedDraft(binding, record, file_bytes, edits_applied)

    def write_generated(
        self,
        *,
        owner: AuthenticatedPrincipal,
        execution_scope: ExecutionScope,
        producer_key: str,
        producer_ref: str,
        kind: str,
        content: str,
        content_digest: str,
        source_artifact_refs: tuple[ResourceRef, ...],
        evidence_refs: tuple[str, ...],
        limitations: tuple[str, ...] = (),
    ) -> ResourceRef:
        if execution_scope.principal != owner:
            raise PermissionError("generated Artifact execution scope mismatch")
        if _digest(content.encode("utf-8")) != content_digest:
            raise ValueError("generated Artifact content digest mismatch")
        publication = GeneratedArtifactPublication(
            kind=kind,
            content=content,
            content_digest=content_digest,
            source_artifact_refs=source_artifact_refs,
            evidence_refs=evidence_refs,
            limitations=limitations,
        )
        record = self._publish(
            binding=ArtifactProducerBinding(
                producer_key=producer_key,
                producer_ref=producer_ref,
                execution_scope=execution_scope,
                purpose="generated",
                request=publication,
            ),
            filename=validate_display_filename(normalize_upload_filename(f"{kind}.md")),
            content_type="text/markdown",
            file_bytes=content.encode("utf-8"),
            kind=kind,
            source_artifact_refs=source_artifact_refs,
            evidence_refs=evidence_refs,
            limitations=limitations,
        )
        return record.resource_ref

    def write_tool_output(
        self, *, execution_scope: ExecutionScope, capability_id: str, content: str,
    ) -> ResourceRef:
        """Install an immutable UTF-8 file in the owning session's output directory."""
        scope = execution_scope
        session = _digest(_canonical_bytes({
            "owner": scope.principal.model_dump(mode="json"), "session": scope.thread_id,
        }))[:24]
        call = _digest(_canonical_bytes(scope.model_dump(mode="json")))[:32]
        artifact_id = f"out_{session}_{call}"
        file_bytes = content.encode("utf-8")
        record = ArtifactRecord(
            resource_ref=ResourceRef(resource_id=artifact_id, resource_type="artifact", owner=scope.principal),
            filename=f"{call}.txt",
            storage_name=f"{call}.txt",
            content_type="text/plain",
            source_type="generated",
            size_bytes=len(file_bytes),
            created_by_principal_id=scope.principal.principal_id,
            artifact_kind="tool_output_file",
            content_digest=_digest(file_bytes),
            purpose="machine",
            execution_scope=scope,
            producer_ref=capability_id,
        )
        root = self._tool_output_root(session)
        root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.mkdir(mode=0o700, exist_ok=True)
        self._commit_record(root, record, file_bytes)
        return record.resource_ref

    def publish_machine(
        self,
        *,
        execution_scope: ExecutionScope,
        producer_key: str,
        producer_ref: str,
        filename: str,
        content_type: str,
        file_bytes: bytes,
        kind: str,
        source_artifact_refs: tuple[ResourceRef, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        limitations: tuple[str, ...] = (),
    ) -> ResourceRef:
        """Internal trusted machine producer API; never the model draft entry."""
        publication = MachineArtifactPublication(
            filename=filename,
            content_type=content_type,
            file_bytes=file_bytes,
            kind=kind,
            source_artifact_refs=source_artifact_refs,
            evidence_refs=evidence_refs,
            limitations=limitations,
        )
        return self._publish(
            binding=ArtifactProducerBinding(
                producer_key=producer_key,
                producer_ref=producer_ref,
                execution_scope=execution_scope,
                purpose="machine",
                request=publication,
            ),
            filename=publication.filename,
            content_type=content_type,
            file_bytes=file_bytes,
            kind=kind,
            source_artifact_refs=source_artifact_refs,
            evidence_refs=evidence_refs,
            limitations=limitations,
        ).resource_ref

    def _publish(
        self,
        *,
        binding: ArtifactProducerBinding,
        filename: str,
        content_type: str,
        file_bytes: bytes,
        kind: str,
        source_artifact_refs: tuple[ResourceRef, ...],
        evidence_refs: tuple[str, ...] = (),
        limitations: tuple[str, ...] = (),
    ) -> ArtifactRecord:
        record = self._publication_record(
            binding=binding,
            filename=filename,
            content_type=content_type,
            file_bytes=file_bytes,
            kind=kind,
            source_artifact_refs=source_artifact_refs,
            evidence_refs=evidence_refs,
            limitations=limitations,
        )
        self._commit_publication(binding, record, file_bytes)
        return record

    def _publication_record(
        self,
        *,
        binding: ArtifactProducerBinding,
        filename: str,
        content_type: str,
        file_bytes: bytes,
        kind: str,
        source_artifact_refs: tuple[ResourceRef, ...],
        evidence_refs: tuple[str, ...] = (),
        limitations: tuple[str, ...] = (),
    ) -> ArtifactRecord:
        owner = binding.execution_scope.principal
        if any(ref.owner != owner for ref in source_artifact_refs):
            raise PermissionError("Artifact source is cross-scope")
        request_bytes = _canonical_bytes(binding.model_dump(mode="json"))
        artifact_id = f"artg_{_digest(request_bytes)[:32]}"
        return ArtifactRecord(
            resource_ref=ResourceRef(
                resource_id=artifact_id, resource_type="artifact", owner=owner
            ),
            filename=filename,
            content_type=content_type,
            source_type="generated",
            size_bytes=len(file_bytes),
            storage_name=f"{artifact_id}.bin",
            created_by_principal_id=owner.principal_id,
            artifact_kind=kind,
            content_digest=_digest(file_bytes),
            purpose=binding.purpose,
            execution_scope=binding.execution_scope,
            producer_key=binding.producer_key,
            producer_ref=binding.producer_ref,
            source_artifact_refs=source_artifact_refs,
            evidence_refs=evidence_refs,
            limitations=limitations,
        )

    def _producer_paths(
        self, binding: ArtifactProducerBinding
    ) -> tuple[Path, Path, Path]:
        root = self.settings.data_dir / "generated_artifacts"
        producer_hash = _digest(binding.producer_key.encode("utf-8"))
        return (
            root,
            root / f"producer_{producer_hash}.json",
            root / f".producer_{producer_hash}.lock",
        )

    def _commit_publication(
        self,
        binding: ArtifactProducerBinding,
        record: ArtifactRecord,
        file_bytes: bytes,
    ) -> None:
        root, producer_path, lock_path = self._producer_paths(binding)
        root.mkdir(parents=True, exist_ok=True)
        with exclusive_artifact_lock(lock_path):
            if not _producer_binding_exists(producer_path, binding):
                # The immutable accepted request precedes content and canonical metadata.
                install_immutable(
                    producer_path, _canonical_bytes(binding.model_dump(mode="json"))
                )
            self._commit_record(root, record, file_bytes)

    def _commit_record(
        self, root: Path, record: ArtifactRecord, file_bytes: bytes
    ) -> None:
        if (
            len(file_bytes) != record.size_bytes
            or _digest(file_bytes) != record.content_digest
        ):
            raise RuntimeError(
                "InvariantViolation: Artifact commit bytes do not match metadata"
            )
        content_path = root / record.storage_name
        metadata_path = content_path.with_suffix(".json")
        install_immutable(content_path, file_bytes)
        install_immutable(
            metadata_path, _canonical_bytes(record.model_dump(mode="json"))
        )

    def read_generated(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> GeneratedArtifactContent:
        snapshot = self.read_snapshot(resource_ref, principal=principal, owner=owner)
        if snapshot.record.source_type != "generated":
            raise ValueError("Artifact is not generated content")
        return GeneratedArtifactContent(
            content=snapshot.content,
            content_digest=snapshot.content_digest,
            evidence_refs=snapshot.record.evidence_refs,
            limitations=snapshot.record.limitations,
        )

    def _tool_output_root(self, session: str) -> Path:
        data_dir = self.settings.data_dir.resolve()
        root = data_dir / tool_output_directory(session)
        if root.resolve() != root:
            raise PermissionError("Tool output directory escapes its canonical location")
        return root

    def _sidecar(self, artifact_id: str) -> Path:
        output = TOOL_OUTPUT_ID_PATTERN.fullmatch(artifact_id)
        if output:
            candidates = (self._tool_output_root(output[1]) / f"{output[2]}.json",)
        elif re.fullmatch(r"art(?:g)?_[0-9a-f]+", artifact_id):
            candidates = (
                self.settings.data_dir / "uploads" / f"{artifact_id}.json",
                self.settings.data_dir / "generated_artifacts" / f"{artifact_id}.json",
            )
        else:
            raise ValueError("invalid Artifact identity")
        existing = [path for path in candidates if path.exists()]
        if len(existing) > 1:
            raise RuntimeError(
                "InvariantViolation: Artifact has multiple canonical records"
            )
        if not existing:
            raise FileNotFoundError(f"Artifact does not exist: {artifact_id}")
        sidecar = existing[0]
        if sidecar.resolve().parent != sidecar.parent.resolve():
            raise PermissionError(
                "Artifact metadata path escapes its canonical directory"
            )
        return sidecar


def _authorize_principal(
    principal: AuthenticatedPrincipal,
    owner: AuthenticatedPrincipal,
) -> None:
    if principal != owner:
        raise PermissionError("principal does not match Artifact owner")


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _producer_binding_exists(
    producer_path: Path, binding: ArtifactProducerBinding
) -> bool:
    if not producer_path.exists():
        return False
    try:
        accepted = ArtifactProducerBinding.model_validate_json(
            producer_path.read_bytes()
        )
    except ValueError as error:
        raise RuntimeError(
            "Artifact producer replay refused: existing binding is incomplete or invalid"
        ) from error
    if accepted != binding:
        raise RuntimeError(
            "InvariantViolation: producer is bound to a different full request"
        )
    return True


def _draft_receipt(record: ArtifactRecord, edits_applied: int) -> ArtifactWriteReceipt:
    return ArtifactWriteReceipt(
        resource_ref=record.resource_ref,
        filename=record.filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        content_digest=record.content_digest,
        source_artifact_refs=record.source_artifact_refs,
        edits_applied=edits_applied,
    )


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _stored_artifact(record: ArtifactRecord, path: Path) -> StoredArtifact:
    return StoredArtifact(
        resource_ref=record.resource_ref,
        filename=record.filename,
        content_type=record.content_type,
        source_type=record.source_type,
        size_bytes=record.size_bytes,
        storage_path=path,
    )


__all__ = ["ArtifactService", "StoredArtifact"]
