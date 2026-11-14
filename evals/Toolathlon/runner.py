from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from dotenv import dotenv_values

from evals.Toolathlon.time_case import ANSWER, MAPPING, QUESTION, SERVER_ID, TOOL, UPSTREAM_REVISION
from personal_agent.kernel.config_models import InteractionLoopConfig
from personal_agent.kernel.feature_flags import FeatureFlags, load_feature_flags, write_feature_flags


_UVICORN = """
import socket
import sys
import time
from pathlib import Path
from threading import Thread
import uvicorn
def shutdown():
    signal = Path(sys.argv[2])
    while not signal.exists():
        time.sleep(0.1)
    server.should_exit = True

with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        'personal_agent.adapters.web.api:app', host='127.0.0.1', port=port,
    ))
    port_file = Path(sys.argv[1])
    pending = port_file.with_suffix('.tmp')
    pending.write_text(str(port), encoding='ascii')
    pending.replace(port_file)
    Thread(target=shutdown, daemon=True).start()
    server.run(sockets=[listener])
"""

_SYSTEM_ENV = (
    "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
    "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "DOCKER_HOST", "DOCKER_CONTEXT",
)
_MODEL_ENV = (
    "STRUCTURED_PROVIDER", "STRUCTURED_API_KEY", "STRUCTURED_BASE_URL",
    "STRUCTURED_MODEL", "STRUCTURED_OUTPUT_TRANSPORT", "STRUCTURED_EXTRA_BODY",
    "STRUCTURED_MODEL_CAPACITY",
)
INTERACTION_BUDGET_OPTIONS = {
    "--model-budget": "max_total_tokens",
    "--model-turns": "max_model_turns",
    "--tool-calls": "max_tool_calls",
}
_INTERACTION_BUDGET_ENV = {
    field: f"PERSONAL_AGENT_INTERACTION_{field.upper()}"
    for field in INTERACTION_BUDGET_OPTIONS.values()
}


def _positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def add_interaction_budget_arguments(parser: argparse.ArgumentParser) -> None:
    for option, field in INTERACTION_BUDGET_OPTIONS.items():
        parser.add_argument(option, dest=field, type=_positive_int)


def configure_interaction_budget(env: dict[str, str], args: argparse.Namespace) -> InteractionLoopConfig:
    values = {}
    for field, name in _INTERACTION_BUDGET_ENV.items():
        override = getattr(args, field)
        if override is not None:
            env[name] = str(override)
        if name in env:
            values[field] = int(env[name])
    return InteractionLoopConfig(**values)


class TimeRunReport(TypedDict, total=False):
    scenario: str
    toolathlon_revision: str
    containers: dict[str, str]
    image_id: str
    model: str | None
    mapped_remote_tools: list[dict[str, str]]
    started: bool
    mcp_connectors: list[dict[str, Any]]
    tool_result: dict[str, Any]
    after_disconnect: dict[str, Any]
    restarted_implicitly: bool
    conversation: dict[str, Any]
    conversation_error: dict[str, Any]
    journal_model_actions: list[dict[str, Any]]
    process_exit_code: int | None
    expected_startup_error: bool
    server_running_after_product_exit: bool
    second_running_after_product_exit: bool
    restart_result: dict[str, Any] | None
    server_running_after_restart_exit: bool
    environment_error: str
    protocol_and_lifecycle_passed: bool


def docker(*args: str) -> str:
    return subprocess.run(
        ("docker", *args), check=True, text=True, stdout=subprocess.PIPE, timeout=60,
    ).stdout.strip()


@contextmanager
def container(image: str, *options: str, command: tuple[str, ...] = ()):
    container_id = docker("create", *options, image, *command)
    try:
        yield container_id
    finally:
        docker("rm", "-f", "-v", container_id)


def running(container_id: str) -> bool:
    return docker("inspect", "--format", "{{.State.Running}}", container_id) == "true"


