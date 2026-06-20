from __future__ import annotations

from personal_agent.tools import ToolExecutor, build_consolidate_notes_tool, tool_governance


def _build_executor(consolidate_fn):
    executor = ToolExecutor()
    executor.register(build_consolidate_notes_tool(consolidate_fn))
    return executor


def test_consolidate_tool_governance_is_low_risk_write():
    tool = build_consolidate_notes_tool(lambda **kw: {"ok": True, "note_id": "n"})
    gov = tool_governance(tool)
    assert gov.risk_level == "low"
    assert gov.requires_confirmation is False
    assert "write_longterm" in gov.side_effects
    assert gov.permission_scope == "memory:write"


def test_consolidate_tool_requires_at_least_two_note_ids():
    executor = _build_executor(lambda **kw: {"ok": True, "note_id": "n"})
    result = executor.invoke_direct("consolidate_notes", note_ids=["only-one"], topic="X")
    # schema min_length=2 -> invalid param, surfaced as a failed artifact
    assert result["ok"] is False


def test_consolidate_tool_returns_superseded_ids_on_success():
    def fake_consolidate(*, note_ids, topic, user_id="default"):
        return {
            "ok": True,
            "note_id": "summary-1",
            "title": f"{topic}（综述）",
            "summary": "合并后的综述",
            "superseded": note_ids,
            "failed": [],
        }

    executor = _build_executor(fake_consolidate)
    result = executor.invoke_direct(
        "consolidate_notes", note_ids=["a", "b", "c"], topic="向量检索"
    )

    assert result["ok"] is True
    data = result["data"]
    assert data["note_id"] == "summary-1"
    assert data["superseded"] == ["a", "b", "c"]
    assert data["failed"] == []


def test_consolidate_tool_propagates_executor_failure():
    executor = _build_executor(lambda **kw: {"ok": False, "error": "笔记不足"})
    result = executor.invoke_direct("consolidate_notes", note_ids=["a", "b"], topic="X")
    assert result["ok"] is False
    assert "笔记不足" in (result["error"] or "")
