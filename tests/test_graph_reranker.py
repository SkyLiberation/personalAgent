from __future__ import annotations

from dataclasses import dataclass

from personal_agent.graphiti.reranker import rank_graph_citation_hits


@dataclass
class EdgeLike:
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    episodes: list[str]


class TestGraphCitationReranker:
    def test_expands_edges_to_episode_hits(self):
        edge = EdgeLike(
            fact="订单服务依赖 Redis 缓存热点数据",
            source_node_uuid="n1",
            target_node_uuid="n2",
            episodes=["ep1", "ep2"],
        )

        hits = rank_graph_citation_hits(
            "订单服务为什么用 Redis？",
            [edge],
            {"n1": "订单服务", "n2": "Redis"},
            limit=None,
        )

        assert [hit.episode_uuid for hit in hits] == ["ep1", "ep2"]
        assert all(hit.relation_fact == edge.fact for hit in hits)
        assert all(hit.entity_overlap_count == 2 for hit in hits)

    def test_prefers_entity_and_keyword_matches(self):
        redis_edge = EdgeLike(
            fact="订单服务依赖 Redis 缓存热点数据",
            source_node_uuid="n1",
            target_node_uuid="n2",
            episodes=["ep-redis"],
        )
        generic_edge = EdgeLike(
            fact="系统包含多个组件",
            source_node_uuid="n3",
            target_node_uuid="n4",
            episodes=["ep-generic"],
        )

        hits = rank_graph_citation_hits(
            "订单服务 Redis 缓存",
            [generic_edge, redis_edge],
            {"n1": "订单服务", "n2": "Redis", "n3": "系统", "n4": "组件"},
            limit=None,
        )

        assert [hit.episode_uuid for hit in hits] == ["ep-redis"]
        assert hits[0].matched_terms
        assert hits[0].score > 0

    def test_deduplicates_same_episode_and_fact(self):
        edge = EdgeLike(
            fact="Redis 用于降低数据库压力",
            source_node_uuid="n1",
            target_node_uuid="n2",
            episodes=["ep1", "ep1"],
        )

        hits = rank_graph_citation_hits(
            "Redis 如何降低数据库压力？",
            [edge],
            {"n1": "Redis", "n2": "数据库压力"},
            limit=None,
        )

        assert len(hits) == 1
        assert hits[0].episode_uuid == "ep1"
