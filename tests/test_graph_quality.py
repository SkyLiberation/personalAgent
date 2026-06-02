"""Unit tests for graph extraction quality observability (PG-0)."""
from __future__ import annotations

import pytest

from personal_agent.core.models import KnowledgeNote
from personal_agent.graphiti.quality_vocab import (
    all_relations_weak,
    is_weak_relation,
)


class TestIsWeakRelation:
    def test_chinese_weak_terms(self) -> None:
        assert is_weak_relation("相关") is True
        assert is_weak_relation("有关") is True
        assert is_weak_relation("涉及") is True
        assert is_weak_relation("属于") is True
        assert is_weak_relation("  相关  ") is True

    def test_english_weak_terms(self) -> None:
        assert is_weak_relation("related to") is True
        assert is_weak_relation("associated with") is True
        assert is_weak_relation("has") is True
        assert is_weak_relation("Is") is True

    def test_strong_relations_chinese(self) -> None:
        assert is_weak_relation("Redis 支持缓存淘汰策略") is False
        assert is_weak_relation("FastAPI 实现了依赖注入") is False
        assert is_weak_relation("服务降级保护核心链路") is False

    def test_strong_relations_english(self) -> None:
        assert is_weak_relation("implements OAuth2 flow") is False
        assert is_weak_relation("caches dependency results") is False
        assert is_weak_relation("triggers a webhook on failure") is False

    def test_empty_is_weak(self) -> None:
        assert is_weak_relation("") is True
        assert is_weak_relation("   ") is True


class TestAllRelationsWeak:
    def test_empty_list_returns_false(self) -> None:
        assert all_relations_weak([]) is False

    def test_all_weak(self) -> None:
        assert all_relations_weak(["相关", "有关", "涉及"]) is True

    def test_one_strong_makes_false(self) -> None:
        assert all_relations_weak(["相关", "Redis 支持缓存"]) is False

    def test_all_strong(self) -> None:
        assert all_relations_weak(["A 实现了 B", "C 依赖 D"]) is False


class TestKnowledgeNoteQualityFields:
    def test_quality_fields_default_none(self) -> None:
        note = KnowledgeNote(title="t", content="c", summary="s")
        assert note.graph_quality_entity_count is None
        assert note.graph_quality_relation_count is None
        assert note.graph_quality_avg_fact_length is None
        assert note.graph_quality_zero_entities is None
        assert note.graph_quality_weak_relations_only is None

    def test_quality_fields_settable(self) -> None:
        note = KnowledgeNote(title="t", content="c", summary="s")
        note.graph_quality_entity_count = 5
        note.graph_quality_relation_count = 3
        note.graph_quality_avg_fact_length = 12.5
        note.graph_quality_zero_entities = False
        note.graph_quality_weak_relations_only = False
        assert note.graph_quality_entity_count == 5
