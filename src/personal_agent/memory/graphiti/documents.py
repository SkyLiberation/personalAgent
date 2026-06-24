from __future__ import annotations

import re
from pathlib import Path

from personal_agent.kernel.projections import GraphIngestDocument

CONTENT_FILTER_ERROR_MARKERS = (
    "content filter",
    "content_filter",
    "filtered",
    "high risk",
    "高风险",
    "risk content",
    "sensitive",
    "safety",
)
MARKDOWN_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
MARKDOWN_TABLE_RULE_RE = re.compile(r"^\s*\|?[\s:\-]+(?:\|[\s:\-]+)+\|?\s*$")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
MARKDOWN_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_|`)")
MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
BLOCKQUOTE_RE = re.compile(r"^\s*>\s?")


def episode_uuids_from_search_result(search_result: object) -> list[str]:
    episode_uuids: list[str] = []
    for episode in getattr(search_result, "episodes", []) or []:
        uuid = getattr(episode, "uuid", None)
        if uuid and uuid not in episode_uuids:
            episode_uuids.append(uuid)
    return episode_uuids


def graphiti_episode_body(document: GraphIngestDocument, max_chars: int = 8000) -> str:
    content = document.content.strip()
    if not content:
        return content

    lines = content.replace("\r", "").split("\n")
    if lines and lines[0].startswith("Uploaded file: "):
        lines = lines[2:] if len(lines) > 1 and not lines[1].strip() else lines[1:]

    is_markdown = document.source_type == "note" and Path(
        document.source_ref
    ).suffix.lower() in {".md", ".markdown"}
    if not is_markdown:
        return content[:max_chars]

    cleaned_lines: list[str] = []
    pending_table: list[list[str]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if pending_table:
                cleaned_lines.extend(flatten_markdown_table(pending_table))
                pending_table = []
            continue
        if MARKDOWN_TABLE_RULE_RE.match(line):
            continue
        if MARKDOWN_TABLE_ROW_RE.match(line):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if any(cells):
                pending_table.append(cells)
            continue
        if pending_table:
            cleaned_lines.extend(flatten_markdown_table(pending_table))
            pending_table = []

        line = MARKDOWN_HEADING_RE.sub("", line)
        line = BLOCKQUOTE_RE.sub("", line)
        line = MARKDOWN_LINK_RE.sub(r"\1", line)
        line = MARKDOWN_EMPHASIS_RE.sub("", line)
        line = line.replace("→", "->")
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        cleaned_lines.append(line)

    if pending_table:
        cleaned_lines.extend(flatten_markdown_table(pending_table))

    compact = "\n".join(line for line in cleaned_lines if line).strip()
    return compact[:max_chars]


def graphiti_safe_episode_body(document: GraphIngestDocument) -> str:
    parts = [
        f"Title: {clean_safe_text(document.title, 240)}",
        f"Summary: {clean_safe_text(document.summary, 800)}",
    ]
    excerpt = clean_safe_text(document.content, 1200)
    if excerpt:
        parts.append(f"Excerpt: {excerpt}")
    return "\n".join(part for part in parts if part.strip())


def clean_safe_text(value: str, max_chars: int) -> str:
    text = value.replace("\r", " ").replace("\n", " ")
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    text = MARKDOWN_EMPHASIS_RE.sub("", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def looks_like_content_filter_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in CONTENT_FILTER_ERROR_MARKERS)


def flatten_markdown_table(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    header = rows[0]
    if len(rows) == 1:
        return [" | ".join(cell for cell in header if cell)]

    flattened: list[str] = []
    for row in rows[1:]:
        pairs = []
        for index, cell in enumerate(row):
            label = header[index] if index < len(header) else f"col{index + 1}"
            if cell:
                pairs.append(f"{label}: {cell}")
        if pairs:
            flattened.append("; ".join(pairs))
    return flattened


def dedupe(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def related_episode_ids_from_edges(
    edge_episode_lists: list[list[str]], exclude: set[str] | None = None
) -> list[str]:
    seen: list[str] = []
    blocked = exclude or set()
    for episode_ids in edge_episode_lists:
        for episode_id in episode_ids:
            if episode_id in blocked or episode_id in seen:
                continue
            seen.append(episode_id)
    return seen
