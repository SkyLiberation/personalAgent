"""Locate matches in the canonical plain-text body without selecting evidence."""

from __future__ import annotations

from bisect import bisect_right
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.application.artifacts.models import (
    ArtifactTextSnapshot,
    ContentDigest,
    TextPosition,
)
from personal_agent.application.artifacts.text_coordinates import TextCoordinates
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .observation_bounds import MAX_OBSERVATION_PAYLOAD_CHARS, serialized_length
from .source_reading import ReturnedSourceLine


class TextMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class ArtifactSearchPort(Protocol):
    def find(
        self, text: str, *, keyword: str, regex: bool
    ) -> tuple[TextMatch, ...]: ...


class SearchActionOutputArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_id: str = Field(min_length=1, description="当前可读文件的resource_id，来自材料或成功工具结果。")
    keyword: str = Field(
        min_length=1, max_length=400, description="搜索正文的字面词或正则表达式。"
    )
    regex: bool = Field(
        default=False, description="默认字面匹配；为 true 时使用 ripgrep 正则。"
    )
    result_offset: int = Field(
        default=0,
        ge=0,
        description="搜索结果分页偏移；续页原样使用 next_offset，不是文件行号。",
    )


class SourceSearchResult(SearchActionOutputArguments):
    resource_ref: ResourceRef
    content_digest: ContentDigest
    eof_position: TextPosition
    lines: tuple[ReturnedSourceLine, ...]
    total_lines: int
    matched_record_count: int
    next_offset: int | None
    explanation: str = Field(
        default_factory=lambda: DEFAULT_PROMPTS.render("conversation.search.explanation")
    )


def search_artifact_text(
    snapshot: ArtifactTextSnapshot,
    *,
    arguments: SearchActionOutputArguments,
    matcher: ArtifactSearchPort,
    max_chars: int = MAX_OBSERVATION_PAYLOAD_CHARS,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> SourceSearchResult:
    if snapshot.resource_ref.resource_id != arguments.resource_id:
        raise ValueError(prompts.render("conversation.search.snapshot_mismatch"))
    text = snapshot.content
    coordinates = TextCoordinates(text)
    records = [line.text for line in coordinates.lines]
    boundaries = [0]
    for line in coordinates.lines:
        boundaries.append(
            boundaries[-1] + len((line.text + line.line_ending).encode("utf-8"))
        )
    body = text
    match_columns: dict[int, int] = {}
    hits: set[int] = set()
    for match in matcher.find(body, keyword=arguments.keyword, regex=arguments.regex):
        if not 0 <= match.start <= match.end <= boundaries[-1]:
            raise ValueError(prompts.render("conversation.search.match_out_of_bounds"))
        if match.start == boundaries[-1]:
            continue
        first = bisect_right(boundaries, match.start)
        last = bisect_right(boundaries, max(match.start, match.end - 1))
        hits.update(range(first, last + 1))
        for number in range(first, last + 1):
            if number not in match_columns:
                local = max(0, match.start - boundaries[number - 1])
                prefix = records[number - 1].encode("utf-8")[:local].decode("utf-8")
                match_columns[number] = len(prefix)
    ordered = sorted(hits)
    if arguments.result_offset > len(ordered):
        raise ValueError(prompts.render("conversation.search.offset_out_of_bounds"))
    selected: list[ReturnedSourceLine] = []
    result = SourceSearchResult(
        **arguments.model_dump(),
        resource_ref=snapshot.resource_ref,
        lines=(),
        content_digest=snapshot.content_digest,
        eof_position=snapshot.eof_position,
        total_lines=len(records),
        matched_record_count=len(ordered),
        next_offset=None,
        explanation=prompts.render("conversation.search.explanation"),
    )
    for number in ordered[arguments.result_offset :]:
        original = records[number - 1]
        start = max(0, match_columns[number] - 160) if len(original) > 2000 else 0
        line = ReturnedSourceLine(
            line=number,
            text=original[start : start + 2000],
            start_column=start + 1,
            line_length=len(original),
        )
        candidate = result.model_copy(
            update={"lines": tuple([*selected, line]), "next_offset": len(ordered)}
        )
        if (
            serialized_length({"ok": True, **candidate.model_dump(mode="json")})
            > max_chars
        ):
            if not selected:
                raise ValueError(
                    prompts.render("conversation.search.record_capacity_exceeded")
                )
            break
        selected.append(line)
    after = arguments.result_offset + len(selected)
    return result.model_copy(
        update={
            "lines": tuple(selected),
            "next_offset": after if after < len(ordered) else None,
        }
    )
