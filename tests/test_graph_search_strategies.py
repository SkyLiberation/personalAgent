from __future__ import annotations

import pytest

from personal_agent.kernel.config import GraphitiConfig, Settings
from personal_agent.graphiti.search_strategies import (
    STRATEGIES,
    apply_search_config_overrides,
    get_graph_search_strategy,
    list_graph_search_strategies,
)
from personal_agent.graphiti.store import GraphitiStore


class TestGraphSearchStrategies:
    def test_default_strategy_exists(self):
        strategy = get_graph_search_strategy(None)
        assert strategy.name == "hybrid_rrf"
        assert strategy.search_config is not None

    def test_unknown_strategy_raises_clear_error(self):
        with pytest.raises(ValueError, match="Unknown graph search strategy"):
            get_graph_search_strategy("missing")

    def test_list_strategies_exposes_names_and_descriptions(self):
        items = list_graph_search_strategies()
        names = {item["name"] for item in items}
        assert set(STRATEGIES).issubset(names)
        assert all(item["description"] for item in items)

    def test_store_uses_configured_strategy(self, temp_dir):
        settings = Settings(
            data_dir=temp_dir,
            graphiti=GraphitiConfig(search_strategy="edge_rrf"),
        )
        store = GraphitiStore(settings)
        assert store.search_strategy.name == "edge_rrf"
        assert store.status()["search_strategy"] == "edge_rrf"

    def test_apply_overrides_caps_hops_and_limit(self):
        base = get_graph_search_strategy("hybrid_rrf")
        original_hops = base.search_config.edge_config.bfs_max_depth
        original_limit = base.search_config.limit
        original_citation_limit = base.citation_limit

        tuned = apply_search_config_overrides(
            base, max_hops=2, limit=5, citation_limit=18, min_score=0.3
        )

        assert tuned.search_config.edge_config.bfs_max_depth == 2
        assert tuned.search_config.node_config.bfs_max_depth == 2
        assert tuned.search_config.limit == 5
        assert tuned.citation_limit == 18
        assert tuned.search_config.reranker_min_score == 0.3
        # base recipe must not be mutated
        assert base.search_config.edge_config.bfs_max_depth == original_hops
        assert base.search_config.limit == original_limit
        assert base.citation_limit == original_citation_limit

    def test_apply_overrides_noop_when_all_none(self):
        base = get_graph_search_strategy("hybrid_rrf")
        same = apply_search_config_overrides(base)
        assert same is base

    def test_store_applies_settings_overrides(self, temp_dir):
        settings = Settings(
            data_dir=temp_dir,
            graphiti=GraphitiConfig(
                search_strategy="hybrid_rrf",
                search_max_hops=2,
                search_limit=6,
                search_citation_limit=16,
                search_min_score=0.2,
            ),
        )
        store = GraphitiStore(settings)
        cfg = store.search_strategy.search_config
        assert cfg.edge_config.bfs_max_depth == 2
        assert cfg.limit == 6
        assert store.search_strategy.citation_limit == 16
        assert cfg.reranker_min_score == 0.2
