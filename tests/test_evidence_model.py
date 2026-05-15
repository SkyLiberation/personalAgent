from __future__ import annotations

from personal_agent.core.evidence import EvidenceItem


class TestEvidenceItem:
    def test_default_values(self):
        item = EvidenceItem(source_type="note", source_id="n1")
        assert item.source_type == "note"
        assert item.source_id == "n1"
        assert item.title == ""
        assert item.snippet == ""
        assert item.fact is None
        assert item.source_span is None
        assert item.url is None
        assert item.score == 0.0
        assert item.metadata == {}
        assert len(item.evidence_id) == 12

    def test_all_source_types(self):
        for st in ("graph_fact", "note", "chunk", "web", "tool"):
            item = EvidenceItem(source_type=st)
            assert item.source_type == st

    def test_full_construction(self):
        item = EvidenceItem(
            source_type="graph_fact",
            source_id="edge-1",
            title="Redis",
            snippet="Redis supports caching",
            fact="Redis supports caching mechanisms",
            source_span="p1-3",
            url="https://example.com",
            score=0.85,
            metadata={"orphan": False, "episode_uuids": ["ep-1"]},
        )
        assert item.fact == "Redis supports caching mechanisms"
        assert item.score == 0.85
        assert item.metadata["orphan"] is False

    def test_serialization_roundtrip(self):
        item = EvidenceItem(
            source_type="web",
            source_id="https://example.com",
            title="Example",
            snippet="Test snippet",
            url="https://example.com",
        )
        data = item.model_dump(mode="json")
        restored = EvidenceItem.model_validate(data)
        assert restored.source_type == item.source_type
        assert restored.source_id == item.source_id
        assert restored.title == item.title

    def test_metadata_preserves_arbitrary_keys(self):
        item = EvidenceItem(
            source_type="graph_fact",
            metadata={"custom_key": [1, 2, 3], "nested": {"a": True}},
        )
        assert item.metadata["custom_key"] == [1, 2, 3]
        assert item.metadata["nested"]["a"] is True

    def test_unique_evidence_ids(self):
        items = [EvidenceItem(source_type="note") for _ in range(100)]
        ids = {item.evidence_id for item in items}
        assert len(ids) == 100
