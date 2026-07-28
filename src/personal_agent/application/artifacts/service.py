from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from personal_agent.application.capture.utils import (
    TEXT_FILE_EXTENSIONS,
    extract_pdf_text,
    normalize_upload_filename,
    preprocess_uploaded_text,
    source_type_from_upload,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.resource import (
    GeneratedArtifactContent,
    ResourceEvidenceRef,
    ResourceRef,
)
from personal_agent.kernel.contracts.scope import (
    AuthenticatedPrincipal,
    ExecutionScope,
    SecurityScope,
)


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    resource_ref: ResourceRef
    filename: str
    content_type: str | None
    source_type: str
    size_bytes: int
    storage_path: Path


class ArtifactService:
    """Owns artifact identity and private storage location resolution."""

    def __init__(self, settings: Settings, logger: logging.Logger | None = None) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)

    def save_upload(
        self,
        *,
        filename: str,
        content_type: str | None,
        file_bytes: bytes,
        uploads_dir: Path,
        principal: AuthenticatedPrincipal,
        security_scope: SecurityScope,
    ) -> ResourceRef:
        _authorize_principal(principal, security_scope)
        normalized = normalize_upload_filename(filename)
        artifact_id = _artifact_id(normalized, file_bytes)
        resource_ref = ResourceRef(
            resource_id=artifact_id,
            resource_type="artifact",
            owner_scope=security_scope,
        )
        uploads_dir.mkdir(parents=True, exist_ok=True)
        stored_path = uploads_dir / f"{artifact_id}_{normalized}"
        temp_path = uploads_dir / f".{artifact_id}.uploading"
        temp_path.write_bytes(file_bytes)
        os.replace(temp_path, stored_path)
        record = {
            "resource_ref": resource_ref.model_dump(mode="json"),
            "filename": normalized,
            "content_type": content_type,
            "source_type": source_type_from_upload(normalized, content_type),
            "size_bytes": len(file_bytes),
            "storage_name": stored_path.name,
            "created_by_principal_id": principal.principal_id,
            "artifact_kind": "upload",
        }
        sidecar = uploads_dir / f"{artifact_id}.json"
        sidecar_tmp = uploads_dir / f".{artifact_id}.json.tmp"
        sidecar_tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(sidecar_tmp, sidecar)
        return resource_ref

    def resolve(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        security_scope: SecurityScope,
    ) -> StoredArtifact:
        if resource_ref.resource_type != "artifact":
            raise ValueError("resource_ref is not an artifact")
        _authorize_principal(principal, security_scope)
        if resource_ref.owner_scope != security_scope:
            raise PermissionError("artifact belongs to a different security scope")
        sidecar = self._sidecar(resource_ref.resource_id)
        if not sidecar.exists():
            raise FileNotFoundError(f"Artifact does not exist: {resource_ref.resource_id}")
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        stored_ref = ResourceRef.model_validate(payload["resource_ref"])
        if stored_ref != resource_ref:
            raise PermissionError("artifact reference does not match its canonical record")
        if payload.get("created_by_principal_id") != principal.principal_id:
            raise PermissionError("artifact principal is not authorized")
        storage_path = sidecar.parent / str(payload["storage_name"])
        if not storage_path.exists():
            raise FileNotFoundError(f"Artifact content is missing: {resource_ref.resource_id}")
        return StoredArtifact(
            resource_ref=stored_ref,
            filename=str(payload["filename"]),
            content_type=payload.get("content_type"),
            source_type=str(payload["source_type"]),
            size_bytes=int(payload["size_bytes"]),
            storage_path=storage_path,
        )

    def read_upload(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        security_scope: SecurityScope,
    ) -> tuple[StoredArtifact, bytes]:
        record = self.resolve(
            resource_ref,
            principal=principal,
            security_scope=security_scope,
        )
        return record, record.storage_path.read_bytes()

    def read_text(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        security_scope: SecurityScope,
    ) -> str:
        """Read a text artifact through the canonical owner and scope checks."""

        record = self.resolve(
            resource_ref,
            principal=principal,
            security_scope=security_scope,
        )
        if record.source_type != "generated" and not (
            record.content_type or ""
        ).startswith("text/"):
            raise ValueError("artifact is not a directly readable text artifact")
        return record.storage_path.read_text(encoding="utf-8")

    def inspect_upload(
        self,
        *,
        resource_ref: ResourceRef,
        principal: AuthenticatedPrincipal,
        security_scope: SecurityScope,
        question: str = "",
    ) -> dict[str, Any]:
        record, file_bytes = self.read_upload(
            resource_ref,
            principal=principal,
            security_scope=security_scope,
        )
        text = self._interpret_bytes(
            filename=record.filename,
            content_type=record.content_type,
            source_type=record.source_type,
            file_bytes=file_bytes,
            question=question,
        )
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        evidence_ref = ResourceEvidenceRef(
            evidence_ref=f"ev_{content_hash[:16]}",
            resource_ref=resource_ref,
            locator="extracted-text:0",
            content_hash=content_hash,
        )
        return {
            "resource_ref": resource_ref.model_dump(mode="json"),
            "filename": record.filename,
            "content_type": record.content_type,
            "source_type": record.source_type,
            "size_bytes": len(file_bytes),
            "text": text,
            "evidence_refs": [evidence_ref.model_dump(mode="json")],
        }

    def write_generated(
        self,
        *,
        security_scope: SecurityScope,
        execution_scope: ExecutionScope,
        producer_key: str,
        producer_ref: str,
        kind: str,
        content: str,
        content_digest: str,
        source_artifact_refs: tuple[ResourceRef, ...],
        evidence_refs: tuple[str, ...],
    ) -> ResourceRef:
        if execution_scope.security_scope != security_scope:
            raise PermissionError("generated artifact execution scope mismatch")
        actual_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        accepted_digests = {
            actual_digest,
            hashlib.sha256(
                json.dumps(
                    {"content": content},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
        if content_digest not in accepted_digests:
            raise ValueError("generated artifact content digest mismatch")
        for source_ref in source_artifact_refs:
            if source_ref.owner_scope != security_scope:
                raise PermissionError("generated artifact source is cross-scope")
        root = self.settings.data_dir / "generated_artifacts"
        root.mkdir(parents=True, exist_ok=True)
        producer_hash = hashlib.sha256(producer_key.encode("utf-8")).hexdigest()
        producer_sidecar = root / f"producer_{producer_hash}.json"
        if producer_sidecar.exists():
            existing = json.loads(producer_sidecar.read_text(encoding="utf-8"))
            if (
                existing.get("producer_key") != producer_key
                or existing.get("content_digest") != content_digest
            ):
                raise RuntimeError(
                    "InvariantViolation: producer key is bound to different content"
                )
            return ResourceRef.model_validate(existing["resource_ref"])
        identity_material = "\0".join((
            security_scope.tenant_id,
            security_scope.workspace_id,
            producer_key,
            content_digest,
        ))
        identity_digest = hashlib.sha256(identity_material.encode("utf-8")).hexdigest()
        artifact_id = f"artg_{identity_digest[:20]}"
        resource_ref = ResourceRef(
            resource_id=artifact_id,
            resource_type="artifact",
            owner_scope=security_scope,
        )
        content_path = root / f"{artifact_id}.txt"
        content_tmp = root / f".{artifact_id}.txt.tmp"
        content_tmp.write_text(content, encoding="utf-8")
        os.replace(content_tmp, content_path)
        record = {
            "resource_ref": resource_ref.model_dump(mode="json"),
            "filename": f"{kind}.md",
            "content_type": "text/markdown",
            "source_type": "generated",
            "size_bytes": len(content.encode("utf-8")),
            "storage_name": content_path.name,
            "created_by_principal_id": execution_scope.principal_id,
            "artifact_kind": kind,
            "producer_key": producer_key,
            "producer_ref": producer_ref,
            "content_digest": content_digest,
            "source_artifact_refs": [
                item.model_dump(mode="json") for item in source_artifact_refs
            ],
            "evidence_refs": list(evidence_refs),
        }
        artifact_sidecar = root / f"{artifact_id}.json"
        artifact_tmp = root / f".{artifact_id}.json.tmp"
        artifact_tmp.write_text(
            json.dumps(record, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(artifact_tmp, artifact_sidecar)
        producer_tmp = root / f".producer_{producer_hash}.json.tmp"
        producer_tmp.write_text(
            json.dumps(record, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            os.replace(producer_tmp, producer_sidecar)
        except Exception:
            producer_tmp.unlink(missing_ok=True)
            raise
        return resource_ref

    def read_generated(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        security_scope: SecurityScope,
    ) -> GeneratedArtifactContent:
        record = self.resolve(
            resource_ref,
            principal=principal,
            security_scope=security_scope,
        )
        if record.source_type != "generated":
            raise ValueError("artifact is not generated content")
        payload = json.loads(
            self._sidecar(resource_ref.resource_id).read_text(encoding="utf-8")
        )
        return GeneratedArtifactContent(
            content=record.storage_path.read_text(encoding="utf-8"),
            content_digest=str(payload["content_digest"]),
            evidence_refs=tuple(payload.get("evidence_refs") or ()),
            limitations=tuple(payload.get("limitations") or ()),
        )

    def _sidecar(self, artifact_id: str) -> Path:
        candidates = (
            self.settings.data_dir / "uploads" / f"{artifact_id}.json",
            self.settings.data_dir / "generated_artifacts" / f"{artifact_id}.json",
        )
        return next((item for item in candidates if item.exists()), candidates[0])

    def _interpret_bytes(self, *, filename, content_type, source_type, file_bytes, question) -> str:
        suffix = Path(filename).suffix.lower()
        mime = (content_type or "").lower()
        if suffix in TEXT_FILE_EXTENSIONS or mime.startswith("text/") or mime in {"application/json", "application/xml"}:
            text = preprocess_uploaded_text(file_bytes.decode("utf-8", errors="replace").strip())
            if text:
                return f"Uploaded text artifact: {filename}\n\n{text[:12000]}"
        if source_type == "pdf":
            text = extract_pdf_text(file_bytes, self.logger)
            if text:
                return f"Uploaded PDF artifact: {filename}\n\n{text[:12000]}"
        if source_type == "image":
            return self._describe_image(filename=filename, content_type=content_type, file_bytes=file_bytes, question=question)
        if source_type == "audio":
            return self._transcribe_audio(filename=filename, content_type=content_type, file_bytes=file_bytes)
        return _metadata_only_context(filename, content_type, source_type, len(file_bytes))

    def _describe_image(self, *, filename, content_type, file_bytes, question) -> str:
        model = self.settings.openai.vision_model or self.settings.openai.model
        if not (self.settings.openai.api_key and self.settings.openai.base_url and model):
            return _metadata_only_context(filename, content_type, "image", len(file_bytes))
        mime = content_type or mimetypes.guess_type(filename)[0] or "image/png"
        encoded = base64.b64encode(file_bytes).decode("ascii")
        prompt = "客观描述附件可见内容并回答用户问题；不要声称已保存。\n用户请求：" + (question or "请概述图片内容")
        try:
            client = OpenAI(api_key=self.settings.openai.api_key, base_url=self.settings.openai.base_url, timeout=self.settings.openai.timeout_seconds, max_retries=self.settings.openai.max_retries)
            response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}]}], max_tokens=900)
            content = (response.choices[0].message.content or "").strip()
            if content:
                return f"Uploaded image artifact: {filename}\n\n{content}"
        except Exception:
            self.logger.exception("Failed to describe uploaded image artifact")
        return _metadata_only_context(filename, content_type, "image", len(file_bytes))

    def _transcribe_audio(self, *, filename, content_type, file_bytes) -> str:
        model = self.settings.openai.transcription_model
        if not (self.settings.openai.api_key and self.settings.openai.base_url and model):
            return _metadata_only_context(filename, content_type, "audio", len(file_bytes))
        try:
            client = OpenAI(api_key=self.settings.openai.api_key, base_url=self.settings.openai.base_url, timeout=self.settings.openai.timeout_seconds, max_retries=self.settings.openai.max_retries)
            audio_file = BytesIO(file_bytes)
            audio_file.name = filename
            response = client.audio.transcriptions.create(model=model, file=audio_file)
            text = str(getattr(response, "text", "") or "").strip()
            if text:
                return f"Uploaded audio artifact: {filename}\n\nTranscript:\n{text[:12000]}"
        except Exception:
            self.logger.exception("Failed to transcribe uploaded audio artifact")
        return _metadata_only_context(filename, content_type, "audio", len(file_bytes))


def _artifact_id(filename: str, file_bytes: bytes) -> str:
    digest = hashlib.sha256(filename.encode("utf-8") + b"\0" + file_bytes).hexdigest()
    return f"art_{digest[:16]}"


def _metadata_only_context(filename: str, content_type: str | None, source_type: str, size_bytes: int) -> str:
    size_kb = max(1, size_bytes // 1024) if size_bytes else 0
    return f"Uploaded artifact: {filename}\nSource type: {source_type}\nMedia type: {content_type or 'unknown'}\nSize: {size_kb} KB\n\nThe artifact is available, but automatic content interpretation did not produce text."


def _authorize_principal(
    principal: AuthenticatedPrincipal,
    security_scope: SecurityScope,
) -> None:
    if principal.tenant_id != security_scope.tenant_id:
        raise PermissionError("principal tenant does not match security scope")


__all__ = ["ArtifactService", "StoredArtifact"]
