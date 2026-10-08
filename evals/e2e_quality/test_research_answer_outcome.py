"""研究评分器的真实模型 Offline Eval；不生成或改写产品答案。"""

from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter

import pytest
from pydantic import TypeAdapter

from evals.e2e_quality.research_answer_outcome import (
    GRADER_VERSION, ResearchAnswerControl, ResearchAnswerReferenceSet,
    grade_research_answer, research_answer_request,
)
from evals.e2e_quality.trace_archive import TraceArchive
from personal_agent.infra.structured_model import build_structured_model_client
from personal_agent.kernel.config import Settings


CASE_ID = "RESEARCH-ANSWER-OUTCOME-001"
CONTROLS_PATH = Path(__file__).with_name("fixtures") / "research_answer_outcome_controls.json"
REFERENCES_PATH = Path(__file__).with_name("fixtures") / "research_answer_official_references.json"
CONTROLS = TypeAdapter(tuple[ResearchAnswerControl, ...]).validate_json(
    CONTROLS_PATH.read_text(encoding="utf-8"),
)
pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv("PERSONAL_AGENT_RUN_RESEARCH_GRADER_CALIBRATION") != "true",
    reason="真实模型 Offline Eval 仅按预声明资格计划显式运行",
)]


@pytest.mark.parametrize("control", CONTROLS, ids=lambda item: item.case_id)
def test_research_answer_outcome_calibration(
    control: ResearchAnswerControl, trace_archive: TraceArchive, request: pytest.FixtureRequest,
) -> None:
    settings = Settings.from_env()
    config = settings.structured
    assert config.model == "mimo-v2.6-flash"
    assert config.output_transport == "json_object"
    assert config.extra_body == {"thinking": {"type": "enabled"}}
    reference_set = ResearchAnswerReferenceSet.model_validate_json(REFERENCES_PATH.read_text(encoding="utf-8"))
    if control.reference_urls is not None:
        assert set(control.reference_urls).issubset({x.source_url for x in reference_set.references})
        reference_set = reference_set.model_copy(update={"references": tuple(
            x for x in reference_set.references if x.source_url in control.reference_urls)})
    client = build_structured_model_client(config, settings.langsmith)
    assert client is not None, "评分模型未配置，不能计为通过"
    model_request = research_answer_request(
        user_request=control.user_request, answer=control.answer, reference_set=reference_set,
    )
    trace_archive.update_environment({
        "evidence_class": "boundary_evaluation", "grader_version": GRADER_VERSION,
        "model": config.model, "extra_body": config.extra_body,
        "references_sha256": sha256(REFERENCES_PATH.read_bytes()).hexdigest(),
        "controls_sha256": sha256(CONTROLS_PATH.read_bytes()).hexdigest(),
        "purpose": "固定真实答案及代表性控制的评分资格；不是新 Product E2E",
    })
    report: dict[str, object] = {
        "control": control.model_dump(mode="json"), "request_messages": model_request.messages,
        "request_schema": model_request.output_type.model_json_schema(),
        "context_projection_ref": model_request.context_projection_ref,
    }
    started = perf_counter()
    try:
        response = grade_research_answer(client, user_request=control.user_request,
                                         answer=control.answer, reference_set=reference_set)
        report.update({"verdict": response.value.model_dump(mode="json"),
                       "evaluation_status": response.value.evaluation_status,
                       "correct": response.value.evaluation_status == control.expected_status,
                       "total_tokens": response.total_tokens, "retry_attempts": response.retry_attempts,
                       "response_content": response.content})
    except Exception as error:
        report["execution_failure_type"] = type(error).__name__
        raise
    finally:
        report["wall_seconds"] = perf_counter() - started
        trace_archive.write_trace(nodeid=request.node.nodeid,
                                  case_id=f"{CASE_ID}-{control.case_id}", trace=report)
    assert report["correct"], json.dumps(report["verdict"], ensure_ascii=False)
