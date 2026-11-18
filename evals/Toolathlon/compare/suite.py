from argparse import ArgumentParser, Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack, contextmanager, nullcontext
from datetime import datetime, timezone
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import subprocess
from threading import Lock
from time import monotonic
from uuid import uuid4
import httpx

from dotenv import dotenv_values

from evals.conversation_http import UNVERIFIED_FLOW, benchmark_feature_flags, submit_turn
from evals.Toolathlon import case_tools, runner
from evals.Toolathlon.workspace_inputs import upload_gateway_attachments
from personal_agent.adapters.web.routes.conversation import ConversationTurnRequest
from evals.Toolathlon.case_tools import EXECUTE_BASH, BashSandbox, TaskToolRequirements
from evals.Toolathlon.compare import mcp_tools, redis_helm
from personal_agent.infra.mcp import MCPJsonRpcClient
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.kernel.feature_flags import load_feature_flags

import preflight
import canvas_official
from run_batch import WORKSPACE, grade


ROOT = preflight.ROOT
UPSTREAM = preflight.UPSTREAM
MODEL = redis_helm.MODEL
REVISION = redis_helm.REVISION
WALL_SECONDS = 1200
BUDGET = Namespace(max_total_tokens=8_000_000, max_model_turns=64, max_tool_calls=128)
FLAGS = benchmark_feature_flags(load_feature_flags())
SHARED = {"canvas", "emails", "woocommerce", "notion", "github", "google_sheet", "google_calendar",
          "google_forms", "huggingface", "k8s"}
SKIP = {"google-cloud", "snowflake"}
shared_lock = Lock()
WORKSPACE_CSV_CASE = "canvas-list-test"
WORKSPACE_CSV_FILES = ("quiz_info.csv", "assignment_info.csv")
PERSONAL_PRINCIPAL = AuthenticatedPrincipal(tenant_id="personal-agent", user_id="toolathlon-compare")


