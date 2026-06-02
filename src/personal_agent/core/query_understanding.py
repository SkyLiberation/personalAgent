"""Models for query understanding and retrieval planning (P2).

The QueryUnderstanding layer classifies the user's question to determine
what retrieval sources are needed and how to optimize the query for recall.
The RetrievalPlan translates that understanding into an executable routing
decision.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


class QueryUnderstanding(BaseModel):
    """LLM-produced analysis of a user question's retrieval needs."""

    needs_freshness: bool = Field(
        default=False,
        description="True when the question asks about latest/current/recent information.",
    )
    needs_personal_memory: bool = Field(
        default=True,
        description="True when the question references personal notes or prior knowledge.",
    )
    needs_graph_reasoning: bool = Field(
        default=False,
        description="True when the question requires multi-hop entity relationship reasoning.",
    )
    query_rewrite: str = Field(
        default="",
        description="Retrieval-optimized rewrite of the original question.",
    )
    sub_queries: list[str] = Field(
        default_factory=list,
        description="Decomposed sub-questions for compound/multi-hop queries.",
    )
    filters: RetrievalFilters = Field(
        default_factory=RetrievalFilters,
        description="Structured metadata filters for local and graph-backed retrieval.",
    )
    answer_policy: Literal["must_cite", "allow_web", "refuse_if_insufficient"] = Field(
        default="must_cite",
        description="How to handle insufficient evidence.",
    )


class RetrievalPlan(BaseModel):
    """Executable routing decision derived from QueryUnderstanding."""

    sources: list[Literal["graph", "local", "web"]] = Field(
        default_factory=lambda: ["graph", "local"],
    )
    parallel: bool = Field(
        default=True,
        description="Whether graph and local retrieval should run in parallel.",
    )
    query: str = Field(
        default="",
        description="The effective query to send to retrieval (rewritten or original).",
    )
    sub_queries: list[str] = Field(
        default_factory=list,
        description="Sub-queries for multi-hop decomposition.",
    )
    filters: RetrievalFilters = Field(
        default_factory=RetrievalFilters,
        description="Metadata filters to push down into retrieval calls.",
    )
