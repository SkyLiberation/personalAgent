"""Unstructured-backed document partitioning and chunking.

Capture treats Unstructured as the source of truth for document structure:
source text is first partitioned into typed elements (Title, NarrativeText,
ListItem, Table, ...), then chunked by element/title boundaries for RAG.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from personal_agent.core.models import ChunkDraft

MAX_CHUNK_CHARS = 4000
SOFT_CHUNK_CHARS = 3000
COMBINE_UNDER_CHARS = 500
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


def partition_to_chunk_drafts(
    content: str,
    *,
    source_type: str = "text",
    source_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[ChunkDraft]:
    """Partition raw content and return structure-aware chunk drafts.

    The returned chunks are built from Unstructured elements, carrying page,
    title-path, category and original element ids where available. Short
    documents may return a single draft; callers decide whether to materialize
    child notes for single-draft documents.
    """
    text = content.strip()
    source_path = Path(source_ref) if source_ref else None
    has_source_file = bool(source_path and source_path.exists() and source_path.is_file())
    if not text and not has_source_file:
        return [
            ChunkDraft(
                title="空内容",
                content=content,
                source_span="",
                category="Empty",
            )
        ]

    elements = _partition_elements(text, source_type=source_type, source_ref=source_ref, metadata=metadata)
    if not elements:
        return [
            ChunkDraft(
                title=_derive_title(text),
                content=text,
                source_span="document",
                category="Text",
            )
        ]

    chunks = _chunk_elements(elements)
    if not chunks:
        chunks = elements

    drafts = [_draft_from_chunk(chunk, index=i) for i, chunk in enumerate(chunks, 1)]
    return [draft for draft in drafts if draft.content.strip()]


def _partition_elements(
    text: str,
    *,
    source_type: str,
    source_ref: str | None,
    metadata: dict[str, Any] | None,
) -> list[Any]:
    try:
        from unstructured.partition.auto import partition
        from unstructured.partition.md import partition_md
        from unstructured.partition.text import partition_text
    except ImportError as exc:  # pragma: no cover - dependency install guard
        raise RuntimeError(
            "unstructured is required for capture partitioning. "
            "Install project dependencies with the unstructured extras."
        ) from exc

    if source_ref:
        path = Path(source_ref)
        if path.exists() and path.is_file():
            suffix = path.suffix.lower()
            if suffix in {".md", ".markdown"}:
                try:
                    file_text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    file_text = path.read_text(encoding="utf-8", errors="replace")
                return list(partition_md(text=file_text))
            if suffix in TEXT_FILE_EXTENSIONS:
                try:
                    file_text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    file_text = path.read_text(encoding="utf-8", errors="replace")
                return list(partition_text(text=file_text))
            return list(partition(filename=str(path)))

    # Text/link captures still arrive as normalized text. Source refs, URLs and
    # file metadata are carried by NoteSource; Unstructured owns structure here.
    return list(partition_text(text=text))


def _chunk_elements(elements: list[Any]) -> list[Any]:
    try:
        from unstructured.chunking.title import chunk_by_title
    except ImportError as exc:  # pragma: no cover - dependency install guard
        raise RuntimeError(
            "unstructured chunking is required for capture chunking."
        ) from exc

    return list(
        chunk_by_title(
            elements,
            max_characters=MAX_CHUNK_CHARS,
            new_after_n_chars=SOFT_CHUNK_CHARS,
            combine_text_under_n_chars=COMBINE_UNDER_CHARS,
            multipage_sections=True,
        )
    )


def _draft_from_chunk(chunk: Any, *, index: int) -> ChunkDraft:
    text = str(chunk).strip()
    metadata = _metadata_dict(chunk)
    orig_elements = _orig_elements(chunk)
    element_ids = [_element_id(element) for element in orig_elements]
    element_ids = [value for value in element_ids if value]
    categories = [_category(element) for element in orig_elements] or [_category(chunk)]
    page_number = _page_number(metadata, orig_elements)
    title_path = _title_path(metadata, orig_elements)
    coordinates = _coordinates(metadata, orig_elements)
    source_span = _source_span(index, page_number, title_path, element_ids, categories)
    title = _chunk_title(text, title_path, metadata)
    draft_metadata = {
        **metadata,
        "unstructured_category": _category(chunk),
        "unstructured_element_categories": categories,
        "unstructured_element_ids": element_ids,
        "title_path": title_path,
    }
    if page_number is not None:
        draft_metadata["page_number"] = page_number
    if coordinates is not None:
        draft_metadata["coordinates"] = coordinates
    return ChunkDraft(
        title=title,
        content=text,
        source_span=source_span,
        title_path=title_path,
        page_number=page_number,
        element_ids=element_ids,
        coordinates=coordinates,
        category=_category(chunk),
        metadata=_jsonable(draft_metadata),
    )


def _metadata_dict(element: Any) -> dict[str, Any]:
    raw = getattr(element, "metadata", None)
    if raw is None:
        return {}
    if hasattr(raw, "to_dict"):
        data = raw.to_dict()
    elif isinstance(raw, dict):
        data = raw
    else:
        data = {}
    return _jsonable(data)


def _orig_elements(chunk: Any) -> list[Any]:
    metadata = getattr(chunk, "metadata", None)
    elements = getattr(metadata, "orig_elements", None)
    if not elements:
        return []
    return list(elements)


def _element_id(element: Any) -> str:
    for attr in ("id", "element_id"):
        value = getattr(element, attr, None)
        if value:
            return str(value)
    metadata = _metadata_dict(element)
    value = metadata.get("element_id")
    return str(value) if value else ""


def _category(element: Any) -> str:
    value = getattr(element, "category", None)
    return str(value or element.__class__.__name__)


def _page_number(metadata: dict[str, Any], elements: list[Any]) -> int | None:
    value = metadata.get("page_number")
    if isinstance(value, int):
        return value
    for element in elements:
        element_value = _metadata_dict(element).get("page_number")
        if isinstance(element_value, int):
            return element_value
    return None


def _coordinates(metadata: dict[str, Any], elements: list[Any]) -> dict[str, Any] | None:
    """First available bounding box across the chunk's elements.

    Unstructured exposes ``metadata.coordinates`` with ``points`` and a
    ``system`` for layout-aware sources (PDF/image). Kept so a citation can
    point at the exact region of the source page, not just the page number.
    """
    def _extract(meta: dict[str, Any]) -> dict[str, Any] | None:
        coords = meta.get("coordinates")
        if isinstance(coords, dict) and coords.get("points"):
            return {
                "points": _jsonable(coords.get("points")),
                "system": coords.get("system"),
                "layout_width": coords.get("layout_width"),
                "layout_height": coords.get("layout_height"),
            }
        return None

    direct = _extract(metadata)
    if direct is not None:
        return direct
    for element in elements:
        found = _extract(_metadata_dict(element))
        if found is not None:
            return found
    return None


def _title_path(metadata: dict[str, Any], elements: list[Any]) -> list[str]:
    candidates = metadata.get("section") or metadata.get("title_path")
    if isinstance(candidates, list):
        return [str(item) for item in candidates if str(item).strip()]
    if isinstance(candidates, str) and candidates.strip():
        return [part.strip() for part in candidates.split("/") if part.strip()]

    titles: list[str] = []
    for element in elements:
        if _category(element) == "Title":
            title = str(element).strip()
            if title and title not in titles:
                titles.append(title)
    return titles[-3:]


def _source_span(
    index: int,
    page_number: int | None,
    title_path: list[str],
    element_ids: list[str],
    categories: list[str],
) -> str:
    parts = [f"chunk {index}"]
    if page_number is not None:
        parts.append(f"page {page_number}")
    if title_path:
        parts.append(" > ".join(title_path))
    if element_ids:
        parts.append(f"elements {element_ids[0]}..{element_ids[-1]}")
    elif categories:
        parts.append("/".join(categories[:4]))
    return " | ".join(parts)


def _chunk_title(text: str, title_path: list[str], metadata: dict[str, Any]) -> str:
    title_path = [title for title in title_path if not _looks_garbled(title)]
    if title_path:
        return title_path[-1][:80]
    for key in ("title", "filename", "file_name"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return _derive_title(text)[:80]


def _looks_garbled(value: str) -> bool:
    if not value:
        return False
    chars = [ch for ch in value if not ch.isspace()]
    if not chars:
        return False
    hangul = sum(1 for ch in chars if "\uac00" <= ch <= "\ud7af")
    cjk = sum(1 for ch in chars if "\u3400" <= ch <= "\u9fff")
    ascii_letters = sum(1 for ch in chars if ch.isascii() and ch.isalpha())
    # Chinese markdown text can be misread as short Hangul strings by some
    # partition paths. Treat Hangul-only short titles as unreliable.
    return hangul >= 2 and cjk == 0 and ascii_letters == 0 and len(chars) <= 12


def _derive_title(content: str) -> str:
    stripped = content.strip()
    for line in stripped.splitlines():
        clean = line.strip()
        if clean:
            return clean[:80] + ("..." if len(clean) > 80 else "")
    return "Untitled chunk"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)