def write(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read(path):
    return json.loads(path.read_bytes())


def now():
    return datetime.now(timezone.utc).isoformat()


def assets():
    for path in sorted((UPSTREAM / "tasks/finalpool").glob("*/task_config.json")):
        yield path.parent, TaskToolRequirements.model_validate_json(path.read_bytes())


def official_setup():
    raw = dotenv_values(Path(".env"))
    assert raw["STRUCTURED_MODEL"] == MODEL and raw["STRUCTURED_BASE_URL"].startswith("https://") and raw["STRUCTURED_API_KEY"]
    config = read(UPSTREAM / "scripts/formal_run_v0.json")
    config["global_task_config"]["max_steps_under_single_turn_mode"] = BUDGET.max_model_turns
    config["agent"]["model"] = {"short_name": MODEL, "provider": "unified"}
    extra = json.loads(raw.get("STRUCTURED_EXTRA_BODY") or "{}")
    generation = {"temperature": 0, "max_completion_tokens": 32768, "extra_body": extra}
    if "reasoning_effort" in extra:
        generation["reasoning_effort"] = extra.pop("reasoning_effort")
    config["agent"]["generation"] = {"extra_request_params": generation}
    env = dict(os.environ, TOOLATHLON_OPENAI_BASE_URL=raw["STRUCTURED_BASE_URL"],
               TOOLATHLON_OPENAI_API_KEY=raw["STRUCTURED_API_KEY"], TA_COMPARE_MCP_TIMEOUT="90")
    return config, env


def official(gateway, port, out, question, result, config, env, selection):
    bundle = "/run/task.json"
    script = "import json,sys; p=sys.argv[1]; d=json.load(open(p)); d['task_str']=sys.argv[2]; " \
             "d['eval_config']=json.loads(sys.argv[3]); d['max_steps_under_single_turn_mode']=d['eval_config']['global_task_config']['max_steps_under_single_turn_mode']; json.dump(d,open(p,'w'))"
    runner.docker("exec", gateway, redis_helm.PYTHON, "-c", script, bundle, question, json.dumps(config))
    runner.docker("cp", str(Path(redis_helm.__file__).with_name("official_session.py").resolve()),
                  f"{gateway}:/run/official_session.py")
    runner.docker("cp", str((out / "mcp-tools.json").resolve()), f"{gateway}:/run/mcp-tools.json")
    command = ("docker", "exec", "-e", "TOOLATHLON_OPENAI_BASE_URL", "-e", "TOOLATHLON_OPENAI_API_KEY",
               "-e", "TA_COMPARE_MCP_TIMEOUT", "-e", "TA_COMPARE_MCP_SELECTION=/run/mcp-tools.json",
               "-e", "PYTHONPATH=/workspace", gateway, "timeout",
               "--kill-after=10", str(WALL_SECONDS), redis_helm.PYTHON, "/run/official_session.py",
               "--bundle_file", bundle, "--gateway_url", f"http://127.0.0.1:{port}/sse", "--debug")
    log_path = out / "agent.log"
    result["agent_started"] = True
    started = monotonic()
    try:
        with log_path.open("wb") as log:
            result["agent_exit"] = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                                   timeout=WALL_SECONDS + 25).returncode
    finally:
        result["agent_seconds"] = monotonic() - started
        log_path.write_bytes(preflight.redact(log_path.read_bytes().replace(env["TOOLATHLON_OPENAI_API_KEY"].encode(), b"[redacted]")))
    for name in ("traj_log.json", "model-usage.jsonl"):
        path = out / name
        copied = subprocess.run(("docker", "cp", f"{gateway}:/workspace/dumps/{name}", str(path)),
                                capture_output=True, timeout=40, check=False)
        if copied.returncode == 0:
            path.write_bytes(preflight.redact(path.read_bytes().replace(env["TOOLATHLON_OPENAI_API_KEY"].encode(), b"[redacted]")))
    usage_path = out / "model-usage.jsonl"
    if usage_path.exists():
        calls = [json.loads(line) for line in usage_path.read_text(encoding="utf-8").splitlines()]
        expected = frozenset(f"gw_{name.replace('-', '_')}" for name in selection.remote_names)
        result["mcp_model_tools"] = mcp_tools.audit_model_tools(expected, [
            {name for name in call.get("request_tools", ()) if name.startswith("gw_")}
            for call in calls
        ])
        successes = [call["usage"] for call in calls if call["http_status"] == 200]
        measured = [usage for usage in successes if usage]
        result.update(model_requests=len(successes), model_http=len(calls),
                      provider_usage_complete=bool(successes) and len(measured) == len(calls),
                      input_tokens=sum(u["prompt_tokens"] for u in measured) if measured else None,
                      output_tokens=sum(u["completion_tokens"] for u in measured) if measured else None)
    if not (out / "traj_log.json").is_file():
        result["disposition"] = "timeout" if result["agent_exit"] in (124, 137) else "missing_trajectory"
        return {}
    trace = read(out / "traj_log.json")
    assert trace["config"]["task_str"] == question
    result.update(disposition=trace["status"], tool_calls=trace["key_stats"]["tool_calls"],
                  model_turns=sum(item["role"] == "assistant" for item in trace["messages"]),
                  formal_answer=trace["status"] == "success" and any(item["role"] == "assistant" and
                                 item.get("content") and not item.get("tool_calls") for item in trace["messages"][-2:]))
    return trace


