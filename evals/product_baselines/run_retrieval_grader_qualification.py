"""本任务研究 grader 的密封真实材料资格；默认 collect 不发模型请求。"""

from __future__ import annotations

import argparse
from functools import wraps
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from evals.e2e_quality.research_answer_outcome import (
    GRADER_VERSION, ResearchAnswerReferenceSet, grade_research_answer, research_answer_request,
)
from personal_agent.infra.structured_model import build_structured_model_client
from personal_agent.capabilities.contracts.model import ModelCapacityRefused, ModelInvocationUnavailable
from personal_agent.application.retrieval_experiment.delivery import manifest_bytes
from personal_agent.application.retrieval_experiment.models import PublishedExperimentResult

from .retrieval_acceptance_server import install_acceptance_observer
from .retrieval_delivery_audit import DownloadedResource, OriginalRankingAudit, read_downloaded_bundle
from .retrieval_qualification import (
    QualificationJudgment, QualificationSummary, grader_identity, verify_qualification,
)
from .retrieval_qualification_review import SealedFile, SourceReview, materialize_references
from .run_retrieval_acceptance import _settings, configuration

QUALIFICATION_VERSION = "retrieval-research-task-qualification-v2"
Kind = Literal["legal_e1", "legal_p1", "unsupported_gain", "scope_extrapolation", "insufficient_evidence", "fake_combination"]
EXPECTED = {"legal_e1": "passed", "legal_p1": "passed", "unsupported_gain": "failed",
            "scope_extrapolation": "failed", "insufficient_evidence": "inconclusive", "fake_combination": "failed"}


class QualificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sample_id: str = Field(pattern=r"^q[1-6]$")
    kind: Kind
    user_request: SealedFile
    complete_answer: SealedFile
    reference_set: SealedFile
    source_capture: SealedFile
    source_checksums: SealedFile
    source_report: SealedFile
    provenance: SealedFile
    independent_original_ranking_audit: SealedFile


class QualificationProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review: SealedFile
    answer_origin: Literal["actual_complete_delivery", "offline_adjacent_control"]
    transformation_record: SealedFile


class QualificationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["retrieval-research-task-qualification-v2"] = QUALIFICATION_VERSION
    grader_version: Literal[GRADER_VERSION] = GRADER_VERSION
    inputs: tuple[QualificationInput, ...] = Field(min_length=6, max_length=6)
    repetitions: Literal[3] = 3
    maximum_known_tokens: Literal[600000] = 600000
    maximum_wall_seconds: Literal[2700] = 2700
    allowed_misclassifications: Literal[0] = 0

    @model_validator(mode="after")
    def validate_group(self) -> QualificationPlan:
        if {item.kind for item in self.inputs} != set(EXPECTED):
            raise ValueError("资格组必须恰好覆盖预声明的六个输入")
        if len({item.sample_id for item in self.inputs}) != len(self.inputs):
            raise ValueError("资格样本 ID 不能重复")
        return self


