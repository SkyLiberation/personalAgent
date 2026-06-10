from __future__ import annotations

from personal_agent.core.evidence import (
    EvidenceItem,
    evidence_to_citations,
    episodes_to_evidence,
    graph_result_to_evidence,
    memory_items_to_evidence,
    notes_to_evidence,
    web_results_to_evidence,
)
from personal_agent.core.models import KnowledgeNote, MemoryEpisode, MemoryItem
from personal_agent.graphiti.reranker import GraphCitationHit
from personal_agent.graphiti.store import (
    GraphAskResult,
    GraphEdgeRef,
    GraphFactRef,
)
from tests.note_factory import make_note


def _note(note_id: str, title: str = "测试笔记", episode_uuid: str | None = None,
          parent_note_id: str | None = None, source_span: str | None = None) -> KnowledgeNote:
    return make_note(
        id=note_id, title=title,
        content=f"{title}的正文内容。", summary=f"{title}摘要",
        graph_episode_uuid=episode_uuid,
        parent_note_id=parent_note_id,
        source_span=source_span,
    )


class TestGraphResultToEvidence:
    def test_fact_refs_to_graph_fact(self):
        result = GraphAskResult(
            enabled=True, fact_refs=[
                GraphFactRef(fact="Redis supports caching", edge_uuid="e1",
                             source_node_name="Redis", target_node_name="Caching",
                             episode_uuids=["ep-1"]),
            ],
        )
        items = graph_result_to_evidence(result, {}, "what is Redis")
        assert len(items) == 1
        assert items[0].source_type == "graph_fact"
        assert items[0].source_id == "e1"
        assert items[0].fact == "Redis supports caching"
        assert items[0].metadata["source_node_name"] == "Redis"

    def test_edge_refs_dedup_against_fact_refs(self):
        result = GraphAskResult(
            enabled=True,
            fact_refs=[GraphFactRef(fact="same fact", edge_uuid="e1")],
            edge_refs=[GraphEdgeRef(uuid="e2", fact="same fact")],
        )
        items = graph_result_to_evidence(result, {}, "test")
        facts = [i for i in items if i.fact == "same fact"]
        assert len(facts) == 1

    def test_citation_hit_with_episode_mapping(self):
        note = _note("n1", "Redis笔记", episode_uuid="ep-1")
        result = GraphAskResult(
            enabled=True,
            citation_hits=[GraphCitationHit(
                episode_uuid="ep-1", relation_fact="Redis supports caching",
                endpoint_names=["Redis", "Caching"], score=15,
            )],
        )
        items = graph_result_to_evidence(result, {"ep-1": note}, "what is Redis")
        assert len(items) == 1
        assert items[0].source_type == "note"
        assert items[0].source_id == "n1"
        assert items[0].fact == "Redis supports caching"
        assert items[0].metadata["orphan"] is False

    def test_citation_hit_chunk_type(self):
        chunk = _note("c1", "Redis chunk", episode_uuid="ep-1", parent_note_id="p1")
        result = GraphAskResult(
            enabled=True,
            citation_hits=[GraphCitationHit(
                episode_uuid="ep-1", relation_fact="Redis fact",
            )],
        )
        items = graph_result_to_evidence(result, {"ep-1": chunk}, "test")
        assert len(items) == 1
        assert items[0].source_type == "chunk"

    def test_orphan_citation_hit(self):
        result = GraphAskResult(
            enabled=True,
            citation_hits=[GraphCitationHit(
                episode_uuid="ep-missing", relation_fact="orphan fact",
                endpoint_names=["X"], score=5,
            )],
        )
        items = graph_result_to_evidence(result, {}, "test")
        assert len(items) == 1
        assert items[0].source_type == "graph_fact"
        assert items[0].metadata["orphan"] is True

    def test_empty_result(self):
        result = GraphAskResult(enabled=True)
        items = graph_result_to_evidence(result, {}, "test")
        assert items == []


class TestNotesToEvidence:
    def test_standalone_note(self):
        note = _note("n1", "Test")
        items = notes_to_evidence([note])
        assert len(items) == 1
        assert items[0].source_type == "note"
        assert items[0].source_id == "n1"
        assert items[0].snippet  # summary for standalone note

    def test_chunk_note(self):
        chunk = _note("c1", "Chunk", parent_note_id="p1", source_span="p1-3")
        items = notes_to_evidence([chunk])
        assert len(items) == 1
        assert items[0].source_type == "chunk"
        assert items[0].source_span == "p1-3"

    def test_multiple_notes(self):
        notes = [_note("n1"), _note("c1", parent_note_id="n1")]
        items = notes_to_evidence(notes)
        assert len(items) == 2
        assert items[0].source_type == "note"
        assert items[1].source_type == "chunk"