def personal(gateway, port, out, question, result, health, selection, *, session_id: str,
             sandbox: BashSandbox | None, web_allowed_domains: tuple[str, ...] | None = None):
    config = preflight.gateway_config(port, gateway)
    mappings = selection.model_dump(mode="json")
    unmapped = [service for service in health["connected_servers"]
                if not any(tool["name"].startswith(service.replace("-", "_") + ".") for tool in mappings)]
    result["unmapped_services"] = unmapped
    if unmapped:
        raise RuntimeError(f"No personalAgent mapping for {', '.join(unmapped)}")
    with ExitStack() as resources:
        database = resources.enter_context(runner.container("paradedb/paradedb:latest", "-p", "127.0.0.1::5432",
                                            "-e", "POSTGRES_PASSWORD=toolathlon", "--tmpfs", "/var/lib/postgresql:rw,size=256m"))
        connection = runner.postgres_url(database)
        server = {**config.model_dump(mode="json"), "tools": mappings}
        deployment = None
        deployment_path = None
        if sandbox is not None:
            workspace = case_tools.bind_gateway_workspace(
                gateway, config.server_id, runtime_volume_name=sandbox.runtime_volume_name,
            )
            deployment = sandbox.deployment(PERSONAL_PRINCIPAL, session_id,
                                            timeout_seconds=WALL_SECONDS, max_total_tokens=BUDGET.max_total_tokens,
                                            workspace=workspace)
            deployment_path = out / "bash-deployment.json"
            write(deployment_path, deployment.model_dump(mode="json"))
            result["bash_tool"] = {"registered": False}
        env = runner.product_environment(out, connection, [server], Path(".env"), feature_flags=FLAGS,
                                         bash_deployment=deployment_path)
        if web_allowed_domains is not None:
            env["PERSONAL_AGENT_WEB_SEARCH_ALLOWED_DOMAINS"] = ",".join(web_allowed_domains)
        runner.configure_interaction_budget(env, BUDGET)
        env.update(PERSONAL_AGENT_E2E_TRACE_DIR=str(out / "e2e"), PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR=str(out / "product"))
        turn = {}
        try:
            with runner.product(out, env) as (base, process):
                if not runner.wait_for_product(base, process, 120):
                    raise RuntimeError("PersonalAgent Web startup failed")
                if deployment is not None:
                    registered = any(tool["name"] == EXECUTE_BASH for tool in runner.request(base, "/api/tools"))
                    result["bash_tool"]["registered"] = registered
                    if not registered:
                        raise RuntimeError(f"Required local tool {EXECUTE_BASH} is missing from Runtime")
                refs = () if deployment is not None else upload_gateway_attachments(
                    base, gateway, out, user_id=PERSONAL_PRINCIPAL.user_id)
                result["attachment_count"] = len(refs)
                result["agent_started"] = True
                started = monotonic()
                try:
                    body = ConversationTurnRequest.model_validate({
                        "user_id": PERSONAL_PRINCIPAL.user_id, "session_id": session_id,
                        "messages": [{"role": "user", "content": question}],
                        "input_artifact_refs": refs,
                    })
                    response = submit_turn(base, body, timeout=WALL_SECONDS)
                    response.raise_for_status()
                    turn = response.json()
                    if turn["session_id"] != session_id:
                        raise ValueError("PersonalAgent returned a different Session")
                    result["turn_id"] = turn["turn_id"]
                except httpx.HTTPStatusError as error:
                    result["http_error"] = error.response.status_code
                    (out / "http-error.log").write_bytes(preflight.redact(error.response.content))
                except httpx.TimeoutException:
                    result["http_error"] = "timeout"
                finally:
                    result["agent_seconds"] = monotonic() - started
        except RuntimeError as error:
            if str(error) != "Product did not shut down gracefully":
                raise
            result["shutdown_error"] = str(error)
    result.update(evidence_class=UNVERIFIED_FLOW, release_eligible=False,
                  disposition=turn.get("disposition"), formal_answer=turn.get("disposition") == "answer")
    trace_root = out / "product-data/interaction_runs"
    snapshots = sorted(trace_root.glob(f"{turn['turn_id']}/[0-9]*.json" if turn else "*/[0-9]*.json"))
    if snapshots:
        trace = read(snapshots[-1])
        result.update(trace=canonical(snapshots[-1].relative_to(out)),
                      trace_sha256=sha256(snapshots[-1].read_bytes()).hexdigest(), **trace["usage"])
        result["model_requests"] = trace["usage"]["model_calls"]
        result["trace_disposition"] = (trace["final_message"] or {}).get("disposition")
        result["flags"] = trace["feature_flags_binding"]
        assert result["flags"] == FLAGS.model_dump()
        assert "writer" not in trace["answer_result_binding"]
        final_submissions = []
        blocked_research_actions = []
        inventories = []
        services = {service.replace("-", "_") for service in health["connected_servers"]}
        for decision in trace["model_decisions"]:
            request_path = snapshots[-1].parent / decision["invocation_id"] / "request.json"
            actual = read(request_path)
            inventories.append({
                action["target_name"] for action in actual["action_definitions"]
                if action["target_name"].partition(".")[0] in services
            })
            for action in actual.get("action_definitions", ()):
                if action["name"] in {"control_select_research_evidence", "control_create_claims"}:
                    blocked_research_actions.append(action["name"])
                if action["name"] == "control_submit_final":
                    options = action["input_schema"]["properties"]["disposition"]["enum"]
                    if "answer" in options:
                        final_submissions.append(decision["step_no"])
        assert not blocked_research_actions, blocked_research_actions
        result["mcp_model_tools"] = mcp_tools.audit_model_tools(selection.product_names, inventories)
        result["normal_answer_available_steps"] = final_submissions
        result["citation_rejections"] = sum(item.get("reason_code", "").startswith("citation_") for item in trace["inputs"])
        assert all(not goal["verification_ref"] for goal in trace["goal_operations"])
        assert not any(item.get("capability_id") == "verify_interaction_draft" for item in trace["inputs"])
        if deployment is not None:
            evidence = case_tools.bash_tool_evidence(out, trace)
            result["bash_tool"].update(evidence)
            if evidence["authorization_digest"] != deployment.authorization.authorization_digest:
                raise RuntimeError(f"Required local tool {EXECUTE_BASH} is not authorized for the benchmark conversation")
            if evidence["tool_request_count"] and not evidence["visible_request_count"]:
                raise RuntimeError(f"Required local tool {EXECUTE_BASH} was absent from all model tool requests")
    return turn


