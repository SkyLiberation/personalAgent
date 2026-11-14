"""Run Toolathlon's official Agent on the Redis Helm case and compare a prior run."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values

from evals.Toolathlon import runner
from evals.Toolathlon.pdf_cases import PDF_IMAGE


CASE = "k8s-redis-helm-upgrade"
TASK = f"finalpool/{CASE}"
CONTAINER_TASK = f"/workspace/tasks/{TASK}"
WORKSPACE = "/workspace/dumps/workspace"
PYTHON = "/workspace/.venv/bin/python"
REVISION = "9be8d8fe07a497b18ee61e3f2ae694e9797f39eb"
MODEL = "MiniMax-M3.1-Flash"
MODEL_TURNS = 32
WALL_SECONDS = 600
SERVERS = {"filesystem", "k8s", "terminal"}


class RunResult(TypedDict):
    status: str
    model_requests: int | None
    tool_calls: int | None
    input_tokens: int | None
    output_tokens: int | None
    agent_wall_seconds: float | None
    grade: dict[str, Any] | None


def read_json(path: Path) -> Any:
    return json.loads(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_seal(directory: Path, name: str) -> str:
    digest = sha256((directory / name).read_bytes()).hexdigest()
    expected = dict(line.split("  ", 1)[::-1] for line in
                    (directory / "checksums.sha256").read_text(encoding="utf-8").splitlines())
    if expected.get(name) != digest:
        raise ValueError(f"Historical checksum mismatch: {name}")
    return digest


def parse_grade(data: str) -> dict[str, Any]:
    report, _ = json.JSONDecoder().raw_decode(data.lstrip())
    if not isinstance(report.get("task_completed"), bool) or not isinstance(report.get("scores"), dict):
        raise ValueError("Unexpected Redis grader result")
    return report


def read_personal_run(path: Path, question: str) -> tuple[RunResult, dict]:
    hashes = {name: check_seal(path, name) for name in ("report.json", "grader.log", "tools.json")}
    report = read_json(path / "report.json")
    if (report["scenario"], report["upstream_revision"], report["model"], report["request"]) != (
        CASE, REVISION, MODEL, question,
    ):
        raise ValueError("Historical run has a different case, upstream version, model or task input")
    turn = report["turn"]
    snapshots = sorted((path / "product-data/interaction_runs" / turn["interaction_run_ref"]).glob("*.json"))
    trace = snapshots[-1]
    usage = read_json(trace)["usage"]
    return {
        "status": turn["disposition"], "model_requests": usage["model_calls"], "tool_calls": usage["tool_calls"],
        "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
        "agent_wall_seconds": None, "grade": parse_grade((path / "grader.log").read_text(encoding="utf-8")),
    }, {
        "path": str(path), "sealed_files": hashes, "trace": str(trace),
        "trace_sha256": sha256(trace.read_bytes()).hexdigest(), "budget": report["budget"],
        "conversation_timeout_seconds": WALL_SECONDS,
    }


def run_phase(args: tuple[str, ...], log: Path, timeout: int) -> int:
    with log.open("wb") as output:
        process = subprocess.run(args, stdout=output, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    return process.returncode


def bind(source: Path, target: str) -> tuple[str, str]:
    return "--mount", f"type=bind,source={source},target={target},readonly"


@contextmanager
def redis_gateway(upstream: Path, out: Path):
    suffix = f"-ta-compare-{uuid4().hex[:8]}"
    ports = out / "ports_config.yaml"
    ports.write_text(f"instance_suffix: {suffix}\n", encoding="utf-8")
    mounts = (
        (upstream / "utils", "/workspace/utils"),
        (upstream / "scripts/decoupled", "/workspace/scripts/decoupled"),
        (upstream / "scripts/lib", "/workspace/scripts/lib"),
        (upstream / "configs/global_configs_example.py", "/workspace/configs/global_configs.py"),
        (upstream / "configs/token_key_session_example.py", "/workspace/configs/token_key_session.py"),
        (upstream / "configs/mcp_servers", "/workspace/configs/mcp_servers"),
        (upstream / "deployment/k8s/configs", "/workspace/deployment/k8s/configs"),
        (out / "eval-config.json", "/run/eval-config.json"),
        (Path(__file__).with_name("official_session.py").resolve(), "/run/official_session.py"),
        (ports, "/workspace/configs/ports_config.yaml"),
    )
    bundle = f"{CONTAINER_TASK}/.task-bundle.json"
    task_volume = runner.docker("volume", "create")
    try:
        workspace_volume = runner.docker("volume", "create")
        try:
            common = (
                "--init", "--network", "host", "--workdir", "/workspace", "--entrypoint", "/bin/bash",
                "-e", "PYTHONUNBUFFERED=1", "-e", "npm_config_prefer_offline=true",
                "--mount", f"type=volume,source={task_volume},target={CONTAINER_TASK}",
                "--mount", f"type=volume,source={workspace_volume},target=/workspace/dumps",
                *(arg for source, target in mounts for arg in bind(source, target)),
            )
            fixture = upstream / "tasks" / TASK
            bind_question = shlex.join((PYTHON, "-c", (
                "import json, pathlib, sys; p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_bytes()); "
                "d['task_str']=d['task_str'].strip()+sys.argv[2]; p.write_text(json.dumps(d), encoding='utf-8')"
            ), bundle, f"\n\nThe task workspace is {WORKSPACE}."))
            prepare = (
                f"cp -r /run/fixture/docs /run/fixture/initial_workspace /run/fixture/preprocess /run/fixture/scripts "
                f"/run/fixture/task_config.json /run/fixture/token_key_session.py {CONTAINER_TASK}/; "
                f"{PYTHON} -m scripts.decoupled.container_preprocess --eval_config /run/eval-config.json "
                f"--task_dir {TASK} --bundle_file {bundle} --debug; {bind_question}"
            )
            with runner.container(PDF_IMAGE, *common, *bind(fixture, "/run/fixture"),
                                  "-v", "/var/run/docker.sock:/var/run/docker.sock",
                                  command=("-ec", prepare)) as preparer:
                if run_phase(("docker", "start", "-a", preparer), out / "preprocess.log", 780) != 0:
                    raise RuntimeError("Official Redis preprocessing failed")
            print("Redis fixture ready", flush=True)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            launch = (f"exec {PYTHON} -m scripts.decoupled.container_tool_gateway --bundle_file {bundle} "
                      f"--host 127.0.0.1 --port {port}")
            with runner.container(PDF_IMAGE, *common, command=("-ec", launch)) as gateway:
                runner.docker("start", gateway)
                try:
                    health = subprocess.check_output(("docker", "exec", gateway, "timeout", "150", "bash", "-c",
                        f"until curl -fsS http://127.0.0.1:{port}/health 2>/dev/null; do sleep 1; done"), timeout=160)
                    health_data = json.loads(health)
                    write_json(out / "health.json", health_data)
                    if set(health_data["connected_servers"]) != SERVERS:
                        raise RuntimeError("Official gateway did not connect all Redis tool servers")
                    yield gateway, port, bundle
                finally:
                    (out / "gateway.log").write_text(runner.docker("logs", gateway), encoding="utf-8")
        finally:
            runner.docker("volume", "rm", workspace_volume)
    finally:
        nodes = runner.docker("ps", "-a", "--filter", f"name={suffix}", "--format", "{{.Names}}")
        for node in nodes.splitlines():
            if node == f"cluster-redis-helm{suffix}-control-plane":
                runner.docker("rm", "-f", "-v", node)
        runner.docker("volume", "rm", task_volume)


def grade_redis(gateway: str, fixture: Path, out: Path) -> dict:
    for name in ("evaluation", "groundtruth_workspace"):
        runner.docker("cp", str(fixture / name), f"{gateway}:{CONTAINER_TASK}/{name}")
    log = out / "grader.log"
    code = run_phase(("docker", "exec", gateway, PYTHON, "-m", f"tasks.finalpool.{CASE}.evaluation.main"), log, 420)
    grade = parse_grade(log.read_text(encoding="utf-8"))
    if code != (0 if grade["task_completed"] else 1):
        raise RuntimeError("Redis grader exit and result disagree")
    return grade


def run_official(upstream: Path, out: Path, env: dict[str, str], report: dict) -> RunResult:
    phase = "preprocessing"
    result: RunResult = {
        "status": "unavailable", "model_requests": None, "tool_calls": None,
        "input_tokens": None, "output_tokens": None, "agent_wall_seconds": None, "grade": None,
    }
    try:
        with redis_gateway(upstream, out) as (gateway, port, bundle):
            phase = "official_agent"
            print("Running Toolathlon official Agent", flush=True)
            start = time.monotonic()
            command = (
                "docker", "exec", "-e", "TOOLATHLON_OPENAI_BASE_URL", "-e", "TOOLATHLON_OPENAI_API_KEY",
                "-e", "TA_COMPARE_MCP_TIMEOUT", "-e", "PYTHONPATH=/workspace",
                gateway, "timeout", "--kill-after=10", str(WALL_SECONDS), PYTHON,
                "/run/official_session.py", "--bundle_file", bundle,
                "--gateway_url", f"http://127.0.0.1:{port}/sse", "--debug",
            )
            secret = env["TOOLATHLON_OPENAI_API_KEY"].encode()
            agent_log = out / "agent.log"
            try:
                with agent_log.open("wb") as log:
                    code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env,
                                          timeout=WALL_SECONDS + 30, check=False).returncode
            finally:
                agent_log.write_bytes(agent_log.read_bytes().replace(secret, b"[redacted]"))
            result["agent_wall_seconds"] = round(time.monotonic() - start, 3)
            report["official_process_exit"] = code
            phase = "trajectory"
            log = out / "traj_log.json"
            exists = subprocess.run(("docker", "exec", gateway, "test", "-f", "/workspace/dumps/traj_log.json"),
                                    timeout=15, check=False).returncode == 0
            if exists:
                runner.docker("cp", f"{gateway}:/workspace/dumps/traj_log.json", str(log))
                log.write_bytes(log.read_bytes().replace(secret, b"[redacted]"))
                trace = read_json(log)
                if trace["config"]["task_str"] != report["task_input"]:
                    raise ValueError("The official Agent received a different task input")
                stats = trace["key_stats"]
                result.update(status=trace["status"], tool_calls=stats.get("tool_calls"))
            else:
                result["status"] = "timeout" if code in (124, 137) else "missing_trajectory"
            usage_path = out / "model-usage.jsonl"
            copied = subprocess.run(("docker", "cp", f"{gateway}:/workspace/dumps/{usage_path.name}", str(usage_path)),
                                    capture_output=True, timeout=30, check=False)
            if copied.returncode == 0:
                calls = [json.loads(line) for line in usage_path.read_text(encoding="utf-8").splitlines()]
                accepted = [call for call in calls if call["http_status"] == 200]
                result["model_requests"] = len(accepted)
                report["official_http_responses"] = len(calls)
                if accepted and all(call.get("usage") for call in accepted):
                    result["input_tokens"] = sum(call["usage"]["prompt_tokens"] for call in accepted)
                    result["output_tokens"] = sum(call["usage"]["completion_tokens"] for call in accepted)
            phase = "grader"
            result["grade"] = grade_redis(gateway, upstream / "tasks" / TASK, out)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report["error"] = {"phase": phase, "type": type(error).__name__}
        print(f"{phase}: {type(error).__name__}. See the phase log in {out}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, default=Path("toolServer/Toolathlon"))
    parser.add_argument("--model-env", type=Path, default=Path(".env"))
    parser.add_argument("--output", type=Path, required=True, help="New run directory under .tmp")
    parser.add_argument("--personal-run", type=Path, help="Optional sealed personalAgent case directory")
    parser.add_argument("--model-turns", type=runner._positive_int, default=MODEL_TURNS,
                        help="Maximum official Agent decision rounds")
    parser.add_argument("--mcp-session-timeout", type=runner._positive_int, help="Override the official SSE client timeout in seconds")
    parser.add_argument("--check-only", action="store_true", help="Validate the input and configuration")
    args = parser.parse_args()

    upstream = args.upstream.resolve(strict=True)
    actual = subprocess.check_output(("git", "-C", str(upstream), "rev-parse", "HEAD"), text=True).strip()
    dirty = subprocess.check_output(("git", "-C", str(upstream), "status", "--porcelain", "-uno"), text=True)
    if actual != REVISION or dirty:
        parser.error(f"Use a Toolathlon checkout at {REVISION} with clean tracked files")
    raw = dotenv_values(args.model_env)
    endpoint, key = raw.get("STRUCTURED_BASE_URL"), raw.get("STRUCTURED_API_KEY")
    if not endpoint or urlsplit(endpoint).scheme != "https" or not key or raw.get("STRUCTURED_MODEL") != MODEL:
        parser.error(f"--model-env must configure {MODEL}, an HTTPS STRUCTURED_BASE_URL and STRUCTURED_API_KEY")
    provider = urlsplit(endpoint)
    if not provider.hostname or provider.username or provider.password or provider.query or provider.fragment:
        parser.error("STRUCTURED_BASE_URL must be an API endpoint without embedded credentials")
    env = dict(os.environ, TOOLATHLON_OPENAI_BASE_URL=endpoint, TOOLATHLON_OPENAI_API_KEY=key,
               TA_COMPARE_MCP_TIMEOUT=str(args.mcp_session_timeout or 0))
    question = (upstream / "tasks" / TASK / "docs/task.md").read_text(encoding="utf-8").strip()
    question += f"\n\nThe task workspace is {WORKSPACE}."
    extra_body = json.loads(raw.get("STRUCTURED_EXTRA_BODY") or "{}")
    settings = {"temperature": 0, "max_completion_tokens": 32768,
                **({"reasoning_effort": extra_body.pop("reasoning_effort")} if "reasoning_effort" in extra_body else {}),
                "extra_body": extra_body}
    config = read_json(upstream / "scripts/formal_run_v0.json")
    config["global_task_config"]["max_steps_under_single_turn_mode"] = args.model_turns
    config["agent"]["model"] = {"short_name": MODEL, "provider": "unified"}
    config["agent"]["generation"] = {"extra_request_params": settings}
    report = {"scenario": CASE, "upstream_revision": actual, "image": PDF_IMAGE, "model": MODEL,
              "provider_host": provider.hostname, "task_input": question, "official_config": config,
              "official_mcp_session_timeout_override": args.mcp_session_timeout,
              "official_budget": {"model_turns": args.model_turns, "wall_seconds": WALL_SECONDS,
                                  "tool_calls": None, "total_tokens": None}}
    if args.personal_run:
        report["personal"], report["personal_source"] = read_personal_run(args.personal_run.resolve(), question)
    if args.check_only:
        print(f"Configuration ready: {CASE}, {MODEL}, {args.model_turns} official Agent turns")
        return 0

    out = args.output.resolve()
    if not out.is_relative_to(Path(".tmp").resolve()) or out == Path(".tmp").resolve():
        parser.error("--output must be a new directory under .tmp")
    out.mkdir(parents=True)
    write_json(out / "eval-config.json", config)
    report["started_at"] = datetime.now(timezone.utc).isoformat()
    report["official"] = run_official(upstream, out, env, report)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["source_sha256"] = {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in ("redis_helm.py", "official_session.py")}
    write_json(out / "report.json", report)
    (out / "checksums.sha256").write_text("".join(
        f"{sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in sorted(out.iterdir()) if path.is_file()
    ), encoding="utf-8")
    print(f"Report: {out / 'report.json'}", flush=True)
    return 0 if report["official"]["grade"] and report["official"]["grade"]["task_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
