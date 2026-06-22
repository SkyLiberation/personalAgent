from __future__ import annotations

from personal_agent.knowledge import ConsolidationResult
from personal_agent.tools import (
    ToolExecutor,
    build_consolidate_knowledge_tool,
    tool_governance,
)


class StubUseCase:
    def __init__(self, result: ConsolidationResult) -> None:
        self.result = result
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def test_consolidate_tool_is_topic_driven_low_risk_write():
    use_case = StubUseCase(ConsolidationResult(ok=True, topic="向量检索", note_id="n"))
    tool = build_consolidate_knowledge_tool(use_case)
    gov = tool_governance(tool)

    assert set(tool.args_schema.model_fields) == {"topic", "user_id"}
    assert gov.risk_level == "low"
    assert gov.requires_confirmation is False
    assert "write_longterm" in gov.side_effects


def test_consolidate_tool_delegates_selection_to_use_case():
    use_case = StubUseCase(ConsolidationResult(
        ok=True,
        topic="向量检索",
        note_id="summary-1",
        source_note_ids=["a", "b"],
        superseded=["a", "b"],
    ))
    executor = ToolExecutor()
    executor.register(build_consolidate_knowledge_tool(use_case))

    result = executor.invoke_direct(
        "consolidate_knowledge",
        topic="向量检索",
        user_id="alice",
    )

    assert result["ok"] is True
    assert result["data"]["note_id"] == "summary-1"
    assert use_case.calls == [{"topic": "向量检索", "user_id": "alice"}]


def test_consolidate_tool_propagates_use_case_failure():
    use_case = StubUseCase(ConsolidationResult(ok=False, topic="X", error="笔记不足"))
    executor = ToolExecutor()
    executor.register(build_consolidate_knowledge_tool(use_case))

    result = executor.invoke_direct("consolidate_knowledge", topic="X")

    assert result["ok"] is False
    assert "笔记不足" in (result["error"] or "")
