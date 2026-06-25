from __future__ import annotations

from personal_agent.orchestration.runtime_ask import AskService, _selected_citations, _selected_matches
from personal_agent.kernel.evidence import ContextPack, EvidenceItem, RankedEvidence
from personal_agent.kernel.models import Citation
from tests.note_factory import make_note


def _ranked(source_id: str, source_type: str = "note") -> RankedEvidence:
    return RankedEvidence(
        evidence=EvidenceItem(source_type=source_type, source_id=source_id, title=f"title-{source_id}"),
        score=1.0,
        selected_for_prompt=True,
    )


def _build(context_pack, matches, citations) -> str:
    # _build_unified_answer_prompt uses only its parameters, no instance state.
    runtime = AskService.__new__(AskService)
    return runtime._build_unified_answer_prompt(
        "question", context_pack, matches, citations, ""
    )


class TestUnifiedPromptHintGating:
    def test_citation_hint_only_includes_selected_ids(self):
        pack = ContextPack(question="q", selected=[_ranked("p1")])
        citations = [
            Citation(note_id="p1", title="kept-citation", snippet="s"),
            Citation(note_id="p2", title="dropped-citation", snippet="s"),
        ]
        prompt = _build(pack, [], citations)
        assert "kept-citation" in prompt
        assert "dropped-citation" not in prompt

    def test_match_hint_only_includes_selected_ids(self):
        pack = ContextPack(question="q", selected=[_ranked("p1")])
        matches = [
            make_note(id="p1", title="kept-note", summary="kept summary"),
            make_note(id="p2", title="dropped-note", summary="dropped summary"),
        ]
        prompt = _build(pack, matches, [])
        assert "kept-note" in prompt
        assert "dropped-note" not in prompt

    def test_empty_selection_drops_all_hints(self):
        pack = ContextPack(question="q", selected=[])
        citations = [Citation(note_id="p1", title="any-citation", snippet="s")]
        matches = [make_note(id="p1", title="any-note", summary="sum")]
        prompt = _build(pack, matches, citations)
        assert "any-citation" not in prompt
        assert "any-note" not in prompt
        # Both hint sections fall back to the "无" placeholder.
        assert "引用锚点摘要：\n无" in prompt
        assert "匹配笔记摘要：\n无" in prompt

    def test_selected_helpers_drop_unselected_hints(self):
        pack = ContextPack(question="q", selected=[_ranked("p1")])
        matches = [
            make_note(id="p1", title="kept-note", summary="kept summary"),
            make_note(id="p2", title="dropped-note", summary="dropped summary"),
        ]
        citations = [
            Citation(note_id="p1", title="kept-citation", snippet="s"),
            Citation(note_id="p2", title="dropped-citation", snippet="s"),
        ]

        assert [note.id for note in _selected_matches(matches, pack.evidence)] == ["p1"]
        assert [citation.note_id for citation in _selected_citations(citations, pack.evidence)] == ["p1"]
