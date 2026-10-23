"""只读核对研究评分资格；不请求模型，也不判断新的产品结果。"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Annotated, Literal

from openai.types.chat import ChatCompletion
from pydantic import BaseModel, ConfigDict, Field

from evals.e2e_quality.research_answer_outcome import (
    GRADER_PROMPT, GRADER_VERSION, ResearchAnswerReport,
    ResearchAnswerVerdict, bind_research_answer_report, research_answer_request,
)
from personal_agent.infra.structured_model import JsonObjectStructuredAdapter, StrictJsonSchemaAdapter
from personal_agent.kernel.config import Settings
from personal_agent.kernel.prompts import get_prompt
from .retrieval_qualification_review import (
    QualificationAccuracyReview, SourceReview, materialize_references, validate_judgment_accuracy,
)

ROOT = Path(__file__).resolve().parents[2]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CaptureID = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


def _digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceFingerprint(_Strict):
    path: str
    sha256: Digest


class GraderIdentity(_Strict):
    version: Literal[1] = 1
    grader_version: Literal[GRADER_VERSION] = GRADER_VERSION
    prompt_sha256: Digest
    schema_sha256: Digest
    structured_prompt_sha256: Digest
    structured_repair_prompt_sha256: Digest
    configured_model_sha256: Digest
    sources: tuple[SourceFingerprint, ...]


def grader_identity(settings: Settings) -> GraderIdentity:
    from .run_retrieval_acceptance import configuration

    source_paths = (
        "evals/e2e_quality/research_answer_outcome.py",
        "evals/product_baselines/retrieval_qualification_review.py",
        "evals/product_baselines/retrieval_qualification.py",
        "evals/product_baselines/run_retrieval_grader_qualification.py",
        "src/personal_agent/infra/structured_model.py",
        "src/personal_agent/infra/model_response.py",
        "src/personal_agent/infra/model_capacity.py",
        "src/personal_agent/kernel/structured_parse.py",
        "src/personal_agent/kernel/llm_schemas.py",
        "src/personal_agent/capabilities/contracts/model.py",
    )
    prompt = get_prompt("structured.system")
    repair_prompt = get_prompt("structured.repair.system")
    return GraderIdentity(
        prompt_sha256=sha256(GRADER_PROMPT.encode()).hexdigest(),
        schema_sha256=_digest(ResearchAnswerReport.model_json_schema()),
        structured_prompt_sha256=_digest((prompt.name, prompt.version, prompt.template)),
        structured_repair_prompt_sha256=_digest((repair_prompt.name, repair_prompt.version, repair_prompt.template)),
        configured_model_sha256=_digest(configuration(settings)["structured"]),
        sources=tuple(SourceFingerprint(path=name, sha256=sha256((ROOT / name).read_bytes()).hexdigest())
                      for name in source_paths),
    )


class QualificationJudgment(_Strict):
    sample_id: str = Field(pattern=r"^q[1-6]$")
    repetition: int = Field(ge=1, le=3)
    expected_status: Literal["passed", "failed", "inconclusive"]
    status: Literal["passed", "failed", "inconclusive", "output_contract_failure"]
    request_messages: list[dict[str, str]]
    request_schema: dict[str, object]
    verdict: ResearchAnswerVerdict | None = None
    response_content: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    retry_attempts: int | None = Field(default=None, ge=0)
    execution_error_type: str | None = None
    actual_http_send_attempts: int = Field(ge=0)
    complete_sdk_responses: int = Field(ge=0)
    http_response_records: int = Field(ge=0)
    candidate_response_ids: tuple[CaptureID, ...]
    http_response_ids: tuple[CaptureID, ...]
    http_send_start_ids: tuple[CaptureID, ...]
    known_physical_tokens: int = Field(ge=0)
    unknown_physical_usage: bool
    capture_complete: bool
    wall_seconds: float = Field(ge=0)


class QualificationSummary(_Strict):
    version: Literal["retrieval-research-task-qualification-v2"]
    grader_version: Literal[GRADER_VERSION]
    classification_threshold_met: bool
    executed: int = Field(ge=0)
    expected: int = Field(ge=0)
    correct: int = Field(ge=0)
    unexecuted: int = Field(ge=0)
    known_tokens: int = Field(ge=0)
    unknown_usage: bool
    stop_reason: str | None
    wall_seconds: float = Field(ge=0)
    interpretation: str


class QualificationAdmission(_Strict):
    qualification_directory: Path
    checksums_sha256: Digest
    grader_identity_sha256: Digest
    accuracy_review_path: Path
    accuracy_review_sha256: Digest
    judgments: Literal[18] = 18
    correct: Literal[18] = 18
    known_tokens: int = Field(ge=0, le=600000)
    wall_seconds: float = Field(ge=0, le=2700)


def verify_qualification(directory: Path, settings: Settings, *, accuracy_review: Path) -> QualificationAdmission:
    """Replay sealed judgment facts before any target process or paid call."""
    from .run_retrieval_grader_qualification import EXPECTED, QualificationPlan, QualificationProvenance

    root = directory.resolve()
    checksum_bytes = (root / "checksums.json").read_bytes()
    checksums = json.loads(checksum_bytes)
    if not isinstance(checksums, dict) or not checksums:
        raise ValueError("资格归档缺少有效 checksum 清单")
    for name, digest in checksums.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("资格归档路径越界或校验和失效")

    def sealed(name: str) -> bytes:
        if name not in checksums:
            raise ValueError("资格必要文件未封存：" + name)
        return (root / name).read_bytes()

    identity = GraderIdentity.model_validate_json(sealed("grader-identity.json"))
    if identity != grader_identity(settings):
        raise ValueError("资格 grader 的代码、Prompt、Schema 或实际模型配置与当前不同")
    plan_bytes = sealed("plan.json")
    plan = QualificationPlan.model_validate_json(plan_bytes)
    summary = QualificationSummary.model_validate_json(sealed("qualification-result.json"))
    if (not summary.classification_threshold_met or summary.unknown_usage or summary.stop_reason is not None
            or (summary.executed, summary.expected, summary.correct, summary.unexecuted) != (18, 18, 18, 0)
            or summary.known_tokens > plan.maximum_known_tokens
            or summary.wall_seconds > plan.maximum_wall_seconds):
        raise ValueError("资格组未满足预声明的 18 次准确性、用量及截止门槛")
    review_bytes = accuracy_review.read_bytes()
    accuracy = QualificationAccuracyReview.model_validate_json(review_bytes)
    accuracy.actor.review_report.read(accuracy_review.resolve().parent)
    if accuracy.plan_sha256 != sha256(plan_bytes).hexdigest():
        raise ValueError("独立准确性审读绑定了不同的资格 plan")
    accuracy_items = {(item.sample_id, item.repetition): item for item in accuracy.judgments}
    adapter = (JsonObjectStructuredAdapter if settings.structured.output_transport == "json_object"
               else StrictJsonSchemaAdapter)(settings.structured)
    seen: dict[str, set[str]] = {kind: set() for kind in ("candidate", "http", "start")}
    statuses = {status: 0 for status in ("passed", "failed", "inconclusive")}
    total_tokens = 0
    for sample in plan.inputs:
        snapshots = {}
        for name in ("user_request", "complete_answer", "reference_set", "source_capture", "source_checksums",
                     "source_report", "provenance", "independent_original_ranking_audit"):
            content = sealed(f"input-snapshots/{sample.sample_id}/{name}")
            if sha256(content).hexdigest() != getattr(sample, name).sha256:
                raise ValueError("资格输入快照与原 plan 摘要不同")
            snapshots[name] = content
        user_request = snapshots["user_request"].decode("utf-8")
        answer = snapshots["complete_answer"].decode("utf-8")
        provenance = QualificationProvenance.model_validate_json(snapshots["provenance"])
        source_review_bytes = sealed(f"input-snapshots/{sample.sample_id}/source_review")
        transformation = sealed(f"input-snapshots/{sample.sample_id}/transformation_record")
        source_review_report = sealed(f"input-snapshots/{sample.sample_id}/source_review_report")
        source_review = SourceReview.model_validate_json(source_review_bytes)
        if (sha256(source_review_bytes).hexdigest() != provenance.source_review.sha256
                or sha256(transformation).hexdigest() != provenance.transformation_record.sha256
                or sha256(source_review_report).hexdigest() != source_review.actor.review_report.sha256):
            raise ValueError("资格来源审读或变换快照与原件摘要不同")
        source_review.validate_materials(
            user_request=snapshots["user_request"], report=snapshots["source_report"], answer=snapshots["complete_answer"],
            references=snapshots["reference_set"], transformation=transformation,
            expected_status=EXPECTED[sample.kind],
        )
        references = materialize_references(snapshots["reference_set"])
        request = research_answer_request(user_request=user_request, answer=answer, reference_set=references)
        expected_kwargs = adapter._chat_kwargs(adapter._structured_chat_request(
            request, request.output_type.model_json_schema(), parse_error=None,
        ))
        for repetition in range(1, plan.repetitions + 1):
            judgment_bytes = sealed(f"{sample.sample_id}-r{repetition}.json")
            judgment = QualificationJudgment.model_validate_json(judgment_bytes)
            if (judgment.sample_id != sample.sample_id or judgment.repetition != repetition
                    or judgment.expected_status != EXPECTED[sample.kind] or judgment.status != EXPECTED[sample.kind]
                    or not judgment.capture_complete or judgment.unknown_physical_usage
                    or judgment.execution_error_type is not None or judgment.verdict is None):
                raise ValueError("资格判断的来源、三态结果或调用完整性不合格")
            if judgment.request_messages != request.messages or judgment.request_schema != request.output_type.model_json_schema():
                raise ValueError("资格判断不是当前 grader 对密封输入构造的请求")
            count = judgment.actual_http_send_attempts
            if count < 1 or count != judgment.complete_sdk_responses or count != judgment.http_response_records:
                raise ValueError("资格判断缺少逐次完整物理请求证据")
            for kind, ids in (("candidate", judgment.candidate_response_ids), ("http", judgment.http_response_ids),
                              ("start", judgment.http_send_start_ids)):
                if len(ids) != count or len(set(ids)) != count or seen[kind].intersection(ids):
                    raise ValueError("资格物理调用身份缺失或跨判断复用")
                seen[kind].update(ids)
            physical_tokens = 0
            last_response = None
            wire_bodies = {}
            for cid in judgment.candidate_response_ids:
                body_bytes = sealed(f"sdk/{cid}.candidate.request.json")
                body = json.loads(body_bytes)
                record = json.loads(sealed(f"sdk/{cid}.candidate.response.json"))
                if (record.get("candidate_id") != cid or record.get("completed") is not True
                        or record.get("candidate_body_sha256") != sha256(body_bytes).hexdigest()
                        or record.get("operation") != request.operation):
                    raise ValueError("资格 SDK 完整响应与原请求摘要不一致")
                if (body.get("messages", [])[-len(request.messages):] != request.messages
                        or {k: v for k, v in body.items() if k != "messages"}
                        != {k: v for k, v in expected_kwargs.items() if k != "messages"}):
                    raise ValueError("资格 SDK 请求没有消费本次原输入或配置不同")
                if cid == judgment.candidate_response_ids[0] and body != expected_kwargs:
                    raise ValueError("资格首次 SDK 请求与当前真实输入构造不同")
                wire_bodies[cid] = {key: value for key, value in body.items() if key != "extra_body"}
                wire_bodies[cid].update(body.get("extra_body") or {})
                usage = record.get("response", {}).get("usage")
                if (not isinstance(usage, dict) or any(type(usage.get(key)) is not int or usage[key] < 0
                        for key in ("prompt_tokens", "completion_tokens", "total_tokens"))):
                    raise ValueError("资格物理调用费用未知")
                physical_tokens += usage["total_tokens"]
                last_response = ChatCompletion.model_validate(record["response"])
            for hid in judgment.http_response_ids:
                body = sealed(f"sdk/{hid}.http.request.json")
                record = json.loads(sealed(f"sdk/{hid}.http.response.json"))
                if (record.get("send_id") != hid or record.get("response_received") is not True
                        or record.get("status_code") != 200
                        or record.get("request_body_sha256") != sha256(body).hexdigest()
                        or not set(judgment.candidate_response_ids).intersection(record.get("candidate_ids_on_client", []))):
                    raise ValueError("资格真实 HTTP 调用与 SDK 记录不能对应")
                if not any(json.loads(body) == wire_bodies[cid] for cid in judgment.candidate_response_ids
                           if cid in record.get("candidate_ids_on_client", [])):
                    raise ValueError("资格实际 HTTP 正文与本次 SDK payload 不同")
            for sid in judgment.http_send_start_ids:
                start = json.loads(sealed(f"sdk/{sid}.http.send-start.json"))
                if start.get("observation") != "httpx_client_send_entered":
                    raise ValueError("资格物理发送起点不完整")
            content, report, error = adapter._parse_typed_response(request, last_response, latency_ms=0)
            if error is not None or report is None:
                raise ValueError("资格原 SDK 响应不能按当前契约解析")
            verdict = bind_research_answer_report(report, user_request=user_request, answer=answer, reference_set=references)
            if verdict != judgment.verdict or content != judgment.response_content or verdict.evaluation_status != judgment.status:
                raise ValueError("资格 verdict 与原响应及引用绑定不同")
            validate_judgment_accuracy(accuracy_items[(sample.sample_id, repetition)], source_review,
                                       judgment=judgment_bytes, source_review=source_review_bytes,
                                       findings_count=len(verdict.findings))
            if physical_tokens != judgment.known_physical_tokens or physical_tokens != judgment.total_tokens:
                raise ValueError("资格逐次费用与已知总用量不一致")
            total_tokens += physical_tokens
            statuses[judgment.status] += 1
    for kind, suffix in (("candidate", "candidate.response"), ("http", "http.response"), ("start", "http.send-start")):
        ids = {name.split("/")[-1].split(".")[0] for name in checksums
               if name.startswith("sdk/") and name.endswith(f".{suffix}.json")}
        if seen[kind] != ids:
            raise ValueError("资格存在未归属的物理调用记录")
    for kind in ("candidate", "http"):
        request_ids = {name.split("/")[-1].split(".")[0] for name in checksums
                       if name.startswith("sdk/") and name.endswith(f".{kind}.request.json")}
        if request_ids != seen[kind]:
            raise ValueError("资格存在没有完整响应的实际请求")
    if statuses != {"passed": 6, "failed": 9, "inconclusive": 3} or total_tokens != summary.known_tokens:
        raise ValueError("资格整组结果或费用汇总不一致")
    return QualificationAdmission(qualification_directory=root, checksums_sha256=sha256(checksum_bytes).hexdigest(),
                                  grader_identity_sha256=_digest(identity.model_dump(mode="json")),
                                  accuracy_review_path=accuracy_review.resolve(),
                                  accuracy_review_sha256=sha256(review_bytes).hexdigest(),
                                  known_tokens=total_tokens, wall_seconds=summary.wall_seconds)
