"""显式验收要求的研究 Product E2E；不注入 Draft 或要求 Verifier 必须触发。"""

import pytest

from evals.e2e_quality.evidence_catalog import RESEARCH_TOOL_PROTOCOL_REVIEW_OUTCOME
from evals.e2e_quality.test_release_user_outcomes import LiveWebProcess
from evals.product_baselines.evidence import ProductEvidenceRecorder
from evals.product_baselines.test_conversation_research_delivery_001 import (
    _Scenario,
    run_research_scenario,
)


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = (
    "evals.e2e_quality.test_release_user_outcomes",
    "evals.e2e_quality.test_product_capability_outcomes",
)

REVIEW_SCENARIO = _Scenario(
    scenario_id="tool-protocol-explicit-review",
    dataset_revision="conversation-research-explicit-review-zh-v1",
    outcome_contract=RESEARCH_TOOL_PROTOCOL_REVIEW_OUTCOME,
    request=(
        "请实际查阅 OpenAI 官方工具文档和 MCP 官方 tools 规范，在本次回复中交付中文比较说明。"
        "验收要求：正文分别解释两者怎样选择工具、谁负责权限检查、工具结果受什么契约约束；"
        "相关结论给出能支持它的官方 URL；不要把资料没有保证的事情写成保证。"
        "提交前请自行核对这些要求，补齐遗漏后给出完整说明。"
    ),
    required_concepts=(("工具", "选择"), ("权限", "边界"), ("结果", "契约")),
    official_source_groups=(
        ("developers.openai.com", "platform.openai.com", "openai.github.io", "openai.com"),
        ("modelcontextprotocol.io", "github.com/modelcontextprotocol"),
    ),
)


def test_conversation_research_review_001(
    request: pytest.FixtureRequest,
    live_web_search_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
) -> None:
    run_research_scenario(
        request, live_web_search_process, product_evidence_recorder, REVIEW_SCENARIO, 1,
    )
