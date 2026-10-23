"""正式研究验收的独立准备与采集入口；采集不替代评分资格。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from queue import Empty, Queue
import secrets
import socket
import subprocess
import sys
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.adapters.web.routes.conversation import (
    ConversationTurnRequest,
    ConversationTurnResponse,
)
from personal_agent.application.conversation.models import InteractionTrace
from personal_agent.application.retrieval_experiment.models import ExperimentLimits
from personal_agent.infra.retrieval_experiment.deployment import load_retrieval_deployment
from personal_agent.kernel.config import Settings
from personal_agent.kernel.config_models import ModelCapacityConfig

from .retrieval_baseline import OWNER, ROOT, SCENARIOS
from .retrieval_capture_process import ActualWebProcess
from .retrieval_http_server import redact_payload
from .retrieval_live_world import LiveRetrievalWorld, prepare_live_world
from .retrieval_qualification import QualificationAdmission
from .retrieval_qualification_review import Digest


class Preparation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    case: Literal["e1", "p1"]
    fault: Literal["start_response_interrupt"] | None = None
    prepared_at: datetime
    world: LiveRetrievalWorld
    request: ConversationTurnRequest
    configuration_digest: str
    source_digest: str
    model_calls: Literal[0] = 0
    database_writes: Literal[0] = 0


class EntryObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    method: Literal["GET", "POST"]
    path: str
    status_code: int | None = None
    exception_type: str | None = None
    body: object | None = None
    wall_seconds: float


class HistoricalCaptureLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    pid: int | None
    exitcode: int | None
    actual_process_stopped: bool
    hard_deadline_reached: bool
    wall_seconds: float = Field(ge=0, allow_inf_nan=False)


class CaptureLifecycle(HistoricalCaptureLifecycle):
    actual_pid: int | None
    actual_exitcode: int | None
    run_deadline_at: datetime | None
    supervision_errors: tuple[str, ...]


class ProcessTermination(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    actual_pid: int
    actual_exitcode: int | None
    errors: tuple[str, ...]


class SourceDrift(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    prepared_sha256: Digest
    current_sha256: Digest | None


CapturePhase = Literal["qualification_preparation", "target", "fault_boundary", "initial_closure"]


class CapturedRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case: Literal["e1", "p1"]
    phase: CapturePhase
    fault: Literal["start_response_interrupt"] | None
    product_result: Literal["not_scored"]
    target_grader_qualified: bool
    qualification_admission: QualificationAdmission | None
    limitation: str
    preparation_sha256: Digest
    configuration_digest: Digest
    source_digest: Digest
    source_changed_during_capture: dict[str, SourceDrift]


class KnowledgeSnapshotFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    boundary: Literal["before", "after"]
    exception_type: str


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return sha256(_json_bytes(value)).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_json_bytes(value))


def _settings() -> Settings:
    settings = Settings.from_env()
    # Keep the original verified default when neither path supplies a profile.
    # Explicit profiles are owned by Settings and bound to each actual path.
    if settings.structured.capacity is None and settings.openai.capacity is None:
        capacity = ModelCapacityConfig(
            provider_host="token-plan-cn.xiaomimimo.com", model="mimo-v2.6-flash",
            context_window_tokens=1_048_576, max_output_tokens=131_072,
            protocol_reserve_tokens=8_192,
        )
        settings = settings.model_copy(update={
            "structured": settings.structured.model_copy(update={"capacity": capacity}),
            "openai": settings.openai.model_copy(update={"capacity": capacity}),
        })
    for model in (settings.structured, settings.openai):
        capacity = model.capacity
        if capacity is None:
            raise ValueError("显式容量配置必须同时绑定两条实际模型路径")
        if model.model != capacity.model or urlsplit(model.base_url or "").hostname != capacity.provider_host:
            raise ValueError("容量身份与实际模型或 Provider 不符，不能跨 profile 推断")
    if not settings.structured.api_key or not settings.structured.base_url:
        raise ValueError("需要 configured 的真实模型；准备不发出调用")
    return settings


def configuration(settings: Settings) -> dict[str, object]:
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
    return result


def _source_identity(directory: Path) -> str:
    paths = sorted({
        *ROOT.joinpath("src").rglob("*.py"),
        *ROOT.joinpath("evals/product_baselines").glob("retrieval*.py"),
        *ROOT.joinpath("evals/product_baselines").glob("run_retrieval_*.py"),
        ROOT / "evals/e2e_quality/research_answer_outcome.py",
        Path(__file__),
        ROOT / "pyproject.toml",
    })
    hashes = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest() for path in paths}
    _write_json(directory / "source-hashes.json", hashes)
    with ZipFile(directory / "source-snapshot.zip", "w", compression=ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(ROOT).as_posix())
    (directory / "repository.patch").write_bytes(subprocess.check_output(
        ("git", "diff", "--binary", "HEAD"), cwd=ROOT,
    ))
    _write_json(directory / "repository.json", {
        "head": subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=ROOT, text=True).strip(),
        "branch": subprocess.check_output(("git", "branch", "--show-current"), cwd=ROOT, text=True).strip(),
        "source_digest": _digest(hashes),
    })
    return _digest(hashes)


def _verify_images(image_ids: tuple[str, ...]) -> None:
    for expected in image_ids:
        output = subprocess.check_output(("docker", "image", "inspect", expected, "--format", "{{.Id}}"), cwd=ROOT, text=True).strip()
        if output != expected:
            raise ValueError("部署镜像内容 ID 与本机 Docker 实际身份不同")


def prepare(args: argparse.Namespace) -> None:
    settings = _settings()
    limits = ExperimentLimits(
        run_timeout_seconds=args.run_timeout_seconds,
        max_execution_seconds=args.max_execution_seconds,
    )
    if args.fault is not None and args.case != "e1":
        raise ValueError("F2 故障准备只能复用原 E1 委托")
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scenario = next(item for item in SCENARIOS if item.key == args.case)
    _verify_images((args.worker_image_id, args.candidate_image_id))
    config = configuration(settings)
    _write_json(output / "configuration.json", config)
    source_digest = _source_identity(output)
    world = prepare_live_world(
        settings.model_copy(update={"data_dir": output / "server-data"}), scenario,
        limits=limits,
        directory=output / "world",
        worker_image_id=args.worker_image_id, candidate_image_id=args.candidate_image_id,
        endpoint=args.endpoint, network=args.network, es_endpoint=args.es_endpoint,
    )
    body = ConversationTurnRequest.model_validate({
        "user_id": OWNER.user_id,
        "conversation_id": world.initial.conversation_id,
        "interaction_run_ref": world.initial.interaction_run_ref,
        "interaction_mode": "auto",
        "messages": [{"role": "user", "content": world.initial.user_input}],
        "input_artifact_refs": [ref.model_dump(mode="json") for ref in world.input_artifact_refs],
    })
    deployment, _ = load_retrieval_deployment(world.deployment_path)
    private = next(item.resource_ref for item in deployment.materials if item.role == "test_qrels")
    if len(body.input_artifact_refs) != 4 or private in body.input_artifact_refs:
        raise ValueError("初始公开材料必须为四份；test 标签不能进入模型可读集合")
    prepared = Preparation(
        case=args.case, fault=args.fault, prepared_at=datetime.now(timezone.utc), world=world, request=body,
        configuration_digest=_digest(config), source_digest=source_digest,
    )
    (output / "preparation.json").write_text(prepared.model_dump_json(indent=2), encoding="utf-8")
    _write_json(output / "checksums.json", {
        str(path.relative_to(output)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*")) if path.is_file()
    })
    print(json.dumps({"preparation": str(output / "preparation.json"), "case": args.case,
                      "model_calls": 0, "database_writes": 0, "http_calls": 0,
                      "public_input_refs": len(body.input_artifact_refs),
                      "deployment_digest": world.deployment_digest}, ensure_ascii=False))


def _database_url(settings: Settings) -> str:
    parsed = urlsplit(settings.postgres_url or "")
    if not parsed.username or not parsed.password:
        raise ValueError("需要既有本机评测数据库凭据")
    # Preserve encoded credentials, never put this URL in the report.
    auth = parsed.netloc.rsplit("@", 1)[0]
    return urlunsplit((parsed.scheme, auth + "@127.0.0.1:16432", "/personal_agent_test", parsed.query, ""))


def _observe_entry(base_url: str, path: str, *, api_key: str, body: object | None = None,
                   timeout: float = 30) -> EntryObservation:
    method = "POST" if body is not None else "GET"
    request = Request(base_url + path, data=_json_bytes(body) if body is not None else None,
                      headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}, method=method)
    started = monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            return EntryObservation(method=method, path=path, status_code=response.status,
                                    body=json.loads(response.read()), wall_seconds=monotonic() - started)
    except HTTPError as error:
        content = error.read()
        try:
            value = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            value = {"body_sha256": sha256(content).hexdigest(), "body_bytes": len(content)}
        return EntryObservation(method=method, path=path, status_code=error.code,
                                exception_type=type(error).__name__, body=value,
                                wall_seconds=monotonic() - started)
    except (URLError, OSError, ValueError) as error:
        return EntryObservation(method=method, path=path, exception_type=type(error).__name__,
                                wall_seconds=monotonic() - started)


def _collect_knowledge_snapshot(preparation: Path, database: str, evidence: Path,
                                boundary: Literal["before", "after"]) -> bool:
    from .retrieval_knowledge_snapshot import capture_snapshot

    try:
        snapshot = capture_snapshot(preparation, database)
    except Exception as error:
        failure = KnowledgeSnapshotFailure(boundary=boundary, exception_type=type(error).__name__)
        _write_json(evidence / f"knowledge-{boundary}-error.json", failure.model_dump(mode="json"))
        return False
    _write_json(evidence / f"knowledge-{boundary}.json", snapshot.model_dump(mode="json"))
    return True


def run(args: argparse.Namespace) -> None:
    """Explicit live command; root authorizes the frozen code and sample quota first."""
    if args.phase == "target" and (args.qualification is None or args.qualification_review is None):
        raise ValueError("target 必须先提供真实完整评分资格归档 --qualification 及独立 --qualification-review")
    if args.phase != "target" and (args.qualification is not None or args.qualification_review is not None):
        raise ValueError("仅 target 消费评分资格归档")
    observe_knowledge = args.phase in {"target", "initial_closure"}
    settings = _settings()
    admission = None
    if args.phase == "target":
        from .retrieval_qualification import verify_qualification
        admission = verify_qualification(args.qualification, settings, accuracy_review=args.qualification_review)
    prepared_path = args.preparation.resolve()
    prepared = Preparation.model_validate_json(prepared_path.read_bytes())
    if (prepared.fault is not None) != (args.phase == "fault_boundary"):
        raise ValueError("故障准备必须且只能作为 fault_boundary 运行")
    root = prepared_path.parent
    deployment, _ = load_retrieval_deployment(prepared.world.deployment_path)
    if deployment.deployment_digest != prepared.world.deployment_digest:
        raise ValueError("准备后的部署或任务预算已变化")
    run_seconds = deployment.limits.run_timeout_seconds
    if _digest(configuration(settings)) != prepared.configuration_digest:
        raise ValueError("实际 configured 模型或预算与准备身份不同")
    hashes = json.loads((root / "source-hashes.json").read_bytes())
    if any(sha256((ROOT / relative).read_bytes()).hexdigest() != digest for relative, digest in hashes.items()):
        raise ValueError("准备后代码已变化；需新准备身份，不能复用旧 source digest")
    evidence = root / args.phase
    evidence.mkdir(exist_ok=False)
    database = _database_url(settings)
    with socket.create_connection(("127.0.0.1", 16432), timeout=1):
        pass
    # Existing process infrastructure only; no test collection or unit execution.
    os.environ["PERSONAL_AGENT_E2E_POSTGRES_URL"] = database
    from evals.e2e_quality.test_release_user_outcomes import _new_live_web_process

    server = _new_live_web_process(root, settings)
    api_key = secrets.token_urlsafe(32)
    env = server.child_env
    env.update({
        "PERSONAL_AGENT_POSTGRES_URL": database,
        "PERSONAL_AGENT_API_KEYS": json.dumps({api_key: OWNER.model_dump(mode="json")}),
        "PERSONAL_AGENT_RETRIEVAL_EXPERIMENT_CONFIG": str(prepared.world.deployment_path),
        "STRUCTURED_MODEL_CAPACITY": settings.structured.capacity.model_dump_json(),
        "OPENAI_MODEL_CAPACITY": settings.openai.capacity.model_dump_json(),
        "PERSONAL_AGENT_E2E_TRACE_DIR": str(evidence / "e2e"),
        "PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR": str(evidence / "product"),
        "PERSONAL_AGENT_MCP_SERVERS": '{"enabled":false}',
        "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
        "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
        "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED": "false",
        "RETRIEVAL_E2E_SDK_DIRECTORY": str(evidence / "sdk"),
        "RETRIEVAL_E2E_HTTP_PORT": str(server.port),
        "RETRIEVAL_E2E_PROCESS_FILE": str(evidence / "server-process.json"),
    })
    env.pop("RETRIEVAL_E2E_FAULT_CONFIGURATION", None)
    env.pop("RETRIEVAL_E2E_WRITE_AUDIT_CONFIGURATION", None)
    if observe_knowledge:
        from .retrieval_knowledge_write_audit import WriteAuditConfiguration

        write_audit_configuration = WriteAuditConfiguration(
            principal=prepared.world.initial.principal,
            interaction_run_ref=prepared.world.initial.interaction_run_ref,
            preparation_sha256=sha256(prepared_path.read_bytes()).hexdigest(),
            directory=evidence / "knowledge-write-audit")
        write_audit_path = evidence / "knowledge-write-audit-configuration.json"
        _write_json(write_audit_path, write_audit_configuration.model_dump(mode="json"))
        env["RETRIEVAL_E2E_WRITE_AUDIT_CONFIGURATION"] = str(write_audit_path)
    if prepared.fault == "start_response_interrupt":
        from .retrieval_start_response_fault import StartResponseFaultConfiguration

        deployment, environment = load_retrieval_deployment(prepared.world.deployment_path)
        fault_configuration = StartResponseFaultConfiguration(
            principal=prepared.world.initial.principal,
            interaction_run_ref=prepared.world.initial.interaction_run_ref,
            deployment_digest=prepared.world.deployment_digest,
            worker_image_id=deployment.worker_image_id,
            endpoint=environment.endpoint,
            workspace_root=environment.workspace_root,
            output_directory=evidence / "fault-control",
        )
        fault_path = evidence / "fault-configuration.json"
        _write_json(fault_path, fault_configuration.model_dump(mode="json"))
        env["RETRIEVAL_E2E_FAULT_CONFIGURATION"] = str(fault_path)
    stopped = Event()
    expired = Event()
    started = monotonic()
    process = None
    actual_process: ActualWebProcess | None = None
    run_deadline_at: datetime | None = None
    supervision_errors: list[str] = []
    supervisor = None
    cleanup_deadline: float | None = None
    cleanup_lock = Lock()
    terminations: Queue[ProcessTermination] = Queue(maxsize=1)

    def begin_cleanup() -> float:
        nonlocal cleanup_deadline
        with cleanup_lock:
            if cleanup_deadline is None:
                remaining = (run_deadline_at - datetime.now(timezone.utc)).total_seconds() if run_deadline_at else 0
                cleanup_deadline = monotonic() + max(0, min(30, remaining + 30))
            return cleanup_deadline

    def finish_actual_process() -> ProcessTermination:
        errors: list[str] = []
        actual_exitcode = None
        try:
            actual_process.stop(deadline=begin_cleanup())
        except Exception as error:
            errors.append("actual_stop:" + type(error).__name__)
        try:
            actual_exitcode = actual_process.poll()
        except Exception as error:
            errors.append("actual_poll:" + type(error).__name__)
        try:
            actual_process.close()
        except Exception as error:
            errors.append("actual_close:" + type(error).__name__)
        return ProcessTermination(actual_pid=actual_process.identity.pid,
                                  actual_exitcode=actual_exitcode, errors=tuple(errors))
    observations: list[EntryObservation] = []
    validation_errors: list[dict[str, str]] = []
    try:
        if observe_knowledge and not _collect_knowledge_snapshot(prepared_path, database, evidence, "before"):
            raise RuntimeError("target 前置知识快照失败，未启动正式进程；具名错误已保存")
        server.log_handle = server.log_path.open("a", encoding="utf-8")
        server.process = subprocess.Popen(
            (sys.executable, "-B", "-m", "evals.product_baselines.retrieval_acceptance_server"),
            cwd=server.cwd, env=env, stdout=server.log_handle, stderr=subprocess.STDOUT,
        )
        process = server.process

        try:
            deadline = monotonic() + 30
            while monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("正式 Web 进程启动失败")
                health = _observe_entry(server.base_url, "/api/health", api_key=api_key, timeout=1)
                if health.status_code == 200:
                    break
                sleep(0.1)
            else:
                raise RuntimeError("正式 Web 进程健康检查超时")
            actual_process = ActualWebProcess(process, evidence / "server-process.json")
            journal = root / "server-data" / "interaction_runs" / prepared.world.initial.interaction_run_ref
            entry_started = monotonic()

            def enforce_deadline() -> None:
                nonlocal run_deadline_at
                errors: list[str] = []
                try:
                    while not stopped.is_set():
                        snapshots = sorted(journal.glob("*.json"))
                        if snapshots:
                            initial = InteractionTrace.model_validate_json(snapshots[0].read_bytes())
                            if (
                                initial.interaction_run_ref != prepared.world.initial.interaction_run_ref
                                or initial.principal != prepared.world.initial.principal
                                or initial.deployment_digest != deployment.deployment_digest
                                or initial.max_execution_seconds != deployment.limits.max_execution_seconds
                                or initial.run_deadline_at is None
                            ):
                                raise ValueError("首份Journal与准备部署或截止不符")
                            run_deadline_at = initial.run_deadline_at
                            break
                        if monotonic() - entry_started >= 30:
                            raise TimeoutError("正式入口30秒内未建立任务截止")
                        stopped.wait(0.1)
                    if run_deadline_at is not None:
                        remaining = (run_deadline_at - datetime.now(timezone.utc)).total_seconds()
                        if not stopped.wait(max(0, remaining)):
                            expired.set()
                except Exception as error:
                    errors.append("supervision:" + type(error).__name__)
                    expired.set()
                finally:
                    outcome = finish_actual_process()
                    terminations.put(outcome.model_copy(update={"errors": tuple(errors) + outcome.errors}))

            candidate_supervisor = Thread(target=enforce_deadline, daemon=True)
            try:
                candidate_supervisor.start()
            except Exception as error:
                supervision_errors.append("supervision_start:" + type(error).__name__)
                raise
            supervisor = candidate_supervisor
            post = _observe_entry(server.base_url, "/api/conversation/turn", api_key=api_key,
                                  body=prepared.request.model_dump(mode="json"), timeout=run_seconds + 60)
            observations.append(post)
            if post.status_code == 200:
                try:
                    ConversationTurnResponse.model_validate(post.body)
                except ValueError as error:
                    validation_errors.append({"boundary": "turn", "exception_type": type(error).__name__})
            # Fetch even after 409/422/503; the old baseline did not do this.
            trace_path = f"/api/conversation/runs/{prepared.world.initial.interaction_run_ref}?" + urlencode({"user_id": OWNER.user_id})
            trace = _observe_entry(server.base_url, trace_path, api_key=api_key)
            observations.append(trace)
            if trace.status_code == 200:
                try:
                    InteractionTrace.model_validate(trace.body)
                except ValueError as error:
                    validation_errors.append({"boundary": "trace", "exception_type": type(error).__name__})
            _write_json(evidence / "entry-observations.json", [item.model_dump(mode="json") for item in observations])
        finally:
            begin_cleanup()
    finally:
        try:
            if observe_knowledge and process is not None and process.poll() is None:
                remaining = begin_cleanup() - monotonic()
                if remaining > 0:
                    closed = _observe_entry(server.base_url, "/__retrieval_e2e_observer__/close", api_key=api_key,
                                            body={}, timeout=min(5, remaining))
                    _write_json(evidence / "knowledge-write-audit-close-entry.json", closed.model_dump(mode="json"))
        finally:
            stopped.set()
            if supervisor is not None:
                supervisor.join(timeout=max(0, begin_cleanup() - monotonic()))
                try:
                    outcome = None if supervisor.is_alive() else terminations.get_nowait()
                    if outcome is None:
                        supervision_errors.append("supervision_thread_unconfirmed")
                except Empty:
                    outcome = None
                    supervision_errors.append("supervision_thread_unconfirmed")
            else:
                outcome = None
            try:
                if supervisor is None and actual_process is None and process is not None and (evidence / "server-process.json").is_file():
                    actual_process = ActualWebProcess(process, evidence / "server-process.json")
                if supervisor is None and actual_process is not None:
                    outcome = finish_actual_process()
            except Exception as error:
                supervision_errors.append(type(error).__name__)
            finally:
                try:
                    if supervisor is None and process is not None and process.poll() is None:
                        process.kill()
                        process.wait(timeout=max(0, begin_cleanup() - monotonic()))
                except Exception as error:
                    supervision_errors.append(type(error).__name__)
                finally:
                    server.process = None
                    if server.log_handle is not None:
                        try:
                            server.log_handle.close()
                        except Exception as error:
                            supervision_errors.append("log_close:" + type(error).__name__)
                        server.log_handle = None
        actual_exitcode = outcome.actual_exitcode if outcome else None
        if outcome is not None:
            supervision_errors.extend(outcome.errors)
        lifecycle = CaptureLifecycle(
            pid=process.pid if process else None,
            exitcode=process.poll() if process else None,
            actual_pid=outcome.actual_pid if outcome else None,
            actual_exitcode=actual_exitcode, run_deadline_at=run_deadline_at,
            supervision_errors=tuple(supervision_errors),
            actual_process_stopped=actual_exitcode is not None and process is not None and process.poll() is not None,
            hard_deadline_reached=expired.is_set(), wall_seconds=monotonic() - started,
        )
        _write_json(evidence / "lifecycle.json", lifecycle.model_dump(mode="json"))
        if observe_knowledge and lifecycle.actual_process_stopped:
            _collect_knowledge_snapshot(prepared_path, database, evidence, "after")
        _write_json(evidence / "entry-observations.json", [item.model_dump(mode="json") for item in observations])
        _write_json(evidence / "validation-errors.json", validation_errors)
        capture_result = CapturedRun(
            case=prepared.case, phase=args.phase, fault=prepared.fault,
            product_result="not_scored", target_grader_qualified=admission is not None,
            qualification_admission=admission,
            limitation="采集身份；Agent能力须核对实际执行、结果消费、当前提交及适用语义；不要求用户下载或结果打包。",
            preparation_sha256=sha256(prepared_path.read_bytes()).hexdigest(),
            configuration_digest=prepared.configuration_digest, source_digest=prepared.source_digest,
            source_changed_during_capture={
                relative: SourceDrift(
                    prepared_sha256=digest,
                    current_sha256=sha256((ROOT / relative).read_bytes()).hexdigest()
                    if (ROOT / relative).is_file() else None,
                )
                for relative, digest in hashes.items()
                if not (ROOT / relative).is_file()
                or sha256((ROOT / relative).read_bytes()).hexdigest() != digest
            },
        )
        _write_json(evidence / "capture-result.json", capture_result.model_dump(mode="json"))
        _write_json(evidence / "checksums.json", {
            str(path.relative_to(evidence)): sha256(path.read_bytes()).hexdigest()
            for path in sorted(evidence.rglob("*")) if path.is_file()
        })
    print(json.dumps({"capture": str(evidence), "phase": args.phase, "result": "not_scored"}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare", help="零模型真实材料、部署和正式请求预检")
    preparation.add_argument("--case", required=True, choices=("e1", "p1"))
    preparation.add_argument("--fault", choices=("start_response_interrupt",))
    preparation.add_argument("--output-root", required=True, type=Path)
    preparation.add_argument("--worker-image-id", required=True)
    preparation.add_argument("--candidate-image-id", required=True)
    preparation.add_argument("--run-timeout-seconds", required=True, type=float)
    preparation.add_argument("--max-execution-seconds", required=True, type=float)
    preparation.add_argument("--endpoint", default="npipe:////./pipe/dockerDesktopLinuxEngine")
    preparation.add_argument("--network", default="retrieval-experiment-tool")
    preparation.add_argument("--es-endpoint", default="http://retrieval-experiment-es:9200")
    live = commands.add_parser("run", help="真实正式 HTTP 采集；需先冻结代码及批准样本额度")
    live.add_argument("--preparation", required=True, type=Path)
    live.add_argument("--phase", required=True, choices=("qualification_preparation", "target", "fault_boundary", "initial_closure"))
    live.add_argument("--qualification", type=Path, help="target 的真实完整评分资格归档")
    live.add_argument("--qualification-review", type=Path, help="target 的独立逐关系准确性审读原件")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
