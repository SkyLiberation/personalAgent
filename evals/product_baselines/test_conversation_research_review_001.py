"""显式验收要求的研究 Product E2E；不注入 Draft 或要求 Verifier 必须触发。"""

import pytest

from evals.e2e_quality.evidence_catalog import RESEARCH_TOOL_PROTOCOL_REVIEW_OUTCOME
from evals.e2e_quality.test_release_user_outcomes import LiveWebProcess
from evals.product_baselines.evidence import ProductEvidenceRecorder
from evals.product_baselines.test_conversation_research_delivery_001 import (
    _Scenario,
    TOOL_PROTOCOL_REFERENCE_PATH,
    run_research_scenario,
)


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = (
    "evals.e2e_quality.test_release_user_outcomes",
    "evals.e2e_quality.test_product_capability_outcomes",
)

REVIEW_SCENARIO = _Scenario(
    scenario_id="tool-protocol-explicit-review",
    dataset_revision="conversation-research-mcp-cooperation-review-zh-v2",
    reference_path=TOOL_PROTOCOL_REFERENCE_PATH,
    outcome_contract=RESEARCH_TOOL_PROTOCOL_REVIEW_OUTCOME,
    request=(
        "请实际查阅 OpenAI 官方工具文档和 MCP 官方 tools 规范，"
        "说明 OpenAI 模型通过 MCP 使用工具时，模型、宿主应用（含 MCP 客户端）"
        "和 MCP 服务器怎样协作。"
        "验收要求：解释工具由谁选择和调用、权限由谁检查、结果由谁校验及受什么约束，"
        "区分模型能力、应用实现与协议要求；"
        "相关结论给出能支持它的官方 URL；不要把资料没有保证的事情写成保证。"
        "资料未明确的部分如实说明。提交前请自行核对这些要求，在本次回复中给出中文说明。"
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
