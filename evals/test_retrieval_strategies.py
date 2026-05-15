from __future__ import annotations

from dataclasses import dataclass

import pytest

from personal_agent.graphiti.search_strategies import STRATEGIES


@dataclass(frozen=True)
class EdgeLike:
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    episodes: list[str]


@dataclass(frozen=True)
class RetrievalStrategyEvalCase:
    id: str
    question: str
    edges: list[EdgeLike]
    node_names_by_uuid: dict[str, str]
    expected_episode: str
    expected_fact_keyword: str


CASES = [
    RetrievalStrategyEvalCase(
        id="redis-hot-data",
        question="订单服务为什么使用 Redis 缓存？",
        edges=[
            EdgeLike("系统包含多个组件", "n3", "n4", ["ep-generic"]),
            EdgeLike("订单服务依赖 Redis 缓存热点数据", "n1", "n2", ["ep-redis"]),
        ],
        node_names_by_uuid={
            "n1": "订单服务",
            "n2": "Redis",
            "n3": "系统",
            "n4": "组件",
        },
        expected_episode="ep-redis",
        expected_fact_keyword="Redis",
    ),
    RetrievalStrategyEvalCase(
        id="degradation-core-link",
        question="服务降级如何保障核心链路？",
        edges=[
            EdgeLike("服务降级会关闭非核心能力以保障核心链路", "n1", "n2", ["ep-degrade"]),
            EdgeLike("缓存可以降低数据库压力", "n3", "n4", ["ep-cache"]),
        ],
        node_names_by_uuid={
            "n1": "服务降级",
            "n2": "核心链路",
            "n3": "缓存",
            "n4": "数据库压力",
        },
        expected_episode="ep-degrade",
        expected_fact_keyword="核心链路",
    ),
]


class TestRetrievalStrategyEval:
    @pytest.mark.parametrize("strategy_name", sorted(STRATEGIES), ids=sorted(STRATEGIES))
    @pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
    def test_strategy_ranks_expected_fact_first(
        self,
        strategy_name: str,
        case: RetrievalStrategyEvalCase,
    ):
        strategy = STRATEGIES[strategy_name]
        hits = strategy.citation_hits(case.question, case.edges, case.node_names_by_uuid)

        assert hits, f"{strategy_name}:{case.id} produced no hits"
        assert hits[0].episode_uuid == case.expected_episode
        assert case.expected_fact_keyword in hits[0].relation_fact
