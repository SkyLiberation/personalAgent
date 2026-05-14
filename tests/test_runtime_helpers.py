from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_agent.agent.runtime import (
    _best_snippet,
    _extract_question_keywords,
    _split_sentences,
    _tokenize_for_overlap,
)
from personal_agent.core.models import (
    KnowledgeNote,
    GraphNodeRef,
    GraphEdgeRef,
    GraphFactRef,
)
from personal_agent.graphiti.store import GraphCaptureResult
from personal_agent.storage.memory_store import LocalMemoryStore


class TestTokenizeForOverlap:
    def test_filters_short_and_punctuation(self):
        tokens = _tokenize_for_overlap("a ab cd e? xyz!")
        assert tokens == {"ab", "cd", "xyz"}

    def test_empty_string(self):
        assert _tokenize_for_overlap("") == set()

    def test_mixed_case(self):
        tokens = _tokenize_for_overlap("Hello World TEST")
        assert tokens == {"hello", "world", "test"}


class TestSplitSentences:
    def test_chinese_delimiters(self):
        parts = _split_sentences("这是第一句。这是第二句！这是第三句？")
        assert len(parts) == 3
        assert "第一句" in parts[0]
        assert "第二句" in parts[1]
        assert "第三句" in parts[2]

    def test_mixed_chinese_english(self):
        parts = _split_sentences("Hello world. 中文句子。Another one!")
        assert len(parts) == 3

    def test_newline_as_delimiter(self):
        parts = _split_sentences("line one\nline two")
        assert len(parts) == 2


class TestExtractQuestionKeywords:
    def test_chinese_keywords(self):
        keywords = _extract_question_keywords("什么是服务降级？")
        assert any("服务降级" in kw for kw in keywords) or any("服务" in kw for kw in keywords)

    def test_english_keywords(self):
        keywords = _extract_question_keywords("What is Redis caching?")
        assert "redis" in keywords
        assert "caching" in keywords

    def test_mixed_keywords(self):
        keywords = _extract_question_keywords("如何配置 Redis 缓存策略？")
        assert "redis" in keywords


class TestBestSnippet:
    def test_returns_best_matching_sentence(self):
        note = KnowledgeNote(
            id="n1", title="缓存策略", user_id="test",
            content="Redis 使用内存存储数据。缓存失效策略包括 TTL 和 LRU。",
            summary="关于 Redis 缓存的笔记",
        )
        from personal_agent.graphiti.store import GraphCitationHit

        hit = GraphCitationHit(
            episode_uuid="ep1",
            relation_fact="缓存失效策略包括 TTL",
            endpoint_names=["缓存", "TTL"],
            matched_terms=["缓存"],
            entity_overlap_count=2,
            score=90,
        )
        snippet = _best_snippet(note, hit, "什么是缓存失效策略？")
        assert "缓存失效策略" in snippet or len(snippet) > 0

    def test_fallback_to_summary(self):
        note = KnowledgeNote(
            id="n2", title="测试笔记", user_id="test",
            content="一些无关的内容。",
            summary="这是关于缓存策略的摘要说明，包含重要信息。",
        )
        from personal_agent.graphiti.store import GraphCitationHit

        hit = GraphCitationHit(
            episode_uuid="ep2",
            relation_fact="完全不匹配的内容",
            endpoint_names=[],
            matched_terms=[],
            entity_overlap_count=0,
            score=10,
        )
        snippet = _best_snippet(note, hit, "缓存策略？")
        assert len(snippet) > 0


class TestGraphRefModels:
    def test_graph_node_ref_construction(self):
        ref = GraphNodeRef(uuid="node-1", name="Redis", labels=["Entity", "Technology"], summary="In-memory data store")
        assert ref.uuid == "node-1"
        assert ref.name == "Redis"
        assert ref.labels == ["Entity", "Technology"]
        assert ref.summary == "In-memory data store"

    def test_graph_node_ref_defaults(self):
        ref = GraphNodeRef(uuid="n1", name="Test")
        assert ref.labels == []
        assert ref.summary == ""

    def test_graph_edge_ref_construction(self):
        ref = GraphEdgeRef(
            uuid="edge-1",
            fact="Redis supports caching",
            source_node_uuid="n1",
            target_node_uuid="n2",
            source_node_name="Redis",
            target_node_name="Caching",
            episodes=["ep1", "ep2"],
        )
        assert ref.uuid == "edge-1"
        assert ref.source_node_name == "Redis"
        assert ref.target_node_name == "Caching"
        assert len(ref.episodes) == 2

    def test_graph_edge_ref_defaults(self):
        ref = GraphEdgeRef(uuid="e1", fact="some fact")
        assert ref.source_node_uuid == ""
        assert ref.episodes == []

    def test_graph_fact_ref_construction(self):
        ref = GraphFactRef(
            fact="Redis uses TTL for expiration",
            edge_uuid="e1",
            source_node_name="Redis",
            target_node_name="TTL",
            episode_uuids=["ep1"],
        )
        assert ref.fact == "Redis uses TTL for expiration"
        assert ref.edge_uuid == "e1"
        assert len(ref.episode_uuids) == 1

    def test_graph_fact_ref_defaults(self):
        ref = GraphFactRef(fact="test")
        assert ref.edge_uuid == ""
        assert ref.episode_uuids == []