class TestWebResultsToEvidence:
    def test_basic_conversion(self):
        results = [{"title": "Test", "url": "https://example.com", "snippet": "Test snippet"}]
        items = web_results_to_evidence(results)
        assert len(items) == 1
        assert items[0].source_type == "web"
        assert items[0].source_id == "https://example.com"
        assert items[0].url == "https://example.com"

    def test_preserves_metadata(self):
        results = [{"title": "Test", "url": "https://x.com", "snippet": "s",
                     "source": "firecrawl", "published_at": "2025-01-01"}]
        items = web_results_to_evidence(results)
        assert items[0].metadata["source"] == "firecrawl"
        assert items[0].metadata["published_at"] == "2025-01-01"

    def test_skips_non_dict(self):
        results = [{"title": "OK", "url": "https://x.com", "snippet": "s"}, "not a dict"]
        items = web_results_to_evidence(results)
        assert len(items) == 1


class TestEpisodesToEvidence:
    def test_basic_conversion(self):
        episode = MemoryEpisode(
            id="episode:run-1",
            user_id="u1",
            session_id="s1",
            thread_id="u1:s1",
            run_id="run-1",
            workflow="solidify_conversation",
            title="固化对话",
            summary="把当前会话沉淀为笔记。",
            decisions=["识别意图为 solidify_conversation"],
            open_items=["等待用户补充"],
            tool_refs=["capture_text"],
            note_refs=["note-1"],
        )

        items = episodes_to_evidence([episode])

        assert len(items) == 1
        assert items[0].source_type == "episode"
        assert items[0].source_id == "episode:run-1"
        assert items[0].metadata["workflow"] == "solidify_conversation"
        assert items[0].metadata["note_refs"] == ["note-1"]


class TestMemoryItemsToEvidence:
    def test_procedural_and_reflection_conversion(self):
        items = [
            MemoryItem(
                id="proc-1",
                memory_type="procedural",
                title="发布流程偏好",
                content="先跑测试再灰度。",
                status="confirmed",
                confidence=0.9,
            ),
            MemoryItem(
                id="refl-1",
                memory_type="reflection",
                title="失败复盘",
                content="目标不清楚时先澄清。",
                status="candidate",
            ),
        ]

        evidence = memory_items_to_evidence(items)

        assert [item.source_type for item in evidence] == ["procedural", "reflection"]
        assert evidence[0].score == 0.9
        assert evidence[1].metadata["status"] == "candidate"


class TestEvidenceToCitations:
    def test_web_evidence_to_citation(self):
        evidence = [EvidenceItem(
            source_type="web", source_id="https://x.com",
            title="Test", snippet="Test snippet", url="https://x.com",
        )]
        citations = evidence_to_citations(evidence)
        assert len(citations) == 1
        assert citations[0].source_type == "web"
        assert citations[0].note_id == ""
        assert citations[0].url == "https://x.com"

    def test_note_evidence_to_citation(self):
        evidence = [EvidenceItem(
            source_type="note", source_id="n1",
            title="Note", snippet="snippet", fact="some fact",
        )]
        citations = evidence_to_citations(evidence)
        assert len(citations) == 1
        assert citations[0].source_type == "note"
        assert citations[0].note_id == "n1"
        assert citations[0].relation_fact == "some fact"

    def test_graph_fact_maps_to_note_citation(self):
        evidence = [EvidenceItem(
            source_type="graph_fact", source_id="e1",
            title="Graph Fact", snippet="snippet", fact="fact text",
        )]
        citations = evidence_to_citations(evidence)
        assert citations[0].source_type == "note"
        assert citations[0].note_id == "e1"

    def test_tool_evidence_maps_to_note_citation(self):
        evidence = [EvidenceItem(
            source_type="tool", source_id="call-1",
            title="Tool Result", snippet="result",
        )]
        citations = evidence_to_citations(evidence)
        assert citations[0].source_type == "note"
        assert citations[0].note_id == "call-1"

    def test_empty_evidence(self):
        assert evidence_to_citations([]) == []

    def test_mixed_evidence_types(self):
        evidence = [
            EvidenceItem(source_type="web", source_id="u1", title="Web", snippet="s"),
            EvidenceItem(source_type="note", source_id="n1", title="Note", snippet="s"),
            EvidenceItem(source_type="graph_fact", source_id="e1", title="Fact", snippet="s"),
        ]
        citations = evidence_to_citations(evidence)
        assert len(citations) == 3
        assert citations[0].source_type == "web"
        assert citations[1].source_type == "note"
        assert citations[2].source_type == "note"
