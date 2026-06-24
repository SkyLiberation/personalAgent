"""Source provenance extraction for the capture pipeline.

Derives author / published_at / doc_type / language from source metadata and
light content signals, so ask-side filtering and freshness judgement have
structured provenance instead of guessing from capture time.

The default extractor is deterministic and heuristic (no LLM), matching the
capture pipeline's no-LLM philosophy. ``ProvenanceExtractor`` is a Protocol so
a model-backed extractor (which can read author/date out of free-form prose)
can be plugged in later without touching the pipeline.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

from personal_agent.core.models import NoteProvenance, RawIngestItem

# Maps file extension / source_type to a coarse doc_type.
_EXT_DOC_TYPE = {
    ".pdf": "pdf", ".doc": "word", ".docx": "word",
    ".md": "markdown", ".markdown": "markdown",
    ".html": "html", ".htm": "html",
    ".csv": "spreadsheet", ".tsv": "spreadsheet", ".xlsx": "spreadsheet",
    ".txt": "text", ".log": "text",
}
_SOURCE_TYPE_DOC_TYPE = {"link": "web", "pdf": "pdf", "file": "document", "text": "note"}

_ISO_DATE = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
_CJK = re.compile(r"[㐀-鿿぀-ヿ가-힯]")


class ProvenanceExtractor(Protocol):
    """Extracts :class:`NoteProvenance` from a raw ingest item."""

    def extract(self, raw_item: RawIngestItem) -> NoteProvenance:
        ...


class HeuristicProvenanceExtractor:
    """Deterministic provenance from metadata + filename + light content scan."""

    name = "heuristic"

    def extract(self, raw_item: RawIngestItem) -> NoteProvenance:
        metadata = dict(raw_item.metadata or {})
        return NoteProvenance(
            author=self._author(metadata),
            published_at=self._published_at(metadata, raw_item.content),
            doc_type=self._doc_type(metadata, raw_item),
            language=self._language(raw_item.content),
        )

    def _author(self, metadata: dict[str, Any]) -> str | None:
        for key in ("author", "creator", "by", "from"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:120]
        return None

    def _published_at(self, metadata: dict[str, Any], content: str) -> str | None:
        for key in ("published_at", "published", "date", "created", "created_at"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:40]
        match = _ISO_DATE.search(content[:500])
        if match:
            year, month, day = match.groups()
            return f"{year}-{int(month):02d}-{int(day):02d}"
        return None

    def _doc_type(self, metadata: dict[str, Any], raw_item: RawIngestItem) -> str | None:
        explicit = metadata.get("doc_type")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        ref = raw_item.source_ref or metadata.get("original_filename") or metadata.get("filename")
        if isinstance(ref, str) and ref.strip():
            suffix = Path(ref).suffix.lower()
            if suffix in _EXT_DOC_TYPE:
                return _EXT_DOC_TYPE[suffix]
        return _SOURCE_TYPE_DOC_TYPE.get(raw_item.source_type)

    def _language(self, content: str) -> str | None:
        sample = content[:1000]
        if not sample.strip():
            return None
        cjk = len(_CJK.findall(sample))
        ascii_alpha = sum(1 for ch in sample if ch.isascii() and ch.isalpha())
        if cjk == 0 and ascii_alpha == 0:
            return None
        return "zh" if cjk >= ascii_alpha else "en"
