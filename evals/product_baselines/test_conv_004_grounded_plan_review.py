"""CONV-004 product E2E for evidence-grounded plan review."""

from __future__ import annotations

import json

import pytest

from evals.e2e_quality.test_release_user_outcomes import _get_json, _post_json
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = pytest.mark.integration
pytest_plugins = (
    "evals.e2e_quality.test_release_user_outcomes",
    "evals.e2e_quality.test_product_capability_outcomes",
)

_MAX_MODEL_TURNS = 7
_MAX_TOTAL_TOKENS = 128_000


def test_conv_004_reads_official_facts_before_presenting_reviewable_plan(
    live_web_search_process,
    product_evidence_recorder: ProductEvidenceRecorder,
) -> None:
    live_web_search_process.child_env[
        "PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS"
    ] = str(_MAX_MODEL_TURNS)
    live_web_search_process.child_env[
        "PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS"
    ] = str(_MAX_TOTAL_TOKENS)
    live_web_search_process.child_env["PERSONAL_AGENT_MCP_SERVERS"] = (
        '{"enabled":false}'
    )
    live_web_search_process.child_env["PERSONAL_AGENT_GITHUB_MCP_ENABLED"] = "false"
    live_web_search_process.restart()
    user_request = (
        "请先查阅 Gemini CLI 官方 Plan Mode 文档 "
        "https://geminicli.com/docs/cli/plan-mode/，确认计划阶段的只读边界和允许的工具类型，"
        "然后给我一份可审阅的本工程 Plan 优化计划。"
        "计划中必须写出查到的具体约束和来源；在我确认前不要修改任何数据，也不要启动"
        "后台任务。"
    )
    conversation_id = "conv-004-grounded-plan-review"
    result = _post_json(
        f"{live_web_search_process.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": user_request}],
            "interaction_mode": "default",
        },
    )
    trace = _get_json(
        f"{live_web_search_process.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}"
    )
    working_plan = result.get("working_plan")
    plan_text = json.dumps(working_plan, ensure_ascii=False).lower()
    tool_results = [
        item for item in trace["inputs"] if item["kind"] == "tool_result"
    ]
    metrics = {
        "plan_visible": isinstance(working_plan, dict),
        "read_before_plan_review": bool(trace["execution_order"]),
        "official_source_in_plan": (
            "github.com/google-gemini/gemini-cli" in plan_text
            or "docs/cli/plan-mode.md" in plan_text
            or "geminicli.com/docs/cli/plan-mode" in plan_text
        ),
        "read_only_constraint_in_plan": any(
            term in plan_text for term in ("只读", "read-only", "read only")
        ),
    }
    settings = live_web_search_process.settings
    report = {
        "case_id": "CONV-004",
        "user_request": user_request,
        "result": result,
        "trace": trace,
        "tool_results": tool_results,
        "metrics": metrics,
    }
    product_evidence_recorder.capture(
        nodeid=(
            "evals/product_baselines/test_conv_004_grounded_plan_review.py::"
            "test_conv_004_reads_official_facts_before_presenting_reviewable_plan"
        ),
        identity=ProductEvidenceIdentity(
            case_id="CONV-004",
            role=product_evidence_role("CONV-004"),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="default",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="default",
            ),
            user_input_digest=canonical_evidence_digest(user_request),
            initial_state_digest=canonical_evidence_digest({"seeded_facts": ()}),
            config_cohort=canonical_evidence_digest({
                "structured_model": settings.structured.model,
                "interaction_policy_revision": (
                    settings.interaction_loop.policy_revision
                ),
                "web_search_provider": settings.web_search.provider,
                "github_mcp_enabled": False,
                "max_model_turns": _MAX_MODEL_TURNS,
                "max_tool_calls": settings.interaction_loop.max_tool_calls,
                "max_total_tokens": _MAX_TOTAL_TOKENS,
            }),
            grader_version="conv-004-deterministic-v5",
        ),
        report=report,
    )

    assert result["disposition"] == "plan_ready"
    assert metrics["plan_visible"]
    assert metrics["read_before_plan_review"], (
        "Agent 在提交可审阅计划前没有执行用户要求的官方资料读取"
    )
    assert tool_results
    assert all(
        item["capability_id"] in {
            "web_search",
            "github.get_file_contents",
            "read_action_output",
            "verify_interaction_draft",
        }
        for item in tool_results
    )
    assert metrics["official_source_in_plan"]
    assert metrics["read_only_constraint_in_plan"]
    assert metrics["no_background_project"]
