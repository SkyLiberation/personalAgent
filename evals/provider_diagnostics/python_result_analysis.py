"""真实报告阶段的Python分析局部回放：准备、单样本执行、独立审读。

本模块不自动运行；--help和--prepare不会构造Runtime或调用模型／Docker。
--validate-inputs构造两arm正式Web Runtime，首SDK截断，禁止HTTP／模型／容器。
--run-next是显式付费入口，每次最多执行B1/C1…B10/C10中的一个原子样本。
所有成稿关系由独立审读记录拥有，文件名、数字或关键词不会自动判通过。
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Iterator, Literal, TypedDict

from evals.provider_diagnostics.python_result_analysis_archive import (
    ROOT,
    digest,
    export_artifacts,
    load_plan,
    prepare,
    restore_branch,
    stamp,
)
from evals.provider_diagnostics.python_result_analysis_capture import (
    GroupLedger,
    SampleStopped,
    SdkCapture,
    write_record,
)
from evals.provider_diagnostics.python_result_analysis_models import (
    FileStamp,
    GroupPlan,
    IndependentReview,
    Record,
    RUN_REF,
    SampleResult,
)
from evals.provider_diagnostics.python_result_analysis_runtime import (
    branch_environment,
    branch_settings,
    build_branch_context,
    converse_source,
    root_configuration,
)


@contextmanager
def group_lock(directory: Path) -> Iterator[None]:
    """拒绝并发和中断后不确定续跑；不自动删除他人的活跃锁。"""
    path = directory / "run-next.lock"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(datetime.now(UTC).isoformat())
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


class SampleFailure(Record):
    sample_id: str
    at: datetime
    error_type: str
    stage: str
    note: str


class SampleSeal(Record):
    files: tuple[FileStamp, ...]


class SampleChanges(TypedDict, total=False):
    status: Literal["running", "awaiting_review", "reviewed"]
    started_at: datetime
    result: FileStamp
    review: FileStamp


def _seal_sample(branch: Path) -> None:
    files = tuple(
        stamp(path)
        for path in sorted(branch.rglob("*"))
        if path.is_file()
        and not path.name.endswith(".lock")
        and path.name != "sample-seal.json"
    )
    write_record(branch / "sample-seal.json", SampleSeal(files=files))


def _mark_sample(
    ledger: GroupLedger,
    sample_id: str,
    *,
    status: Literal["running", "awaiting_review", "reviewed"],
    started_at: datetime | None = None,
    result: FileStamp | None = None,
    review: FileStamp | None = None,
) -> None:
    changes: SampleChanges = {"status": status}
    if started_at is not None:
        changes["started_at"] = started_at
    if result is not None:
        changes["result"] = result
    if review is not None:
        changes["review"] = review
    ledger.save(
        ledger.state.model_copy(
            update={
                "samples": tuple(
                    sample.model_copy(update=changes)
                    if sample.sample_id == sample_id
                    else sample
                    for sample in ledger.state.samples
                ),
            }
        )
    )


def _run_one(
    plan: GroupPlan, ledger: GroupLedger, directory: Path, sample_id: str, settings
) -> SampleResult:
    """消费同轨迹实际输出；模型、工具及成稿均不由评测脚本补写。"""
    from personal_agent.application.conversation.journal import FileInteractionJournal
    from personal_agent.application.conversation.models import InteractionTrace

    started = datetime.now(UTC)
    branch = directory / sample_id
    mapping = restore_branch(plan, branch)
    (branch / "sdk").mkdir()
    original = InteractionTrace.model_validate_json(plan.source.trace.path.read_bytes())
    original_actions = frozenset(
        item.action_id for item in original.accepted_tool_requests
    )
    write_record(branch / "root-configuration.json", root_configuration(plan, settings))
    capture = SdkCapture(
        ledger=ledger,
        sample_id=sample_id,
        directory=branch / "sdk",
        source_sdk=json.loads(plan.source.request.path.read_text(encoding="utf-8")),
        mapped_deadline=mapping.mapped_deadline_at,
        provider_host=settings.structured.capacity.provider_host,
        provider_timeout=settings.structured.timeout_seconds,
    )
    reason = "runtime_returned"
    # Capture is installed before construction, so unexpected model activity
    # during initialization cannot escape the physical-send accounting.
    context = None
    with capture.installed(), branch_environment(branch):
        try:
            context = build_branch_context(settings, baseline=sample_id.startswith("B"))
            view = converse_source(context.service, original)
            (branch / "turn.json").write_text(
                view.model_dump_json(indent=2), encoding="utf-8"
            )
        except SampleStopped as stopped:
            reason = stopped.reason
            if stopped.stop_group:
                ledger.stop(reason)
        except Exception as error:
            reason = "runtime_failure"
            write_record(
                branch / "runtime-failure.json",
                SampleFailure(
                    sample_id=sample_id,
                    at=datetime.now(UTC),
                    error_type=type(error).__name__,
                    stage="composition_or_conversation",
                    note="保留原失败；不重试或补样。",
                ),
            )
            ledger.stop(reason)
        finally:
            if context is not None:
                context.shutdown()
    journal = FileInteractionJournal(branch / "data/interaction_runs")
    trace = journal.get(RUN_REF)
    if trace is None:
        raise ValueError("实际恢复Journal丢失")
    trace_path = branch / "final-trace.json"
    trace_path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
    artifacts, accepted = export_artifacts(
        trace, branch, original_action_ids=original_actions
    )
    audit_path = branch / "first-sdk-audit.json"
    return SampleResult(
        sample_id=sample_id,
        reason=reason,
        started_at=started,
        finished_at=datetime.now(UTC),
        source_trace_sha256=plan.source.trace.sha256,
        clock_mapping=stamp(branch / "clock-mapping.json"),
        final_trace=stamp(trace_path),
        new_artifacts=artifacts,
        accepted_request_files=accepted,
        first_sdk_audit=stamp(audit_path) if audit_path.exists() else None,
        physical_send_ids=tuple(
            item.send_id
            for item in ledger.state.physical_calls
            if item.sample_id == sample_id
        ),
        sdk_directory=branch / "sdk",
    )


def run_next(directory: Path, input_validation: Path) -> dict[str, object]:
    from evals.provider_diagnostics.python_result_analysis_inputs import (
        require_validated_inputs,
    )

    with group_lock(directory):
        plan = load_plan(directory)
        ledger = GroupLedger(directory, plan)
        if ledger.state.stopped_reason:
            raise ValueError(f"本组已停止，不能补样：{ledger.state.stopped_reason}")
        if any(
            item.status in {"running", "awaiting_review"}
            for item in ledger.state.samples
        ):
            raise ValueError("上一原子样本尚未完成独立审读，禁止推进")
        pending = next(
            (item for item in ledger.state.samples if item.status == "pending"), None
        )
        if pending is None:
            return {
                "status": "all_samples_reviewed",
                "repair_claim": "需读取完整独立审读，不自动宣称修复",
            }
        settings = branch_settings(plan, directory / pending.sample_id)
        require_validated_inputs(input_validation, plan, settings)
        now = datetime.now(UTC)
        if ledger.state.started_at is None:
            ledger.save(ledger.state.model_copy(update={"started_at": now}))
        if (now - ledger.state.started_at).total_seconds() >= plan.limits.wall_seconds:
            ledger.stop("group_wall_limit")
            raise ValueError("两小时组时限已到，剩余样本保留未执行")
        _mark_sample(ledger, pending.sample_id, status="running", started_at=now)
        try:
            result = _run_one(plan, ledger, directory, pending.sample_id, settings)
            result_path = directory / pending.sample_id / "result.json"
            write_record(result_path, result)
            _seal_sample(directory / pending.sample_id)
        except BaseException as error:
            ledger.stop("sample_setup_or_archive_failure")
            result_path = directory / f"{pending.sample_id}.failure.json"
            write_record(
                result_path,
                SampleFailure(
                    sample_id=pending.sample_id,
                    at=datetime.now(UTC),
                    error_type=type(error).__name__,
                    stage="setup_or_archive",
                    note="可能存在实际响应，检查SDK和group-state；禁止重新执行该样本。",
                ),
            )
            _mark_sample(
                ledger,
                pending.sample_id,
                status="awaiting_review",
                result=stamp(result_path),
            )
            raise
        _mark_sample(
            ledger,
            pending.sample_id,
            status="awaiting_review",
            result=stamp(result_path),
        )
        return {
            "sample_id": pending.sample_id,
            "result": str(result_path),
            "reason": result.reason,
            "known_group_tokens": ledger.state.known_tokens,
            "group_physical_calls": len(ledger.state.physical_calls),
            "status": "awaiting_independent_review",
            "stopped_reason": ledger.state.stopped_reason,
            "draft_candidates": [
                str(item.content_path)
                for item in result.new_artifacts
                if item.role == "draft_candidate"
            ],
            "published_reports": [
                str(item.content_path)
                for item in result.new_artifacts
                if item.role == "report"
            ],
            "note": "配置和程序不算报告；全部代码、回执、原响应与关系由独立审读确认。",
        }


def record_review(directory: Path, review_path: Path) -> dict[str, object]:
    with group_lock(directory):
        plan = load_plan(directory)
        ledger = GroupLedger(directory, plan)
        review = IndependentReview.model_validate_json(review_path.read_bytes())
        waiting = [
            item for item in ledger.state.samples if item.status == "awaiting_review"
        ]
        if len(waiting) != 1 or waiting[0].sample_id != review.sample_id:
            raise ValueError("审读必须属于唯一待审原子样本")
        sample = waiting[0]
        if (
            sample.result is None
            or sample.result.sha256 != review.result_sha256
            or digest(sample.result.path) != sample.result.sha256
        ):
            raise ValueError("审读未绑定当前完整样本结果")
        seal_path = directory / sample.sample_id / "sample-seal.json"
        if seal_path.exists():
            seal = SampleSeal.model_validate_json(seal_path.read_bytes())
            for item in seal.files:
                if digest(item.path) != item.sha256:
                    raise ValueError("样本原件在审读前变化，不能继续该组")
        target = directory / f"{sample.sample_id}.review.json"
        if target.exists():
            raise FileExistsError("独立审读已封存，不能覆盖")
        write_record(target, review)
        _mark_sample(ledger, sample.sample_id, status="reviewed", review=stamp(target))
        if sample.sample_id.startswith("C") and (
            review.user_report == "failed"
            or any(item.verdict == "failed" for item in review.relations)
        ):
            ledger.stop("candidate_semantic_failure")
        return {
            "sample_id": sample.sample_id,
            "review": str(target),
            "stopped_reason": ledger.state.stopped_reason,
            "reviewed_samples": sum(
                item.status == "reviewed" for item in ledger.state.samples
            ),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--prepare",
        action="store_true",
        help="零模型准备新独立组并封存来源、计划、代码",
    )
    mode.add_argument(
        "--validate-inputs",
        type=Path,
        metavar="DIR",
        help="独立目录构造两arm完整首SDK并截断；零HTTP，不更新样本",
    )
    mode.add_argument(
        "--run-next",
        action="store_true",
        help="显式付费：仅执行下一原子样本，随后等待独立审读",
    )
    mode.add_argument(
        "--record-review",
        type=Path,
        metavar="JSON",
        help="登记绑定结果摘要的独立审读；不调用业务",
    )
    parser.add_argument(
        "--input-validation",
        type=Path,
        help="run-next必需：当前身份已通过的两arm输入预检目录",
    )
    parser.add_argument(
        "--group-dir", type=Path, required=True, help="本工作区.tmp内的新组／既有组目录"
    )
    parser.add_argument(
        "--source-preflight",
        type=Path,
        default=ROOT
        / ".tmp/python-analysis-implementation-20261021/source-preflight.json",
    )
    args = parser.parse_args()
    directory = args.group_dir.resolve()
    if not directory.is_relative_to((ROOT / ".tmp").resolve()):
        parser.error("group-dir必须在仓库.tmp内，不能写回源证据目录")
    source_root = ROOT / ".tmp/context-compression-research-20261021"
    legacy_root = ROOT / ".tmp/report-statistics-20261021"
    if directory.is_relative_to(source_root) or directory.is_relative_to(legacy_root):
        parser.error("不能把新组放入sealed原来源或已关闭组")
    try:
        if args.prepare:
            plan = prepare(directory, args.source_preflight.resolve())
            result = {
                "group_id": plan.group_id,
                "plan": str(directory / "plan.json"),
                "model_calls": 0,
                "container_calls": 0,
                "cost_estimate": plan.cost_estimate.model_dump(mode="json"),
                "status": "prepared_not_run",
            }
        elif args.run_next:
            if args.input_validation is None:
                parser.error("run-next须提供--input-validation，不能跳过两arm预检")
            result = run_next(directory, args.input_validation.resolve())
        elif args.validate_inputs is not None:
            from evals.provider_diagnostics.python_result_analysis_inputs import (
                validate_inputs,
            )

            validation_dir = args.validate_inputs.resolve()
            if (
                not validation_dir.is_relative_to((ROOT / ".tmp").resolve())
                or validation_dir.is_relative_to(directory)
                or validation_dir.is_relative_to(source_root)
                or validation_dir.is_relative_to(legacy_root)
            ):
                parser.error("预检须使用.tmp内独立新目录，不能写入既有组或sealed来源")
            validation = validate_inputs(directory, validation_dir)
            result = {
                "passed": validation.passed,
                "validation": str(validation_dir / "validation-result.json"),
                "physical_sends": 0,
                "model_responses": 0,
                "container_starts": 0,
                "arms": [
                    {"arm": item.arm, "passed": item.passed, "reason": item.reason}
                    for item in validation.arms
                ],
            }
        else:
            result = record_review(directory, args.record_review.resolve())
    except (ValueError, FileNotFoundError, FileExistsError) as error:
        parser.exit(2, f"{type(error).__name__}: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
