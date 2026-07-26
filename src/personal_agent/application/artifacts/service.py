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
from personal_agent.kernel.contracts.resource import ResourceEvidenceRef, ResourceRef


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
        user_id: str,
        workspace_id: str,
    ) -> ResourceRef:
        normalized = normalize_upload_filename(filename)
        artifact_id = _artifact_id(normalized, file_bytes)
        resource_ref = ResourceRef(
            resource_id=artifact_id,
            resource_type="artifact",
            workspace_id=workspace_id,
            user_id=user_id,
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
        }
        sidecar = uploads_dir / f"{artifact_id}.json"
        sidecar_tmp = uploads_dir / f".{artifact_id}.json.tmp"
        sidecar_tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(sidecar_tmp, sidecar)
        return resource_ref

    def resolve(self, resource_ref: ResourceRef, *, user_id: str) -> StoredArtifact:
        if resource_ref.resource_type != "artifact":
            raise ValueError("resource_ref is not an artifact")
        if resource_ref.user_id != user_id:
            raise PermissionError("artifact belongs to a different user scope")
        sidecar = self.settings.data_dir / "uploads" / f"{resource_ref.resource_id}.json"
        if not sidecar.exists():
            raise FileNotFoundError(f"Artifact does not exist: {resource_ref.resource_id}")
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        stored_ref = ResourceRef.model_validate(payload["resource_ref"])
        if stored_ref != resource_ref:
            raise PermissionError("artifact reference does not match its canonical record")
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

    def read_upload(self, resource_ref: ResourceRef, *, user_id: str) -> tuple[StoredArtifact, bytes]:
        record = self.resolve(resource_ref, user_id=user_id)
        return record, record.storage_path.read_bytes()

    def inspect_upload(
        self,
        *,
        resource_ref: ResourceRef,
        user_id: str,
        question: str = "",
    ) -> dict[str, Any]:
        record, file_bytes = self.read_upload(resource_ref, user_id=user_id)
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


__all__ = ["ArtifactService", "StoredArtifact"]
