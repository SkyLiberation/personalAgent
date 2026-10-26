"""LongDS 正式 HTTP 基线：只传题、上传原件、记录实际回答。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
from time import monotonic, sleep
from typing import Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.adapters.web.routes.artifacts import ArtifactResourceView
from personal_agent.adapters.web.routes.conversation import (
    ConversationTurnRequest,
    ConversationTurnResponse,
)
from personal_agent.application.conversation import ConversationMessage
from personal_agent.application.conversation.journal import FileInteractionJournal
from personal_agent.application.python_execution.models import PythonExecutionAuthorization
from personal_agent.infra.python_execution.deployment import PythonExecutionDeploymentConfig
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.kernel.contracts.resource import ResourceRef

from evals.e2e_quality.evidence_catalog import LONGDS_OUTCOME
from .longds_materials import json_bytes, prepare, seal, verify_preparation, verify_seal
from .retrieval_capture_process import ActualWebProcess
from .run_retrieval_acceptance import configuration
from .retrieval_capture_audit import _wire_groups


ROOT = Path(__file__).resolve().parents[2]


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
    actual_process_stopped: bool
    wall_seconds: float = Field(ge=0)
    semantic_score: Literal["not_scored"] = "not_scored"


class LongDSRecoveryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    next_user_turn: Literal[18] = 18
    principal: AuthenticatedPrincipal
    conversation_id: str
    messages: tuple[ConversationMessage, ...]
    input_artifact_refs: tuple[ResourceRef, ...]
    preparation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    known_tokens: int = Field(ge=0)


def _checkpoint(directory: Path, *, run_ref: str, messages: list[ConversationMessage],
                references: tuple[ResourceRef, ...], materials: Path) -> None:
    deployment = PythonExecutionDeploymentConfig.model_validate_json((directory / "python-deployment.json").read_bytes())
    authorization = deployment.authorization
    journal = FileInteractionJournal(directory / "server-data/interaction_runs")
    trace = journal.get(run_ref)
    if (trace is None or trace.final_message is None or trace.final_message.disposition != "answer"
            or trace.python_authorization_digest != authorization.authorization_digest
            or trace.principal != authorization.authorized_principal
            or trace.conversation_id != authorization.conversation_id
            or len(messages) != 34 or tuple(messages[:-1]) != trace.messages
            or messages[-1].role != "assistant" or messages[-1].content != trace.final_message.message
            or journal.execution_budget(trace).unsettled_action_ids):
        raise ValueError("第17轮尚无完整Final或仍存在未决工具执行，不能建立恢复检查点")
    _, used, _ = _usage(directory / "sdk")
    snapshot = directory / "checkpoint-17"
    snapshot.mkdir(exist_ok=False)
    shutil.copytree(directory / "server-data", snapshot / "server-data")
    shutil.copyfile(directory / "python-deployment.json", snapshot / "python-deployment.json")
    shutil.copyfile(directory / "configuration.json", snapshot / "configuration.json")
    recovery = LongDSRecoveryInput(principal=trace.principal, conversation_id=trace.conversation_id,
        messages=tuple(messages), input_artifact_refs=references,
        preparation_sha256=sha256((materials / "preparation.json").read_bytes()).hexdigest(),
        source_digest=json.loads((directory / "repository.json").read_bytes())["source_digest"],
        configuration_sha256=sha256((directory / "configuration.json").read_bytes()).hexdigest(), known_tokens=used)
    _write(snapshot / "recovery-input.json", recovery.model_dump(mode="json"))
    seal(snapshot)


def _write(path: Path, value: object) -> None:
    path.write_bytes(json_bytes(value))


def _configuration(settings: Settings) -> dict[str, object]:
    return {**configuration(settings), "answer_result": settings.answer_result.model_dump(mode="json")}


def _usage(sdk: Path) -> tuple[int, int, int]:
    groups, _ = _wire_groups(sdk)
    return (
        sum(len(g.http_ids) for g in groups),
        sum(g.known_tokens for g in groups),
        sum(g.unknown_usage_attempts for g in groups),
    )


def _source_paths() -> list[Path]:
    return [*ROOT.joinpath("src").rglob("*.py"),
            *ROOT.joinpath("evals/product_baselines").glob("*.py"),
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
                 api_key: str, port: int, authorization_file: Path | None) -> dict[str, str]:
    parsed = urlsplit(settings.postgres_url or "")
    if not parsed.username or not parsed.password:
        raise ValueError("缺少既有本机评测数据库凭据")
    auth = parsed.netloc.rsplit("@", 1)[0]
    database = urlunsplit((parsed.scheme, auth + "@127.0.0.1:16432", "/personal_agent_test", parsed.query, ""))
    env = os.environ.copy()
    env.update({
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONPATH": os.pathsep.join((str(ROOT), str(ROOT / "src"))),
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
        "RETRIEVAL_E2E_SDK_DIRECTORY": str(directory / "sdk"),
        "RETRIEVAL_E2E_HTTP_PORT": str(port),
        "RETRIEVAL_E2E_PROCESS_FILE": str(directory / "server-process.json"),
        "PERSONAL_AGENT_ANSWER_RESULT": settings.answer_result.model_dump_json(),
    })
    for name in ("PERSONAL_AGENT_RETRIEVAL_EXPERIMENT_CONFIG", "PERSONAL_AGENT_PYTHON_EXECUTION_CONFIG", "PERSONAL_AGENT_ADMIN_API_KEYS",
                 "RETRIEVAL_E2E_WRITE_AUDIT_CONFIGURATION", "RETRIEVAL_E2E_FAULT_CONFIGURATION",
                 "FEISHU_APP_ID", "FEISHU_APP_SECRET"):
        env.pop(name, None)
    if authorization_file is not None:
        env["PERSONAL_AGENT_PYTHON_EXECUTION_CONFIG"] = str(authorization_file)
    return env


def baseline(materials: Path, directory: Path, *, purpose: Literal["baseline", "target"] = "baseline",
             user_turns: int = 2, python_image_id: str | None = None,
             docker_endpoint: str | None = None, recovery_checkpoint: Path | None = None,
             task_token_limit: int | None = None, stop_after_checkpoint: bool = False) -> LongDSCapture:
    prepared = verify_preparation(materials)
    total_turns = len(prepared.turns)
    if user_turns not in {2, total_turns} or (purpose == "baseline" and user_turns != 2):
        raise ValueError("L1固定最多两轮，完整target须使用原题全部轮数")
    if (python_image_id is None) != (docker_endpoint is None):
        raise ValueError("分析镜像和Docker端点须同时显式提供")
    if user_turns > 2 and python_image_id is None and recovery_checkpoint is None:
        raise ValueError("L2须使用已固定的通用分析环境")
    if task_token_limit is not None and (type(task_token_limit) is not int or task_token_limit <= 0):
        raise ValueError("任务停止阈值必须为显式正整数")
    if user_turns == 2 and task_token_limit not in (None, 20_000_000):
        raise ValueError("L1固定20M任务额度")
    if stop_after_checkpoint and (purpose != "target" or user_turns != total_turns or recovery_checkpoint is not None):
        raise ValueError("仅完整任务的原始运行可在第17轮真实完成后退出")
    effective_task_limit = task_token_limit if task_token_limit is not None else 20_000_000
    recovery = None
    if recovery_checkpoint is not None:
        if purpose != "target" or user_turns != total_turns or python_image_id is not None:
            raise ValueError("恢复必须为完整target，且继承原许可而非提供新镜像")
        verify_seal(recovery_checkpoint)
        original_authorization = PythonExecutionDeploymentConfig.model_validate_json(
            (recovery_checkpoint / "python-deployment.json").read_bytes()).authorization
        if task_token_limit is not None and task_token_limit != original_authorization.max_total_tokens:
            raise ValueError("恢复不能更换原任务额度")
        effective_task_limit = original_authorization.max_total_tokens
        recovery = LongDSRecoveryInput.model_validate_json((recovery_checkpoint / "recovery-input.json").read_bytes())
        if recovery.preparation_sha256 != sha256((materials / "preparation.json").read_bytes()).hexdigest():
            raise ValueError("恢复检查点与本次原题准备身份不同")
    settings = Settings.from_env()
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
        shutil.copyfile(recovery_checkpoint / "python-deployment.json", directory / "python-deployment.json")
    unverified = settings.answer_result.verification == "none"
    _write(directory / "outcome-contract.json", (
        {"evidence_class": "unverified_flow_capture", "release_eligible": False,
         "answer_result": settings.answer_result.model_dump(mode="json"),
         "planned_user_turns": user_turns, "semantic_score": "separate_official_judge"}
        if unverified else asdict(LONGDS_OUTCOME)
    ))
    _write(directory / "configuration.json", _configuration(settings))
    _write(directory / "input-identity.json", {
        "preparation_sha256": sha256((materials / "preparation.json").read_bytes()).hexdigest(),
        "checksums_sha256": sha256((materials / "checksums.json").read_bytes()).hexdigest(),
        "case_total_token_limit": effective_task_limit, "per_user_turn_timeout_seconds": 3600,
        "stop_after_checkpoint": stop_after_checkpoint,
        "recovery_checksums_sha256": (sha256((recovery_checkpoint / "checksums.json").read_bytes()).hexdigest()
                                      if recovery_checkpoint is not None else None),
    })
    principal = (recovery.principal if recovery is not None else
                 AuthenticatedPrincipal(tenant_id="longds-" + uuid4().hex, user_id="analyst"))
    conversation_id = recovery.conversation_id if recovery is not None else "longds-" + uuid4().hex
    authorization_file = directory / "python-deployment.json" if recovery is not None else None
    if recovery is not None:
        deployment = PythonExecutionDeploymentConfig.model_validate_json(authorization_file.read_bytes())
        if (deployment.authorization.authorized_principal != principal
                or deployment.authorization.conversation_id != conversation_id
                or datetime.now(UTC) >= deployment.authorization.expires_at):
            raise ValueError("原恢复授权不匹配或已经到期，不能重置许可")
    if python_image_id is not None:
        authorization = PythonExecutionAuthorization(
            authorized_principal=principal, conversation_id=conversation_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=user_turns * 3600),
            max_total_tokens=effective_task_limit, max_execution_seconds=user_turns * 3600,
            image_id=python_image_id,
        )
        deployment = PythonExecutionDeploymentConfig(authorization=authorization, endpoint=docker_endpoint)
        authorization_file = directory / "python-deployment.json"
        authorization_file.write_text(deployment.model_dump_json(indent=2), encoding="utf-8")
    api_key = secrets.token_urlsafe(32)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = _environment(settings, directory, principal=principal, api_key=api_key, port=port,
                       authorization_file=authorization_file)
    requested = answered = 0
    stop_reason = "not_started"
    failure = None
    actual = None
    process = None
    process_stopped = False
    started = monotonic()
    try:
        with (directory / "server.log").open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, "-B", "-m", "evals.product_baselines.retrieval_acceptance_server"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            with httpx.Client(base_url=f"http://127.0.0.1:{port}",
                              headers={"Authorization": "Bearer " + api_key}, timeout=30) as client:
                deadline = monotonic() + 45
                while monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("正式 Web 进程启动失败")
                    try:
                        if client.get("/api/health", timeout=1).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    sleep(0.1)
                else:
                    raise TimeoutError("正式 Web 健康检查超时")
                actual = ActualWebProcess(process, directory / "server-process.json")
                schema = client.get("/openapi.json")
                schema.raise_for_status()
                (directory / "openapi.json").write_bytes(schema.content)
                references = list(recovery.input_artifact_refs) if recovery is not None else []
                for item in (() if recovery is not None else prepared.inputs):
                    content = (materials / "data" / item.filename).read_bytes()
                    response = client.post("/api/artifacts/upload", files={
                        "file": (item.filename, content, mimetypes.guess_type(item.filename)[0] or "application/octet-stream")}, timeout=3600)
                    response.raise_for_status()
                    view = ArtifactResourceView.model_validate_json(response.content)
                    references.append(view.resource.resource_ref)
                _write(directory / "initial-attachments.json", [ref.model_dump(mode="json") for ref in references])
                messages = list(recovery.messages) if recovery is not None else []
                first = recovery.next_user_turn if recovery is not None else 1
                for turn in prepared.turns[first - 1:user_turns]:
                    _, used, _ = _usage(directory / "sdk")
                    if used + (recovery.known_tokens if recovery is not None else 0) >= effective_task_limit:
                        stop_reason = "case_budget_exhausted"
                        break
                    messages.append(ConversationMessage(role="user", content=turn.user_message(language=prepared.language)))
                    request = ConversationTurnRequest(
                        conversation_id=conversation_id, interaction_run_ref="irun_" + uuid4().hex,
                        messages=list(messages), interaction_mode="auto", input_artifact_refs=tuple(references))
                    prefix = directory / f"turn-{turn.turn_id:02}"
                    _write(prefix.with_suffix(".request.json"), request.model_dump(mode="json"))
                    requested += 1
                    response = client.post("/api/conversation/turn", json=request.model_dump(mode="json"), timeout=3600)
                    prefix.with_suffix(".response.json").write_bytes(response.content)
                    _write(prefix.with_suffix(".http.json"), {"status_code": response.status_code})
                    trace = client.get(f"/api/conversation/runs/{request.interaction_run_ref}")
                    prefix.with_suffix(".trace.json").write_bytes(trace.content)
                    response.raise_for_status()
                    result = ConversationTurnResponse.model_validate_json(response.content)
                    if result.disposition != "answer":
                        stop_reason = "terminal_" + result.disposition
                        break
                    answered += 1
                    messages.append(result.message)
                    stop_reason = "planned_turns_finished"
                    if turn.turn_id == 17 and recovery is None:
                        _checkpoint(directory, run_ref=request.interaction_run_ref, messages=messages,
                                    references=tuple(references), materials=materials)
                        if stop_after_checkpoint:
                            stop_reason = "checkpoint_17_completed"
                            break
    except Exception as error:
        failure = type(error).__name__
        stop_reason = "entry_or_environment_failure"
        _write(directory / "failure.json", {"exception_type": failure, "requested_turns": requested,
                                            "potential_inflight_usage": isinstance(error, httpx.TimeoutException)})
    finally:
        if actual is not None:
            try:
                actual.stop(deadline=monotonic() + 20)
                process_stopped = actual.poll() is not None
            finally:
                actual.close()
        elif process is not None:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)
            process_stopped = process.poll() is not None
    physical, used, unknown = _usage(directory / "sdk")
    result = LongDSCapture(
        evidence_class="unverified_flow_capture" if unverified else "unscored_product_capture",
        answer_result=settings.answer_result,
        purpose=purpose, planned_user_turns=user_turns - (17 if recovery is not None else 0),
        preceding_source_turns=17 if recovery is not None else 0,
        requested_turns=requested, answered_turns=answered, unexecuted_turns=total_turns - requested - (17 if recovery is not None else 0),
        stop_reason=stop_reason, exception_type=failure, physical_model_requests=physical,
        known_tokens=used, unknown_usage_attempts=unknown, actual_process_stopped=process_stopped,
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
    run.add_argument("--python-image-id")
    run.add_argument("--docker-endpoint")
    run.add_argument("--recovery-checkpoint", type=Path)
    run.add_argument("--task-token-limit", type=int)
    run.add_argument("--stop-after-checkpoint", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.output, source_directory=args.source_directory)
        print(json.dumps({"turns": len(result.turns), "files": len(result.inputs),
                          "bytes": sum(x.bytes for x in result.inputs), "model_calls": 0}))
    else:
        result = baseline(args.materials, args.output, purpose=args.purpose,
                          user_turns=args.user_turns, python_image_id=args.python_image_id,
                          docker_endpoint=args.docker_endpoint, recovery_checkpoint=args.recovery_checkpoint,
                          task_token_limit=args.task_token_limit, stop_after_checkpoint=args.stop_after_checkpoint)
        print(result.model_dump_json())


if __name__ == "__main__":
    main()
