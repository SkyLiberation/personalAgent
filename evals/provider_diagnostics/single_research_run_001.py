"""Run one bounded GPT Researcher task through the production AgentGateway."""

from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from time import monotonic, perf_counter, sleep
from typing import Any, get_args
from urllib.parse import urlparse
from uuid import uuid4

from evals.e2e_quality.trace_archive import TraceArchive
from personal_agent.agents import AgentGateway
from personal_agent.agents.gpt_researcher_a2a import (
    GPTResearcherA2AAdapter,
    _status_from_a2a,
)
from personal_agent.application.artifacts.service import ArtifactService
from personal_agent.capabilities.contracts.grants import (
    DelegationGrant,
    GrantDependencySet,
)
from personal_agent.governance.policy import PolicyEngine
from personal_agent.infra.storage.postgres_agent_run_store import (
    PostgresAgentRunStore,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.agent import (
    ChildAgentRunProjection,
    ChildAgentRunRecord,
    ChildAgentRunStatus,
    AgentGatewayContext,
    AgentTask,
)
from personal_agent.kernel.contracts.resource import OperationScope, ResourceSelector
from personal_agent.kernel.contracts.scope import interaction_execution_scope


CASE_ID = "SINGLE-RESEARCH-RUN-001"
GRADER_VERSION = "single-research-run-provider-diagnostic-v1"
TERMINAL_STATUSES = {
    "completed",
    "completed_degraded",
    "cancelled",
    "failed",
    "timed_out",
}
URL_PATTERN = re.compile(r"https?://[^\s)\]>}\"']+")
TASK_TEXT = """请完成一次独立研究任务，并输出中文 Markdown 报告。

比较以下三个官方契约：
1. Gemini Deep Research agent；
2. OpenAI deep research 与 Responses API 的后台运行契约；
3. OpenAI Agents SDK Runner 的 Agent loop。

只使用 ai.google.dev、developers.openai.com 和 github.com/openai/openai-agents-python
下的官方页面。报告必须包含可直接访问的 URL，并至少覆盖 Gemini 与 OpenAI 两个独立来源组。

报告回答三个问题：
- 谁拥有 Plan、Search、Read、Iterate 和最终输出循环；
- 调用方应拥有哪些身份、权限、生命周期、取消、Verification 与 Completion 边界；
- 当前 InvestigationProject 与 GPT Researcher 同时规划、检索和修复时，应保留什么、删除什么、
  如何迁移，以及迁移失败时如何退出。

请按“机制比较、信任边界、迁移建议、限制”组织，不要引用博客、教程或搜索结果摘要。
""".strip()


def _source_groups(report: str) -> tuple[str, ...]:
    groups: set[str] = set()
    for raw_url in URL_PATTERN.findall(report):
        parsed = urlparse(raw_url.rstrip(".,;，。；"))
        host = (parsed.hostname or "").casefold()
        path = parsed.path.casefold()
        if host == "ai.google.dev":
            groups.add("gemini")
        elif host == "developers.openai.com":
            groups.add("openai_deep_research")
        elif host == "github.com" and path.startswith(
            "/openai/openai-agents-python"
        ):
            groups.add("openai_agents_sdk")
    return tuple(sorted(groups))


def _term_group_covered(report: str, alternatives: tuple[str, ...]) -> bool:
    normalized = report.casefold()
    return any(term.casefold() in normalized for term in alternatives)


def score_research_report(report: str) -> dict[str, Any]:
    source_groups = _source_groups(report)
    mechanism_coverage = all((
        _term_group_covered(report, ("plan", "规划")),
        _term_group_covered(report, ("search", "搜索", "检索")),
        _term_group_covered(report, ("iterate", "迭代")),
        _term_group_covered(report, ("output", "输出", "报告")),
    ))
    trust_coverage = sum(
        _term_group_covered(report, alternatives)
        for alternatives in (
            ("责任主体", "owner"),
            ("权限", "authorization", "permission"),
            ("生命周期", "lifecycle"),
            ("verification", "验证"),
            ("completion", "完成门禁"),
        )
    ) >= 3
    migration_coverage = sum(
        _term_group_covered(report, alternatives)
        for alternatives in (
            ("迁移", "migration"),
            ("删除", "remove", "delete"),
            ("保留", "retain", "keep"),
            ("退出", "撤回", "exit", "rollback"),
        )
    ) >= 3
    independent_source_coverage = (
        "gemini" in source_groups
        and any(group.startswith("openai_") for group in source_groups)
    )
    passed = (
        len(report) >= 800
        and independent_source_coverage
        and mechanism_coverage
        and trust_coverage
        and migration_coverage
    )
    return {
        "passed": passed,
        "report_chars": len(report),
        "source_groups": list(source_groups),
        "independent_source_coverage": independent_source_coverage,
        "mechanism_coverage": mechanism_coverage,
        "trust_boundary_coverage": trust_coverage,
        "migration_coverage": migration_coverage,
    }


def lifecycle_contract_facts(run: ChildAgentRunRecord | None) -> dict[str, Any]:
    typed_statuses = set(get_args(ChildAgentRunStatus))
    projection_fields = {field.name for field in fields(ChildAgentRunProjection)}
    metadata: dict[str, Any] = {}
    if run is not None:
        raw_metadata = run.projection.result.get("metadata")
        if isinstance(raw_metadata, dict):
            metadata = raw_metadata
    provider_usage = metadata.get("usage")
    return {
        "failed_status_typed": "failed" in typed_statuses,
        "cancelled_status_typed": "cancelled" in typed_statuses,
        "timed_out_status_typed": "timed_out" in typed_statuses,
        "provider_timeout_maps_to_typed_status": (
            _status_from_a2a("timed_out") == "timed_out"
        ),
        "projection_error_typed": "error" in projection_fields,
        "projection_usage_typed": "usage" in projection_fields,
        "provider_usage_observed": isinstance(provider_usage, dict),
        "provider_usage": provider_usage if isinstance(provider_usage, dict) else None,
    }


def lifecycle_contract_passed(facts: dict[str, Any]) -> bool:
    return all((
        facts["failed_status_typed"],
        facts["cancelled_status_typed"],
        facts["timed_out_status_typed"],
        facts["provider_timeout_maps_to_typed_status"],
        facts["projection_error_typed"],
        facts["projection_usage_typed"],
        facts["provider_usage_observed"],
    ))


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _grant(*, action_ref: str, task_text: str, timeout_seconds: int) -> DelegationGrant:
    task_digest = _digest(task_text)
    return DelegationGrant(
        request_id=f"provider-diagnostic:{CASE_ID}",
        action_ref=action_ref,
        granted_resource_selector=ResourceSelector(),
        granted_operation_scope=OperationScope(
            operations=frozenset({"delegate"})
        ),
        granted_data_egress="content",
        granted_credential_mode="none",
        retry_family_id=f"provider-diagnostic:{task_digest[:16]}",
        dependency_set=GrantDependencySet(
            task_revision=1,
            goal_definition_fingerprint=task_digest,
            action_fingerprint=task_digest,
            capability_definition_revision=1,
            provider_binding_revision=1,
            authority_revision=1,
            policy_bundle_hash="provider-diagnostic-v1",
        ),
        agent_binding_ref="local:gpt_researcher",
        bounded_sub_goal=task_text,
        token_budget=20_000,
        cost_budget=20.0,
        time_budget_seconds=timeout_seconds,
        completion_contract="one evidence-backed Markdown report",
        authorization_digest=_digest(f"authorization\0{task_text}"),
        execution_command_digest=_digest(f"execution\0{task_text}"),
    )


def _run_projection(run: ChildAgentRunRecord | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "agent_run_id": run.definition.agent_run_id,
        "agent_id": run.definition.agent_id,
        "submission_key": run.definition.submission_key,
        "status": run.projection.status,
        "external_task_id": run.projection.external_task_id,
        "error": run.projection.error,
        "artifact_count": len(run.artifact_index.artifacts),
        "event_types": [event.type for event in run.events],
    }


def run_diagnostic() -> tuple[bool, Path, dict[str, Any]]:
    settings = Settings.from_env()
    if not settings.gpt_researcher_a2a.enabled:
        raise RuntimeError("GPT Researcher A2A is disabled in the current configuration")
    database_url = (
        os.environ.get("PERSONAL_AGENT_PROVIDER_DIAGNOSTIC_POSTGRES_URL")
        or settings.postgres_url
    )
    if not database_url:
        raise RuntimeError("production Postgres configuration is required")

    timeout_seconds = max(1, int(settings.gpt_researcher_a2a.timeout_seconds))
    execution_suffix = uuid4().hex[:12]
    execution_id = f"provider-diagnostic-{execution_suffix}"
    action_ref = "single-research-run"
    submission_key = f"{CASE_ID.lower()}:{execution_suffix}"
    context = AgentGatewayContext(
        execution_scope=interaction_execution_scope(
            tenant_id="personal-agent",
            user_id=f"provider-diagnostic-{execution_suffix}",
            execution_id=execution_id,
            task_id=action_ref,
        ),
        source_platform="provider_diagnostic",
    )
    task = AgentTask(task_text=TASK_TEXT, task_type="research")
    store = PostgresAgentRunStore(database_url)
    artifact_service = ArtifactService(settings)
    gateway = AgentGateway(policy_engine=PolicyEngine(), store=store)
    gateway.register(
        GPTResearcherA2AAdapter(
            settings.gpt_researcher_a2a,
            artifact_service,
        )
    )

    archive = TraceArchive(
        Path("data/e2e_traces/provider_diagnostics") / CASE_ID.lower(),
        manifest_metadata={
            "evidence_class": "provider_diagnostic",
            "grader_version": GRADER_VERSION,
            "provider": "gpt_researcher_a2a",
            "provider_host": urlparse(
                settings.gpt_researcher_a2a.endpoint
            ).hostname,
            "database_host": urlparse(database_url).hostname,
            "database_name": urlparse(database_url).path.lstrip("/"),
            "timeout_seconds": timeout_seconds,
            "max_search_results": settings.gpt_researcher_a2a.max_search_results,
            "max_concurrent_runs": (
                settings.gpt_researcher_a2a.max_concurrent_runs
            ),
            "structured_model": settings.structured.model,
            "structured_output_transport": settings.structured.output_transport,
        },
    )
    nodeid = (
        "evals/provider_diagnostics/single_research_run_001.py::"
        "run_diagnostic"
    )
    started = perf_counter()
    run: ChildAgentRunRecord | None = None
    report = ""
    timed_out = False
    provider_error: dict[str, str] | None = None
    cancellation_error: dict[str, str] | None = None
    store_error: dict[str, str] | None = None
    try:
        run = gateway.submit(
            "gpt_researcher",
            task,
            context,
            _grant(
                action_ref=action_ref,
                task_text=TASK_TEXT,
                timeout_seconds=timeout_seconds,
            ),
            submission_key=submission_key,
        )
        deadline = monotonic() + timeout_seconds
        while run.projection.status not in TERMINAL_STATUSES:
            if monotonic() >= deadline:
                timed_out = True
                run = gateway.timeout(run.definition.agent_run_id, context)
                break
            sleep(min(3.0, max(0.0, deadline - monotonic())))
            run = gateway.poll(run.definition.agent_run_id, context)
        report = str(run.projection.result.get("report") or "")
        if not report and run.artifact_index.artifacts:
            report = artifact_service.read_text(
                run.artifact_index.artifacts[0].artifact_ref,
                principal=context.execution_scope.principal,
                owner=context.execution_scope.principal,
            )
    except Exception as exc:  # the archive owns the typed diagnostic failure
        provider_error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        if run is not None and run.projection.status not in TERMINAL_STATUSES:
            try:
                run = gateway.cancel(run.definition.agent_run_id, context)
            except Exception as cancel_exc:
                cancellation_error = {
                    "type": type(cancel_exc).__name__,
                    "message": str(cancel_exc),
                }

    try:
        scoped_runs = gateway.list_runs(
            run_id=execution_id,
            agent_id="gpt_researcher",
        )
    except Exception as exc:
        scoped_runs = ()
        store_error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    report_score = score_research_report(report)
    lifecycle_facts = lifecycle_contract_facts(run)
    lifecycle_passed = lifecycle_contract_passed(lifecycle_facts)
    one_run_record = len(scoped_runs) == 1
    completed = run is not None and run.projection.status == "completed"
    passed = (
        provider_error is None
        and store_error is None
        and not timed_out
        and one_run_record
        and completed
        and bool(run and run.artifact_index.artifacts)
        and report_score["passed"]
        and lifecycle_passed
    )
    elapsed = round(perf_counter() - started, 6)
    trace = {
        "case_id": CASE_ID,
        "grader_version": GRADER_VERSION,
        "evidence_class": "provider_diagnostic",
        "task_text": TASK_TEXT,
        "execution_id": execution_id,
        "submission_key": submission_key,
        "elapsed_seconds": elapsed,
        "timed_out": timed_out,
        "provider_error": provider_error,
        "store_error": store_error,
        "cancellation_error": cancellation_error,
        "one_run_record": one_run_record,
        "scoped_run_count": len(scoped_runs),
        "run": _run_projection(run),
        "report": report,
        "report_score": report_score,
        "lifecycle_contract": lifecycle_facts,
        "lifecycle_contract_passed": lifecycle_passed,
        "research_capability_passed": bool(
            one_run_record and completed and report_score["passed"]
        ),
        "passed": passed,
    }
    archive.write_trace(nodeid=nodeid, case_id=CASE_ID, trace=trace)
    archive.record_test_result(
        nodeid=nodeid,
        phase="call",
        outcome="passed" if passed else "failed",
        duration_seconds=elapsed,
        detail=None if passed else json.dumps({
            "provider_error": provider_error,
            "store_error": store_error,
            "timed_out": timed_out,
            "run": _run_projection(run),
            "report_score": report_score,
            "lifecycle_contract": lifecycle_facts,
        }, ensure_ascii=False),
    )
    archive.finalize(exit_status=0 if passed else 1)
    return passed, archive.run_dir, trace


def main() -> int:
    passed, archive_dir, trace = run_diagnostic()
    print(json.dumps({
        "passed": passed,
        "research_capability_passed": trace["research_capability_passed"],
        "lifecycle_contract_passed": trace["lifecycle_contract_passed"],
        "run": trace["run"],
        "report_score": trace["report_score"],
        "lifecycle_contract": trace["lifecycle_contract"],
        "provider_error": trace["provider_error"],
        "store_error": trace["store_error"],
        "timed_out": trace["timed_out"],
        "archive_dir": str(archive_dir),
    }, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
