"""只读审计已停止的研究采集及物理用量；不生成产品通过结论。"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

from openai.types.chat.chat_completion import Choice
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from personal_agent.application.conversation.models import ActionObservation, InteractionTrace
from personal_agent.application.conversation.research_delivery import experiment_submission
from personal_agent.capabilities.contracts.research import ResearchClaims, ResearchReview

from .retrieval_qualification_review import Digest
from .run_retrieval_acceptance import (
    CapturedRun, CaptureLifecycle, CapturePhase, HistoricalCaptureLifecycle, EntryObservation, Preparation, _digest,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunSealJournalProof(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    identity: str
    files: dict[str, Digest]


class ObservedProviderUsage(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ObservedProviderCompletion(BaseModel):
    """Provider 拥有的完整响应；用量字段缺失时仍保留其余真实内容。"""
    model_config = ConfigDict(extra="allow", frozen=True)
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: tuple[Choice, ...]
    usage: ObservedProviderUsage | None = None


class SdkResponseObservation(_Strict):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    observation: Literal["before_capacity_admission"]
    operation: str
    completed: bool
    candidate_body_sha256: Digest | None = None
    response: ObservedProviderCompletion | None = None
    exception_type: str | None = None
    reason_code: str | None = None
    body_observation_error: str | None = None
    wall_seconds: float = Field(ge=0, allow_inf_nan=False)


class HttpSendObservation(_Strict):
    send_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    observation: Literal["httpx_client_send_invoked"]
    candidate_ids_on_client: tuple[str, ...]
    provider_host: str
    method: str
    path: str
    response_received: bool
    request_body_sha256: Digest | None = None
    request_body_bytes: int | None = Field(default=None, ge=0)
    status_code: int | None = None
    exception_type: str | None = None
    body_observation_error: str | None = None
    wall_seconds: float = Field(ge=0, allow_inf_nan=False)


class WireUsageGroup(_Strict):
    wire_value_sha256: Digest
    http_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    complete_sdk_responses: int = Field(ge=0)
    known_tokens: int = Field(ge=0)
    unknown_usage_attempts: int = Field(ge=0)
    missing_http_response_sidecars: tuple[str, ...]


class CaptureAudit(_Strict):
    version: Literal[1] = 1
    evidence_class: Literal["sealed_capture_mechanical_audit"] = "sealed_capture_mechanical_audit"
    auditor_source_sha256: Digest
    case: Literal["e1", "p1"]
    phase: CapturePhase
    preparation_sha256: Digest
    capture_sha256: Digest
    checksums_sha256: Digest
    trace_sha256: Digest
    trace_binding: Literal["authenticated_http_trace", "same_run_seal"]
    trace_seal_sha256: Digest | None
    source_snapshot_sha256: Digest
    source_count: int = Field(gt=0)
    source_changed_during_capture: bool
    trace_revision: int = Field(ge=1)
    lifecycle: CaptureLifecycle | HistoricalCaptureLifecycle
    post_status: int | None
    trace_get_status: int | None
    final_disposition: str | None
    delivery_roles: tuple[Literal["report", "manifest", "bundle"], ...]
    downloads_index_present: bool
    user_delivery: Literal["missing", "present_unscored"]
    candidate_requests: int = Field(ge=0)
    physical_http_requests: int = Field(ge=0)
    complete_sdk_responses: int = Field(ge=0)
    known_tokens: int = Field(ge=0)
    unknown_usage_attempts: int = Field(ge=0)
    wire_groups: tuple[WireUsageGroup, ...]
    model_calls_by_this_audit: Literal[0] = 0
    limitation: str


def _load(path: Path):
    return json.loads(path.read_bytes())


def _wire_groups(directory: Path) -> tuple[tuple[WireUsageGroup, ...], int]:
    """匹配 JSON 值；不把重新序列化的值摘要冒充实际 HTTP bytes 摘要。"""
    candidates: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(directory.glob("*.candidate.request.json")):
        kwargs = _load(path)
        wire = {key: value for key, value in kwargs.items() if key != "extra_body"}
        wire.update(kwargs.get("extra_body") or {})
        candidates[_digest(wire)].append(path)
    http: dict[str, list[Path]] = defaultdict(list)
    body_ids = {path.name.split(".")[0] for path in directory.glob("*.http.request.json")}
    response_ids = {path.name.split(".")[0] for path in directory.glob("*.http.response.json")}
    if response_ids - body_ids:
        raise ValueError("实际 HTTP send 缺完整 body；须保留未知并另审观察失败，不能少计物理请求")
    for path in sorted(directory.glob("*.http.request.json")):
        http[_digest(_load(path))].append(path)
    groups = []
    for digest, paths in http.items():
        matching = candidates.get(digest, [])
        if not matching:
            raise ValueError("实际 HTTP body 无对应 SDK kwargs，不能推测其归属或费用")
        complete = full_usage = known = 0
        for candidate in matching:
            response = candidate.with_name(candidate.name.replace(".request.json", ".response.json"))
            if not response.is_file():
                continue
            record = SdkResponseObservation.model_validate_json(response.read_bytes())
            if (record.candidate_id != candidate.name.split(".")[0]
                    or record.candidate_body_sha256 != sha256(candidate.read_bytes()).hexdigest()
                    or record.body_observation_error):
                raise ValueError("SDK 观察与候选原件不一致或观察失败")
            if not record.completed:
                continue
            actual = record.response
            if actual is None:
                raise ValueError("SDK completed 缺实际响应")
            complete += 1
            if actual.usage is not None:
                if actual.usage.total_tokens is not None:
                    known += actual.usage.total_tokens
                if all(value is not None for value in (actual.usage.prompt_tokens,
                       actual.usage.completion_tokens, actual.usage.total_tokens)):
                    full_usage += 1
        if complete > len(paths):
            raise ValueError("完整 SDK 响应数超过同 body 的真实物理发送，观察身份不成立")
        missing = []
        for path in paths:
            sidecar = path.with_name(path.name.replace(".request.json", ".response.json"))
            identity = path.name.split(".")[0]
            if not sidecar.is_file():
                missing.append(identity)
                continue
            observation = HttpSendObservation.model_validate_json(sidecar.read_bytes())
            if (observation.send_id != identity
                    or observation.request_body_sha256 != sha256(path.read_bytes()).hexdigest()
                    or observation.body_observation_error):
                raise ValueError("实际 HTTP sidecar 与原 body 不一致或观察失败")
        groups.append(WireUsageGroup(
            wire_value_sha256=digest, http_ids=tuple(path.name.split(".")[0] for path in paths),
            candidate_ids=tuple(path.name.split(".")[0] for path in matching), complete_sdk_responses=complete,
            known_tokens=known, unknown_usage_attempts=len(paths) - full_usage,
            missing_http_response_sidecars=tuple(missing)))
    for digest, paths in candidates.items():
        if digest in http:
            continue
        for path in paths:
            response = path.with_name(path.name.replace(".request.json", ".response.json"))
            if response.is_file() and SdkResponseObservation.model_validate_json(response.read_bytes()).completed:
                raise ValueError("完整 SDK 响应没有真实 HTTP 观察，不能宣称物理费用完整")
    return tuple(groups), sum(len(paths) for paths in candidates.values())


def audit_capture(preparation: Path, capture: Path, trace_path: Path, *, trace_seal: Path | None = None) -> CaptureAudit:
    prepared_bytes, capture_bytes = preparation.read_bytes(), capture.read_bytes()
    prepared = Preparation.model_validate_json(prepared_bytes)
    facts = CapturedRun.model_validate_json(capture_bytes)
    root, run_root = capture.resolve().parent, preparation.resolve().parent
    if (root.parent != run_root or root.name != facts.phase or facts.case != prepared.case
            or facts.fault != prepared.fault
            or facts.preparation_sha256 != sha256(prepared_bytes).hexdigest()
            or facts.source_digest != prepared.source_digest
            or facts.configuration_digest != prepared.configuration_digest
            or _digest(_load(run_root / "configuration.json")) != prepared.configuration_digest):
        raise ValueError("采集与准备／配置不是同一身份")
    checksums_path = root / "checksums.json"
    checksums = TypeAdapter(dict[str, Digest]).validate_python(_load(checksums_path))
    required = {"capture-result.json", "lifecycle.json", "entry-observations.json"}
    if not required.issubset(checksums) or checksums["capture-result.json"] != sha256(capture_bytes).hexdigest():
        raise ValueError("没有封存同一 capture 及必要正式入口事实")
    for relative, digest in checksums.items():
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root) or sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("采集原件 checksum 失效")
    expected_files = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()
                      and path != checksums_path}
    if expected_files != set(checksums):
        raise ValueError("采集存在未封存文件或缺文件，不能据不完整 SDK 集合计量")
    if _load(run_root / "configuration.json").get("timeout_policy") == "configured-native-timeouts-v3":
        lifecycle = CaptureLifecycle.model_validate_json((root / "lifecycle.json").read_bytes())
        if (lifecycle.actual_pid is None or lifecycle.actual_exitcode is None or lifecycle.supervision_errors):
            raise ValueError("实际解释器或监督事实不完整，不能作最终审计")
    else:
        lifecycle = HistoricalCaptureLifecycle.model_validate_json((root / "lifecycle.json").read_bytes())
    if not lifecycle.actual_process_stopped or lifecycle.exitcode is None:
        raise ValueError("采集进程尚未实际停止，不能作最终审计")
    hashes = TypeAdapter(dict[str, Digest]).validate_python(_load(run_root / "source-hashes.json"))
    if not hashes or _digest(hashes) != prepared.source_digest:
        raise ValueError("源码清单与准备摘要不同")
    snapshot_path = run_root / "source-snapshot.zip"
    with ZipFile(snapshot_path) as snapshot:
        names = snapshot.namelist()
        if len(names) != len(set(names)) or set(names) != set(hashes):
            raise ValueError("源码快照集合与准备清单不同")
        if any(sha256(snapshot.read(name)).hexdigest() != digest for name, digest in hashes.items()):
            raise ValueError("源码快照原字节与准备身份不同")
    trace_bytes = trace_path.read_bytes()
    trace = InteractionTrace.model_validate_json(trace_bytes)
    journal = run_root / "server-data" / "interaction_runs" / prepared.world.initial.interaction_run_ref
    if (trace_path.resolve().parent != journal.resolve() or trace_path.resolve() != sorted(journal.glob("*.json"))[-1].resolve()
            or trace.principal != prepared.world.initial.principal
            or trace.interaction_run_ref != prepared.world.initial.interaction_run_ref
            or trace.input_artifact_refs != prepared.world.input_artifact_refs):
        raise ValueError("最终 Journal 路径／主体／run／初始公开引用不属于同一采集")
    observations = TypeAdapter(tuple[EntryObservation, ...]).validate_json((root / "entry-observations.json").read_bytes())
    posts = [item for item in observations if item.method == "POST" and item.path == "/api/conversation/turn"]
    gets = [item for item in observations if item.method == "GET" and item.path.startswith("/api/conversation/runs/")]
    if len(posts) != 1 or len(gets) != 1:
        raise ValueError("采集缺唯一正式 POST／run GET 观察")
    get_url = urlsplit(gets[0].path)
    if (get_url.path != f"/api/conversation/runs/{trace.interaction_run_ref}"
            or parse_qs(get_url.query) != {"user_id": [trace.principal.user_id]}):
        raise ValueError("正式 GET 不是准备时的确切 run／user_id")
    seal_digest = None
    if gets[0].status_code == 200:
        if InteractionTrace.model_validate(gets[0].body) != trace:
            raise ValueError("正式 GET 与最终 Journal 不是同版完整 Trace")
        trace_binding = "authenticated_http_trace"
    else:
        if trace_seal is None:
            raise ValueError("未取得正式 GET Trace，须提供同 run seal 绑定最终 Journal")
        seal_bytes = trace_seal.read_bytes()
        proof = RunSealJournalProof.model_validate_json(seal_bytes)
        if proof.identity != run_root.name:
            raise ValueError("最终 Journal seal 属于其他 run 准备目录")
        for path in (preparation, capture, checksums_path, trace_path):
            if proof.files.get(str(path.resolve().relative_to(run_root))) != sha256(path.read_bytes()).hexdigest():
                raise ValueError("run seal 未绑定当前准备／capture／checksums／最终 Journal 原件")
        trace_binding, seal_digest = "same_run_seal", sha256(seal_bytes).hexdigest()
    if facts.phase == "initial_closure" and any(
        isinstance(item, (ResearchClaims, ResearchReview))
        or (isinstance(item, ActionObservation) and item.capability_id == "verify_interaction_draft")
        for item in trace.inputs
    ):
        raise ValueError("初步闭环不能混入 claim 或语义 verifier 执行事实")
    report_present = bool(trace.final_message and trace.final_message.disposition == "answer")
    if report_present:
        submission = experiment_submission(trace)
        if submission.final != trace.final_message:
            raise ValueError("当前回答与实际提交不一致")
    present = report_present and posts[0].status_code == 200 and gets[0].status_code == 200
    roles = ["report"] if report_present else []
    downloads = (root / "downloads/index.json").is_file()
    groups, candidates = _wire_groups(root / "sdk")
    return CaptureAudit(
        auditor_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        case=prepared.case, phase=facts.phase, preparation_sha256=sha256(prepared_bytes).hexdigest(),
        capture_sha256=sha256(capture_bytes).hexdigest(), checksums_sha256=sha256(checksums_path.read_bytes()).hexdigest(),
        trace_sha256=sha256(trace_bytes).hexdigest(), trace_binding=trace_binding, trace_seal_sha256=seal_digest,
        source_snapshot_sha256=sha256(snapshot_path.read_bytes()).hexdigest(),
        source_count=len(hashes), source_changed_during_capture=bool(facts.source_changed_during_capture),
        trace_revision=trace.revision, lifecycle=lifecycle, post_status=posts[0].status_code, trace_get_status=gets[0].status_code,
        final_disposition=trace.final_message.disposition if trace.final_message else None, delivery_roles=tuple(roles),
        downloads_index_present=downloads, user_delivery="present_unscored" if present else "missing",
        candidate_requests=candidates, physical_http_requests=sum(len(group.http_ids) for group in groups),
        complete_sdk_responses=sum(group.complete_sdk_responses for group in groups),
        known_tokens=sum(group.known_tokens for group in groups), unknown_usage_attempts=sum(group.unknown_usage_attempts for group in groups),
        wire_groups=groups, limitation="仅机械采集及物理费用；完整语义、资格、执行结果有效性、权限／知识零写入和 agency 未由此审计判定。")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", required=True, type=Path)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--trace-seal", type=Path, help="正式 GET 未取得 Trace 时的同 run 原封存")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit_capture(args.preparation.resolve(), args.capture.resolve(), args.trace.resolve(),
                           trace_seal=args.trace_seal.resolve() if args.trace_seal else None)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(report.model_dump_json(indent=2))
    print(json.dumps({"output": str(args.output), "user_delivery": report.user_delivery,
                      "physical_http_requests": report.physical_http_requests,
                      "complete_sdk_responses": report.complete_sdk_responses,
                      "known_tokens": report.known_tokens, "unknown_usage_attempts": report.unknown_usage_attempts}))


if __name__ == "__main__":
    main()
