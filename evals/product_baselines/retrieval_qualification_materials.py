"""从封存的正式完整交付恢复资格材料；不生成研究答案、不调用模型。"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from evals.e2e_quality.research_answer_outcome import OfficialReference, ResearchAnswerReferenceSet
from personal_agent.application.conversation.models import InteractionTrace
from personal_agent.application.retrieval_experiment.delivery import manifest_bytes
from personal_agent.infra.retrieval_experiment.reproduction import ReproductionReport
from personal_agent.kernel.contracts.resource import ResourceRef

from .retrieval_delivery_audit import DownloadedResource, OriginalRankingAudit, read_downloaded_bundle
from .retrieval_qualification_review import Digest, SealedFile, SourceReview


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WholeFile(_Strict):
    kind: Literal["whole"] = "whole"


class TextRange(_Strict):
    kind: Literal["text_range"] = "text_range"
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class JsonPointer(_Strict):
    kind: Literal["json_pointer"] = "json_pointer"
    pointer: str = Field(pattern=r"^(?:/.*)?$")


Location = Annotated[WholeFile | TextRange | JsonPointer, Field(discriminator="kind")]


class ReferenceSelection(_Strict):
    source: SealedFile
    origin: Literal["downloaded_artifact", "qrels", "environment", "original_ranking_audit", "clean_reproduction"]
    artifact_ref: ResourceRef | None = None
    location: Location


class AdjacentEdit(_Strict):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    replacement: SealedFile


class SourceDelivery(_Strict):
    preparation: SealedFile
    capture: SealedFile
    checksums: SealedFile
    original_ranking_audit: SealedFile | None = None
    reproduction: SealedFile | None = None
    reproduction_execution: SealedFile | None = None


class SampleSelection(_Strict):
    sample_id: str = Field(pattern=r"^q[1-6]$")
    kind: Literal["legal_e1", "legal_p1", "unsupported_gain", "scope_extrapolation", "insufficient_evidence", "fake_combination"]
    source: SourceDelivery
    references: tuple[ReferenceSelection, ...] = Field(min_length=1)
    omitted_reference_indices: tuple[int, ...] = ()
    answer_edit: AdjacentEdit | None = None
    source_review: SealedFile


class MaterialSelection(_Strict):
    version: Literal[1] = 1
    samples: tuple[SampleSelection, ...] = Field(min_length=6, max_length=6)


class CliReproductionExecution(_Strict):
    argv: tuple[str, ...] = Field(min_length=1)
    exitcode: Literal[0]
    actual_process_stopped: Literal[True]
    manifest_sha256: Digest
    report_sha256: Digest
    wall_seconds: float = Field(ge=0, allow_inf_nan=False)
    model_calls: Literal[0]


def _sealed(path: Path) -> SealedFile:
    return SealedFile(path=path.resolve(), sha256=sha256(path.read_bytes()).hexdigest())


def read_complete_delivery(source: SourceDelivery, base: Path):
    """只接受已停止、经正式 HTTP 返回并下载的完整研究交付。"""
    from .run_retrieval_acceptance import EntryObservation, Preparation

    capture_bytes = source.capture.read(base)
    capture = json.loads(capture_bytes)
    if capture.get("phase") != "qualification_preparation" or capture.get("fault") is not None:
        raise ValueError("资格来源必须为无故障的独立 qualification_preparation")
    root = (base / source.capture.path).resolve().parent
    checksums = json.loads(source.checksums.read(base))
    if not checksums or (base / source.checksums.path).resolve() != root / "checksums.json":
        raise ValueError("资格来源 checksum 不是当前采集原件")
    for name, digest in checksums.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("正式来源归档 checksum 失效")
    for name in ("capture-result.json", "lifecycle.json", "entry-observations.json", "downloads/index.json"):
        if name not in checksums:
            raise ValueError("来源缺完整正式交付：" + name)
    if source.capture.sha256 != checksums["capture-result.json"]:
        raise ValueError("使用的 capture 不是该正式归档已封存的原件")
    if not json.loads((root / "lifecycle.json").read_bytes())["actual_process_stopped"]:
        raise ValueError("仍在运行的研究不能作为资格来源")
    prepared_bytes = source.preparation.read(base)
    if (capture.get("preparation_sha256") != sha256(prepared_bytes).hexdigest()
            or capture.get("source_changed_during_capture")):
        raise ValueError("采集准备身份变化或运行期间源码漂移")
    prepared = Preparation.model_validate_json(prepared_bytes)
    observations = TypeAdapter(tuple[EntryObservation, ...]).validate_json((root / "entry-observations.json").read_bytes())
    posts = [item for item in observations if item.method == "POST" and item.path == "/api/conversation/turn"]
    traces = [item for item in observations if item.method == "GET" and item.path.startswith("/api/conversation/runs/")]
    if len(posts) != 1 or posts[0].status_code != 200 or len(traces) != 1 or traces[0].status_code != 200:
        raise ValueError("来源未通过正式入口取得完整结果与 Trace")
    trace = InteractionTrace.model_validate(traces[0].body)
    delivery = trace.research_experiment_delivery
    if (not trace.final_message or trace.final_message.disposition != "answer" or not delivery
            or not delivery.report_ref or not delivery.reproduction_ref or not delivery.bundle_ref):
        raise ValueError("来源缺完整 Final、报告、manifest 或复现包")
    if (trace.principal != prepared.world.initial.principal
            or trace.interaction_run_ref != prepared.world.initial.interaction_run_ref
            or trace.input_artifact_refs != prepared.world.input_artifact_refs):
        raise ValueError("正式来源主体、任务或公开初始材料不一致")
    manifest, contents = read_downloaded_bundle(root / "downloads")
    records = TypeAdapter(tuple[DownloadedResource, ...]).validate_json((root / "downloads/index.json").read_bytes())
    manifest_records = [item for item in records if item.resource.filename == "manifest.json"]
    bundle_records = [item for item in records if item.resource.filename == "reproduction.zip"]
    binding = delivery.binding
    if (len(manifest_records) != 1 or len(bundle_records) != 1
            or manifest_records[0].resource.resource_ref != delivery.reproduction_ref
            or bundle_records[0].resource.resource_ref != delivery.bundle_ref
            or manifest.submission_ref != binding.submission_ref or manifest.body_digest != binding.body_digest
            or manifest.facts.frozen_ref != binding.frozen_ref
            or manifest.facts.final_result_refs != binding.final_result_refs
            or manifest.facts.candidate_development_refs != binding.candidate_development_refs):
        raise ValueError("正式 manifest/ZIP 与本轨迹的确切研究交付绑定不同")
    reports = [item for item in records if item.resource.resource_ref == delivery.report_ref]
    if len(reports) != 1 or not reports[0].resource.filename.endswith(".md"):
        raise ValueError("没有正式下载的同稿 Markdown 报告")
    report_path = root / "downloads" / reports[0].download_path
    report = report_path.read_bytes()
    if report.decode("utf-8") != trace.final_message.message or sha256(report).hexdigest() != binding.body_digest:
        raise ValueError("正式下载报告与本次 Final 不是同一正文")
    if not source.original_ranking_audit or not source.reproduction or not source.reproduction_execution:
        raise ValueError("完整来源仍缺独立原排名审计或干净 CLI 复现证据")
    audit = OriginalRankingAudit.model_validate_json(source.original_ranking_audit.read(base))
    digest = sha256(manifest_bytes(manifest)).hexdigest()
    if audit.manifest_sha256 != digest or {item.split for item in audit.results} != {"train", "test"}:
        raise ValueError("原排名审计没有绑定同一完整 train/test 交付")
    reproduction_bytes = source.reproduction.read(base)
    reproduced = ReproductionReport.model_validate_json(reproduction_bytes)
    expected = {*manifest.facts.final_result_refs, *manifest.facts.candidate_development_refs}
    actual = [item.expected_result_ref for item in reproduced.comparisons]
    if reproduced.manifest_digest != digest or set(actual) != expected or len(actual) != len(expected):
        raise ValueError("干净复现没有恰好覆盖同一 manifest 的实际任务")
    execution = CliReproductionExecution.model_validate_json(source.reproduction_execution.read(base))
    if (execution.manifest_sha256 != digest or execution.report_sha256 != sha256(reproduction_bytes).hexdigest()
            or "scripts.retrieval_experiment" not in execution.argv or "reproduce" not in execution.argv):
        raise ValueError("复现报告未绑定正式 CLI 实际进程记录")
    return prepared, trace, manifest, contents, report_path, report


def _excerpt(content: bytes, location: Location) -> str:
    text = content.decode("utf-8")
    if isinstance(location, WholeFile):
        return text
    if isinstance(location, TextRange):
        if location.end <= location.start or location.end > len(text):
            raise ValueError("参考原文范围越界或为空")
        return text[location.start:location.end]
    value = json.loads(content)
    for token in location.pointer.split("/")[1:] if location.pointer else ():
        if re.search(r"~(?![01])", token):
            raise ValueError("JSON pointer 含非法转义")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if re.fullmatch(r"0|[1-9][0-9]*", token) is None:
                raise ValueError("JSON pointer 数组下标必须为规范非负整数")
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value[token]
        else:
            raise ValueError("JSON pointer 不能进入标量")
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def assemble(selection_path: Path, output: Path) -> Path:
    from .run_retrieval_grader_qualification import (
        EXPECTED, QualificationInput, QualificationPlan, QualificationProvenance, load_inputs,
    )

    selection = MaterialSelection.model_validate_json(selection_path.read_bytes())
    base = selection_path.parent
    if ({item.kind for item in selection.samples} != set(EXPECTED)
            or len({item.sample_id for item in selection.samples}) != 6):
        raise ValueError("材料选择必须恰好覆盖原六项独立输入")
    # 先核对真实完整来源；缺交付时不写出看似可运行的 plan。
    sources = [read_complete_delivery(item.source, base) for item in selection.samples]
    legal = {item.kind: (item, source) for item, source in zip(selection.samples, sources)
             if item.kind.startswith("legal")}
    for item, source in zip(selection.samples, sources):
        if item.kind.startswith("legal"):
            continue
        original, original_source = legal["legal_p1" if item.kind == "fake_combination" else "legal_e1"]
        if item.source.capture.sha256 != original.source.capture.sha256 or source[-1] != original_source[-1]:
            raise ValueError("相邻控制必须来自对应合法项的同一实际 capture 和报告")
        if item.references != original.references:
            raise ValueError("相邻控制的完整参考选择表必须保持原合法项，仅缺证项可显式移除依据")
    output.mkdir(parents=True, exist_ok=False)
    inputs = []
    for sample, (prepared, trace, manifest, contents, report_path, report) in zip(selection.samples, sources):
        directory = output / sample.sample_id
        directory.mkdir()
        programs = [contents[item.resource.resource_ref].decode("utf-8")
                    for item in manifest.artifacts if item.resource.filename.endswith(".py")]
        answer = "\n\n".join((report.decode("utf-8"), *programs))
        program_ranges = []
        offset = len(report.decode("utf-8"))
        for program in programs:
            offset += 2
            program_ranges.append((offset, offset + len(program)))
            offset += len(program)
        if sample.kind == "legal_p1" and (prepared.case != "p1" or not programs):
            raise ValueError("合法 P1 需要实际 P1 完整程序")
        if sample.kind == "legal_e1" and prepared.case != "e1":
            raise ValueError("合法 E1 不能使用其他委托")
        if sample.answer_edit:
            edit = sample.answer_edit
            if sample.kind in {"legal_e1", "legal_p1", "insufficient_evidence"}:
                raise ValueError("合法稿或缺证控制不得编辑原答案")
            if edit.end <= edit.start or edit.end > len(answer):
                raise ValueError("相邻控制编辑范围非法")
            if sample.kind == "fake_combination":
                if prepared.case != "p1" or not any(start <= edit.start < edit.end <= end for start, end in program_ranges):
                    raise ValueError("伪组合控制只能修改实际 P1 已交付程序中的一处")
            elif edit.end > len(report.decode("utf-8")):
                raise ValueError("无据提升或范围外推控制只能修改原报告的一处")
            answer = answer[:edit.start] + edit.replacement.read(base).decode("utf-8") + answer[edit.end:]
        elif sample.kind in {"unsupported_gain", "scope_extrapolation", "fake_combination"}:
            raise ValueError("错误控制缺少唯一相邻变换")
        omitted = set(sample.omitted_reference_indices)
        if ((sample.kind == "insufficient_evidence") != bool(omitted)
                or len(omitted) != len(sample.omitted_reference_indices)
                or any(index < 1 or index > len(sample.references) for index in omitted)):
            raise ValueError("只允许缺证控制移除预声明必要参考")
        references = []
        for index, selected in enumerate(sample.references, 1):
            content = selected.source.read(base)
            if selected.origin != "downloaded_artifact" and selected.artifact_ref is not None:
                raise ValueError("非 Artifact 参考不能声明 Artifact 身份")
            if selected.origin == "downloaded_artifact":
                if selected.artifact_ref not in contents or contents[selected.artifact_ref] != content:
                    raise ValueError("参考 Artifact 不是本次正式下载原件")
            elif selected.origin == "qrels":
                allowed = {item.source_sha256["qrels"] for item in (manifest.environment.development, manifest.environment.final)}
                if sha256(content).hexdigest() not in allowed:
                    raise ValueError("评分标注不是同一数据身份")
            else:
                expected = {"environment": prepared.world.initial.environment_sha256,
                            "original_ranking_audit": sample.source.original_ranking_audit.sha256,
                            "clean_reproduction": sample.source.reproduction.sha256}[selected.origin]
                if sha256(content).hexdigest() != expected:
                    raise ValueError("参考事实与原件身份不同")
            if index not in omitted:
                location_digest = sha256(selected.location.model_dump_json().encode()).hexdigest()
                identity = (f"artifact:{selected.artifact_ref.resource_type}:{selected.artifact_ref.resource_id}:r{selected.artifact_ref.revision}"
                            if selected.artifact_ref else selected.origin)
                source_id = f"{identity}:sha256:{selected.source.sha256}:location:{location_digest}"
                references.append(OfficialReference(source_url=source_id, source_text=_excerpt(content, selected.location)))
        reference_bytes = ResearchAnswerReferenceSet(revision="opaque-materialization", references=tuple(references)).model_dump_json(indent=2).encode()
        transformation = sample.model_dump_json(exclude={"source_review"}, indent=2).encode()
        review_bytes = sample.source_review.read(base)
        review = SourceReview.model_validate_json(review_bytes)
        review.validate_materials(user_request=prepared.world.initial.user_input.encode(),
                                  report=report, answer=answer.encode(), references=reference_bytes,
                                  transformation=transformation, expected_status=EXPECTED[sample.kind])
        review.actor.review_report.read((base / sample.source_review.path).resolve().parent)
        values = {"user-request.txt": prepared.world.initial.user_input.encode(), "answer.txt": answer.encode(),
                  "references.json": reference_bytes, "source-review.json": review_bytes,
                  "transformation.json": transformation}
        for name, content in values.items():
            (directory / name).write_bytes(content)
        provenance = QualificationProvenance(
            source_report_sha256=sha256(report).hexdigest(),
            source_review=sample.source_review.model_copy(update={"path": (base / sample.source_review.path).resolve()}),
            answer_origin="actual_complete_delivery" if sample.kind.startswith("legal") else "offline_adjacent_control",
            transformation_record=_sealed(directory / "transformation.json"),
        )
        (directory / "provenance.json").write_text(provenance.model_dump_json(indent=2), encoding="utf-8")
        inputs.append(QualificationInput(
            sample_id=sample.sample_id, kind=sample.kind,
            user_request=_sealed(directory / "user-request.txt"), complete_answer=_sealed(directory / "answer.txt"),
            reference_set=_sealed(directory / "references.json"), source_capture=sample.source.capture.model_copy(update={"path": (base / sample.source.capture.path).resolve()}),
            source_checksums=sample.source.checksums.model_copy(update={"path": (base / sample.source.checksums.path).resolve()}),
            source_report=_sealed(report_path), provenance=_sealed(directory / "provenance.json"),
            independent_original_ranking_audit=sample.source.original_ranking_audit.model_copy(update={"path": (base / sample.source.original_ranking_audit.path).resolve()}),
        ))
    pending = output / "unvalidated-plan.json"
    pending.write_text(QualificationPlan(inputs=tuple(inputs)).model_dump_json(indent=2), encoding="utf-8")
    load_inputs(pending)
    path = output / "plan.json"
    pending.rename(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(assemble(args.selection.resolve(), args.output.resolve()))


if __name__ == "__main__":
    main()