def postgres_url(container_id: str) -> str:
    docker("start", container_id)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        result = subprocess.run(
            ("docker", "exec", container_id, "pg_isready", "-h", "127.0.0.1"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
        if result.returncode == 0:
            port = docker("port", container_id, "5432/tcp").rsplit(":", 1)[1]
            return f"postgresql://postgres:toolathlon@127.0.0.1:{port}/postgres?sslmode=disable"
        time.sleep(0.25)
    raise RuntimeError("Toolathlon Postgres did not become ready")


_PDF_INTEGER_STRING_FIELDS = {
    "read_pdf_pages": ("start_page", "end_page"),
    "search_pdf_content": ("page_size",),
}


def _configure_pdf_integer_fields(tool: dict) -> dict:
    namespace, _, operation = (tool.get("name") or "").partition(".")
    fields = _PDF_INTEGER_STRING_FIELDS.get(operation)
    if (
        namespace in {"pdf", "pdf_tools"}
        and fields
        and tool.get("remote_name") in {operation, f"pdf-tools-{operation}"}
    ):
        return {"model_integer_string_fields": fields, **tool}
    return tool


def model_request_paths(output: Path) -> list[Path]:
    return sorted((output / "product-data" / "interaction_runs").glob("*/*/request.json"))


def product_environment(
    output: Path, db_url: str, servers: list[dict], model_env: Path | None, *,
    feature_flags: FeatureFlags | None = None,
):
    flags_path = (output / "feature_flags.toml").resolve()
    flags = feature_flags or load_feature_flags()
    write_feature_flags(flags_path, flags)
    env = {name: os.environ[name] for name in _SYSTEM_ENV if name in os.environ}
    if model_env is not None:
        values = dotenv_values(model_env)
        env.update({name: str(values[name]) for name in _MODEL_ENV if values.get(name)})
        env.update({
            name: value for name in _INTERACTION_BUDGET_ENV.values()
            if (value := values.get(name)) is not None
        })
        if not env.get("STRUCTURED_API_KEY") or not env.get("STRUCTURED_MODEL"):
            raise ValueError("Model env must specify STRUCTURED_API_KEY and STRUCTURED_MODEL")
    env.update(
        PYTHONUTF8="1",
        PYTHON_DOTENV_DISABLED="1",
        PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"),
        PERSONAL_AGENT_DATA_DIR=str(output / "product-data"),
        PERSONAL_AGENT_POSTGRES_URL=db_url,
        PERSONAL_AGENT_FEATURE_FLAGS_CONFIG=str(flags_path),
        PERSONAL_AGENT_MCP_SERVERS=json.dumps({
            "enabled": True,
            "servers": [
                {**server, "tools": [_configure_pdf_integer_fields(tool) for tool in server.get("tools", ())]}
                for server in servers
            ],
        }),
        PERSONAL_AGENT_GITHUB_MCP_ENABLED="false",
        PERSONAL_AGENT_NOTION_MCP_ENABLED="false",
        PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED="false",
        PERSONAL_AGENT_FEISHU_ENABLED="false",
        PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_ENABLED="false",
        PERSONAL_AGENT_KNOWLEDGE_GAP_SCHEDULER_ENABLED="false",
        PERSONAL_AGENT_RESEARCH_SCHEDULER_ENABLED="false",
        PERSONAL_AGENT_LANGSMITH_ENABLED="false",
    )
    return env


def request(base: str, path: str, payload: dict | None = None, *, timeout: float = 3) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        return json.load(response)


def wait_for_product(base: str, process: subprocess.Popen, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            return request(base, "/api/health")["status"] == "ok"
        except URLError:
            time.sleep(0.2)
    raise RuntimeError("Product Web process did not become ready")


@contextmanager
def product(output: Path, env: dict[str, str]):
    port_file = output / "web.port"
    stop_signal = output / "stop-web"
    with (output / "web.log").open("wb") as log:
        process = subprocess.Popen(
            (sys.executable, "-c", _UVICORN, str(port_file), str(stop_signal)),
            cwd=Path(__file__).resolve().parents[2],
            env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            while not port_file.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"Product Web process did not bind a port. See {output / 'web.log'}.")
                time.sleep(0.05)
            port = int(port_file.read_text(encoding="ascii"))
            yield f"http://127.0.0.1:{port}", process
        finally:
            stop_signal.touch()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError("Product did not shut down gracefully") from None


def server(container_id: str, server_id: str, mapping: dict) -> dict:
    return {
        "server_id": server_id, "transport": "stdio", "command": "docker",
        "args": ["start", "-ai", container_id], "tools": [mapping],
    }


def invoke(base: str) -> dict:
    return request(base, f"/api/tools/{TOOL}/execute", {
        "tenant_id": "personal-agent", "user_id": "toolathlon",
        "kwargs": {"source_timezone": "Asia/Shanghai", "target_timezone": "Asia/Tokyo", "time": "09:00"},
    }, timeout=25)


def run(args: argparse.Namespace, report: TimeRunReport) -> None:
    with ExitStack() as resources:
        database = resources.enter_context(container(
            args.postgres_image, "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=toolathlon",
        ))
        db_url = postgres_url(database)
        time_server = resources.enter_context(container(args.time_image, "-i", "--network", "none"))
        servers = [] if args.scenario == "unmapped" else [server(time_server, SERVER_ID, MAPPING)]
        failure = args.scenario in {"partial", "duplicate"}
        if failure:
            second = resources.enter_context(container(args.time_image, "-i", "--network", "none"))
            if args.scenario == "partial":
                servers.append(server(second, "missing-time", {
                    **MAPPING, "remote_name": "missing", "name": "time.missing",
                }))
            else:
                servers.append(server(second, "duplicate-time", MAPPING))

        env = product_environment(args.output, db_url, servers, args.model_env)
        report["containers"] = {"time": time_server, "postgres": database}
        report["image_id"] = docker("image", "inspect", args.time_image, "--format", "{{.Id}}")
        report["model"] = env.get("STRUCTURED_MODEL")
        report["mapped_remote_tools"] = [
            {"server_id": entry["server_id"], "remote_name": tool["remote_name"], "local_name": tool["name"]}
            for entry in servers for tool in entry["tools"]
        ]
        with product(args.output, env) as (base, process):
            report["started"] = wait_for_product(base, process, args.startup_timeout)
            if report["started"]:
                inventory = request(base, "/api/capabilities/inventory")
                report["mcp_connectors"] = inventory["mcp_connectors"]
                report["tool_result"] = invoke(base)
                if args.scenario == "disconnect":
                    docker("stop", time_server)
                    report["after_disconnect"] = invoke(base)
                    report["restarted_implicitly"] = running(time_server)
                if args.model_env is not None:
                    try:
                        report["conversation"] = request(base, "/api/conversation/turn", {
                            "conversation_id": "toolathlon-" + uuid4().hex, "user_id": "toolathlon",
                            "messages": [{"role": "user", "content": QUESTION}],
                        }, timeout=90)
                    except HTTPError as error:
                        report["conversation_error"] = {"status": error.code, "detail": json.load(error)}
                    report["journal_model_actions"] = [
                        {
                            "request": str(path.relative_to(args.output)),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "actions": [
                                action["name"] for action in json.loads(
                                    path.read_text(encoding="utf-8")
                                )["action_definitions"]
                            ],
                        }
                        for path in model_request_paths(args.output)
                    ]
        report["process_exit_code"] = process.returncode
        report["server_running_after_product_exit"] = running(time_server)
        if failure:
            report["second_running_after_product_exit"] = running(second)
            expected = (
                "does not expose tool 'missing'" if args.scenario == "partial"
                else "Invalid or duplicate MCP tool name"
            )
            report["expected_startup_error"] = expected in (
                args.output / "web.log"
            ).read_text(encoding="utf-8")
        if args.scenario == "disconnect" and report["started"]:
            with product(args.output / "restart", env) as (base, restarted):
                report["restart_result"] = invoke(base) if wait_for_product(base, restarted, args.startup_timeout) else None
            report["server_running_after_restart_exit"] = running(time_server)


def converted_time_matches(result: dict) -> bool:
    if not result.get("ok"):
        return False
    try:
        target = json.loads(result["data"]["text"])["target"]
        local_time = datetime.fromisoformat(target["datetime"]).strftime("%H:%M")
        return target["timezone"] == "Asia/Tokyo" and local_time == ANSWER
    except (KeyError, TypeError, ValueError):
        return False


def passed(report: TimeRunReport) -> bool:
    if "environment_error" in report or report.get("server_running_after_product_exit") is not False:
        return False
    scenario = report["scenario"]
    if scenario in {"partial", "duplicate"}:
        return (
            report.get("started") is False
            and report.get("process_exit_code") not in {None, 0}
            and report.get("expected_startup_error") is True
            and report.get("second_running_after_product_exit") is False
        )
    if report.get("started") is not True or report.get("process_exit_code") != 0:
        return False
    result = report.get("tool_result", {})
    names = {item["local_tool_name"] for item in report.get("mcp_connectors", [])}
    if scenario == "unmapped":
        return not names and result.get("ok") is False
    if names != {TOOL} or not converted_time_matches(result):
        return False
    if scenario == "disconnect":
        return (
            report["after_disconnect"].get("ok") is False
            and report["restarted_implicitly"] is False
            and converted_time_matches(report.get("restart_result") or {})
            and report["server_running_after_restart_exit"] is False
        )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Toolathlon Time 真实 MCP 接线及生命周期验证")
    parser.add_argument("--scenario", choices=("read", "unmapped", "partial", "duplicate", "disconnect"), required=True)
    parser.add_argument("--time-image", required=True)
    parser.add_argument("--postgres-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-env", type=Path)
    parser.add_argument("--startup-timeout", type=float, default=300)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    if args.scenario == "disconnect":
        (args.output / "restart").mkdir()
    report: TimeRunReport = {"scenario": args.scenario, "toolathlon_revision": UPSTREAM_REVISION}
    try:
        run(args, report)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        report["environment_error"] = str(error)
    report["protocol_and_lifecycle_passed"] = passed(report)
    path = args.output / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "report.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "\n")
    print(f"{path} [{report['protocol_and_lifecycle_passed']}]")
    return 0 if report["protocol_and_lifecycle_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
