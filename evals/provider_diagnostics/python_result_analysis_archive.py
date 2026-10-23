"""真实来源封存、隔离恢复及原件导出；不调用模型或执行器。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from evals.provider_diagnostics.python_result_analysis_capture import write_record
from evals.provider_diagnostics.python_result_analysis_runtime import branch_settings
from evals.provider_diagnostics.python_result_analysis_models import (
    ClockMapping,
    CostEstimate,
    ExportedArtifact,
    FileStamp,
    GroupPlan,
    GroupState,
    Record,
    RUN_REF,
    SOURCE_ID,
    SOURCE_REQUEST_SHA256,
    SOURCE_TRACE_SHA256,
    SampleState,
    SourceBudget,
    SourceFile,
    SourceSelection,
)

ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = ROOT / "docs/optimization/to_verify/python-data-analysis-tool.md"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def stamp(path: Path) -> FileStamp:
    return FileStamp(path=path.resolve(), sha256=digest(path))


def verify_file(item: FileStamp) -> None:
    if not item.path.is_file() or digest(item.path) != item.sha256:
        raise ValueError(f"归档校验和失效：{item.path}")


def _source_stamp(raw: dict[str, Any]) -> FileStamp:
    path = Path(raw["path"])
    return FileStamp(
        path=path if path.is_absolute() else ROOT / path, sha256=raw["sha256"]
    )


def select_source(preflight: Path) -> SourceSelection:
    raw = json.loads(preflight.read_text(encoding="utf-8"))
    matches = [item for item in raw["sources"] if item["candidate_id"] == SOURCE_ID]
    if len(matches) != 1:
        raise ValueError("预检必须唯一绑定af209真实报告阶段")
    stage = matches[0]
    request, trace = _source_stamp(stage["request"]), _source_stamp(stage["journal"])
    if request.sha256 != SOURCE_REQUEST_SHA256 or trace.sha256 != SOURCE_TRACE_SHA256:
        raise ValueError("真实源不是预声明的af209／0056")
    verify_file(trace)
    journal = json.loads(trace.path.read_text(encoding="utf-8"))
    sdk = json.loads(request.path.read_text(encoding="utf-8"))
    budget_lines = [
        line.removeprefix("剩余预算：")
        for line in sdk["messages"][0]["content"].splitlines()
        if line.startswith("剩余预算：")
    ]
    if len(budget_lines) != 1:
        raise ValueError("真实SDK缺少唯一源预算快照")
    remaining = SourceBudget.model_validate_json(budget_lines[0])
    execution_remaining = journal["max_execution_seconds"] - sum(
        item["execution"]["elapsed_seconds"]
        for item in journal["experiment_records"]
        if item.get("execution") is not None
    )
    if (
        remaining != SourceBudget.model_validate(stage["remaining_at_input"])
        or execution_remaining != stage["remaining_execution_seconds"]
    ):
        raise ValueError("预检预算与真实SDK／Journal不一致，不能重置余量")
    files = tuple(
        SourceFile.model_validate({key: item[key] for key in SourceFile.model_fields})
        for item in raw["artifacts"]
        if "report_stage" in item["visible_in"]
    )
    source = SourceSelection(
        request=request,
        trace=trace,
        profile=_source_stamp(raw["original_identity"]["configuration"]),
        deployment=_source_stamp(raw["docker_configuration"]["private_source"]),
        artifact_root=ROOT / raw["artifact_roots"]["original"],
        journal_root=trace.path.parent,
        artifact_files=files,
        remaining=remaining,
        original_deadline_at=journal["run_deadline_at"],
        execution_remaining_seconds=execution_remaining,
    )
    if len(files) != 57 or stage["input_count"] != 89 or stage["tool_count"] != 19:
        raise ValueError("源完整输入或可读集数量与已审计阶段不同")
    visible = {
        item["resource"]["resource_ref"]["resource_id"]
        for item in journal["inputs"]
        if item["kind"] == "artifact_source"
    }
    if visible != {item.resource_ref.resource_id for item in files}:
        raise ValueError("57项原件必须恰为0056的实际可见集，不能补进其他归档原件")
    for item in (source.request, source.trace, source.profile, source.deployment):
        verify_file(item)
    return source


def code_identity() -> dict[str, str]:
    paths = list((ROOT / "src").rglob("*.py"))
    paths += list(
        (ROOT / "evals/provider_diagnostics").glob("python_result_analysis*.py")
    )
    paths += [
        ROOT / "evals/product_baselines/retrieval_http_server.py",
        ROOT / "pyproject.toml",
    ]
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(paths)}


def verify_plan(plan: GroupPlan) -> None:
    for item in (
        plan.source.request,
        plan.source.trace,
        plan.source.profile,
        plan.source.deployment,
        plan.authority,
    ):
        verify_file(item)
    for name, expected in plan.code_files.items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"准备后代码身份已变：{name}；不能混入当前组")


def prepare(directory: Path, preflight: Path) -> GroupPlan:
    if directory.exists():
        raise FileExistsError("新组目录必须不存在；不覆盖或续期旧组")
    source = select_source(preflight)
    request = json.loads(source.request.path.read_text(encoding="utf-8"))
    wire = {key: value for key, value in request.items() if key != "extra_body"}
    wire.update(request.get("extra_body") or {})
    ascii_bytes = len(
        json.dumps(wire, ensure_ascii=True, sort_keys=True).encode("ascii")
    )
    profile = json.loads(source.profile.path.read_text(encoding="utf-8"))
    if profile["structured"]["model"] != "deepseek-flash":
        raise ValueError("来源profile已不是预声明DeepSeek配置")
    plan = GroupPlan(
        group_id=f"python-analysis-{uuid4().hex}",
        created_at=datetime.now(UTC),
        source=source,
        order=tuple(f"{arm}{index}" for index in range(1, 11) for arm in ("B", "C")),
        cost_estimate=CostEstimate(
            source_measured_input_tokens=146271,
            source_body_ascii_bytes=ascii_bytes,
            source_sized_80_call_tokens=(146271 + 32768) * 80,
            first_call_reservation_tokens=ascii_bytes + 32768 + 8192,
            note=(
                "146271是源实测输入；ASCII SDK正文＋协议预留＋最大输出逐次预留，"
                "按实际usage结算；后继输入增长未知，不承诺预算容纳完整20个分支。"
            ),
        ),
        code_files=code_identity(),
        authority=stamp(AUTHORITY),
    )
    branch_settings(plan, directory / "preflight")
    directory.mkdir(parents=True)
    write_record(directory / "plan.json", plan)
    write_record(
        directory / "group-state.json",
        GroupState(
            group_id=plan.group_id,
            samples=tuple(SampleState(sample_id=item) for item in plan.order),
        ),
    )
    with ZipFile(
        directory / "code-snapshot.zip", "x", compression=ZIP_DEFLATED
    ) as archive:
        for name in plan.code_files:
            archive.write(ROOT / name, name)
        archive.write(AUTHORITY, AUTHORITY.relative_to(ROOT).as_posix())
    seal = PreparationSeal(
        plan=stamp(directory / "plan.json"),
        code_snapshot=stamp(directory / "code-snapshot.zip"),
        preflight=stamp(preflight),
    )
    write_record(directory / "preparation-seal.json", seal)
    return plan


class PreparationSeal(Record):
    plan: FileStamp
    code_snapshot: FileStamp
    preflight: FileStamp


def load_plan(directory: Path) -> GroupPlan:
    seal = PreparationSeal.model_validate_json(
        (directory / "preparation-seal.json").read_bytes()
    )
    for item in (seal.plan, seal.code_snapshot, seal.preflight):
        verify_file(item)
    plan = GroupPlan.model_validate_json((directory / "plan.json").read_bytes())
    verify_plan(plan)
    return plan


def restore_branch(plan: GroupPlan, branch: Path) -> ClockMapping:
    """仅在独立Offline副本映射deadline；原预算和原件不变。"""
    source = plan.source
    mapped_at = datetime.now(UTC)
    mapping = ClockMapping(
        source_deadline_at=source.original_deadline_at,
        mapped_at=mapped_at,
        source_remaining_seconds=source.remaining.wall_seconds_at_input,
        mapped_deadline_at=mapped_at
        + timedelta(seconds=source.remaining.wall_seconds_at_input),
        source_trace_sha256=source.trace.sha256,
    )
    branch.mkdir()
    data_dir = branch / "data"
    for artifact in source.artifact_files:
        folder = source.artifact_root / artifact.subdirectory
        original = folder / artifact.storage_name
        metadata = folder / f"{artifact.resource_ref.resource_id}.json"
        # Metadata is parsed at its owning typed boundary before copying.
        from personal_agent.application.artifacts.models import ArtifactRecord

        record = ArtifactRecord.model_validate_json(metadata.read_bytes())
        if (
            record.resource_ref != artifact.resource_ref
            or record.filename != artifact.filename
            or record.storage_name != artifact.storage_name
            or record.content_digest != artifact.sha256
            or record.size_bytes != artifact.bytes
            or digest(original) != artifact.sha256
            or original.stat().st_size != artifact.bytes
        ):
            raise ValueError("原件版本／摘要／长度／metadata不符")
        target = data_dir / artifact.subdirectory
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target / original.name)
        shutil.copy2(metadata, target / metadata.name)
    run_dir = data_dir / "interaction_runs" / RUN_REF
    run_dir.mkdir(parents=True)
    for revision in range(1, 57):
        name = f"{revision:04d}.json"
        shutil.copy2(source.journal_root / name, run_dir / name)
    trace = json.loads((run_dir / "0056.json").read_text(encoding="utf-8"))
    trace["run_deadline_at"] = mapping.mapped_deadline_at.isoformat()
    (run_dir / "0056.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_record(branch / "clock-mapping.json", mapping)
    return mapping


def export_artifacts(trace, branch: Path, *, original_action_ids: frozenset[str]):
    """导出新draft和Python全部原件；不据文件名或关键词判断报告正确。"""
    from personal_agent.application.artifacts.models import ArtifactRecord
    from personal_agent.application.conversation.models import SubmittedFinal
    from personal_agent.kernel.contracts.resource import ResourceRef

    refs: dict[ResourceRef, str] = {}
    accepted_paths = []
    accepted_dir = branch / "accepted"
    accepted_dir.mkdir(exist_ok=True)
    for accepted in trace.accepted_tool_requests:
        if accepted.action_id in original_action_ids:
            continue
        path = accepted_dir / f"{sha256(accepted.action_id.encode()).hexdigest()}.json"
        path.write_text(accepted.model_dump_json(indent=2), encoding="utf-8")
        accepted_paths.append(path)
        if accepted.tool_name == "write_artifact" and accepted.receipt is not None:
            refs[accepted.receipt.resource_ref] = "draft_candidate"
        elif accepted.tool_name == "execute_python":
            if accepted.command is not None:
                refs[accepted.command.program.resource_ref] = "python_original"
                refs.update(
                    {
                        item.resource_ref: "python_original"
                        for item in accepted.command.inputs
                    }
                )
            receipt = accepted.receipt
            if receipt is not None:
                for ref in (
                    receipt.program_ref,
                    receipt.input_manifest_ref,
                    receipt.stdout_ref,
                    receipt.stderr_ref,
                ):
                    if ref is not None:
                        refs[ref] = "python_original"
    report_submission = None
    delivery = trace.research_experiment_delivery
    if delivery is not None and delivery.report_ref is not None:
        submissions = [
            item
            for item in trace.inputs
            if isinstance(item, SubmittedFinal)
            and item.resource_ref == delivery.binding.submission_ref
        ]
        if len(submissions) != 1:
            raise ValueError("真实发布报告缺少唯一SubmittedFinal绑定")
        report_submission = submissions[0]
        if (
            sha256(report_submission.final.message.encode("utf-8")).hexdigest()
            != delivery.binding.body_digest
        ):
            raise ValueError("发布绑定与SubmittedFinal正文摘要不同")
        refs[delivery.report_ref] = "report"
    exported = []
    export_dir = branch / "artifacts"
    export_dir.mkdir(exist_ok=True)
    for ref, role in refs.items():
        folder = (
            branch
            / "data"
            / (
                "uploads"
                if ref.resource_id.startswith("art_")
                else "generated_artifacts"
            )
        )
        record = ArtifactRecord.model_validate_json(
            (folder / f"{ref.resource_id}.json").read_bytes()
        )
        original = folder / record.storage_name
        if record.resource_ref != ref or digest(original) != record.content_digest:
            raise ValueError("产物导出原件身份／字节失效")
        if role == "report" and (
            report_submission is None
            or record.content_digest != delivery.binding.body_digest
            or original.read_bytes() != report_submission.final.message.encode("utf-8")
        ):
            raise ValueError("发布报告原字节与SubmittedFinal／body_digest不同")
        # The original display name stays in metadata. Bound the actual host
        # basename so a legal long model filename cannot exceed Windows MAX_PATH.
        content_path = export_dir / f"{ref.resource_id}.bin"
        shutil.copy2(original, content_path)
        exported.append(
            ExportedArtifact(
                resource_ref=ref,
                filename=record.filename,
                content_type=record.content_type,
                content_path=content_path,
                sha256=record.content_digest,
                role=role,
                report_binding=delivery.binding if role == "report" else None,
            )
        )
    return tuple(exported), tuple(accepted_paths)
