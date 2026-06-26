"""Offline tool execution contract gate.

This gate invokes selected tools through ToolExecutor/ToolGateway using fake
dependencies. It validates artifact shape, error kind, confirmation behavior,
and idempotency replay without touching a real database or network.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from personal_agent.governance import ToolExecutor
from personal_agent.kernel.config import Settings
from personal_agent.kernel.models import WebSearchResult
from personal_agent.tools import (
    build_capture_text_tool,
    build_delete_note_tool,
    build_graph_search_tool,
    build_restore_note_tool,
    build_web_search_tool,
)

from .dataset import (
    ToolExecutionRunOutput,
    default_execution_cases_path,
    load_execution_cases,
)
from .scorer import score_execution_all


class CountingCalls:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def bump(self, name: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + 1


class FakeGraphStore:
    def __init__(self, calls: CountingCalls) -> None:
        self._calls = calls

    def configured(self) -> bool:
        return False

    def ask(self, question: str, user_id: str):
        self._calls.bump("graph.ask")
        raise AssertionError("graph.ask should not be reached when graph is disabled.")


class FakeWebProvider:
    def __init__(self, calls: CountingCalls) -> None:
        self._calls = calls

    def search(self, query: str, limit: int = 5) -> list[WebSearchResult]:
        self._calls.bump("web.search")
        return [
            WebSearchResult(
                title="OpenAI news",
                url="https://example.com/openai-news",
                snippet="A short public web result.",
                source="fake",
            )
        ][:limit]


class FakeCaptureResultFactory:
    def __init__(self, calls: CountingCalls) -> None:
        self._calls = calls

    def __call__(self, **kwargs):
        self._calls.bump("capture.execute")
        text = str(kwargs["text"])
        return SimpleNamespace(
            note=SimpleNamespace(
                id="note-capture-1",
                body=SimpleNamespace(
                    title="DNS",
                    summary="DNS summary",
                    content=text,
                ),
                graph_sync=SimpleNamespace(status="pending"),
            )
        )


class FakeMemory:
    def __init__(self, calls: CountingCalls) -> None:
        self._calls = calls

    def build_delete_confirmation(self, note_id: str, user_id: str):
        self._calls.bump("memory.build_delete_confirmation")
        return SimpleNamespace(
            ok=True,
            title="DNS note",
            summary="DNS summary",
            description="Delete DNS note?",
            message="请确认删除。",
        )

    def delete_note_confirmed(
        self,
        note_id: str,
        user_id: str,
        *,
        delete_reason: str = "",
    ):
        self._calls.bump("memory.delete_note_confirmed")
        return SimpleNamespace(
            ok=True,
            snapshot_id="snapshot-1",
            title="DNS note",
            message="已删除。",
            graph_cleaned=True,
            graph_failed=False,
        )

    def restore_note_confirmed(
        self,
        *,
        note_id: str | None = None,
        snapshot_id: str | None = None,
        user_id: str = "default",
    ):
        self._calls.bump("memory.restore_note_confirmed")
        return SimpleNamespace(
            ok=True,
            note_id=note_id or "note-1",
            snapshot_id=snapshot_id or "snapshot-1",
            title="DNS note",
            message="已恢复。",
            restored_notes=[],
            restored_reviews=[],
        )


def _executor_and_calls() -> tuple[ToolExecutor, CountingCalls]:
    calls = CountingCalls()
    executor = ToolExecutor()
    executor.register(build_graph_search_tool(FakeGraphStore(calls)))
    executor.register(build_web_search_tool(Settings(), FakeWebProvider(calls)))
    executor.register(build_capture_text_tool(FakeCaptureResultFactory(calls)))
    memory = FakeMemory(calls)
    executor.register(build_delete_note_tool(memory))
    executor.register(build_restore_note_tool(memory))
    return executor, calls


def _project_result(
    *,
    tool_name: str,
    result: dict,
    calls: CountingCalls,
    repeat_result: dict | None = None,
) -> ToolExecutionRunOutput:
    data = result.get("data")
    return ToolExecutionRunOutput(
        tool_name=tool_name,
        ok=bool(result.get("ok")),
        error_kind=result.get("error_kind"),
        data_keys=sorted(data.keys()) if isinstance(data, dict) else [],
        evidence_count=len(result.get("evidence") or []),
        repeat_ok=(
            bool(repeat_result.get("ok"))
            if repeat_result is not None else None
        ),
        repeat_error_kind=(
            repeat_result.get("error_kind")
            if repeat_result is not None else None
        ),
        call_counts=dict(calls.counts),
    )


def test_tool_execution_contract_meets_quality_baseline():
    cases = load_execution_cases(default_execution_cases_path())
    runs: dict[str, ToolExecutionRunOutput] = {}

    for case in cases:
        executor, calls = _executor_and_calls()
        first = executor.invoke_direct(case.tool_name, **case.args)
        repeat = (
            executor.invoke_direct(case.tool_name, **case.args)
            if case.repeat_same_call else None
        )
        runs[case.id] = _project_result(
            tool_name=case.tool_name,
            result=first,
            calls=calls,
            repeat_result=repeat,
        )

    report = score_execution_all(cases, runs)
    baseline = json.loads(
        (Path(__file__).parent / "execution_baseline.json").read_text(encoding="utf-8")
    )
    failures = report.check_thresholds(baseline)
    assert not failures, f"regression:\n{report.summary()}\nfailures={failures}"
