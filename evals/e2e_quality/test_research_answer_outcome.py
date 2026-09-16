"""WEB-RESEARCH-EVIDENCE-CONTEXT-001 前置 Offline Eval，不是 Product E2E。"""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse

import pytest
from pydantic import TypeAdapter

from evals.e2e_quality.research_answer_outcome import (
    GRADER_VERSION,
    ResearchAnswerControl,
    grade_research_answer,
    research_answer_request,
)
from evals.e2e_quality.trace_archive import TraceArchive
from evals.product_baselines.evidence import load_finalized_product_evidence
from personal_agent.infra.structured_model import build_structured_model_client
from personal_agent.kernel.config import Settings


CASE_ID = "RESEARCH-ANSWER-OUTCOME-001"
HISTORICAL_TRACE_SHA256 = "9ca625c24f5732d8e146e3317e77409de3849f6278a989e608aee5f05aac92b8"
USER_REQUEST = (
    "请实际查阅 OpenAI 官方工具文档和 MCP 官方 tools 规范，在这次回复中比较"
    "工具选择、权限边界和结果契约，给出带官方 URL 的中文结论。"
)
CONTROLS_PATH = Path(__file__).with_name("fixtures") / "research_answer_outcome_controls.json"
CONTROLS = TypeAdapter(tuple[ResearchAnswerControl, ...]).validate_json(
    CONTROLS_PATH.read_text(encoding="utf-8"),
)
SAMPLE_IDS = ("historical-sealed-answer", *(item.case_id for item in CONTROLS))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PERSONAL_AGENT_RUN_RESEARCH_GRADER_CALIBRATION") != "true",
        reason="真实模型 Offline Eval 仅按前置校准计划显式运行",
    ),
]


@pytest.mark.parametrize("control_id", SAMPLE_IDS)
@pytest.mark.parametrize("repetition", (1, 2))
def test_research_answer_outcome_calibration(
    control_id: str,
    repetition: int,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    settings = Settings.from_env()
    config = settings.structured
    assert config.model == "mimo-v2.5"
    assert config.output_transport == "json_object"
    assert config.extra_body == {"thinking": {"type": "disabled"}}
    client = build_structured_model_client(config, settings.langsmith)
    assert client is not None, "校准模型未配置，不能计为通过"
    origin: dict[str, object] | None = None
    if control_id == "historical-sealed-answer":
        original_dir = Path(os.environ["PERSONAL_AGENT_RESEARCH_ORIGINAL_ARCHIVE"])
        original = load_finalized_product_evidence(original_dir)
        trace_path, = original_dir.glob("*.trace.json")
        assert sha256(trace_path.read_bytes()).hexdigest() == HISTORICAL_TRACE_SHA256
        assert original.report["natural_user_text"] == USER_REQUEST
        control = ResearchAnswerControl(
            case_id=control_id,
            answer=original.report["result"]["message"]["content"],
            expected_passed=False,
        )
        origin = {
            "archive": str(original_dir),
            "trace_sha256": HISTORICAL_TRACE_SHA256,
            "original_pytest_outcome": original.outcome,
            "original_identity": original.identity.model_dump(mode="json"),
        }
    else:
        control = next(item for item in CONTROLS if item.case_id == control_id)
    model_request = research_answer_request(user_request=USER_REQUEST, answer=control.answer)
    config_identity = {
        "model": config.model,
        "provider_host": urlparse(config.base_url).hostname,
        "transport": config.output_transport,
        "extra_body": config.extra_body,
        "timeout_seconds": config.timeout_seconds,
        "max_retries": config.max_retries,
    }
    trace_archive.update_environment({
        "evidence_class": "boundary_evaluation",
        "purpose": "校准最终答案评测，不经过 Agent，不证明产品修复",
        "grader_version": GRADER_VERSION,
        "grader_config": config_identity,
        "sample_plan": {
            "controls": SAMPLE_IDS,
            "repetitions": 2,
            "required_correct": 20,
            "max_sample_seconds": 60,
            "estimated_tokens": 80_000,
            "max_tokens": 120_000,
            "max_wall_seconds": 600,
            "monetary_cost": None,
            "stop": "先运行一个历史样本 pilot；错误、超时或成本超限后停止新增样本",
        },
        "controls_sha256": sha256(CONTROLS_PATH.read_bytes()).hexdigest(),
    })
    started = perf_counter()
    report: dict[str, object] = {
        "case_id": CASE_ID,
        "control": control.model_dump(mode="json"),
        "repetition": repetition,
        "origin": origin,
        "request_messages": model_request.messages,
        "request_schema": model_request.output_type.model_json_schema(),
        "context_projection_ref": model_request.context_projection_ref,
        "grader_config": config_identity,
    }
    try:
        response = grade_research_answer(
            client, user_request=USER_REQUEST, answer=control.answer,
        )
        report.update({
            "verdict": response.value.model_dump(mode="json"),
            "actual_passed": response.value.passed,
            "correct": response.value.passed == control.expected_passed,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "total_tokens": response.total_tokens,
            "retry_attempts": response.retry_attempts,
            "response_content": response.content,
        })
    except Exception as exc:
        # 保留失败类别后原样抛出，不把 Provider 失败伪装成语义不通过。
        report["execution_failure_type"] = type(exc).__name__
        raise
    finally:
        report["wall_seconds"] = perf_counter() - started
        trace_archive.write_trace(
            nodeid=request.node.nodeid,
            case_id=f"{CASE_ID}-{repetition}-{control_id}",
            trace=report,
        )
    assert report["correct"], json.dumps(report["verdict"], ensure_ascii=False)
    assert report["wall_seconds"] <= 60, "原子样本超时；停止新增样本，保留语义判断"
