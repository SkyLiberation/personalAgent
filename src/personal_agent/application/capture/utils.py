from __future__ import annotations

import logging
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException

TEXT_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".csv",
    ".tsv",
    ".log",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".html",
    ".css",
    ".sql",
    ".yaml",
    ".yml",
    ".xml",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}


def source_type_from_upload(filename: str, content_type: str | None) -> str:
    suffix = Path(filename).suffix.lower()
    mime = (content_type or "").lower()
    if suffix == ".pdf" or mime == "application/pdf":
        return "pdf"
    if suffix in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return "image"
    if suffix in AUDIO_EXTENSIONS or mime.startswith("audio/"):
        return "audio"
    return "note"


def normalize_upload_filename(filename: str) -> str:
    normalized_name = Path(filename).name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Missing file name.")
    return normalized_name


def validate_capture_url(raw_url: str) -> str:
    url = raw_url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Only http/https URLs are supported for link capture.")
    return url


def preprocess_uploaded_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r", "").split("\n")]
    filtered_lines: list[str] = []
    for line in lines:
        if not line:
            continue
        if line.startswith("*Exported from "):
            continue
        if line.startswith("**Date**:") or line.startswith("**Turns**:") or line.startswith("**Source**:"):
            continue
        if line.startswith("---"):
            continue
        filtered_lines.append(line)

    normalized = "\n".join(filtered_lines)
    normalized = normalized.replace("### 👤 User", "User")
    normalized = normalized.replace("### 🤖 Assistant", "Assistant")
    normalized = normalized.replace("## Turn 1", "")
    return normalized.strip()


def extract_pdf_text(file_bytes: bytes, logger: logging.Logger) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf is not installed; PDF upload will fall back to metadata-only capture.")
        return ""

    try:
        reader = PdfReader(BytesIO(file_bytes))
    except Exception:
        logger.exception("Failed to parse uploaded PDF.")
        return ""

    parts: list[str] = []
    for page in reader.pages[:20]:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            logger.exception("Failed to extract text from PDF page.")
            continue
        cleaned = " ".join(page_text.split())
        if cleaned:
            parts.append(cleaned)
        if sum(len(part) for part in parts) >= 12000:
            break
    return "\n".join(parts).strip()


def extract_html_text(html: str) -> str:
    parser = ReadableHtmlParser()
    parser.feed(html)
    parser.close()
    lines = [line.strip() for line in parser.text_parts if line.strip()]
    deduped: list[str] = []
    for line in lines:
        if line not in deduped:
            deduped.append(line)
    return "\n".join(deduped)


class ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self._ignored_stack: list[str] = []
        self._block_tags = {
            "article",
            "br",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "footer",
            "li",
            "main",
            "p",
            "section",
            "title",
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored_stack.append(tag)
            return
        if tag in self._block_tags:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_stack and self._ignored_stack[-1] == tag:
            self._ignored_stack.pop()
            return
        if tag in self._block_tags:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_stack:
            return
        compact = " ".join(data.split())
        if compact:
            self.text_parts.append(compact)
