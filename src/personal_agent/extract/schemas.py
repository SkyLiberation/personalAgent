"""Schemas for the lightweight pre-extraction layer.

These are intentionally narrow: section-level topic, entity hints, and a
graph_worthy routing flag. Entity properties / relations / facts stay on the
graphiti deep-extraction layer.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


InformationDensity = Literal["high", "medium", "low"]


class SectionRecord(BaseModel):
    """One section's lightweight extraction result."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(default="", description="Section title or auto-generated label.")
    char_start: int = Field(default=0, description="Inclusive start offset in source text.")
    char_end: int = Field(default=0, description="Exclusive end offset in source text.")
    topic: str = Field(default="", description="One-line topic of this section.")
    summary: str = Field(default="", description="<=120 char summary of this section.")
    contains_entities: list[str] = Field(
        default_factory=list,
        description="Representative entity names mentioned in this section.",
    )
    contains_relations: bool = Field(
        default=False,
        description="Whether this section contains explicit subject-verb-object relations.",
    )
    information_density: InformationDensity = Field(default="medium")
    graph_worthy: bool = Field(
        default=False,
        description=(
            "True when the section contains decisions, dependencies, definitions, "
            "causes, tradeoffs, or contrasts that justify deep graph extraction."
        ),
    )
    reason: str = Field(
        default="",
        description="<=30 char justification for the graph_worthy verdict.",
    )


class SectionMap(BaseModel):
    """Document-level section map produced by the pre-extraction layer."""

    model_config = ConfigDict(extra="ignore")

    doc_topic: str = Field(default="", description="One-line topic for the whole document.")
    sections: list[SectionRecord] = Field(default_factory=list)

    def graph_worthy_sections(self) -> list[SectionRecord]:
        return [s for s in self.sections if s.graph_worthy]
