from __future__ import annotations

import base64
import hashlib
import logging
from io import BytesIO
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
from personal_agent.kernel.models import ArtifactRef


class ArtifactService:
    """Stores and interprets user artifacts without implying knowledge capture."""

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
    ) -> ArtifactRef:
        normalized = normalize_upload_filename(filename)
        artifact_id = _artifact_id(normalized, file_bytes)
        stored_path = uploads_dir / f"{artifact_id}_{normalized}"
        stored_path.write_bytes(file_bytes)
        return ArtifactRef(
            artifact_id=artifact_id,
            filename=normalized,
            content_type=content_type,
            source_type=source_type_from_upload(normalized, content_type),
            file_path=str(stored_path),
            size_bytes=len(file_bytes),
        )

    def inspect_upload(
        self,
        *,
        file_path: str,
        filename: str,
        content_type: str | None = None,
        source_type: str | None = None,
        question: str = "",
    ) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Artifact file does not exist: {file_path}")
        file_bytes = path.read_bytes()
        resolved_source_type = source_type or source_type_from_upload(filename, content_type)
        text = self._interpret_bytes(
            filename=filename,
            content_type=content_type,
            source_type=resolved_source_type,
            file_bytes=file_bytes,
            question=question,
        )
        return {
            "filename": filename,
            "content_type": content_type,
            "source_type": resolved_source_type,
            "size_bytes": len(file_bytes),
            "text": text,
        }

    def _interpret_bytes(
        self,
        *,
        filename: str,
        content_type: str | None,
        source_type: str,
        file_bytes: bytes,
        question: str,
    ) -> str:
        suffix = Path(filename).suffix.lower()
        mime = (content_type or "").lower()
        if suffix in TEXT_FILE_EXTENSIONS or mime.startswith("text/") or mime in {
            "application/json",
            "application/xml",
        }:
            text = preprocess_uploaded_text(file_bytes.decode("utf-8", errors="replace").strip())
            if text:
                return f"Uploaded text artifact: {filename}\n\n{text[:12000]}"

        if source_type == "pdf":
            text = extract_pdf_text(file_bytes, self.logger)
            if text:
                return f"Uploaded PDF artifact: {filename}\n\n{text[:12000]}"

        if source_type == "image":
            return self._describe_image(
                filename=filename,
                content_type=content_type,
                file_bytes=file_bytes,
                question=question,
            )

        if source_type == "audio":
            return self._transcribe_audio(
                filename=filename,
                content_type=content_type,
                file_bytes=file_bytes,
            )

        return _metadata_only_context(filename, content_type, source_type, len(file_bytes))

    def _describe_image(
        self,
        *,
        filename: str,
        content_type: str | None,
        file_bytes: bytes,
        question: str,
    ) -> str:
        model = self.settings.openai.vision_model or self.settings.openai.model
        if not (self.settings.openai.api_key and self.settings.openai.base_url and model):
            return _metadata_only_context(filename, content_type, "image", len(file_bytes))
        mime = content_type or "image/png"
        encoded = base64.b64encode(file_bytes).decode("ascii")
        prompt = (
            "请理解这张用户上传的图片。先客观描述可见内容；"
            "如果用户请求中有问题，请围绕问题回答。不要声称已经把内容保存到知识库。\n"
            f"用户请求：{question or '请概述图片内容'}"
        )
        try:
            client = OpenAI(
                api_key=self.settings.openai.api_key,
                base_url=self.settings.openai.base_url,
                timeout=self.settings.openai.timeout_seconds,
                max_retries=self.settings.openai.max_retries,
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{encoded}"},
                        },
                    ],
                }],
                max_tokens=900,
            )
            content = (response.choices[0].message.content or "").strip()
            if content:
                return f"Uploaded image artifact: {filename}\n\n{content}"
        except Exception:
            self.logger.exception("Failed to describe uploaded image artifact")
        return _metadata_only_context(filename, content_type, "image", len(file_bytes))

    def _transcribe_audio(
        self,
        *,
        filename: str,
        content_type: str | None,
        file_bytes: bytes,
    ) -> str:
        model = self.settings.openai.transcription_model
        if not (self.settings.openai.api_key and self.settings.openai.base_url and model):
            return _metadata_only_context(filename, content_type, "audio", len(file_bytes))
        try:
            client = OpenAI(
                api_key=self.settings.openai.api_key,
                base_url=self.settings.openai.base_url,
                timeout=self.settings.openai.timeout_seconds,
                max_retries=self.settings.openai.max_retries,
            )
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


def _metadata_only_context(
    filename: str,
    content_type: str | None,
    source_type: str,
    size_bytes: int,
) -> str:
    size_kb = max(1, size_bytes // 1024) if size_bytes else 0
    return (
        f"Uploaded artifact: {filename}\n"
        f"Source type: {source_type}\n"
        f"Media type: {content_type or 'unknown'}\n"
        f"Size: {size_kb} KB\n\n"
        "The artifact is available, but automatic content interpretation did not produce text."
    )
