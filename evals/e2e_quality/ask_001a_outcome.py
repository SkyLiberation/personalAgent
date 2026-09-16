"""Case-specific final-answer grader for ASK-001A."""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field


ASK_001A_GRADER_VERSION = "ask-001a-original-passages-v1"
_MARKDOWN_CONTROL = re.compile(r"[`*_~#>|]")
_TERMINAL_PUNCTUATION = "。.!！"


class Ask001AOutcomeVerdict(BaseModel):
    """Whether both user-owned source passages are visible in the final answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passage_presence: tuple[bool, bool]
    missing_passage_indexes: tuple[int, ...]

    @property
    def passed(self) -> bool:
        return not self.missing_passage_indexes


class Ask001AControlCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    expected_passed: bool


class Ask001AControlDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    grader_version: str = Field(min_length=1)
    expected_passages: tuple[str, str]
    cases: tuple[Ask001AControlCase, ...] = Field(min_length=1)


def _normalize_source_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = _MARKDOWN_CONTROL.sub("", normalized)
    normalized = "".join(normalized.split())
    return normalized.strip(_TERMINAL_PUNCTUATION)


def grade_ask_001a_answer(
    *,
    answer: str,
    expected_passages: tuple[str, str],
) -> Ask001AOutcomeVerdict:
    """Check source visibility without constraining answer layout or Agent strategy."""

    normalized_answer = _normalize_source_text(answer)
    passage_presence = tuple(
        _normalize_source_text(passage) in normalized_answer
        for passage in expected_passages
    )
    missing = tuple(
        index
        for index, present in enumerate(passage_presence)
        if not present
    )
    return Ask001AOutcomeVerdict(
        passage_presence=passage_presence,
        missing_passage_indexes=missing,
    )


__all__ = [
    "ASK_001A_GRADER_VERSION",
    "Ask001AControlDataset",
    "Ask001AOutcomeVerdict",
    "grade_ask_001a_answer",
]
