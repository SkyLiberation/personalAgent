"""HARNESS-001 product baseline for neutral-request plan review semantics."""

from __future__ import annotations

from uuid import uuid4

from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _post_json,
)
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


def test_harness_001_neutral_formal_plan_waits_before_execution(
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
) -> None:
    user_request = (
        "请只基于 OpenAI 官方开发者文档、Google Gemini CLI 官方 GitHub 仓库和 "
        "NousResearch Hermes Agent 官方 GitHub 仓库，比较它们在复杂任务中如何保持"
        "未完成工作、更新进度和恢复上下文，并结合本工程给出有来源的采用与不采用建议。"
        "不要启动后台任务。"
    )
    assert all(
        directive not in user_request.lower()
        for directive in (
            "计划",
            "步骤",
            "确认",
            "auto",
            "直接开始",
            "无需等待",
            "无需等我",
            "planner",
            "workflow",
            "investigationproject",
        )
    )
    conversation_id = f"harness-001-{uuid4().hex[:8]}"
    result = _post_json(
        f"{live_web_process.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": user_request}],
        },
    )
    trace = _get_json(
        f"{live_web_process.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}"
    )
    report = {
        "case_id": "HARNESS-001",
        "conversation_id": conversation_id,
        "user_request": user_request,
        "result": result,
        "trace": trace,
    }
    settings = live_web_process.settings
    product_evidence_recorder.capture(
        nodeid=(
            "evals/product_baselines/test_harness_001_default_plan_review.py::"
            "test_harness_001_neutral_formal_plan_waits_before_execution"
        ),
        identity=ProductEvidenceIdentity(
            case_id="HARNESS-001",
            role=product_evidence_role("HARNESS-001"),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="default",
            ),
            user_input_digest=canonical_evidence_digest(user_request),
            initial_state_digest=canonical_evidence_digest({
                "seeded_facts": (),
            }),
            config_cohort=canonical_evidence_digest({
                "structured_model": settings.structured.model,
                "interaction_policy_revision": (
                    settings.interaction_loop.policy_revision
                ),
                "max_model_turns": settings.interaction_loop.max_model_turns,
                "max_tool_calls": settings.interaction_loop.max_tool_calls,
                "max_total_tokens": settings.interaction_loop.max_total_tokens,
            }),
            grader_version="harness-001-assertions-v1",
        ),
        report=report,
    )

    working_plan = result.get("working_plan")
    if working_plan is None:
        answer = str(result["message"]["content"])
        assert result["disposition"] == "answer"
        assert all(name in answer for name in ("OpenAI", "Gemini", "Hermes"))
        return
    assert result["disposition"] == "plan_ready", (
        "默认模式生成正式计划后没有停在用户审阅边界"
    )
    assert trace["execution_order"] == [], (
        "用户看到并接受正式计划前已经执行了动作"
    )
    assert all(
        step["status"] == "pending"
        for step in working_plan["steps"]
    )