def load_inputs(plan_path: Path) -> tuple[QualificationPlan, list[tuple[QualificationInput, str, str, ResearchAnswerReferenceSet]]]:
    plan = QualificationPlan.model_validate_json(plan_path.read_bytes())
    base = plan_path.parent
    inputs = []
    for sample in plan.inputs:
        capture = json.loads(sample.source_capture.read(base))
        if capture.get("phase") != "qualification_preparation":
            raise ValueError("只有独立 preparation 可参与校准，target/baseline 不能混入")
        checksums = json.loads(sample.source_checksums.read(base))
        capture_root = (base / sample.source_capture.path).resolve().parent
        for relative, digest in checksums.items():
            path = (capture_root / relative).resolve()
            if not path.is_relative_to(capture_root) or sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("资格来源归档校验和失效")
        report = sample.source_report.read(base).decode("utf-8")
        downloads = capture_root / "downloads"
        downloaded_index = TypeAdapter(tuple[DownloadedResource, ...]).validate_json((downloads / "index.json").read_bytes())
        report_path = (base / sample.source_report.path).resolve()
        if not any(
            report_path == (downloads / item.download_path).resolve()
            and item.resource.content_digest == sample.source_report.sha256
            and item.resource.filename.endswith(".md")
            for item in downloaded_index
        ):
            raise ValueError("资格报告必须为当前用户正式下载的完整原始 Markdown")
        provenance = QualificationProvenance.model_validate_json(sample.provenance.read(base))
        if provenance.source_report_sha256 != sha256(report.encode("utf-8")).hexdigest():
            raise ValueError("相邻控制必须绑定完整真实报告")
        audit = OriginalRankingAudit.model_validate_json(sample.independent_original_ranking_audit.read(base))
        if not audit.results or {item.split for item in audit.results} != {"train", "test"}:
            raise ValueError("没有完整原排名独立复算依据")
        user_request = sample.user_request.read(base).decode("utf-8")
        answer = sample.complete_answer.read(base).decode("utf-8")
        reference_bytes = sample.reference_set.read(base)
        references = materialize_references(reference_bytes)
        source_review_bytes = provenance.source_review.read(base)
        source_review = SourceReview.model_validate_json(source_review_bytes)
        source_review.validate_materials(
            user_request=user_request.encode("utf-8"), report=report.encode("utf-8"),
            answer=answer.encode("utf-8"), references=reference_bytes,
            transformation=provenance.transformation_record.read(base), expected_status=EXPECTED[sample.kind],
        )
        source_review.actor.review_report.read((base / provenance.source_review.path).resolve().parent)
        if sample.kind.startswith("legal") and provenance.answer_origin != "actual_complete_delivery":
            raise ValueError("合法稿必须来自实际完整交付，不能人工补写")
        if not sample.kind.startswith("legal") and provenance.answer_origin != "offline_adjacent_control":
            raise ValueError("相邻错误或缺证控制只能按 Offline Eval 身份使用")
        manifest, downloaded = read_downloaded_bundle(capture_root / "downloads")
        if audit.manifest_sha256 != sha256(manifest_bytes(manifest)).hexdigest():
            raise ValueError("原排名审计必须绑定当前下载清单的确切原字节")
        expected_sources = {}
        for exported in manifest.artifacts:
            ref = exported.resource.resource_ref
            try:
                wrapper = PublishedExperimentResult.model_validate_json(downloaded[ref])
            except ValueError:
                continue
            expected_sources[ref] = (sha256(downloaded[ref]).hexdigest(),
                                     sha256(downloaded[wrapper.raw_result_ref]).hexdigest())
        actual_sources = {item.result_ref: (item.wrapper_sha256, item.raw_result_sha256) for item in audit.results}
        if len(actual_sources) != len(audit.results) or actual_sources != expected_sources:
            raise ValueError("原排名审计的确切结果引用集合及来源摘要与当前下载不同")
        if audit.qrels_sha256 != {item.split: item.source_sha256["qrels"]
                                 for item in (manifest.environment.development, manifest.environment.final)}:
            raise ValueError("原排名审计标注来源与当前冻结数据不同")
        if sample.kind.startswith("legal"):
            programs = [downloaded[item.resource.resource_ref].decode("utf-8")
                        for item in manifest.artifacts if item.resource.filename.endswith(".py")]
            if answer != "\n\n".join((report, *programs)):
                raise ValueError("合法稿必须逐字使用实际完整报告和全部已交付程序，不能人工补写")
            if sample.kind == "legal_p1" and not programs:
                raise ValueError("合法 P1 资格必须提供本轨迹实际交付的完整程序")
        inputs.append((sample, user_request, answer, references))
    return plan, inputs


def _write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def _install_send_starts(directory: Path, provider_host: str) -> None:
    """Mark send entry before a background deadline can outlive its finally."""
    import httpx

    original = httpx.Client.send

    @wraps(original)
    def observed(client, request, *args, **kwargs):
        if request.url.host == provider_host and request.url.path.endswith("/chat/completions"):
            _write(directory / f"{uuid4().hex}.http.send-start.json", {
                "observation": "httpx_client_send_entered", "provider_host": request.url.host,
                "method": request.method, "path": request.url.path,
            })
        return original(client, request, *args, **kwargs)

    httpx.Client.send = observed


