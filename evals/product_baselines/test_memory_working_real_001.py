"""MEMORY-WORKING-REAL-001: real GitHub reads survive steering and restart."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest

from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _new_github_mcp_web_process,
    _post_json,
    _require_live_dependencies,
    _yield_started_server,
)
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)

_CASE_ID = "MEMORY-WORKING-REAL-001"
_MODEL_TURNS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS"
_TOOL_CALLS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS"
_TOTAL_TOKENS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS"


@pytest.fixture(scope="module")
def live_working_memory_github_process(
    server_temp_dir: Path,
) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    server = _new_github_mcp_web_process(
        server_temp_dir / "memory-working-real-github",
        settings,
    )
    server.child_env[_MODEL_TURNS_ENV] = str(settings.interaction_loop.max_model_turns)
    server.child_env[_TOOL_CALLS_ENV] = "2"
    server.child_env[_TOTAL_TOKENS_ENV] = "64000"
    yield from _yield_started_server(server)


def _turn(
    server: LiveWebProcess,
    *,
    user_id: str,
    conversation_id: str,
    messages: list[dict[str, str]],
) -> tuple[dict[str, object], dict[str, object]]:
    result = _post_json(
        f"{server.base_url}/api/conversation/turn",
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "interaction_mode": "auto",
            "messages": messages,
        },
    )
    trace = _get_json(
        f"{server.base_url}/api/conversation/runs/{result['interaction_run_ref']}"
        f"?user_id={user_id}"
    )
    return result, trace


def _github_file_reads(trace: dict[str, object]) -> list[dict[str, object]]:
    executed_action_ids = set(trace["execution_order"])
    return [
        item for item in trace["inputs"]
        if item.get("kind") == "tool_result"
        and item.get("capability_id") == "github.get_file_contents"
        and item.get("status") == "succeeded"
        and item.get("action_id") in executed_action_ids
    ]


def test_real_provider_observations_are_reused_after_restart_and_steering(
    live_working_memory_github_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    request: pytest.FixtureRequest,
) -> None:
    server = live_working_memory_github_process
    repetitions = int(os.getenv("MEMORY_WORKING_REAL_REPETITIONS", "5"))
    initial_request = (
        "请实际读取 GitHub 仓库 github/github-mcp-server 的 README.md、LICENSE "
        "和 SECURITY.md，每个文件最多访问一次。最终列出 README 一级标题、许可证名称"
        "和安全文档一级标题。直接开始，不要启动后台任务；如果本轮预算不足，保留已经"
        "取得的结果，下一轮继续，不要重新读取成功的文件。"
    )
    steering_request = (
        "继续完成并给出最终结果；新增要求：按 README、LICENSE、SECURITY 的顺序列出，"
        "其他要求不变。"
    )
    reports: list[dict[str, object]] = []
    for repetition in range(1, repetitions + 1):
        server.child_env[_TOOL_CALLS_ENV] = "2"
        server.child_env[_TOTAL_TOKENS_ENV] = "64000"
        server.restart()
        user_id = f"memory-working-real-{repetition}"
        conversation_id = f"memory-working-real-{repetition}-conversation"
        first_messages = [{"role": "user", "content": initial_request}]
        first, first_trace = _turn(
            server,
            user_id=user_id,
            conversation_id=conversation_id,
            messages=first_messages,
        )

        server.child_env[_TOOL_CALLS_ENV] = str(
            server.settings.interaction_loop.max_tool_calls
        )
        server.child_env[_TOTAL_TOKENS_ENV] = "128000"
        server.restart()
        second_messages = [
            *first_messages,
            {"role": "assistant", "content": str(first["message"]["content"])},
            {"role": "user", "content": steering_request},
        ]
        second, second_trace = _turn(
            server,
            user_id=user_id,
            conversation_id=conversation_id,
            messages=second_messages,
        )
        first_reads = _github_file_reads(first_trace)
        second_reads = _github_file_reads(second_trace)
        answer = str(second["message"]["content"])
        first_plan = first.get("working_plan")
        second_plan = second.get("working_plan")
        delivered = (
            first["disposition"] == "limitation"
            and bool(first_reads)
            and second["disposition"] == "answer"
            and "GitHub MCP Server" in answer
            and "MIT License" in answer
            and "SECURITY" in answer
            and "一级标题" in answer
            and "Security" in answer
            and len(first_reads) + len(second_reads) <= 3
            and isinstance(first_plan, dict)
            and isinstance(second_plan, dict)
            and first_plan.get("plan_id") == second_plan.get("plan_id")
        )
        reports.append({
            "repetition": repetition,
            "delivered": delivered,
            "first": first,
            "first_trace": first_trace,
            "second": second,
            "second_trace": second_trace,
            "first_read_count": len(first_reads),
            "second_read_count": len(second_reads),
        })
    role = product_evidence_role(_CASE_ID)
    product_evidence_recorder.capture(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id=_CASE_ID,
            role=role,
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="memory-working-real-cohort",
            ),
            user_input_digest=canonical_evidence_digest(
                (initial_request, steering_request, repetitions)
            ),
            initial_state_digest=canonical_evidence_digest({
                "repository": "github/github-mcp-server",
                "paths": ["README.md", "LICENSE", "SECURITY.md"],
                "first_turn_tool_budget": 2,
            }),
            config_cohort="real-github+working-plan-observations-" + role,
            grader_version="memory-working-real-001-deterministic-v3",
        ),
        report={
            "repetitions": repetitions,
            "delivered_count": sum(bool(item["delivered"]) for item in reports),
            "reports": reports,
        },
    )

    assert all(item["delivered"] for item in reports), [
        item["repetition"] for item in reports if not item["delivered"]
    ]
