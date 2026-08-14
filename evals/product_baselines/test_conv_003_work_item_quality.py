"""CONV-003 product E2E for outcome-bearing foreground work items."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _post_json,
)
from personal_agent.capabilities.contracts.model import (
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.infra.structured_model import build_structured_model_client
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


class _WorkItemQualityVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all_items_state_verifiable_results: bool
    bare_activity_step_ids: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)


def _grade_work_items(
    server: LiveWebProcess,
    *,
    user_request: str,
    working_plan: dict[str, object],
) -> _WorkItemQualityVerdict:
    client = build_structured_model_client(
        server.settings.structured,
        server.settings.langsmith,
    )
    assert client is not None
    messages = [
        {
            "role": "system",
            "content": (
                "Judge a user-visible Agent work list against the user's requested "
                "results. A passing item states a result, artifact, finding, decision, "
                "or change whose completion can be evaluated. An item fails when it "
                "only says to search, read, inspect, call a tool, or gather material "
                "without stating what result that activity must produce. Do not fail "
                "an item merely because it uses an action verb. A mechanism explanation "
                "from a named official source is a verifiable artifact; do not invent "
                "requirements for document titles, chapters, counts, or detail that the "
                "user did not request. A qualitative completion condition may refer to "
                "the stated artifact or finding. Mark a step as a bare activity only "
                "when it lacks either a stated result or a condition for accepting that "
                "result as complete. Return the requested structured verdict only."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_request": user_request,
                    "working_plan": working_plan,
                },
                ensure_ascii=False,
            ),
        },
    ]
    response = client.generate(StructuredModelRequest(
        operation="conversation_work_item_quality_e2e",
        version="v1",
        temperature=0,
        max_tokens=1_000,
        kind="structured",
        messages=messages,
        context_projection_ref=sealed_context_projection_ref(
            purpose="conversation_work_item_quality_e2e",
            messages=messages,
        ),
        output_type=_WorkItemQualityVerdict,
        metadata={"case_id": "CONV-003"},
    ))
    return response.value


def test_conv_003_work_items_state_verifiable_results(
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
) -> None:
    user_request = (
        "请只基于 OpenAI 官方开发者文档、Google Gemini CLI 官方 GitHub 仓库和 "
        "NousResearch Hermes Agent 官方 GitHub 仓库，比较它们在复杂任务中如何保持"
        "未完成工作、更新进度和恢复上下文，并给出本工程应采用与不采用的建议。"
        "请先列出一份我能查看的工作清单并直接开始，不要启动后台任务，也无需等我确认。"
    )
    live_web_process.child_env["PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS"] = "1"
    live_web_process.child_env["PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS"] = "0"
    live_web_process.restart()

    result = _post_json(
        f"{live_web_process.base_url}/api/conversation/turn",
        {
            "conversation_id": "conv-003-work-item-quality",
            "messages": [{"role": "user", "content": user_request}],
            "interaction_mode": "auto",
        },
    )
    working_plan = result.get("working_plan")
    assert isinstance(working_plan, dict), (
        "资源边界到达时没有保留可供后续继续的工作清单"
    )
    descriptions = [
        str(step["description"])
        for step in working_plan["steps"]
    ]
    assert all(
        "Result:" not in description and "Complete when:" not in description
        for description in descriptions
    ), "中文请求的用户可见工作项不应混用英文结构标签"
    verdict = _grade_work_items(
        live_web_process,
        user_request=user_request,
        working_plan=working_plan,
    )
    report = {
        "case_id": "CONV-003",
        "user_request": user_request,
        "result": result,
        "verdict": verdict.model_dump(mode="json"),
    }
    settings = live_web_process.settings
    product_evidence_recorder.capture(
        nodeid=(
            "evals/product_baselines/test_conv_003_work_item_quality.py::"
            "test_conv_003_work_items_state_verifiable_results"
        ),
        identity=ProductEvidenceIdentity(
            case_id="CONV-003",
            role=product_evidence_role("CONV-003"),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
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
                "max_model_turns": 1,
                "max_tool_calls": 0,
            }),
            grader_version="conv-003-model-grader-v1",
        ),
        report=report,
    )

    assert verdict.all_items_state_verifiable_results, verdict.rationale
    assert not verdict.bare_activity_step_ids, verdict.rationale
