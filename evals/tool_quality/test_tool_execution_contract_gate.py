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
from personal_agent.kernel.contracts.scope import interaction_execution_scope
from personal_agent.kernel.models import WebSearchResult
from personal_agent.tools import (
    build_capture_text_tool,
    build_graph_search_tool,
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


def _executor_and_calls() -> tuple[ToolExecutor, CountingCalls]:
    calls = CountingCalls()
    executor = ToolExecutor()
    executor.register(build_graph_search_tool(FakeGraphStore(calls)))
    executor.register(build_web_search_tool(Settings(), FakeWebProvider(calls)))
    executor.register(build_capture_text_tool(FakeCaptureResultFactory(calls)))
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
        execution_scope = interaction_execution_scope(
            tenant_id="tool-quality",
            workspace_id="tool-quality",
            user_id="alice",
            execution_id=case.id,
            thread_id=case.id,
        )
        first = executor.invoke_direct(
            case.tool_name,
            execution_scope=execution_scope,
            **case.args,
        )
        repeat = (
            executor.invoke_direct(
                case.tool_name,
                execution_scope=execution_scope,
                **case.args,
            )
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