def canonical(path):
    return path.as_posix()


def export_workspace(gateway, out, allow_archive):
    workspace = out / "workspace"
    workspace.mkdir()
    with (out / "export.log").open("wb") as log:
        copied = subprocess.run(("docker", "cp", f"{gateway}:{WORKSPACE}/.", str(workspace)),
                                stdout=log, stderr=subprocess.STDOUT, timeout=180)
    if copied.returncode == 0:
        return workspace, None
    if not allow_archive:
        raise RuntimeError("Could not export Kubernetes workspace")
    archive = out / "workspace.tar"
    with archive.open("wb") as stream, (out / "export.log").open("ab") as log:
        subprocess.run(("docker", "cp", f"{gateway}:{WORKSPACE}/.", "-"), stdout=stream, stderr=log,
                       timeout=180, check=True)
    return workspace, archive


def check_csv_workspace(gateway, port, mappings, result):
    required = {"filesystem.list_directory", "filesystem.read_file", "filesystem.write_file"}
    mapped = {item["name"]: item["remote_name"] for item in mappings}
    missing = required - mapped.keys()
    if missing:
        raise RuntimeError(f"Missing benchmark workspace tools: {', '.join(sorted(missing))}")
    client = MCPJsonRpcClient(preflight.gateway_config(port, gateway))
    try:
        checked = {}
        for name in WORKSPACE_CSV_FILES:
            response = client.call_tool(mapped["filesystem.read_file"], {"path": f"{WORKSPACE}/{name}"})
            if not response.get("content"):
                raise RuntimeError(f"Filesystem returned no content for {name}")
            checked[name] = sha256(json.dumps(response["content"], sort_keys=True).encode()).hexdigest()
    finally:
        client.close()
    result["workspace_preflight"] = {"mapped": sorted(required), "read_result_sha256": checked}


@contextmanager
def agent_environment(case, arm, out, *, shared_workspace=False):
    if case.name == canvas_official.CASE and arm == "official":
        with canvas_official.execution_environment(case, out) as (container, port, health):
            yield container, port, health, preflight.gateway_tools(port, container, out)
        return
    workspace_filesystem = case.name == WORKSPACE_CSV_CASE and arm == "personal"
    with preflight.task_gateway(case.name, out, workspace_filesystem=workspace_filesystem,
                                shared_workspace=shared_workspace) as gateway:
        yield gateway


