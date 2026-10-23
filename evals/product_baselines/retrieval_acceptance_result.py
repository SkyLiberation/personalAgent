"""只读汇总已封存研究的缺交付结果；不构造完整通过结论。"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from personal_agent.application.conversation.models import InteractionTrace
from personal_agent.kernel.contracts.resource import ResourceRef

from .retrieval_capture_audit import CaptureAudit, audit_capture
from .retrieval_qualification_review import Digest, SealedFile
from .run_retrieval_acceptance import CapturedRun


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReceiptProgress(_Strict):
    """成功回执的只读投影；不代表覆盖、质量或任务完成。"""

    development_result_refs: tuple[ResourceRef, ...]
    frozen_refs: tuple[ResourceRef, ...]
    final_result_refs: tuple[ResourceRef, ...]


class MissingDeliveryResult(_Strict):
    version: Literal[1] = 1
    evidence_class: Literal["sealed_research_missing_delivery_result"] = "sealed_research_missing_delivery_result"
    aggregator_source_sha256: Digest
    original_product_result: Literal["not_scored"]
    user_result: Literal["failed"] = "failed"
    failure_attribution: Literal["not_adjudicated"] = "not_adjudicated"
    capture_audit: CaptureAudit
    source_files: tuple[SealedFile, ...]
    receipt_progress: ReceiptProgress
    missing_delivery_items: tuple[Literal["answer_final", "report", "manifest", "bundle"], ...]
    unverified_aspects: tuple[str, ...]
    model_calls_by_this_aggregation: Literal[0] = 0
    limitation: str


class InitialClosureResult(_Strict):
    """Mechanical delivery projection, with no semantic or reproduction verdict."""

    version: Literal[1] = 1
    evidence_class: Literal["initial_research_delivery_result"] = "initial_research_delivery_result"
    aggregator_source_sha256: Digest
    original_product_result: Literal["not_scored"]
    user_result: Literal["failed", "not_scored"]
    capture_audit: CaptureAudit
    source_files: tuple[SealedFile, ...]
    model_calls_by_this_aggregation: Literal[0] = 0
    limitation: str


def summarize_initial_closure(
    preparation: Path, capture: Path, trace_path: Path, *, trace_seal: Path | None = None,
) -> InitialClosureResult:
    audit = audit_capture(preparation, capture, trace_path, trace_seal=trace_seal)
    if audit.phase != "initial_closure":
        raise ValueError("本入口只汇总 initial_closure，不改变旧 target 或资格准备结果")
    paths = [preparation, capture, capture.parent / "checksums.json", trace_path]
    expected = [audit.preparation_sha256, audit.capture_sha256, audit.checksums_sha256, audit.trace_sha256]
    if audit.trace_seal_sha256 is not None:
        if trace_seal is None:
            raise ValueError("机械审计消费的同run seal未提供")
        paths.append(trace_seal)
        expected.append(audit.trace_seal_sha256)
    files = tuple(SealedFile(path=path.resolve(), sha256=sha256(path.read_bytes()).hexdigest()) for path in paths)
    if [item.sha256 for item in files] != expected:
        raise ValueError("初步汇总原件在审计后变化")
    return InitialClosureResult(
        aggregator_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        original_product_result="not_scored", user_result="failed" if audit.user_delivery == "missing" else "not_scored",
        capture_audit=audit, source_files=files,
        limitation="仅汇总同一任务的实际机械交付及费用；完整报告存在不代表语义通过，执行结果有效性、权限观察及agency须分别消费实际证据；下载与打包不在能力验收范围。",
    )


def summarize_missing_delivery(
    preparation: Path, capture: Path, trace_path: Path, *, trace_seal: Path | None = None,
) -> MissingDeliveryResult:
    """消费原审计的完整绑定；旧 capture、seal 和分子全部保持原身份。"""
    audit = audit_capture(preparation, capture, trace_path, trace_seal=trace_seal)
    if audit.user_delivery != "missing":
        raise ValueError("已存在完整交付；须按真实资格、语义预算及全证据契约准入完整汇总，本入口不能判通过")
    trace_bytes, capture_bytes = trace_path.read_bytes(), capture.read_bytes()
    trace = InteractionTrace.model_validate_json(trace_bytes)
    captured = CapturedRun.model_validate_json(capture_bytes)
    # Reject any change between the canonical mechanical audit and this projection.
    if (sha256(trace_bytes).hexdigest() != audit.trace_sha256
            or sha256(capture_bytes).hexdigest() != audit.capture_sha256):
        raise ValueError("机械审计后源原件变化，不能跨版本汇总")
    development, frozen, final = [], [], []
    for record in trace.experiment_records:
        receipt = record.receipt
        if receipt is None or receipt.status != "succeeded":
            continue
        if receipt.operation == "run_development":
            development.extend(receipt.result_refs)
        elif receipt.operation == "freeze":
            if receipt.frozen_ref is not None:
                frozen.append(receipt.frozen_ref)
        elif receipt.operation == "evaluate_final":
            final.extend(receipt.result_refs)
    missing = []
    if audit.final_disposition != "answer":
        missing.append("answer_final")
    if "report" not in audit.delivery_roles:
        missing.append("report")
    if not missing:
        raise ValueError("仅有正式入口／下载取证不足，Journal无明确交付缺项，不能据此判定用户结果失败")
    inputs = (preparation, capture, capture.parent / "checksums.json", trace_path)
    if audit.trace_seal_sha256 is not None:
        if trace_seal is None:
            raise ValueError("机械审计消费的同run seal未提供")
        inputs = (*inputs, trace_seal)
    source_files = tuple(SealedFile(path=p.resolve(), sha256=sha256(p.read_bytes()).hexdigest()) for p in inputs)
    expected = (audit.preparation_sha256, audit.capture_sha256, audit.checksums_sha256, audit.trace_sha256)
    if audit.trace_seal_sha256 is not None:
        expected = (*expected, audit.trace_seal_sha256)
    if tuple(item.sha256 for item in source_files) != expected:
        raise ValueError("汇总源摘要与机械审计不同")
    return MissingDeliveryResult(
        aggregator_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        original_product_result=captured.product_result, capture_audit=audit,
        source_files=source_files,
        receipt_progress=ReceiptProgress(development_result_refs=tuple(development),
            frozen_refs=tuple(frozen), final_result_refs=tuple(final)),
        missing_delivery_items=tuple(missing),
        unverified_aspects=(
            "正式回答与当前实际提交一致",
            "完整查询执行覆盖与配置／test隔离的独立核对",
            "实际实验结果有效性及后继消费",
            "本任务评分资格及同一target的独立语义判断",
            "同主体知识全量前后摘要与完整写入口归因",
            "同轨迹证据驱动选择、agency及机制收益",
        ),
        limitation="用户结果仅按已证实的正式交付缺项记失败；回执只证明局部事实，硬截止和未知消费不等于最早原因。原采集仍not_scored，本输出不是target通过或发布资格。",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", required=True, type=Path)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--trace-seal", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    phase = CapturedRun.model_validate_json(args.capture.read_bytes()).phase
    summarize = summarize_initial_closure if phase == "initial_closure" else summarize_missing_delivery
    report = summarize(args.preparation.resolve(), args.capture.resolve(), args.trace.resolve(),
        trace_seal=args.trace_seal.resolve() if args.trace_seal else None)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(report.model_dump_json(indent=2))
    print(json.dumps({"output": str(args.output), "user_result": report.user_result,
        "original_product_result": report.original_product_result,
        "user_delivery": report.capture_audit.user_delivery,
        **({"missing_delivery_items": report.missing_delivery_items} if isinstance(report, MissingDeliveryResult) else {}),
        "known_tokens": report.capture_audit.known_tokens,
        "unknown_usage_attempts": report.capture_audit.unknown_usage_attempts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
