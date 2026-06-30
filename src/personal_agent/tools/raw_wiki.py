from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.kernel.config_models import EnterpriseKnowledgeConfig
from personal_agent.tools.base import governance_extras, tool_response, tool_success

_TOKEN_RE = re.compile(r"[a-z0-9_+-]{2,}|[\u3400-\u9fff]{2,}", re.IGNORECASE)


class RawWikiSearchArgs(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)
    user_id: str = "default"
    run_id: str | None = None


def build_raw_wiki_search_tools(config: EnterpriseKnowledgeConfig) -> list[BaseTool]:
    tools: list[BaseTool] = []
    for root in config.raw_roots:
        resolved = Path(root).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            continue
        tools.append(build_raw_wiki_search_tool(resolved, config))
    return tools


def build_raw_wiki_search_tool(
    root: Path,
    config: EnterpriseKnowledgeConfig,
) -> BaseTool:
    tool_name = _tool_name_for_root(root)

    @tool(
        tool_name,
        description=f"Search Markdown documents under {root}.",
        args_schema=RawWikiSearchArgs,
        response_format="content_and_artifact",
        extras={
            **governance_extras(
                exposure="scoped_agent",
                side_effects=("read_longterm",),
                permission_scope="enterprise_knowledge:read",
                timeout_seconds=10,
                max_retries=0,
            ),
            "enterprise_knowledge": {
                "business_role": "enterprise_knowledge_search",
                "provider": "raw_wiki",
                "root": str(root),
            },
        },
    )
    def raw_wiki_search(
        query: str,
        limit: int = 5,
        user_id: str = "default",
        run_id: str | None = None,
    ):
        del user_id, run_id
        results = search_raw_wiki(
            root,
            query=query,
            limit=limit,
            file_globs=config.raw_file_globs,
            max_file_bytes=config.raw_max_file_bytes,
        )
        return tool_response(tool_success({
            "query": query,
            "results": results,
        }))

    return raw_wiki_search


def search_raw_wiki(
    root: Path,
    *,
    query: str,
    limit: int = 5,
    file_globs: tuple[str, ...] = ("*.md",),
    max_file_bytes: int = 2_000_000,
) -> list[dict[str, Any]]:
    query_terms = _terms(query)
    if not query_terms:
        return []
    candidates: list[dict[str, Any]] = []
    for path in _iter_files(root, file_globs):
        try:
            if path.stat().st_size > max_file_bytes:
                continue
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue
        score = _score_document(query_terms, path, text)
        if score <= 0:
            continue
        rel_path = path.relative_to(root).as_posix()
        candidates.append({
            "id": f"raw_wiki:{rel_path}",
            "title": path.stem,
            "content": _best_snippet(text, query_terms),
            "url": path.as_uri(),
            "path": str(path),
            "relative_path": rel_path,
            "score": round(score, 4),
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:limit]


def _iter_files(root: Path, globs: tuple[str, ...]):
    seen: set[Path] = set()
    for pattern in globs:
        for path in root.rglob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def _score_document(query_terms: set[str], path: Path, text: str) -> float:
    title = path.stem.lower()
    rel = str(path).lower()
    lowered = text.lower()
    score = 0.0
    for term in query_terms:
        if term in title:
            score += 4.0
        if term in rel:
            score += 1.5
        count = lowered.count(term)
        if count:
            score += min(6.0, 1.0 + count * 0.35)
    return score


def _best_snippet(text: str, query_terms: set[str], *, max_chars: int = 900) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= max_chars:
        return normalized
    lowered = normalized.lower()
    positions = [lowered.find(term) for term in query_terms if lowered.find(term) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - max_chars // 3)
    end = min(len(normalized), start + max_chars)
    return normalized[start:end].strip()


def _terms(text: str) -> set[str]:
    terms = {match.group(0).lower() for match in _TOKEN_RE.finditer(text)}
    cjk_runs = re.findall(r"[\u3400-\u9fff]{2,}", text)
    for run in cjk_runs:
        for size in (2, 3, 4):
            for index in range(0, max(0, len(run) - size + 1)):
                terms.add(run[index:index + size].lower())
    return terms


def _tool_name_for_root(root: Path) -> str:
    raw = re.sub(r"[^0-9a-zA-Z_]+", "_", root.name.lower()).strip("_")
    return f"enterprise.raw_wiki_{raw or 'docs'}"


__all__ = [
    "build_raw_wiki_search_tool",
    "build_raw_wiki_search_tools",
    "search_raw_wiki",
]
