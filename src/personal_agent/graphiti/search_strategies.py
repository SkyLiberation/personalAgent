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


def apply_search_config_overrides(
    strategy: GraphSearchStrategy,
    *,
    max_hops: int | None = None,
    limit: int | None = None,
    citation_limit: int | None = None,
    min_score: float | None = None,
) -> GraphSearchStrategy:
    base_config = strategy.search_config
    config_updates: dict[str, Any] = {}
    if limit is not None and limit > 0:
        config_updates["limit"] = limit
    if min_score is not None and min_score > 0:
        config_updates["reranker_min_score"] = min_score

    sub_updates: dict[str, Any] = {}
    if max_hops is not None and max_hops > 0:
        for sub_name in ("edge_config", "node_config", "community_config"):
            sub = getattr(base_config, sub_name, None)
            if sub is None:
                continue
            sub_updates[sub_name] = sub.model_copy(update={"bfs_max_depth": max_hops})

    if not config_updates and not sub_updates:
        if citation_limit is None or citation_limit <= 0:
            return strategy

    new_config = base_config.model_copy(update={**config_updates, **sub_updates})
    return BaseGraphSearchStrategy(
        name=strategy.name,
        description=strategy.description,
        search_config=new_config,
        citation_limit=(
            citation_limit
            if citation_limit is not None and citation_limit > 0
            else getattr(strategy, "citation_limit", 12)
        ),
    )


def list_graph_search_strategies() -> list[dict[str, str]]:
    return [
        {"name": strategy.name, "description": strategy.description}
        for strategy in STRATEGIES.values()
    ]