def run_arm(case, requirements: TaskToolRequirements, arm, out, config, env, *, sandbox: BashSandbox | None,
            environment=agent_environment, grader=grade, web_allowed_domains: tuple[str, ...] | None = None):
    out.mkdir(parents=True)
    question = (case / "docs/task.md").read_text(encoding="utf-8").strip() + f"\n\nThe task workspace is {WORKSPACE}."
    result = {"case": case.name, "arm": arm, "started_at": now(), "agent_started": False,
              "request_sha256": sha256(question.encode()).hexdigest(),
              "needed_local_tools": requirements.needed_local_tools}
    session_id = "toolathlon-" + uuid4().hex
    if arm == "personal":
        result["session_id"] = session_id
    phase = "preflight"
    try:
        workspace_filesystem = case.name == WORKSPACE_CSV_CASE and arm == "personal"
        with environment(case, arm, out, shared_workspace=sandbox is not None) as (gateway, port, health, tools):
            result["gateway_ready"] = True
            result["gateway_network_mode"] = runner.docker("inspect", "--format", "{{.HostConfig.NetworkMode}}", gateway)
            isolation = out / "official-isolation.json"
            if isolation.is_file():
                result["official_isolation"] = read(isolation)
            manifest = out.parent / "mcp-tools.json"
            if manifest.is_file():
                selection = mcp_tools.ComparisonMCPTools.model_validate_json(manifest.read_bytes())
            else:
                selection = mcp_tools.ComparisonMCPTools.from_gateway(health, tools)
                write(manifest, selection.model_dump(mode="json"))
            selection.require_available(tools)
            if case.name == "apply-phd-email" and "pdf-tools-merge_pdfs" not in selection.remote_names:
                raise RuntimeError("Task requires the pdf-tools-merge_pdfs MCP mapping")
            write(out / manifest.name, selection.model_dump(mode="json"))
            result["mcp_selection_sha256"] = sha256(manifest.read_bytes()).hexdigest()
            result["mcp_selected_count"] = len(selection.remote_names)
            if workspace_filesystem:
                check_csv_workspace(gateway, port, selection.model_dump(mode="json"), result)
            phase = "agent"
            trajectory = official(gateway, port, out, question, result, config, env, selection) if arm == "official" else None
            turn = personal(gateway, port, out, question, result, health, selection,
                            session_id=session_id, sandbox=sandbox,
                            web_allowed_domains=web_allowed_domains) if arm == "personal" else {}
            phase = "artifact_export"
            live = gateway if "k8s" in requirements.needed_mcp_servers else None
            workspace, archive = export_workspace(gateway, out, live is None)
            phase = "grader"
            if live:
                runner.docker("cp", str(case / "evaluation"), f"{gateway}:/workspace/tasks/finalpool/{case.name}/evaluation")
            result["grader_exit"] = grader(case, out, workspace, turn, health.get("launch_time"),
                                           gateway=live, trajectory=trajectory, workspace_archive=archive)
    except Exception as error:
        detail = preflight.redact(str(error).encode("utf-8")).decode("utf-8", errors="replace")
        result["error"] = {"phase": phase, "type": type(error).__name__, "detail": detail[:1700]}
    finally:
        result["finished_at"] = now()
        write(out / "report.json", result)
        seals = []
        for path in sorted(out.iterdir()):
            if path.is_file():
                with path.open("rb") as source:
                    seals.append(f"{file_digest(source, 'sha256').hexdigest()}  {path.name}")
        (out / "checksums.sha256").write_text("\n".join(seals) + "\n", encoding="utf-8")
        print(case.name, arm, result.get("grader_exit"), result.get("disposition"), result.get("error"), flush=True)
    return result


