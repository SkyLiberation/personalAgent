"""Read bounded windows using the same natural line coordinates as artifact search."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.kernel.contracts.resource import ResourceRef

from .observation_bounds import MAX_OBSERVATION_PAYLOAD_CHARS, serialized_length
from .source_reading import ReturnedSourceLine, SourceReadWindow


class ReadArtifactArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_ref: ResourceRef
    start_line: int = Field(default=1, ge=1, description="正文起始行，1 起计，与搜索返回的 line 相同。")
    limit: int = Field(default=200, ge=1, le=2000, description="最多读取的行数；输出容量不足时返回续读位置。")
    start_column: int = Field(default=1, ge=1, description="通常省略；超长行续读时原样使用 next_read 中的值，按字符 1 起计。")


class ArtifactReadResult(SourceReadWindow):
    next_read: ReadArtifactArguments | None
    explanation: str = "line 是正文行号；只看见实际返回的文字。next_read 是可直接调用 read_artifact 的续读参数；读到末尾不等于此前各行均已读。"


def read_artifact_text(text: str, *, arguments: ReadArtifactArguments,
                       max_chars: int = MAX_OBSERVATION_PAYLOAD_CHARS) -> ArtifactReadResult:
    lines = text.splitlines()
    if arguments.start_line > len(lines) and (lines or arguments.start_line != 1):
        raise ValueError(f"start_line 超出正文范围，正文共 {len(lines)} 行。")
    result = ArtifactReadResult(resource_ref=arguments.resource_ref, total_lines=len(lines), lines=(), next_read=None)
    selected: list[ReturnedSourceLine] = []
    for number in range(arguments.start_line, min(len(lines), arguments.start_line + arguments.limit - 1) + 1):
        original = lines[number - 1]
        start = arguments.start_column - 1 if number == arguments.start_line else 0
        if start > len(original):
            raise ValueError("start_column 超出正文行长度。")

        def candidate(size: int) -> ArtifactReadResult:
            end = start + size
            more = end < len(original)
            next_read = arguments.model_copy(update={"start_line": number if more else number + 1,
                                                      "start_column": end + 1 if more else 1}) if more or number < len(lines) else None
            line = ReturnedSourceLine(line=number, text=original[start:end], start_column=start + 1, line_length=len(original))
            return result.model_copy(update={"lines": tuple([*selected, line]), "next_read": next_read})

        full = candidate(len(original) - start)
        if serialized_length({"ok": True, **full.model_dump(mode="json")}) <= max_chars:
            result = full
            selected = list(result.lines)
            continue
        if selected:
            return result
        low, high = 0, min(len(original) - start, max_chars)
        while low < high:
            mid = (low + high + 1) // 2
            if serialized_length({"ok": True, **candidate(mid).model_dump(mode="json")}) <= max_chars:
                low = mid
            else:
                high = mid - 1
        if low == 0:
            raise ValueError("输出容量不足以返回正文及续读参数。")
        return candidate(low)
    return result
