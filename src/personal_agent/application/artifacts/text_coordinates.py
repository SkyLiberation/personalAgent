"""One lossless splitlines coordinate map for reading, searching and editing."""

from __future__ import annotations

from dataclasses import dataclass

from .models import DRAFT_MAX_BYTES, TextEdit, TextPosition

_LINE_BREAKS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")


@dataclass(frozen=True, slots=True)
class TextLine:
    line: int
    text: str
    start_offset: int
    end_offset: int
    line_ending: str


class TextCoordinates:
    """Offsets count Unicode code points; CRLF has no internal position."""

    def __init__(self, content: str) -> None:
        self.content = content
        lines: list[TextLine] = []
        offset = 0
        for number, segment in enumerate(content.splitlines(keepends=True), 1):
            ending = (
                "\r\n"
                if segment.endswith("\r\n")
                else (segment[-1:] if segment[-1:] in _LINE_BREAKS else "")
            )
            text = segment[: -len(ending)] if ending else segment
            lines.append(TextLine(number, text, offset, offset + len(text), ending))
            offset += len(segment)
        self.lines = tuple(lines)
        self.eof_position = (
            TextPosition(line=1, column=1)
            if not lines
            else TextPosition(line=len(lines) + 1, column=1)
            if lines[-1].line_ending
            else TextPosition(line=len(lines), column=len(lines[-1].text) + 1)
        )

    def offset(self, position: TextPosition) -> int:
        if position == self.eof_position:
            return len(self.content)
        if position.line > len(self.lines):
            raise ValueError("text position is beyond EOF")
        line = self.lines[position.line - 1]
        if position.column > len(line.text) + 1:
            raise ValueError("text position is beyond the line or inside a newline")
        return line.start_offset + position.column - 1

    def apply_edits(self, edits: tuple[TextEdit, ...]) -> str:
        ranges: list[tuple[int, int, str]] = []
        for edit in edits:
            start, end = self.offset(edit.range.start), self.offset(edit.range.end)
            if start > end:
                raise ValueError("patch range starts after its end")
            ranges.append((start, end, edit.new_text))
        # All offsets refer to the same original snapshot. Validate before writes.
        for index, (start, end, _) in enumerate(ranges):
            for other_start, other_end, _ in ranges[index + 1 :]:
                if start == end and other_start == other_end:
                    conflict = start == other_start
                elif start == end:
                    conflict = other_start < start < other_end
                elif other_start == other_end:
                    conflict = start < other_start < end
                else:
                    conflict = max(start, other_start) < min(end, other_end)
                if conflict:
                    raise ValueError("patch ranges overlap or repeat an insertion")
        result = self.content
        # Replacement precedes insertion at an equal start, placing insertion first.
        for start, end, text in sorted(
            ranges, key=lambda item: (item[0], item[1]), reverse=True
        ):
            result = result[:start] + text + result[end:]
        if len(result.encode("utf-8")) > DRAFT_MAX_BYTES:
            raise ValueError("patched draft exceeds the 65536-byte UTF-8 limit")
        return result
