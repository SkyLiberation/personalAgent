from __future__ import annotations

import pytest

from personal_agent.core.config import Settings
from personal_agent.graphiti.search_strategies import (
    STRATEGIES,
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
        settings = Settings(data_dir=temp_dir, graph_search_strategy="edge_rrf")
        store = GraphitiStore(settings)
        assert store.search_strategy.name == "edge_rrf"
        assert store.status()["search_strategy"] == "edge_rrf"