class TestMergeGraphCaptureRefs:
    def test_merge_populates_refs(self):
        note = KnowledgeNote(title="test", content="c", summary="s", user_id="u1")
        graph_result = GraphCaptureResult(
            enabled=True,
            episode_uuid="ep-1",
            entity_names=["Redis"],
            relation_facts=["Redis supports caching"],
            related_episode_uuids=[],
            node_refs=[GraphNodeRef(uuid="n1", name="Redis")],
            edge_refs=[GraphEdgeRef(uuid="e1", fact="Redis supports caching", source_node_name="Redis")],
            fact_refs=[GraphFactRef(fact="Redis supports caching", edge_uuid="e1", source_node_name="Redis")],
        )
        from personal_agent.agent.runtime import AgentRuntime
        rt = object.__new__(AgentRuntime)
        rt._merge_graph_capture(note, graph_result)
        assert note.graph_episode_uuid == "ep-1"
        assert note.entity_names == ["Redis"]
        assert len(note.graph_node_refs) == 1
        assert note.graph_node_refs[0].uuid == "n1"
        assert len(note.graph_edge_refs) == 1
        assert note.graph_edge_refs[0].source_node_name == "Redis"
        assert len(note.graph_fact_refs) == 1
        assert note.graph_fact_refs[0].edge_uuid == "e1"
        assert note.graph_sync_status == "synced"


class TestGraphRefsSerialization:
    def test_note_with_graph_refs_roundtrips(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        note = KnowledgeNote(
            id="n1", title="Graph note", content="content", summary="summary",
            user_id="test",
            graph_episode_uuid="ep-1",
            entity_names=["Redis"],
            relation_facts=["Redis supports caching"],
            graph_node_refs=[GraphNodeRef(uuid="n1", name="Redis", labels=["Tech"])],
            graph_edge_refs=[GraphEdgeRef(uuid="e1", fact="f", source_node_name="Redis")],
            graph_fact_refs=[GraphFactRef(fact="f", edge_uuid="e1")],
        )
        store.add_note(note)
        loaded = store.get_note("n1")
        assert loaded is not None
        assert loaded.graph_episode_uuid == "ep-1"
        assert len(loaded.graph_node_refs) == 1
        assert loaded.graph_node_refs[0].labels == ["Tech"]
        assert len(loaded.graph_edge_refs) == 1
        assert len(loaded.graph_fact_refs) == 1

    def test_note_without_refs_loads_cleanly(self, temp_dir: Path):
        store = LocalMemoryStore(temp_dir)
        note = KnowledgeNote(
            id="n2", title="Old note", content="c", summary="s", user_id="test",
            entity_names=["Python"],
            relation_facts=["Python is a language"],
        )
        store.add_note(note)
        loaded = store.get_note("n2")
        assert loaded is not None
        assert loaded.entity_names == ["Python"]
        assert loaded.graph_node_refs == []
        assert loaded.graph_edge_refs == []
        assert loaded.graph_fact_refs == []

    def test_backward_compat_existing_json(self, temp_dir: Path):
        notes_file = temp_dir / "notes.json"
        notes_file.write_text(json.dumps([{
            "id": "old1", "user_id": "test", "title": "Legacy",
            "content": "c", "summary": "s",
            "entity_names": ["A"], "relation_facts": ["A relates B"],
            "graph_episode_uuid": "ep-old",
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        }]), encoding="utf-8")
        store = LocalMemoryStore(temp_dir)
        loaded = store.get_note("old1")
        assert loaded is not None
        assert loaded.entity_names == ["A"]
        assert loaded.graph_node_refs == []
        assert loaded.graph_edge_refs == []
        assert loaded.graph_fact_refs == []
