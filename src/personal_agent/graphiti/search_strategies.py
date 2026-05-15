from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from graphiti_core.search.search_config import SearchConfig
from graphiti_core.search.search_config_recipes import (
    COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
    COMBINED_HYBRID_SEARCH_MMR,
    COMBINED_HYBRID_SEARCH_RRF,
    EDGE_HYBRID_SEARCH_NODE_DISTANCE,
    EDGE_HYBRID_SEARCH_RRF,
)

from .reranker import GraphCitationHit, rank_graph_citation_hits


class GraphSearchStrategy(Protocol):
    name: str
    description: str
    search_config: SearchConfig

    def citation_hits(
        self,
        question: str,
        edges: list[Any],
        node_names_by_uuid: dict[str, str],
    ) -> list[GraphCitationHit]:
        ...


@dataclass(frozen=True)
class BaseGraphSearchStrategy:
    name: str
    description: str
    search_config: SearchConfig
    citation_limit: int = 12

    def citation_hits(
        self,
        question: str,
        edges: list[Any],
        node_names_by_uuid: dict[str, str],
    ) -> list[GraphCitationHit]:
        return rank_graph_citation_hits(
            question,
            edges,
            node_names_by_uuid,
            limit=self.citation_limit,
        )


STRATEGIES: dict[str, GraphSearchStrategy] = {
    "hybrid_rrf": BaseGraphSearchStrategy(
        name="hybrid_rrf",
        description="Graphiti combined hybrid search with RRF over edges, nodes, episodes, and communities.",
        search_config=COMBINED_HYBRID_SEARCH_RRF,
    ),
    "hybrid_mmr": BaseGraphSearchStrategy(
        name="hybrid_mmr",
        description="Graphiti combined hybrid search with MMR reranking.",
        search_config=COMBINED_HYBRID_SEARCH_MMR,
    ),
    "hybrid_cross_encoder": BaseGraphSearchStrategy(
        name="hybrid_cross_encoder",
        description="Graphiti combined hybrid search with BFS and cross-encoder reranking.",
        search_config=COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
    ),
    "edge_rrf": BaseGraphSearchStrategy(
        name="edge_rrf",
        description="Graphiti edge-only hybrid search with RRF reranking.",
        search_config=EDGE_HYBRID_SEARCH_RRF,
    ),
    "edge_node_distance": BaseGraphSearchStrategy(
        name="edge_node_distance",
        description="Graphiti edge-only hybrid search with node-distance reranking.",
        search_config=EDGE_HYBRID_SEARCH_NODE_DISTANCE,
    ),
}


def get_graph_search_strategy(name: str | None) -> GraphSearchStrategy:
    normalized = (name or "hybrid_rrf").strip().lower()
    if normalized not in STRATEGIES:
        available = ", ".join(sorted(STRATEGIES))
        raise ValueError(f"Unknown graph search strategy '{name}'. Available: {available}")
    return STRATEGIES[normalized]


def list_graph_search_strategies() -> list[dict[str, str]]:
    return [
        {"name": strategy.name, "description": strategy.description}
        for strategy in STRATEGIES.values()
    ]
