"""CONV-001 product E2E for user-visible foreground-plan steering."""

from __future__ import annotations

import os
from uuid import uuid4

from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _post_json,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


def _turn(
    server: LiveWebProcess,
    *,
    conversation_id: str,
    messages: list[dict[str, str]],
) -> dict[str, object]:
    return _post_json(
        f"{server.base_url}/api/conversation/turn",
        {"conversation_id": conversation_id, "messages": messages},
    )


def _capture_memory_text(
    server: LiveWebProcess,
    *,
    text: str,
) -> dict[str, object]:
    return _post_json(
        f"{server.base_url}/api/tools/capture_text/execute",
        {
            "tenant_id": "personal-agent",
            "user_id": "default",
            "kwargs": {
                "text": text,
                "user_id": "default",
                "source_type": "text",
            },
        },
    )


def test_conv_001_frontstage_working_plan_is_visible_and_revisable(
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
) -> None:
    marker = uuid4().hex[:8]
    evidence_seed = os.environ.get("PERSONAL_AGENT_CONV_001_EVIDENCE_SEED")
    random_fact = (
        f"CONV-001-{evidence_seed}"
        if evidence_seed
        else f"CONV-001-{uuid4().hex[:12]}"
    )
    conversation_id = f"conv-001-{marker}"
    seeded_text = (
        f"我最近保存的项目验收标记是 {random_fact}，它属于计划功能验收资料。"
    )
    seeded = _capture_memory_text(
        live_web_process,
        text=seeded_text,
    )
    assert seeded["ok"] is True
    initial_request = (
        "我需要在当前对话里完成一项多步整理：先检查我最近保存的知识，归纳主要主题，"
        "列出涉及的验收标记，再找出明显缺口，最后给出下一步建议。请先给出我能查看的"
        "剩余步骤，先不要创建"
        "后台任务；等我调整后再继续。"
    )
    assert all(
        internal not in initial_request
        for internal in ("Tool", "Planner", "Workflow", "InvestigationProject")
    )
    first_messages = [{"role": "user", "content": initial_request}]
    first = _turn(
        live_web_process,
        conversation_id=conversation_id,
        messages=first_messages,
    )
    first_trace = _get_json(
        f"{live_web_process.base_url}/api/conversation/runs/"
        f"{first['interaction_run_ref']}"
    )

    revision_request = "把“找出明显缺口”改成“优先识别互相冲突的记录”，其他未完成步骤保持不变。"
    second_messages = [
        *first_messages,
        {"role": "assistant", "content": str(first["message"]["content"])},
        {"role": "user", "content": revision_request},
    ]
    second = _turn(
        live_web_process,
        conversation_id=conversation_id,
        messages=second_messages,
    )
    second_trace = _get_json(
        f"{live_web_process.base_url}/api/conversation/runs/"
        f"{second['interaction_run_ref']}"
    )
    live_web_process.restart()
    continue_request = (
        "按修改后的计划继续执行并完成，最后给我主题、涉及的验收标记、冲突检查和下一步建议。"
    )
    third_messages = [
        *second_messages,
        {"role": "assistant", "content": str(second["message"]["content"])},
        {"role": "user", "content": continue_request},
    ]
    third = _turn(
        live_web_process,
        conversation_id=conversation_id,
        messages=third_messages,
    )
    third_trace = _get_json(
        f"{live_web_process.base_url}/api/conversation/runs/"
        f"{third['interaction_run_ref']}"
    )
    final_answer = str(third["message"]["content"])
    result_metrics = {
        "revised_requirement_present": "冲突" in final_answer,
        "superseded_requirement_absent": (
            "找出明显缺口" not in final_answer
            and "**缺口" not in final_answer
        ),
        "seeded_result_present": random_fact in final_answer,
        "duplicate_execution_count": (
            len(third_trace["execution_order"])
            - len(set(third_trace["execution_order"]))
        ),
    }
    report = {
        "case_id": "CONV-001",
        "conversation_id": conversation_id,
        "initial_request": initial_request,
        "revision_request": revision_request,
        "continue_request": continue_request,
        "seeded": seeded,
        "random_fact": random_fact,
        "first": first,
        "first_trace": first_trace,
        "second": second,
        "second_trace": second_trace,
        "third": third,
        "third_trace": third_trace,
        "result_metrics": result_metrics,
    }
    settings = live_web_process.settings
    product_evidence_recorder.capture(
        nodeid=(
            "evals/product_baselines/test_conv_001_working_plan.py::"
            "test_conv_001_frontstage_working_plan_is_visible_and_revisable"
        ),
        identity=ProductEvidenceIdentity(
            case_id="CONV-001",
            role=product_evidence_role("CONV-001"),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="default",
            ),
            user_input_digest=canonical_evidence_digest(
                (initial_request, revision_request, continue_request)
            ),
            initial_state_digest=canonical_evidence_digest({
                "seeded_text": seeded_text,
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
            grader_version="conv-001-user-steering-v2",
        ),
        report=report,
    )
    first_plan = first.get("working_plan")
    second_plan = second.get("working_plan")
    assert first_plan is not None, "用户无法从正式响应查询当前前台计划"
    assert first.get("project_reference") is None, "前台计划不应创建 durable Project"
    assert second_plan is not None, "用户修订后没有返回更新后的剩余义务"
    assert second_plan["revision"] > first_plan["revision"]
    assert any(
        "冲突" in step["description"]
        for step in second_plan["steps"]
        if step["status"] != "completed"
    )
    assert "冲突" in second_plan["goal"]
    assert "缺口" not in second_plan["goal"]
    assert not any(
        step["step_id"] == "identify_gaps" for step in second_plan["steps"]
    )
    assert all(
        "缺口" not in step["description"]
        for step in second_plan["steps"]
        if step["status"] != "completed"
    )
    final_plan = third.get("working_plan")
    successful_execution_actions = [
        item
        for item in third_trace["inputs"]
        if item["kind"] in {"tool_result", "agent_artifact"}
        and item["status"] == "succeeded"
    ]
    assert third["disposition"] == "answer"
    assert result_metrics["seeded_result_present"]
    assert result_metrics["revised_requirement_present"], (
        "最终结果没有落实用户修订后的冲突检查"
    )
    assert result_metrics["superseded_requirement_absent"], (
        "最终结果仍包含用户已替换的缺口分析"
    )
    assert final_plan is not None
    assert all(
        step["status"] in {"completed", "superseded"}
        for step in final_plan["steps"]
    )
    assert not any(step["status"] == "pending" for step in final_plan["steps"])
    assert third.get("project_reference") is None
    assert result_metrics["duplicate_execution_count"] == 0
    assert any(
        item["capability_id"] == "search_personal_knowledge"
        for item in successful_execution_actions
    )
    assert all(item["plan_step_id"] for item in successful_execution_actions)
    completed_by_id = {
        step["step_id"]: set(step["completion_action_ids"])
        for step in final_plan["steps"]
    }
    assert all(
        item["action_id"] in completed_by_id[item["plan_step_id"]]
        for item in successful_execution_actions
    )
