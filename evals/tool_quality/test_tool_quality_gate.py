"""Offline tool governance golden-set gate.

This gate validates business obligations encoded in tool governance metadata.
It does not invoke tools or require a database/network connection.
"""

from __future__ import annotations

import json
from pathlib import Path

from personal_agent.kernel.config import Settings
from personal_agent.tools import (
    build_capture_text_tool,
    build_capture_upload_tool,
    build_capture_url_tool,
    build_consolidate_knowledge_tool,
    build_create_research_subscription_tool,
    build_delete_note_tool,
    build_graph_search_tool,
    build_inspect_knowledge_gaps_tool,
    build_inspect_workflow_run_tool,
    build_retry_worker_task_tool,
    build_restore_note_tool,
    build_review_digest_tool,
    build_update_note_tool,
    build_web_search_tool,
    tool_governance,
)
from personal_agent.tools.research_pipeline import build_research_run_loop_tool

from .dataset import ToolRunOutput, default_cases_path, load_cases
from .scorer import score_all


class _NotInvoked:
    def __getattr__(self, name):
        def _method(*args, **kwargs):
            raise AssertionError(f"Tool golden gate must not invoke dependency {name!r}.")

        return _method


def _build_registered_tools():
    dependency = _NotInvoked()
    return [
        build_graph_search_tool(dependency),
        build_web_search_tool(Settings(), dependency, dependency),
        build_capture_text_tool(lambda **kwargs: dependency.capture_text(**kwargs)),
        build_capture_url_tool(dependency),
        build_capture_upload_tool(dependency),
        build_delete_note_tool(dependency),
        build_restore_note_tool(dependency),
        build_update_note_tool(dependency),
        build_consolidate_knowledge_tool(dependency),
        build_review_digest_tool(dependency),
        build_create_research_subscription_tool(dependency),
        build_research_run_loop_tool(dependency),
        build_inspect_workflow_run_tool(dependency),
        build_retry_worker_task_tool(dependency),
        build_inspect_knowledge_gaps_tool(dependency),
    ]


def _project_tool(tool) -> ToolRunOutput:
    governance = tool_governance(tool)
    return ToolRunOutput(
        tool_name=tool.name,
        exposure=governance.exposure,
        risk_level=governance.risk_level,
        requires_confirmation=governance.requires_confirmation,
        side_effects=list(governance.side_effects),
        permission_scope=governance.permission_scope,
        idempotency_key_required=governance.idempotency_key_required,
        audit_required=governance.audit_required,
        timeout_seconds=governance.timeout_seconds,
        max_retries=governance.max_retries,
        rate_limit_per_minute=governance.rate_limit_per_minute,
    )


def test_tool_governance_meets_quality_baseline():
    cases = load_cases(default_cases_path())
    runs = {
        tool.name: _project_tool(tool)
        for tool in _build_registered_tools()
    }
    missing = sorted({case.tool_name for case in cases} - set(runs))
    assert not missing, f"tool quality cases reference unregistered tools: {missing}"

    report = score_all(cases, runs)
    baseline = json.loads(
        (Path(__file__).parent / "baseline.json").read_text(encoding="utf-8")
    )
    failures = report.check_thresholds(baseline)
    assert not failures, f"regression:\n{report.summary()}\nfailures={failures}"
