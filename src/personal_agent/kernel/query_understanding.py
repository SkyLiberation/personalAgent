"""Typed filters accepted by knowledge retrieval ports."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RetrievalFilters(BaseModel):
    """Structured metadata filters extracted from the user's question."""

    source_types: list[str] = Field(
        default_factory=list,
        description="Restrict retrieval to source types such as text, link, file, note, pdf.",
    )
    source_ref_contains: str = Field(
        default="",
        description="Substring that should appear in source_ref, e.g. a filename or URL domain.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags that candidate notes should contain.",
    )
    created_after: str = Field(
        default="",
        description="ISO datetime lower bound for note creation time.",
    )
    created_before: str = Field(
        default="",
        description="ISO datetime upper bound for note creation time.",
    )
    metadata_contains: str = Field(
        default="",
        description="Substring that should appear in note metadata.",
    )
    parent_note_id: str = Field(
        default="",
        description="Restrict retrieval to a parent document/chunk tree.",
    )

    @field_validator(
        "source_ref_contains",
        "created_after",
        "created_before",
        "metadata_contains",
        "parent_note_id",
        mode="before",
    )
    @classmethod
    def _coerce_string_filter(cls, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            for item in value:
                text = str(item).strip()
                if text:
                    return text
            return ""
        return str(value).strip()

    def active(self) -> bool:
        return bool(
            self.source_types
            or self.source_ref_contains
            or self.tags
            or self.created_after
            or self.created_before
            or self.metadata_contains
            or self.parent_note_id
        )
