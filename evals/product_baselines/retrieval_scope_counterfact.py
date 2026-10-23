"""F1：真实 Runtime HTTP 的初始 Artifact 授权拒绝，预期零模型调用。"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Event, Thread
from time import monotonic, sleep
from typing import Literal
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict

from personal_agent.adapters.web.routes.artifacts import artifact_resource_view
from personal_agent.application.artifacts import ArtifactService
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

from .retrieval_baseline import OWNER, ROOT
from .retrieval_capture_process import ActualWebProcess
from .run_retrieval_acceptance import (
    EntryObservation, Preparation, _database_url, _digest, _observe_entry, _settings, _write_json, configuration,
)


class ScopeCounterfactualReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case: Literal["RETRIEVAL-EXPERIMENT-SCOPE-001"] = "RETRIEVAL-EXPERIMENT-SCOPE-001"
    evidence_class: Literal["boundary_evaluation"] = "boundary_evaluation"
    passed: bool
    observations: tuple[EntryObservation, ...]
    actual_model_http_requests: int
    candidate_model_requests: int
    interaction_snapshots: int
    artifacts_unchanged: bool
    foreign_content_disclosed_to_requester: bool
    actual_process_stopped: bool
    process_id: int | None
    process_exit_code: int | None
    hard_deadline_reached: bool
    wall_seconds: float
    execution_error_type: str | None = None
    limitation: str = "只证明初始材料的正式授权拒绝；不计完整研究交付或全库状态验收。"


def _artifact_hashes(data_dir: Path) -> dict[str, str]:
    return {str(path.relative_to(data_dir)): sha256(path.read_bytes()).hexdigest()
            for name in ("uploads", "generated_artifacts")
            for path in sorted((data_dir / name).rglob("*")) if path.is_file()}


def _get_bytes(base_url: str, path: str, api_key: str) -> tuple[int, bytes]:
    request = Request(urljoin(base_url, path), headers={"Authorization": "Bearer " + api_key})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def run(preparation: Path, output: Path) -> ScopeCounterfactualReport:
    settings = _settings()
    prepared = Preparation.model_validate_json(preparation.read_bytes())
    root = preparation.resolve().parent
    if output.resolve() != root / "scope":
        raise ValueError("F1 输出必须为本次独立准备目录下的 scope")
    if prepared.case != "e1" or prepared.fault is not None or any((root / name).exists() for name in ("qualification_preparation", "target", "fault_boundary", "initial_closure")):
        raise ValueError("F1 只使用独立新 E1 准备，不能修改已执行研究目录")
    if _digest(configuration(settings)) != prepared.configuration_digest:
        raise ValueError("F1 实际模型配置与准备身份不同")
    hashes = json.loads((root / "source-hashes.json").read_bytes())
    if any(sha256((ROOT / name).read_bytes()).hexdigest() != digest for name, digest in hashes.items()):
        raise ValueError("F1 准备后源码变化，需要新准备身份")
    data_dir = root / "server-data"
    if any((data_dir / "interaction_runs").rglob("*.json")):
        raise ValueError("F1 不能复用已执行的 Interaction Journal")
    output.mkdir(parents=True, exist_ok=False)
    settings = settings.model_copy(update={"data_dir": data_dir})
    foreign = AuthenticatedPrincipal(tenant_id=OWNER.tenant_id, user_id="retrieval-scope-other-" + secrets.token_hex(6))
    own_key, foreign_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    api_keys = {own_key: OWNER, foreign_key: foreign}
    settings = settings.model_copy(update={"web": settings.web.model_copy(update={"api_keys": api_keys, "admin_api_keys": {}})})
    content = ("F1 授权反事实专用原件：" + secrets.token_hex(24)).encode("utf-8")
    artifacts = ArtifactService(settings)
    ref = artifacts.save_upload(filename="scope-fixture.txt", content_type="text/plain", file_bytes=content,
                                uploads_dir=data_dir / "uploads", principal=foreign, owner=foreign)
    resource = artifacts.resource_item(ref, principal=foreign, owner=foreign)
    download = artifact_resource_view(resource, principal=foreign, settings=settings).download_url
    before = _artifact_hashes(data_dir)
    _write_json(output / "fixture.json", {"resource": resource.model_dump(mode="json"),
                "content_hex": content.hex(), "preparation_sha256": sha256(preparation.read_bytes()).hexdigest()})
    _write_json(output / "artifacts-before.json", before)
    entry_sources = (Path(__file__), ROOT / "evals/e2e_quality/test_retrieval_scope_boundary.py",
                     ROOT / "evals/e2e_quality/evidence_catalog.py")
    (output / "source").mkdir()
    for path in entry_sources:
        (output / "source" / path.name).write_bytes(path.read_bytes())
    _write_json(output / "entry-sources.json", {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest()
                                              for path in entry_sources})
    from evals.e2e_quality.test_release_user_outcomes import _new_live_web_process

    server = _new_live_web_process(root, settings)
    server.child_env.pop("RETRIEVAL_E2E_FAULT_CONFIGURATION", None)
    server.child_env.pop("RETRIEVAL_E2E_WRITE_AUDIT_CONFIGURATION", None)
    server.child_env.update({
        "PERSONAL_AGENT_POSTGRES_URL": _database_url(settings),
        "PERSONAL_AGENT_API_KEYS": json.dumps({key: principal.model_dump(mode="json") for key, principal in api_keys.items()}),
        "PERSONAL_AGENT_RETRIEVAL_EXPERIMENT_CONFIG": str(prepared.world.deployment_path),
        "STRUCTURED_MODEL_CAPACITY": settings.structured.capacity.model_dump_json(),
        "OPENAI_MODEL_CAPACITY": settings.openai.capacity.model_dump_json(),
        "PERSONAL_AGENT_MCP_SERVERS": '{"enabled":false}',
        "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false", "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
        "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED": "false",
        "PERSONAL_AGENT_E2E_TRACE_DIR": str(output / "e2e"),
        "PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR": str(output / "evidence"),
        "RETRIEVAL_E2E_SDK_DIRECTORY": str(output / "sdk"), "RETRIEVAL_E2E_HTTP_PORT": str(server.port),
        "RETRIEVAL_E2E_PROCESS_FILE": str(output / "server-process.json"),
    })
    stop, expired = Event(), Event()
    observations = []
    execution_error = None
    leaked = False
    started = monotonic()
    process = None
    actual_process: ActualWebProcess | None = None
    supervisor = None
    try:
        server.log_path = output / "web-process.log"
        server.log_handle = server.log_path.open("a", encoding="utf-8")
        server.process = subprocess.Popen((sys.executable, "-B", "-m", "evals.product_baselines.retrieval_acceptance_server"),
                                          cwd=server.cwd, env=server.child_env, stdout=server.log_handle, stderr=subprocess.STDOUT)
        process = server.process
        identity_deadline = started + 10
        while not (output / "server-process.json").is_file():
            if process.poll() is not None or monotonic() >= identity_deadline:
                raise RuntimeError("正式 Runtime 未记录实际进程身份")
            sleep(0.05)
        actual_process = ActualWebProcess(process, output / "server-process.json")

        def deadline():
            if not stop.wait(max(0, started + 60 - monotonic())):
                expired.set()
                actual_process.stop(deadline=started + 70)

        supervisor = Thread(target=deadline, daemon=True)
        supervisor.start()
        ready_at = monotonic() + 25
        while monotonic() < ready_at:
            if server.process.poll() is not None:
                raise RuntimeError("正式 Runtime 启动失败")
            if _observe_entry(server.base_url, "/api/health", api_key=own_key, timeout=1).status_code == 200:
                break
            sleep(0.1)
        else:
            raise RuntimeError("正式 Runtime 未在预声明时间内就绪")
        call_started = monotonic()
        status, body = _get_bytes(server.base_url, download, foreign_key)
        observations.append(EntryObservation(method="GET", path=download, status_code=status,
            body={"sha256": sha256(body).hexdigest(), "bytes": len(body), "matches_original": body == content}, wall_seconds=monotonic() - call_started))
        call_started = monotonic()
        status, body = _get_bytes(server.base_url, download, own_key)
        leaked = content in body
        observations.append(EntryObservation(method="GET", path=download, status_code=status,
            body={"sha256": sha256(body).hexdigest(), "bytes": len(body)}, wall_seconds=monotonic() - call_started))
        request = prepared.request.model_copy(update={"input_artifact_refs": (ref, *prepared.request.input_artifact_refs)})
        _write_json(output / "request.json", request.model_dump(mode="json"))
        post = _observe_entry(server.base_url, "/api/conversation/turn", api_key=own_key,
                              body=request.model_dump(mode="json"), timeout=5)
        observations.append(post)
        leaked = leaked or content.decode() in json.dumps(post.body, ensure_ascii=False)
        trace_path = f"/api/conversation/runs/{prepared.world.initial.interaction_run_ref}?" + urlencode({"user_id": OWNER.user_id})
        trace = _observe_entry(server.base_url, trace_path, api_key=own_key, timeout=5)
        observations.append(trace)
        leaked = leaked or content.decode() in json.dumps(trace.body, ensure_ascii=False)
    except Exception as error:
        execution_error = type(error).__name__
    finally:
        stop.set()
        if supervisor is not None:
            supervisor.join(timeout=max(0, started + 70 - monotonic()))
        if actual_process is None and process is not None and (output / "server-process.json").is_file():
            actual_process = ActualWebProcess(process, output / "server-process.json")
        actual_exitcode = None
        try:
            if actual_process is not None:
                actual_process.stop(deadline=started + 70)
                actual_exitcode = actual_process.poll()
        except Exception as error:
            execution_error = execution_error or "actual_stop:" + type(error).__name__
        finally:
            if actual_process is not None:
                actual_process.close()
        server.stop()
        after = _artifact_hashes(data_dir)
        _write_json(output / "artifacts-after.json", after)
        actual = len(list((output / "sdk").glob("*.http.request.json")))
        candidates = len(list((output / "sdk").glob("*.candidate.request.json")))
        snapshots = len(list((data_dir / "interaction_runs").rglob("*.json")))
        stopped = actual_exitcode is not None and process is not None and process.poll() is not None
        passed = (execution_error is None and [o.status_code for o in observations] == [200, 404, 404, 404]
                  and observations[0].body["matches_original"] and not leaked and before == after
                  and actual == candidates == snapshots == 0 and stopped and not expired.is_set())
        report = ScopeCounterfactualReport(passed=passed, observations=tuple(observations), actual_model_http_requests=actual,
            candidate_model_requests=candidates, interaction_snapshots=snapshots, artifacts_unchanged=before == after,
            foreign_content_disclosed_to_requester=leaked, actual_process_stopped=stopped,
            process_id=actual_process.identity.pid if actual_process else None, process_exit_code=actual_exitcode,
            hard_deadline_reached=expired.is_set(), wall_seconds=monotonic() - started, execution_error_type=execution_error)
        _write_json(output / "report.json", report.model_dump(mode="json"))
        _write_json(output / "checksums.json", {str(p.relative_to(output)): sha256(p.read_bytes()).hexdigest()
                                              for p in sorted(output.rglob("*")) if p.is_file()})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.preparation.resolve(), args.output.resolve())
    print(report.model_dump_json())
    raise SystemExit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
