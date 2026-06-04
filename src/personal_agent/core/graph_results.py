"""Provider-neutral graph result models.

These models are the boundary between graph providers (Graphiti, structural
retrievers, future hybrid) and the core evidence/normalize layer. They live in ``core`` so
that ``core.evidence`` no longer has to import from ``graphiti.store`` (which
would be a layering inversion: core depending on a concrete provider).

The graphiti package re-exports these for backward compatibility.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .models import Citation, GraphEdgeRef, GraphFactRef, GraphNodeRef


class GraphCitationHit(BaseModel):
    episode_uuid: str
    relation_fact: str
    endpoint_names: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    entity_overlap_count: int = 0
    score: int = 0


class GraphCaptureResult(BaseModel):
    enabled: bool = False
    error: str | None = None
    episode_uuid: str | None = None
    entity_names: list[str] = Field(default_factory=list)
    relation_facts: list[str] = Field(default_factory=list)
    related_episode_uuids: list[str] = Field(default_factory=list)
    node_refs: list[GraphNodeRef] = Field(default_factory=list)
    edge_refs: list[GraphEdgeRef] = Field(default_factory=list)
    fact_refs: list[GraphFactRef] = Field(default_factory=list)


class GraphAskResult(BaseModel):
    enabled: bool = False
    error: str | None = None
    answer: str | None = None
    entity_names: list[str] = Field(default_factory=list)
    relation_facts: list[str] = Field(default_factory=list)
    related_episode_uuids: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    citation_hits: list[GraphCitationHit] = Field(default_factory=list)
    node_refs: list[GraphNodeRef] = Field(default_factory=list)
    edge_refs: list[GraphEdgeRef] = Field(default_factory=list)
    fact_refs: list[GraphFactRef] = Field(default_factory=list)