def run_pair(case, requirements: TaskToolRequirements, args, config, env, *, sandbox: BashSandbox | None):
    with shared_lock if set(requirements.needed_mcp_servers) & SHARED else nullcontext():
        arms = ("official", "personal") if args.arm is None else (args.arm,)
        for arm in arms:
            if (ROOT / "stop-dispatch").exists():
                return
            out = args.output / case.name / arm
            if (out / "report.json").exists():
                continue
            result = run_arm(case, requirements, arm, out, config, env,
                             sandbox=sandbox if arm == "personal" and requirements.needs_bash else None)
            quota_log = out / ("agent.log" if arm == "official" else "http-error.log")
            if quota_log.is_file():
                diagnostic = quota_log.read_bytes()
                if (arm == "official" and b"(2056)" in diagnostic or
                        arm == "personal" and b'"provider_status_code":429' in diagnostic):
                    (ROOT / "stop-dispatch").touch()


def main():
    with ExitStack() as resources:
        run(resources)


def run(resources):
    parser = ArgumentParser()
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--output", type=Path, default=ROOT / "runs")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--arm", choices=("official", "personal"))
    args = parser.parse_args()
    assert subprocess.check_output(("git", "-C", str(UPSTREAM), "rev-parse", "HEAD"), text=True).strip() == REVISION
    config, env = official_setup()
    inputs = dict(assets())
    inventory = {case.name: {"services": requirements.needed_mcp_servers, "local_tools": requirements.needed_local_tools,
                             "skip": sorted(set(requirements.needed_mcp_servers) & SKIP)}
                 for case, requirements in inputs.items()}
    assert len(inventory) == 108 and sum(not row["skip"] for row in inventory.values()) == 96
    selected = [(case, requirements) for case, requirements in inputs.items()
                if not inventory[case.name]["skip"] and (not args.cases or case.name in args.cases)]
    if args.cases and len(set(args.cases)) != len(selected):
        parser.error("Supply unique eligible case names")
    sandbox = None
    if args.arm != "official" and any(requirements.needs_bash for _, requirements in selected):
        try:
            sandbox = resources.enter_context(BashSandbox.from_fixture_image(preflight.PDF_IMAGE))
        except subprocess.CalledProcessError:
            parser.error("Cannot prepare Bash from the pinned Toolathlon task image")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    project = Path.cwd()
    sources = sorted((Path(__file__), *Path("src/personal_agent").rglob("*.py"), *ROOT.glob("*.py"), *ROOT.glob("*.yaml"),
                      ROOT / "fixture_recipients.js", ROOT / "route-probe.json",
            Path(runner.__file__), Path(case_tools.__file__), Path(mcp_tools.__file__), Path(redis_helm.__file__),
                      Path("evals/conversation_http.py"), Path("evals/web_process.py"), Path("evals/Toolathlon/workspace_inputs.py"),
                      Path(redis_helm.__file__).with_name("official_session.py"), Path("config/feature_flags.toml")))
    identity = {"upstream_revision": REVISION, "model": MODEL, "personal_flags": FLAGS.model_dump(),
                "personal_budget": vars(BUDGET), "official_config": config, "wall_seconds": WALL_SECONDS,
                "official_sse_seconds": 90, "fixture_image": preflight.PDF_IMAGE,
                "personal_bash_sandbox": vars(sandbox) if sandbox is not None else None,
                "head": subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip(),
                "source_sha256": {p.resolve().relative_to(project).as_posix(): sha256(p.read_bytes()).hexdigest() for p in sources}}
    identity_path = args.output / "identity.json"
    if not identity_path.exists():
        write(identity_path, identity)
    write(ROOT / "inventory.json", inventory)
    shared = [(case, requirements) for case, requirements in selected if set(requirements.needed_mcp_servers) & SHARED]
    independent = [(case, requirements) for case, requirements in selected if not set(requirements.needed_mcp_servers) & SHARED]

    def run_shared():
        for case, requirements in shared:
            run_pair(case, requirements, args, config, env, sandbox=sandbox)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        pending = [executor.submit(run_shared)] if shared else []
        pending.extend(executor.submit(run_pair, case, requirements, args, config, env, sandbox=sandbox)
                       for case, requirements in independent)
        for task in as_completed(pending):
            task.result()


if __name__ == "__main__":
    main()