def collect(plan_path: Path) -> None:
    plan, inputs = load_inputs(plan_path)
    print(json.dumps({"version": plan.version, "input_count": len(inputs),
                      "independent_judgments": len(inputs) * plan.repetitions,
                      "model_calls": 0, "maximum_known_tokens": plan.maximum_known_tokens,
                      "maximum_wall_seconds": plan.maximum_wall_seconds}, ensure_ascii=False))


def run(plan_path: Path, output: Path) -> None:
    plan, inputs = load_inputs(plan_path)
    output.mkdir(parents=True, exist_ok=False)
    settings = _settings()
    client = build_structured_model_client(
        settings.structured, settings.langsmith.model_copy(update={"enabled": False}),
    )
    if client is None:
        raise ValueError("没有 configured 的真实评分模型")
    _write(output / "plan.json", plan.model_dump(mode="json"))
    _write(output / "configuration.json", configuration(settings))
    _write(output / "grader-identity.json", grader_identity(settings).model_dump(mode="json"))
    _write(output / "source-identity.json", {
        str(path): sha256(path.read_bytes()).hexdigest()
        for path in (Path(__file__), Path(__file__).with_name("retrieval_acceptance_server.py"),
                     Path(__file__).parents[1] / "e2e_quality/research_answer_outcome.py")
    })
    for sample in plan.inputs:
        snapshot = output / "input-snapshots" / sample.sample_id
        snapshot.mkdir(parents=True)
        for name in ("user_request", "complete_answer", "reference_set", "source_capture",
                     "source_checksums", "source_report", "provenance", "independent_original_ranking_audit"):
            (snapshot / name).write_bytes(getattr(sample, name).read(plan_path.parent))
        provenance = QualificationProvenance.model_validate_json(sample.provenance.read(plan_path.parent))
        review_bytes = provenance.source_review.read(plan_path.parent)
        review = SourceReview.model_validate_json(review_bytes)
        (snapshot / "source_review").write_bytes(review_bytes)
        (snapshot / "transformation_record").write_bytes(provenance.transformation_record.read(plan_path.parent))
        (snapshot / "source_review_report").write_bytes(review.actor.review_report.read(
            (plan_path.parent / provenance.source_review.path).resolve().parent))
    install_acceptance_observer(output / "sdk")
    _install_send_starts(output / "sdk", settings.structured.capacity.provider_host)
    started = monotonic()
    known_tokens = 0
    unknown_usage = False
    stop_reason = None
    results = []
    try:
        # Interleave the fixed inputs; no output feeds any subsequent judgment.
        for repetition in range(1, plan.repetitions + 1):
            for sample, user_request, answer, references in inputs:
                if monotonic() - started >= plan.maximum_wall_seconds or known_tokens >= plan.maximum_known_tokens:
                    stop_reason = "predeclared_budget_reached"
                    break
                record: dict[str, object] = {"sample_id": sample.sample_id, "repetition": repetition,
                                             "expected_status": EXPECTED[sample.kind]}
                request = research_answer_request(user_request=user_request, answer=answer, reference_set=references)
                record["request_messages"] = request.messages
                record["request_schema"] = request.output_type.model_json_schema()
                call_started = monotonic()
                before_responses = set((output / "sdk").glob("*.candidate.response.json"))
                before_sends = set((output / "sdk").glob("*.http.response.json"))
                before_requests = set((output / "sdk").glob("*.http.send-start.json"))
                try:
                    response = grade_research_answer(client, user_request=user_request, answer=answer, reference_set=references)
                    record.update(status=response.value.evaluation_status, verdict=response.value.model_dump(mode="json"),
                                  response_content=response.content, input_tokens=response.input_tokens,
                                  output_tokens=response.output_tokens, total_tokens=response.total_tokens,
                                  retry_attempts=response.retry_attempts)
                except Exception as error:
                    record["execution_error_type"] = type(error).__name__
                    # Never print exception text; provider errors can include headers.
                    record["status"] = "output_contract_failure"
                    if isinstance(error, ModelCapacityRefused):
                        stop_reason = "model_capacity_refused"
                    elif isinstance(error, ModelInvocationUnavailable):
                        stop_reason = "provider_failure"
                physical_paths = sorted(set((output / "sdk").glob("*.candidate.response.json")) - before_responses,
                                        key=lambda path: (path.stat().st_mtime_ns, path.name))
                sent_paths = sorted(set((output / "sdk").glob("*.http.response.json")) - before_sends)
                start_paths = sorted(set((output / "sdk").glob("*.http.send-start.json")) - before_requests)
                physical = [json.loads(path.read_bytes()) for path in physical_paths]
                sent = [json.loads(path.read_bytes()) for path in sent_paths]
                # Client.send may still be unwinding in the deadline thread;
                # its start record exists before its response record.
                send_count = len(start_paths)
                complete = [item for item in physical if item.get("completed") is True]
                usages = [item.get("response", {}).get("usage") for item in complete]
                call_known = sum(item["total_tokens"] for item in usages if item and item.get("total_tokens") is not None)
                known_tokens += call_known
                call_unknown = send_count > len(complete) or any(
                    item is None or any(item.get(name) is None for name in ("prompt_tokens", "completion_tokens", "total_tokens"))
                    for item in usages
                )
                record.update(actual_http_send_attempts=send_count, complete_sdk_responses=len(complete),
                              http_response_records=len(sent),
                              candidate_response_ids=[path.name.split(".")[0] for path in physical_paths],
                              http_response_ids=[path.name.split(".")[0] for path in sent_paths],
                              http_send_start_ids=[path.name.split(".")[0] for path in start_paths],
                              known_physical_tokens=call_known, unknown_physical_usage=call_unknown,
                              capture_complete=all("body_observation_error" not in item for item in (*physical, *sent)))
                if not record["capture_complete"]:
                    stop_reason = "sdk_observation_incomplete"
                if call_unknown:
                    unknown_usage = True
                    stop_reason = "provider_failure_or_unknown_model_usage"
                record["wall_seconds"] = monotonic() - call_started
                judgment = QualificationJudgment.model_validate(record)
                results.append(judgment.model_dump(mode="json", exclude_none=True))
                _write(output / f"{sample.sample_id}-r{repetition}.json", judgment.model_dump(mode="json", exclude_none=True))
                if stop_reason:
                    break
            if stop_reason:
                break
    finally:
        if known_tokens > plan.maximum_known_tokens or monotonic() - started > plan.maximum_wall_seconds:
            stop_reason = stop_reason or "predeclared_budget_reached"
        correct = sum(item.get("status") == item["expected_status"] for item in results)
        expected_count = len(inputs) * plan.repetitions
        summary = QualificationSummary.model_validate({
            "version": plan.version, "grader_version": plan.grader_version,
            "classification_threshold_met": len(results) == expected_count and correct == expected_count and not stop_reason
            and all(item.get("capture_complete") for item in results),
            "executed": len(results), "expected": expected_count, "correct": correct,
            "unexecuted": expected_count - len(results), "known_tokens": known_tokens,
            "unknown_usage": unknown_usage, "stop_reason": stop_reason,
            "wall_seconds": monotonic() - started,
            "interpretation": "原三态门槛记录；须另消费独立逐关系准确性审读后才取得资格，不估计总体成功率。",
        })
        _write(output / "qualification-result.json", summary.model_dump(mode="json"))
        _write(output / "checksums.json", {
            str(path.relative_to(output)): sha256(path.read_bytes()).hexdigest()
            for path in sorted(output.rglob("*")) if path.is_file()
        })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("collect", "run"):
        command = commands.add_parser(name)
        command.add_argument("--plan", required=True, type=Path)
        if name == "run":
            command.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser("verify", help="零模型只读核对已经执行的完整资格归档")
    verify.add_argument("--qualification", required=True, type=Path)
    verify.add_argument("--accuracy-review", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "collect":
        collect(args.plan.resolve())
    elif args.command == "run":
        run(args.plan.resolve(), args.output.resolve())
    else:
        admission = verify_qualification(args.qualification, _settings(), accuracy_review=args.accuracy_review)
        print(admission.model_dump_json())


if __name__ == "__main__":
    main()
