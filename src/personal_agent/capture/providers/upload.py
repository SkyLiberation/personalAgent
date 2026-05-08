from __future__ import annotations

import logging
from pathlib import Path

from ..models import UploadCaptureRequest
from ..utils import TEXT_FILE_EXTENSIONS, extract_pdf_text, preprocess_uploaded_text
from .base import UploadCaptureProvider


class DefaultUploadCaptureProvider(UploadCaptureProvider):
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

    def capture(self, request: UploadCaptureRequest) -> str:
        suffix = Path(request.filename).suffix.lower()
        mime = (request.content_type or "").lower()

        if suffix in TEXT_FILE_EXTENSIONS or mime.startswith("text/") or mime in {
            "application/json",
            "application/xml",
        }:
            text_content = preprocess_uploaded_text(
                request.file_bytes.decode("utf-8", errors="replace").strip()
            )
            if text_content:
                return f"Uploaded file: {request.filename}\n\n{text_content[:12000]}"

        if suffix == ".pdf" or mime == "application/pdf":
            pdf_text = extract_pdf_text(request.file_bytes, self.logger)
            if pdf_text:
                return f"Uploaded PDF: {request.filename}\n\n{pdf_text[:12000]}"

        size_kb = max(1, len(request.file_bytes) // 1024) if request.file_bytes else 0
        return (
            f"Uploaded file: {request.filename}\n"
            f"Source type: {request.source_type}\n"
            f"Media type: {request.content_type or 'unknown'}\n"
            f"Size: {size_kb} KB\n\n"
            "This file was uploaded through the web UI. Automatic content extraction for this file type "
            "is not implemented yet, so the knowledge note currently stores file metadata only."
        )
