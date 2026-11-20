"""LongDS 正式 HTTP 基线：只传题、上传原件、记录实际回答。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from evals.conversation_http import (
    ROOT, UNVERIFIED_FLOW, benchmark_feature_flags, local_attachments, product, submit_turn, turn_path,
    upload_attachments, wait_for_product,
)
from evals.sdk_capture import redact_payload
from personal_agent.adapters.web.routes.conversation import (
    ConversationTurnRequest,
    ConversationTurnResponse,
    PendingConversationTurn,
)
from personal_agent.application.bash_execution.models import BashExecutionAuthorization
from personal_agent.infra.storage.sqlite_conversation_journal import SqliteInteractionJournal
from personal_agent.infra.bash_execution.deployment import BashExecutionDeploymentConfig
from personal_agent.kernel.config import Settings
from personal_agent.kernel.feature_flags import write_feature_flags
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.kernel.contracts.resource import ResourceRef

from .longds_materials import json_bytes, prepare, seal, verify_preparation, verify_seal
from .retrieval_capture_audit import (
    GenerationTokenBreakdown, GenerationUsage, _digest, read_generation_usage,
)


@dataclass(frozen=True, slots=True)
class LongDSOutcomeContract:
    """Why one Product E2E may contribute to product completion claims."""

    outcome_id: str
    persona: str
    source_ref: str
    natural_goal: str
    observable_result: str
    counterfactuals: tuple[str, ...]
    baseline_kind: Literal["implementation_failure"]
    baseline_ref: str
    assertion_owner: str


LONGDS_ANSWER_RESULT = AnswerResultConfig(test_mode=True)
LONGDS_OUTCOME = LongDSOutcomeContract(
    outcome_id="LONGDS-NETFLIX-003",
    persona="持续调整市场分析条件并回看历史口径的中文分析用户",
    source_ref="docs/optimization/to_verify/longds-analysis.md#longds-长程数据分析-spec",
    natural_goal="分析 Netflix 目录与各国搜索热度，连续处理 36 轮调整和历史比较，最终推荐三个市场。",
    observable_result="逐轮从正式入口得到实际分析答案；按固定官方协议分别报告正确轮数、最终推荐和流程完成。",
    counterfactuals=("未来问题和参考答案不进入生产输入", "未授权跨对话原件拒绝且零执行",
                     "同请求恢复不重复执行", "总预算耗尽不新增付费调用，未知消费保留且不单独停止"),
    baseline_kind="implementation_failure",
    baseline_ref="docs/optimization/to_verify/longds-analysis.md#6-分阶段验收与停止条件",
    assertion_owner="evals/longDS/longds_judge.py",
)


class LongDSCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_class: Literal["unscored_product_capture", "unverified_flow_capture"] = "unscored_product_capture"
    release_eligible: Literal[False] = False
    answer_result: AnswerResultConfig | None = None
    purpose: Literal["baseline", "target"]
    planned_user_turns: int = Field(ge=1, le=50)
    preceding_source_turns: int = Field(default=0, ge=0, le=49)
    requested_turns: int = Field(ge=0, le=50)
    answered_turns: int = Field(ge=0, le=50)
    unexecuted_turns: int = Field(ge=0, le=50)
    stop_reason: str
    exception_type: str | None = None
    physical_model_requests: int = Field(ge=0)
    known_tokens: int = Field(ge=0)
    unknown_usage_attempts: int = Field(ge=0)
    token_breakdown: GenerationTokenBreakdown | None = None
    actual_process_stopped: bool
    wall_seconds: float = Field(ge=0)
    semantic_score: Literal["not_scored"] = "not_scored"


class LongDSRecoveryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    next_user_turn: Literal[18] = 18
    principal: AuthenticatedPrincipal
    session_id: str
    input_artifact_refs: tuple[ResourceRef, ...]
    preparation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    known_tokens: int = Field(ge=0)


def _checkpoint(directory: Path, *, result: ConversationTurnResponse,
                references: tuple[ResourceRef, ...], materials: Path, usage: GenerationUsage) -> None:
    deployment = BashExecutionDeploymentConfig.model_validate_json((directory / "bash-deployment.json").read_bytes())
    authorization = deployment.authorization
    journal = SqliteInteractionJournal(directory / "server-data/conversation_journal")
    trace = journal.get(result.turn_id)
    if (trace is None or trace.final_message is None or trace.final_message.disposition != "answer"
            or trace.bash_authorization_digest != authorization.authorization_digest
            or trace.principal != authorization.authorized_principal
            or trace.interaction_run_ref != result.turn_id
            or trace.conversation_id != result.session_id or result.session_id != authorization.conversation_id
            or len(trace.messages) != 33 or trace.input_artifact_refs != references
            or result.message.role != "assistant" or result.message.content != trace.final_message.message
            or journal.execution_budget(trace).unsettled_action_ids):
        raise ValueError("第17轮尚无完整Final或仍存在未决工具执行，不能建立恢复检查点")
    snapshot = directory / "checkpoint-17"
    snapshot.mkdir(exist_ok=False)
    shutil.copytree(directory / "server-data", snapshot / "server-data")
    shutil.copyfile(directory / "bash-deployment.json", snapshot / "bash-deployment.json")
    shutil.copyfile(directory / "configuration.json", snapshot / "configuration.json")
    recovery = LongDSRecoveryInput(principal=trace.principal, session_id=trace.conversation_id,
        input_artifact_refs=references,
        preparation_sha256=sha256((materials / "preparation.json").read_bytes()).hexdigest(),
        source_digest=json.loads((directory / "repository.json").read_bytes())["source_digest"],
        configuration_sha256=sha256((directory / "configuration.json").read_bytes()).hexdigest(),
        known_tokens=usage.known_tokens)
    _write(snapshot / "recovery-input.json", recovery.model_dump(mode="json"))
    seal(snapshot)


def _write(path: Path, value: object) -> None:
    path.write_bytes(json_bytes(value))


def _configuration(settings: Settings) -> dict[str, object]:
    result: dict[str, object] = {
        "profile": "configured",
        "timeout_policy": "configured-native-timeouts-v3",
        "budget": settings.interaction_loop.model_dump(mode="json"),
        "authentication": "ephemeral API key bound to the exact initial principal",
    }
    for name, model in (("structured", settings.structured), ("openai", settings.openai)):
        result[name] = {
            "model": model.model,
            "provider_host": urlsplit(model.base_url or "").hostname,
            "provider_url_digest": sha256((model.base_url or "").encode()).hexdigest(),
            "timeout_seconds": model.timeout_seconds,
            "max_retries": model.max_retries,
            "capacity": model.capacity.model_dump(mode="json") if model.capacity else None,
        }
    result["structured"].update({
        "output_transport": settings.structured.output_transport,
        "extra_body": redact_payload(settings.structured.extra_body),
        "extra_body_digest": _digest(settings.structured.extra_body),
    })
    return {**result, "answer_result": settings.answer_result.model_dump(mode="json"),
            "feature_flags": settings.feature_flags.model_dump(mode="json"),
            "prompt_language": settings.prompt_language,
            "web_search_available": settings.web_search_available}


def _source_paths() -> list[Path]:
    return [*ROOT.joinpath("src").rglob("*.py"),
            *Path(__file__).resolve().parent.glob("*.py"),
            *(ROOT / "evals" / name for name in ("conversation_http.py", "sdk_capture.py", "web_process.py")),
            Path(__file__).with_name("longds_zh.json"), ROOT / "pyproject.toml"]


def _source_identity(directory: Path) -> None:
    paths = _source_paths()
    hashes = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
              for p in sorted(paths)}
    _write(directory / "source-hashes.json", hashes)
    _write(directory / "repository.json", {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_digest": sha256(json_bytes(hashes)).hexdigest(),
    })
    (directory / "repository.patch").write_bytes(subprocess.check_output(
        ["git", "diff", "--binary", "HEAD"], cwd=ROOT))
    # 未提交的新评测源码也必须可还原，不只保存未跟踪文件名。
    sources = directory / "source-snapshot"
    for p in paths:
        target = sources / p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.read_bytes())


def _environment(settings: Settings, directory: Path, *, principal: AuthenticatedPrincipal,
                 api_key: str, authorization_file: Path | None) -> dict[str, str]:
    parsed = urlsplit(settings.postgres_url or "")
    if not parsed.username or not parsed.password:
        raise ValueError("缺少既有本机评测数据库凭据")
    auth = parsed.netloc.rsplit("@", 1)[0]
    database = urlunsplit((parsed.scheme, auth + "@127.0.0.1:16432", "/personal_agent_test", parsed.query, ""))
    env = os.environ.copy()
    env.update({
        "PERSONAL_AGENT_POSTGRES_URL": database,
        "PERSONAL_AGENT_DATA_DIR": str(directory / "server-data"),
        "PERSONAL_AGENT_API_KEYS": json.dumps({api_key: principal.model_dump(mode="json")}),
        "PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_ENABLED": "false",
        "PERSONAL_AGENT_KNOWLEDGE_GAP_SCHEDULER_ENABLED": "false",
        "PERSONAL_AGENT_RESEARCH_SCHEDULER_ENABLED": "false",
        "PERSONAL_AGENT_LANGSMITH_ENABLED": "false", "PERSONAL_AGENT_FEISHU_ENABLED": "false",
        "PERSONAL_AGENT_MCP_SERVERS": '{"enabled":false}',
        "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false", "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
        "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED": "false",
        "PERSONAL_AGENT_GRAPHITI_GROUP_PREFIX": "longds-" + uuid4().hex,
        "PERSONAL_AGENT_E2E_TRACE_DIR": str(directory / "e2e"),
        "PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR": str(directory / "product"),
        "PERSONAL_AGENT_ANSWER_RESULT": settings.answer_result.model_dump_json(),
        "PERSONAL_AGENT_FEATURE_FLAGS_CONFIG": str((directory / "feature_flags.toml").resolve()),
    })
    for name in ("PERSONAL_AGENT_RETRIEVAL_EXPERIMENT_CONFIG", "PERSONAL_AGENT_BASH_EXECUTION_CONFIG", "PERSONAL_AGENT_ADMIN_API_KEYS",
                 "RETRIEVAL_E2E_WRITE_AUDIT_CONFIGURATION", "RETRIEVAL_E2E_FAULT_CONFIGURATION",
                 "FEISHU_APP_ID", "FEISHU_APP_SECRET"):
        env.pop(name, None)
    if authorization_file is not None:
        env["PERSONAL_AGENT_BASH_EXECUTION_CONFIG"] = str(authorization_file)
    write_feature_flags(directory / "feature_flags.toml", settings.feature_flags)
    return env


def baseline(materials: Path, directory: Path, *, purpose: Literal["baseline", "target"] = "baseline",
             user_turns: int = 2, bash_image_id: str | None = None,
             docker_endpoint: str | None = None, recovery_checkpoint: Path | None = None,
             task_token_limit: int | None = None, stop_after_checkpoint: bool = False,
             retain_task_workspace: bool = False) -> LongDSCapture:
    prepared = verify_preparation(materials)
    total_turns = len(prepared.turns)
    if not 2 <= user_turns <= total_turns or (purpose == "baseline" and user_turns != 2):
        raise ValueError("baseline固定两轮；target须显式选择2至原题总轮数的连续前缀")
    if (bash_image_id is None) != (docker_endpoint is None):
        raise ValueError("分析镜像和Docker端点须同时显式提供")
    if retain_task_workspace and (bash_image_id is None or stop_after_checkpoint):
        raise ValueError("任务工作区须绑定独立 Bash 镜像并连续执行")
    if user_turns > 2 and bash_image_id is None and recovery_checkpoint is None:
        raise ValueError("L2须使用已固定的通用分析环境")
    if task_token_limit is not None and (type(task_token_limit) is not int or task_token_limit <= 0):
        raise ValueError("任务停止阈值必须为显式正整数")
    if purpose == "baseline" and task_token_limit not in (None, 20_000_000):
        raise ValueError("L1固定20M任务额度")
    if (purpose == "target" and task_token_limit not in (None, 20_000_000)
            and bash_image_id is None and recovery_checkpoint is None):
        raise ValueError("显式任务额度须绑定Bash 执行授权，不能只在用户轮次之间计量")
    if stop_after_checkpoint and (purpose != "target" or user_turns != total_turns or recovery_checkpoint is not None):
        raise ValueError("仅完整任务的原始运行可在第17轮真实完成后退出")
    effective_task_limit = task_token_limit if task_token_limit is not None else 20_000_000
    recovery = None
    if recovery_checkpoint is not None:
        if purpose != "target" or user_turns != total_turns or bash_image_id is not None:
            raise ValueError("恢复必须为完整target，且继承原许可而非提供新镜像")
        verify_seal(recovery_checkpoint)
        original_authorization = BashExecutionDeploymentConfig.model_validate_json(
            (recovery_checkpoint / "bash-deployment.json").read_bytes()).authorization
        if task_token_limit is not None and task_token_limit != original_authorization.max_total_tokens:
            raise ValueError("恢复不能更换原任务额度")
        effective_task_limit = original_authorization.max_total_tokens
        recovery = LongDSRecoveryInput.model_validate_json((recovery_checkpoint / "recovery-input.json").read_bytes())
        if recovery.preparation_sha256 != sha256((materials / "preparation.json").read_bytes()).hexdigest():
            raise ValueError("恢复检查点与本次原题准备身份不同")
    settings = Settings.from_env()
    settings = settings.model_copy(update={
        "feature_flags": benchmark_feature_flags(settings.feature_flags),
        "answer_result": LONGDS_ANSWER_RESULT,
    })
    if recovery is not None and recovery.configuration_sha256 != sha256(json_bytes(_configuration(settings))).hexdigest():
        raise ValueError("恢复必须保持原模型、容量、预算和调用配置")
    for model in (settings.structured, settings.openai):
        if not model.api_key or model.capacity is None:
            raise ValueError("基线需要显式真实模型及容量配置")
        if model.model != model.capacity.model or urlsplit(model.base_url or "").hostname != model.capacity.provider_host:
            raise ValueError("模型身份与容量配置不符")
    if settings.interaction_loop.max_total_tokens != 10_000_000 or settings.interaction_loop.max_model_turns != 40:
        raise ValueError("本轮基线每 run 预算须为已预声明的 10M／40 次决策")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    _source_identity(directory)
    if recovery is not None:
        if recovery.source_digest != json.loads((directory / "repository.json").read_bytes())["source_digest"]:
            raise ValueError("恢复必须使用原完整任务的相同代码版本")
        shutil.copytree(recovery_checkpoint / "server-data", directory / "server-data")
        shutil.copyfile(recovery_checkpoint / "bash-deployment.json", directory / "bash-deployment.json")
    _write(directory / "outcome-contract.json", {
        **asdict(LONGDS_OUTCOME),
        "evidence_class": UNVERIFIED_FLOW, "release_eligible": False,
        "answer_result": settings.answer_result.model_dump(mode="json"),
        "feature_flags": settings.feature_flags.model_dump(mode="json"),
        "planned_user_turns": user_turns, "semantic_score": "separate_official_judge",
    })
    _write(directory / "configuration.json", _configuration(settings))
    session_id = recovery.session_id if recovery is not None else "longds-" + uuid4().hex
    _write(directory / "input-identity.json", {
        "session_id": session_id,
        "preparation_sha256": sha256((materials / "preparation.json").read_bytes()).hexdigest(),
        "checksums_sha256": sha256((materials / "checksums.json").read_bytes()).hexdigest(),
        "case_total_token_limit": effective_task_limit, "per_user_turn_timeout_seconds": 3600,
        "stop_after_checkpoint": stop_after_checkpoint,
        "recovery_checksums_sha256": (sha256((recovery_checkpoint / "checksums.json").read_bytes()).hexdigest()
                                      if recovery_checkpoint is not None else None),
    })
    principal = (recovery.principal if recovery is not None else
                 AuthenticatedPrincipal(tenant_id="longds-" + uuid4().hex, user_id="analyst"))
    authorization_file = directory / "bash-deployment.json" if recovery is not None else None
    if recovery is not None:
        deployment = BashExecutionDeploymentConfig.model_validate_json(authorization_file.read_bytes())
        if (deployment.authorization.authorized_principal != principal
                or deployment.authorization.conversation_id != session_id
                or datetime.now(UTC) >= deployment.authorization.expires_at):
            raise ValueError("原恢复授权不匹配或已经到期，不能重置许可")
    if bash_image_id is not None:
        authorization = BashExecutionAuthorization(
            authorized_principal=principal, conversation_id=session_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=user_turns * 3600),
            max_total_tokens=effective_task_limit, max_execution_seconds=user_turns * 3600,
            image_id=bash_image_id,
            retain_task_workspace=True if retain_task_workspace else None,
        )
        deployment = BashExecutionDeploymentConfig(authorization=authorization, endpoint=docker_endpoint)
        authorization_file = directory / "bash-deployment.json"
        authorization_file.write_text(deployment.model_dump_json(indent=2), encoding="utf-8")
    api_key = secrets.token_urlsafe(32)
    env = _environment(settings, directory, principal=principal, api_key=api_key,
                       authorization_file=authorization_file)
    requested = answered = 0
    stop_reason = "not_started"
    failure = None
    process = None
    started = monotonic()
    try:
        with product(directory, env, sdk_directory=directory / "sdk", log_name="server.log") as (base, process):
            if not wait_for_product(base, process, 45):
                raise RuntimeError("正式 Web 进程启动失败")
            with httpx.Client(base_url=base,
                              headers={"Authorization": "Bearer " + api_key}, timeout=30) as client:
                schema = client.get("/openapi.json")
                schema.raise_for_status()
                (directory / "openapi.json").write_bytes(schema.content)
                data = materials / "data"
                references = recovery.input_artifact_refs if recovery is not None else upload_attachments(
                    base, local_attachments((data / item.filename for item in prepared.inputs), directory=data),
                    manifest=directory / "fixture-uploads.json", api_key=api_key,
                )
                _write(directory / "initial-attachments.json", [ref.model_dump(mode="json") for ref in references])
                first = recovery.next_user_turn if recovery is not None else 1
                preceding_known_tokens = recovery.known_tokens if recovery is not None else 0
                sdk_directory = directory / "sdk"
                usage = read_generation_usage(sdk_directory)
                for turn in prepared.turns[first - 1:user_turns]:
                    if usage.reaches_case_limit(effective_task_limit, preceding_known_tokens=preceding_known_tokens):
                        stop_reason = "case_budget_exhausted"
                        break
                    request = ConversationTurnRequest(
                        session_id=session_id, client_request_id=uuid4().hex,
                        text=turn.user_message(language=prepared.language), create_session=turn.turn_id == 1,
                        interaction_mode="auto", input_artifact_refs=references)
                    prefix = directory / f"turn-{turn.turn_id:02}"
                    _write(prefix.with_suffix(".request.json"), request.model_dump(mode="json"))
                    requested += 1
                    response = submit_turn(base, request, timeout=3600, api_key=api_key)
                    prefix.with_suffix(".response.json").write_bytes(response.content)
                    _write(prefix.with_suffix(".http.json"), {"status_code": response.status_code})
                    response.raise_for_status()
                    result = (PendingConversationTurn if response.status_code == 202 else
                              ConversationTurnResponse).model_validate_json(response.content)
                    trace = client.get(turn_path(result.turn_id))
                    prefix.with_suffix(".trace.json").write_bytes(trace.content)
                    trace.raise_for_status()
                    trace_identity = trace.json()
                    if (result.session_id != session_id or trace_identity["session_id"] != session_id
                            or trace_identity["turn_id"] != result.turn_id):
                        raise ValueError("正式响应和查询返回的会话或轮次身份不匹配")
                    usage = read_generation_usage(sdk_directory)
                    _write(prefix.with_suffix(".generation-usage.json"), usage.model_dump(mode="json"))
                    if isinstance(result, PendingConversationTurn):
                        stop_reason = "turn_pending"
                        break
                    if result.disposition != "answer":
                        stop_reason = "terminal_" + result.disposition
                        break
                    answered += 1
                    stop_reason = "planned_turns_finished"
                    if turn.turn_id == 17 and recovery is None:
                        _checkpoint(directory, result=result, references=references, materials=materials, usage=usage)
                        if stop_after_checkpoint:
                            stop_reason = "checkpoint_17_completed"
                            break
    except Exception as error:
        failure = type(error).__name__
        stop_reason = "entry_or_environment_failure"
        _write(directory / "failure.json", {"exception_type": failure, "requested_turns": requested,
                                            "potential_inflight_usage": isinstance(error, httpx.TimeoutException)})
    usage = read_generation_usage(directory / "sdk")
    result = LongDSCapture(
        evidence_class=UNVERIFIED_FLOW,
        answer_result=settings.answer_result,
        purpose=purpose, planned_user_turns=user_turns - (17 if recovery is not None else 0),
        preceding_source_turns=17 if recovery is not None else 0,
        requested_turns=requested, answered_turns=answered, unexecuted_turns=total_turns - requested - (17 if recovery is not None else 0),
        stop_reason=stop_reason, exception_type=failure, **usage.model_dump(mode="python"),
        actual_process_stopped=process is not None and process.stopped,
        wall_seconds=monotonic() - started)
    _write(directory / "report.json", result.model_dump(mode="json"))
    seal(directory)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--source-directory", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("baseline")
    run.add_argument("--materials", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--purpose", choices=("baseline", "target"), default="baseline")
    run.add_argument("--user-turns", type=int, choices=range(2, 51), default=2)
    run.add_argument("--bash-image-id")
    run.add_argument("--docker-endpoint")
    run.add_argument("--recovery-checkpoint", type=Path)
    run.add_argument("--task-token-limit", type=int)
    run.add_argument("--stop-after-checkpoint", action="store_true")
    run.add_argument("--task-workspace", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.output, source_directory=args.source_directory)
        print(json.dumps({"turns": len(result.turns), "files": len(result.inputs),
                          "bytes": sum(x.bytes for x in result.inputs), "model_calls": 0}))
    else:
        result = baseline(args.materials, args.output, purpose=args.purpose,
                          user_turns=args.user_turns, bash_image_id=args.bash_image_id,
                          docker_endpoint=args.docker_endpoint, recovery_checkpoint=args.recovery_checkpoint,
                          task_token_limit=args.task_token_limit, stop_after_checkpoint=args.stop_after_checkpoint,
                          retain_task_workspace=args.task_workspace)
        print(result.model_dump_json())


if __name__ == "__main__":
    main()
