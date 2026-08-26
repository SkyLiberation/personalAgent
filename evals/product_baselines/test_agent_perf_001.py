"""AGENT-PERF-001 same-cohort product measurements by task family."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any
from urllib.parse import urlencode, urlparse

import pytest

from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _post_json,
)
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = pytest.mark.integration
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)

_GRADER_VERSION = "agent-perf-001-user-outcome-v1"
_DATASET_REVISION = "agent-perf-001-20x3-v1"


@dataclass(frozen=True, slots=True)
class _Scenario:
    family: str

    @property
    def case_id(self) -> str:
        return f"AGENT-PERF-001-{self.family.upper()}"


_SCENARIOS = (
    _Scenario("direct"),
    _Scenario("plan"),
    _Scenario("memory"),
)


def _turn(
    server: LiveWebProcess,
    *,
    user_id: str,
    conversation_id: str,
    text: str,
) -> dict[str, Any]:
    return _post_json(
        f"{server.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "messages": [{"role": "user", "content": text}],
        },
    )


def _trace(
    server: LiveWebProcess,
    *,
    user_id: str,
    turn: dict[str, Any],
) -> dict[str, Any]:
    return _get_json(
        f"{server.base_url}/api/conversation/runs/"
        f"{turn['interaction_run_ref']}?"
        + urlencode({"user_id": user_id})
    )


def _capture_text(
    server: LiveWebProcess,
    *,
    user_id: str,
    text: str,
) -> dict[str, Any]:
    return _post_json(
        f"{server.base_url}/api/tools/capture_text/execute",
        {
            "tenant_id": "personal-agent",
            "user_id": user_id,
            "kwargs": {
                "text": text,
                "user_id": user_id,
                "source_type": "text",
            },
        },
    )


def _request(scenario: _Scenario, repetition: int) -> tuple[str, str | None]:
    marker = f"PERF-{scenario.family.upper()}-{repetition:02d}-7Q9X"
    if scenario.family == "direct":
        return (
            f"请简洁确认本次公开测试标记 {marker}，只说明已收到该标记。",
            marker,
        )
    if scenario.family == "plan":
        return (
            "我要整理一次发布评审，最终需要风险、回滚条件和下一步建议。"
            f"本次公开评审标记是 {marker}。先只列出可供我查看和调整的剩余步骤，"
            "等我补充现场事实后再继续；不要创建后台任务。",
            marker,
        )
    return (
        f"我保存的 PERF-MEMORY-{repetition:02d} 项目验收标记是什么？请给出原文依据。",
        marker,
    )


def _config_cohort(server: LiveWebProcess, *, family: str) -> str:
    settings = server.settings
    return canonical_evidence_digest({
        "structured_model": settings.structured.model,
        "structured_provider_host": urlparse(
            settings.structured.base_url or ""
        ).hostname,
        "structured_output_transport": settings.structured.output_transport,
        "interaction_policy_revision": settings.interaction_loop.policy_revision,
        "max_model_turns": settings.interaction_loop.max_model_turns,
        "max_tool_calls": settings.interaction_loop.max_tool_calls,
        "max_total_tokens": settings.interaction_loop.max_total_tokens,
        "formal_entrypoint": "POST /api/conversation/turn",
        "persistence": "production-postgres-composition",
        "dataset_revision": _DATASET_REVISION,
        "task_family": family,
        "streaming": False,
    })


@pytest.mark.parametrize("repetition", range(1, 21), ids=lambda value: f"run-{value}")
@pytest.mark.parametrize(
    "scenario",
    _SCENARIOS,
    ids=lambda scenario: scenario.family,
)
def test_agent_perf_001_same_cohort_user_outcome(
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    scenario: _Scenario,
    repetition: int,
) -> None:
    user_id = f"agent-perf-{scenario.family}-{repetition:02d}"
    request_text, marker = _request(scenario, repetition)
    setup_duration = 0.0
    initial_state: dict[str, Any] = {"isolated_user": True}
    if scenario.family == "memory":
        seed = (
            f"PERF-MEMORY-{repetition:02d} 项目的验收标记是 {marker}，"
            "它属于本次个人验收资料。"
        )
        setup_started = perf_counter()
        seeded = _capture_text(
            live_web_process,
            user_id=user_id,
            text=seed,
        )
        setup_duration = perf_counter() - setup_started
        assert seeded["ok"] is True
        initial_state["seed_digest"] = canonical_evidence_digest(seed)

    started = perf_counter()
    result = _turn(
        live_web_process,
        user_id=user_id,
        conversation_id=f"agent-perf-{scenario.family}-{repetition:02d}",
        text=request_text,
    )
    duration = perf_counter() - started
    trace = _trace(
        live_web_process,
        user_id=user_id,
        turn=result,
    )
    answer = str(result.get("message", {}).get("content", ""))
    if scenario.family == "direct":
        delivered = result.get("disposition") == "answer" and marker in answer
        required_capability = None
    elif scenario.family == "plan":
        plan = result.get("working_plan")
        delivered = (
            result.get("disposition") == "plan_ready"
            and isinstance(plan, dict)
            and bool(plan.get("steps"))
            and result.get("project_reference") is None
        )
        required_capability = None
    else:
        required_capability = "search_personal_knowledge"
        delivered = (
            result.get("disposition") == "answer"
            and marker in answer
            and any(
                isinstance(item, dict)
                and item.get("capability_id") == required_capability
                and item.get("status") == "succeeded"
                and marker in str(item.get("payload"))
                for item in trace.get("inputs", [])
            )
        )
    failure_class = "delivered" if delivered else f"{scenario.family}_result_missing"
    report = {
        "case_id": scenario.case_id,
        "task_family": scenario.family,
        "repetition": repetition,
        "natural_user_text": request_text,
        "initial_state": initial_state,
        "result": result,
        "interaction_trace": trace,
        "result_metrics": {
            "delivered": delivered,
            "failure_class": failure_class,
            "end_to_end_seconds": round(duration, 6),
            "first_user_visible_seconds": round(duration, 6),
            "first_visible_equals_response_completion": True,
            "streaming_available": False,
            "setup_seconds_excluded": round(setup_duration, 6),
            "usage": trace.get("usage"),
            "required_capability": required_capability,
        },
    }
    product_evidence_recorder.capture(
        nodeid=(
            "evals/product_baselines/test_agent_perf_001.py::"
            "test_agent_perf_001_same_cohort_user_outcome"
        ),
        identity=ProductEvidenceIdentity(
            case_id=scenario.case_id,
            role="baseline",
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=user_id,
            ),
            user_input_digest=canonical_evidence_digest(request_text),
            initial_state_digest=canonical_evidence_digest(initial_state),
            config_cohort=_config_cohort(
                live_web_process,
                family=scenario.family,
            ),
            grader_version=_GRADER_VERSION,
        ),
        report=report,
    )
    assert delivered, report["result_metrics"]
