from __future__ import annotations

from personal_agent.application.insight import KnowledgeGap, KnowledgeGapAnalyzer
from tests.note_factory import make_note


class FakeMemory:
    def __init__(self, notes=None) -> None:
        self._notes = notes or []

    def list_recent_notes(self, user_id, *, limit=5, include_chunks=True):
        return list(self._notes)[:limit]


class FakeGraphStore:
    def __init__(self, topology) -> None:
        self.topology = topology

    def get_topology(self, user_id):
        return self.topology


def test_detects_isolated_entity_as_gap():
    # n3 has degree 0 (no links touch it) -> isolated.
    topology = {
        "nodes": [
            {"id": "n1", "name": "向量检索"},
            {"id": "n2", "name": "重排序"},
            {"id": "n3", "name": "冷门概念"},
        ],
        "links": [
            {"source": "n1", "target": "n2", "fact": "a"},
        ],
    }
    analyzer = KnowledgeGapAnalyzer(FakeMemory(), FakeGraphStore(topology), min_degree=0)

    gaps = analyzer.detect("alice")

    isolated = [g for g in gaps if g.gap_type == "isolated_entity"]
    assert isolated, "should detect the unconnected entity"
    assert "冷门概念" in isolated[0].entities
    assert isolated[0].key == "isolated:n3"


def test_well_connected_graph_yields_no_isolated_gap():
    topology = {
        "nodes": [{"id": "n1", "name": "A"}, {"id": "n2", "name": "B"}],
        "links": [
            {"source": "n1", "target": "n2", "fact": "x"},
            {"source": "n2", "target": "n1", "fact": "y"},
        ],
    }
    analyzer = KnowledgeGapAnalyzer(FakeMemory(), FakeGraphStore(topology), min_degree=0)

    gaps = analyzer.detect("alice")

    assert [g for g in gaps if g.gap_type == "isolated_entity"] == []


def test_detects_potential_conflict_between_opposite_polarity_notes():
    note_a = make_note(title="咖啡 提神 效果", summary="咖啡能提神", user_id="alice")
    note_b = make_note(title="咖啡 提神 效果", summary="咖啡不能提神", user_id="alice")
    analyzer = KnowledgeGapAnalyzer(FakeMemory([note_a, note_b]), graph_store=None)

    gaps = analyzer.detect("alice")

    conflicts = [g for g in gaps if g.gap_type == "potential_conflict"]
    assert conflicts, "opposite-polarity overlapping notes should be a conflict gap"
    assert set(conflicts[0].note_ids) == {note_a.id, note_b.id}


def test_same_polarity_notes_are_not_conflicts():
    note_a = make_note(title="咖啡 提神 效果", summary="咖啡能提神", user_id="alice")
    note_b = make_note(title="咖啡 提神 效果", summary="咖啡确实提神", user_id="alice")
    analyzer = KnowledgeGapAnalyzer(FakeMemory([note_a, note_b]), graph_store=None)

    gaps = analyzer.detect("alice")

    assert [g for g in gaps if g.gap_type == "potential_conflict"] == []


def test_max_gaps_caps_output():
    nodes = [{"id": f"n{i}", "name": f"实体{i}"} for i in range(10)]
    topology = {"nodes": nodes, "links": []}
    analyzer = KnowledgeGapAnalyzer(
        FakeMemory(), FakeGraphStore(topology), min_degree=0, max_gaps=2
    )

    gaps = analyzer.detect("alice")

    assert len(gaps) == 2


def test_graph_failure_degrades_gracefully():
    class FailingGraph:
        def get_topology(self, user_id):
            raise RuntimeError("neo4j down")

    analyzer = KnowledgeGapAnalyzer(FakeMemory(), FailingGraph())

    assert analyzer.detect("alice") == []


def _isolated_topology():
    return {
        "nodes": [{"id": "n1", "name": "冷门概念"}],
        "links": [],
    }


def test_question_llm_rewrites_phrasing():
    analyzer = KnowledgeGapAnalyzer(
        FakeMemory(),
        FakeGraphStore(_isolated_topology()),
        min_degree=0,
        question_llm=lambda gap: "关于冷门概念，你能补充点什么吗？",
    )

    gaps = analyzer.detect("alice")

    assert gaps[0].question == "关于冷门概念，你能补充点什么吗？"


def test_question_llm_failure_keeps_template():
    def boom(gap):
        raise RuntimeError("llm down")

    analyzer = KnowledgeGapAnalyzer(
        FakeMemory(),
        FakeGraphStore(_isolated_topology()),
        min_degree=0,
        question_llm=boom,
    )

    gaps = analyzer.detect("alice")

    # Falls back to the deterministic template question.
    assert "冷门概念" in gaps[0].question
    assert gaps[0].question  # non-empty


def test_question_llm_empty_result_keeps_template():
    analyzer = KnowledgeGapAnalyzer(
        FakeMemory(),
        FakeGraphStore(_isolated_topology()),
        min_degree=0,
        question_llm=lambda gap: "   ",
    )

    gaps = analyzer.detect("alice")

    assert "冷门概念" in gaps[0].question
