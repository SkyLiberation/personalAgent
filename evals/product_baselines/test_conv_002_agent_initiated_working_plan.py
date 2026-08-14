"""CONV-002 paired product E2E for agent-initiated foreground planning."""

from __future__ import annotations

import json

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


_MODEL_TURNS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS"
_TOOL_CALLS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS"
_TOTAL_TOKENS_ENV = "PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS"


def _turn(
    server: LiveWebProcess,
    *,
    conversation_id: str,
    messages: list[dict[str, str]],
) -> dict[str, object]:
    return _post_json(
        f"{server.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "messages": messages,
            "interaction_mode": "auto",
        },
    )


def _restart_with_budget(
    server: LiveWebProcess,
    *,
    max_model_turns: int,
    max_tool_calls: int,
    max_total_tokens: int = 64000,
) -> None:
    server.child_env[_MODEL_TURNS_ENV] = str(max_model_turns)
    server.child_env[_TOOL_CALLS_ENV] = str(max_tool_calls)
    server.child_env[_TOTAL_TOKENS_ENV] = str(max_total_tokens)
    server.restart()


def test_conv_002_agent_initiates_and_recovers_foreground_coordination(
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
) -> None:
    conversation_id = "conv-002-agent-initiated-coordination"
    initial_request = (
        "请只基于 OpenAI 官方开发者文档、Google Gemini CLI 官方 GitHub 仓库和 NousResearch "
        "Hermes Agent 官方 GitHub 仓库，比较它们在复杂任务中如何保持未完成义务、何时主动"
        "记录或更新进度、上下文压缩后如何恢复，并结合本工程给出有来源的采用与不采用建议。"
        "请直接开始，不要启动后台任务，也无需等我确认。"
    )
    assert all(
        internal not in initial_request
        for internal in (
            "Plan",
            "plan",
            "计划",
            "步骤",
            "Planner",
            "Workflow",
            "InvestigationProject",
        )
    )
    continue_request = "继续完成。"

    _restart_with_budget(
        live_web_process,
        max_model_turns=1,
        max_tool_calls=0,
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

    _restart_with_budget(
        live_web_process,
        max_model_turns=live_web_process.settings.interaction_loop.max_model_turns,
        max_tool_calls=live_web_process.settings.interaction_loop.max_tool_calls,
        max_total_tokens=128000,
    )
    report: dict[str, object] = {
        "case_id": "CONV-002",
        "conversation_id": conversation_id,
        "initial_request": initial_request,
        "first": first,
        "first_trace": first_trace,
    }
    settings = live_web_process.settings
    product_evidence_recorder.capture(
        nodeid=(
            "evals/product_baselines/"
            "test_conv_002_agent_initiated_working_plan.py::"
            "test_conv_002_agent_initiates_and_recovers_foreground_coordination"
        ),
        identity=ProductEvidenceIdentity(
            case_id="CONV-002",
            role=product_evidence_role("CONV-002"),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id="default",
            ),
            user_input_digest=canonical_evidence_digest(
                (initial_request, continue_request)
            ),
            initial_state_digest=canonical_evidence_digest({
                "seeded_facts": (),
            }),
            config_cohort=canonical_evidence_digest({
                "structured_model": settings.structured.model,
                "interaction_policy_revision": (
                    settings.interaction_loop.policy_revision
                ),
                "first_turn_budget": {
                    "max_model_turns": 1,
                    "max_tool_calls": 0,
                },
                "continuation_budget": {
                    "max_model_turns": (
                        settings.interaction_loop.max_model_turns
                    ),
                    "max_tool_calls": settings.interaction_loop.max_tool_calls,
                    "max_total_tokens": 128000,
                },
            }),
            grader_version="conv-002-assertions-v1",
        ),
        report=report,
    )

    first_plan = first.get("working_plan")
    assert first_plan is not None, (
        "首轮无法执行外部检索时没有保留用户可观察的剩余义务"
    )
    assert first["disposition"] == "limitation"
    assert first.get("project_reference") is None
    assert any(step["status"] == "pending" for step in first_plan["steps"])
    assert first_trace["execution_order"] == []

    second_messages = [
        *first_messages,
        {"role": "assistant", "content": str(first["message"]["content"])},
        {"role": "user", "content": continue_request},
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
    report.update({
        "continue_request": continue_request,
        "second": second,
        "second_trace": second_trace,
    })

    final_plan = second.get("working_plan")
    final_answer = str(second["message"]["content"])
    assert second["disposition"] == "answer"
    assert final_plan is not None
    assert final_plan["plan_id"] == first_plan["plan_id"]
    assert final_plan["revision"] > first_plan["revision"]
    assert all(step["status"] == "completed" for step in final_plan["steps"])
    assert all(name in final_answer for name in ("OpenAI", "Gemini", "Hermes"))
    assert any(term in final_answer for term in ("来源", "官方", "仓库", "文档"))
    official_evidence = json.dumps(
        [
            item
            for item in second_trace["inputs"]
            if item["kind"] == "tool_result"
        ],
        ensure_ascii=False,
    ).lower()
    assert any(
        host in official_evidence
        for host in ("developers.openai.com", "openai.github.io")
    )
    assert "github.com/google-gemini/gemini-cli" in official_evidence
    assert any(
        host in official_evidence
        for host in (
            "github.com/nousresearch/hermes-agent",
            "hermes-agent.nousresearch.com",
        )
    )
    assert len(second_trace["execution_order"]) == len(
        set(second_trace["execution_order"])
    )
    assert second.get("project_reference") is None
