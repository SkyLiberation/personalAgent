"""Deterministic content chunking for long documents.

Splits long text into structured chunks suitable for independent
KnowledgeNote records. Markdown headings are preferred boundaries;
paragraph-based splitting is the fallback.

Short content (< 2000 chars) returns a single chunk to avoid
unnecessary fragmentation of brief notes.
"""

from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_PARAGRAPH_SPLIT_RE = re.compile(r"\n{2,}")
_SINGLE_NL_RE = re.compile(r"\n")

MIN_CHUNK_CHARS = 2000
MAX_CHUNK_CHARS = 4000


def chunk_content(content: str, source_type: str = "text") -> list[dict[str, str]]:
    """Split content into structured chunk dicts.

    Returns a list of dicts with 'title', 'content', and 'source_span' keys.
    Always returns at least one chunk.
    """
    if not content or not content.strip():
        return [{"title": "空内容", "content": content, "source_span": ""}]

    # 1. Try heading-based splitting for markdown content
    heading_chunks = _split_by_headings(content)
    if len(heading_chunks) > 1:
        return _finalize_chunks(heading_chunks)

    # 2. Fall back to paragraph-based splitting
    para_chunks = _split_by_paragraphs(content)
    if len(para_chunks) > 1:
        return _finalize_chunks(para_chunks)

    # 3. Single chunk — no splitting needed
    title = _derive_title(content)
    return [{"title": title, "content": content.strip(), "source_span": title}]


def _split_by_headings(content: str) -> list[dict[str, str]]:
    """Split content on markdown heading boundaries (##, ###, etc.)."""
    headings = list(_HEADING_RE.finditer(content))
    if not headings:
        return []

    chunks: list[dict[str, str]] = []

    # Text before the first heading becomes the preamble chunk
    first_heading_start = headings[0].start()
    if first_heading_start > 0:
        preamble = content[:first_heading_start].strip()
        if len(preamble) > 40:
            chunks.append({
                "title": _derive_title(preamble),
                "content": preamble,
                "source_span": "前言",
            })

    for i, match in enumerate(headings):
        level = len(match.group(1))
        heading_text = match.group(2).strip()
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
        body = content[start:end].strip()

        if not body:
            continue

        # Sub-split oversized sections
        if len(body) > MAX_CHUNK_CHARS:
            sub_chunks = _split_long_section(body, heading_text)
            chunks.extend(sub_chunks)
        else:
            chunks.append({
                "title": heading_text,
                "content": body,
                "source_span": f"{'#' * level} {heading_text}",
            })

    # If only a preamble (no body chunks), treat as single
    if not chunks:
        return []

    return chunks


def _split_by_paragraphs(content: str) -> list[dict[str, str]]:
    """Split content on double-newline paragraph boundaries."""
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(content) if p.strip()]
    if len(paragraphs) <= 1:
        return []

    chunks: list[dict[str, str]] = []
    buffer: list[str] = []
    buffer_len = 0

    for i, para in enumerate(paragraphs, 1):
        if buffer_len > 0 and buffer_len + len(para) > MAX_CHUNK_CHARS:
            chunks.append(_para_chunk(buffer, len(chunks) + 1, i - 1))
            buffer = []
            buffer_len = 0
        buffer.append(para)
        buffer_len += len(para)

    if buffer:
        chunks.append(_para_chunk(buffer, len(chunks) + 1, len(paragraphs)))

    if len(chunks) <= 1:
        return []

    return chunks


def _para_chunk(paragraphs: list[str], start_idx: int, end_idx: int) -> dict[str, str]:
    text = "\n\n".join(paragraphs)
    return {
        "title": _derive_title(text),
        "content": text,
        "source_span": f"paragraphs {start_idx}-{end_idx}",
    }


def _split_long_section(body: str, heading: str) -> list[dict[str, str]]:
    """Sub-split a very long section by single newlines."""
    lines = [l.strip() for l in _SINGLE_NL_RE.split(body) if l.strip()]
    if len(lines) <= 1:
        return [{"title": heading, "content": body, "source_span": f"## {heading}"}]

    chunks: list[dict[str, str]] = []
    buf: list[str] = []
    buf_len = 0
    part = 1

    for line in lines:
        if buf_len > 0 and buf_len + len(line) > MAX_CHUNK_CHARS:
            text = "\n".join(buf)
            chunks.append({
                "title": f"{heading}（{part}）",
                "content": text,
                "source_span": f"## {heading}（第{part}部分）",
            })
            buf = []
            buf_len = 0
            part += 1
        buf.append(line)
        buf_len += len(line)

    if buf:
        text = "\n".join(buf)
        label = f"{heading}（{part}）" if part > 1 else heading
        span = f"## {heading}（第{part}部分）" if part > 1 else f"## {heading}"
        chunks.append({"title": label, "content": text, "source_span": span})

    return chunks


def _derive_title(content: str) -> str:
    """Derive a short title from the beginning of content."""
    stripped = content.strip()
    # Try to use the first non-heading line
    for line in stripped.split("\n"):
        clean = line.strip()
        if clean and not clean.startswith("#"):
            return clean[:24] + ("..." if len(clean) > 24 else "")
    return stripped[:24] + ("..." if len(stripped) > 24 else "")


def _finalize_chunks(chunks: list[dict[str, str]]) -> list[dict[str, str]]:
    """Merge undersized chunks or return as-is."""
    if len(chunks) <= 1:
        return chunks

    merged: list[dict[str, str]] = []
    pending: dict[str, str] | None = None

    for ch in chunks:
        if pending is not None and len(pending["content"]) < MIN_CHUNK_CHARS:
            # Merge with previous undersized chunk
            pending["content"] = pending["content"] + "\n\n" + ch["content"]
            pending["source_span"] = (
                pending["source_span"] + "; " + ch["source_span"]
            )
            pending["title"] = _derive_title(pending["content"])
            if len(pending["content"]) >= MIN_CHUNK_CHARS:
                merged.append(pending)
                pending = None
        elif len(ch["content"]) < MIN_CHUNK_CHARS:
            pending = ch
        else:
            merged.append(ch)

    if pending is not None:
        if merged:
            # Append undersized tail to last chunk
            last = merged[-1]
            last["content"] = last["content"] + "\n\n" + pending["content"]
            last["source_span"] = last["source_span"] + "; " + pending["source_span"]
        else:
            merged.append(pending)

    return merged or chunks
