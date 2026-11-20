"""Run the two native entry points across the destination's committed-write barrier."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
from time import monotonic, perf_counter_ns
from typing import Any, Callable
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, Field

from evals.Toolathlon.runner import container as docker_container, postgres_url, product_environment
from evals.conversation_http import product, resume_turn, stream_turn, turn_path, wait_for_product
from evals.run_deepseek_harness import CHECKOUT, sha256
from personal_agent.adapters.web.routes.conversation import ConversationTurnRequest, ConversationTurnResponse

from .destination import DESCRIPTIONS, Destination, READ, WRITE

TIMEOUT = 120
OUTPUT_LIMIT = 32_768
DSH_REVISION = "2e39e70496aa02986ca6a820c5d497e816b69d7e"
DSH_CLI = CHECKOUT / "apps/cli/lib/bin.js"
CONTINUE = "请继续完成刚才的请求。"


class Recovery(BaseModel):
    session_id: str | None = None
    recovered_session_id: str | None = None
    turn_id: str | None = None
    recovered_turn_id: str | None = None
    first_pid: int | None = None
    recovered_pid: int | None = None
    first_exit: int | None = None
    write_committed_and_reply_held: bool = False
    stop_requested_ns: int | None = None
    exit_observed_ns: int | None = None
    recovered_ns: int | None = None
    final_outcomes: int = 0
    finish_reason: str | None = None
    answer: str = ""
    native: dict[str, Any] = Field(default_factory=dict)


class DshFinishReason(BaseModel):
    kind: str


class DshFinalEvent(BaseModel):
    sessionId: str
    reason: DshFinishReason | None
    text: str


def save(path: Path, value: BaseModel | dict[str, Any]) -> None:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def await_write(destination: Destination, poll: Callable[[], int | None]) -> None:
    deadline = monotonic() + TIMEOUT
    while monotonic() < deadline:
        if destination.committed.wait(0.1):
            if poll() is not None:
                raise RuntimeError("The agent exited before the injected fault")
            return
        if poll() is not None:
            raise RuntimeError("The agent exited before the first write")
    raise TimeoutError("The agent did not reach the committed-write barrier")


def interrupt(
    destination: Destination, recovery: Recovery, *, stop: Callable[[], None], poll: Callable[[], int | None],
) -> None:
    recovery.write_committed_and_reply_held = destination.committed.is_set() and not destination.release_reply.is_set()
    if not recovery.write_committed_and_reply_held:
        raise RuntimeError("The committed-write reply was not held at the fault")
    recovery.stop_requested_ns = perf_counter_ns()
    stop()
    code = poll()
    if code is None:
        raise RuntimeError("Expected the bound execution process to have exited")
    recovery.first_exit = code
    recovery.exit_observed_ns = perf_counter_ns()
    destination.release_reply.set()


def _server(endpoint: str) -> dict[str, Any]:
    return {
        "server_id": "durability", "transport": "http", "endpoint": endpoint, "timeout_seconds": TIMEOUT + 10,
        "tools": [
            {
                "name": f"durability.{name}", "remote_name": name, "description": description,
                "semantic_domains": ["workspace"], "resource_types": ["operation"],
                "operations": ["read" if name == READ else "create"],
                "trust_level": "scoped", "credential_mode": "none", "data_egress_class": "none",
                "attestation_status": "pinned", "freshness_profile": "realtime",
                "output_contract": "effect_receipt", "evidence_contract": "provider_output",
                "failure_semantics": "typed_failure", "side_effects": ["write_local" if name == WRITE else "read_local"],
                "max_retries": 0, "timeout_seconds": TIMEOUT + 10,
            }
            for name, description in DESCRIPTIONS.items()
        ],
    }


def _first_turn_id(lines: Iterator[str], session_id: str) -> str:
    for line in lines:
        if line.startswith("data: "):
            event = json.loads(line[6:])
            if event.get("session_id") == session_id and isinstance(event.get("turn_id"), str):
                return event["turn_id"]
            raise ValueError("Initial SSE event did not bind the requested session and turn")
    raise ValueError("No initial SSE event")


def personal_agent(
    destination: Destination, recovery: Recovery, endpoint: str, output: Path, question: str, model_env: Path,
    postgres_image: str,
) -> None:
    auth = uuid4().hex
    recovery.session_id = f"durability-{uuid4().hex}"
    request = ConversationTurnRequest(
        session_id=recovery.session_id, text=question, client_request_id="ambiguous-effect", create_session=True,
    )
    save(output / "initial-request.json", request)
    with docker_container(
        postgres_image, "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=toolathlon",
        "--tmpfs", "/var/lib/postgresql:rw,size=256m",
    ) as database:
        env = product_environment(output, postgres_url(database), [_server(endpoint)], model_env)
        env.update(
            PERSONAL_AGENT_API_KEYS=json.dumps({auth: {"tenant_id": "durability", "user_id": "pilot"}}),
            PERSONAL_AGENT_WORKSPACE_CHANGES="",
            PERSONAL_AGENT_E2E_TRACE_DIR=str(output / "e2e"),
            PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR=str(output / "product"),
        )
        with _web(output, env, "first") as (base, process):
            recovery.first_pid = process.identity.pid
            with stream_turn(base, request, timeout=TIMEOUT, api_key=auth) as stream:
                stream.raise_for_status()
                recovery.turn_id = _first_turn_id(stream.iter_lines(), recovery.session_id)
                await_write(destination, process.poll)
                interrupt(destination, recovery, stop=lambda: process.stop(deadline=monotonic() + 8), poll=process.poll)
        with _web(output, env, "restart") as (base, process):
            recovery.recovered_pid = process.identity.pid
            recovery.recovered_ns = perf_counter_ns()
            response = resume_turn(base, recovery.turn_id, timeout=TIMEOUT, api_key=auth)
            (output / "resume-response.json").write_bytes(response.content)
            recovery.native["resume_status"] = response.status_code
            response.raise_for_status()
            view = ConversationTurnResponse.model_validate_json(response.content)
            recovery.recovered_turn_id = view.turn_id
            recovery.recovered_session_id = view.session_id
            recovery.finish_reason = view.disposition
            recovery.final_outcomes = int(view.disposition == "answer")
            recovery.answer = view.message.content
            trace = httpx.get(base + turn_path(view.turn_id), headers={"Authorization": f"Bearer {auth}"}, timeout=10)
            if trace.is_success:
                (output / "turn-trace.json").write_bytes(trace.content)


@contextmanager
def _web(output: Path, env: dict[str, str], stage: str):
    boot = output / stage
    boot.mkdir()
    with product(boot, env, sdk_directory=boot / "sdk") as (base, process):
        if not wait_for_product(base, process, 45):
            raise RuntimeError(f"Product Web exited during {stage} startup")
        yield base, process


def _dsh_profile(output: Path, endpoint: str, values: dict[str, str | None]) -> Path:
    model = values["STRUCTURED_MODEL"]
    capacity = json.loads(values.get("STRUCTURED_MODEL_CAPACITY") or "{}")
    hidden = (
        "typert-loader", "tool-bash", "tool-pwsh", "tool-fs", "tool-fs-search", "tool-jobs", "tool-web",
        "tool-subagent", "tool-subagent-fork", "tool-subagent-control", "tool-agent-team", "tool-plugin-manager",
        "tool-skill", "tool-workflow", "llm-deepseek",
    )
    patch: list[dict[str, Any]] = [{"id": key, "disabled": True} for key in hidden]
    patch.extend((
        {"id": "agent-default-model", "config": {"provider": "durability-model", "model": model}},
        {"id": "session-persistence-jsonl", "config": {"root": (output / "sessions").as_posix(), "compression": "none"}},
        {"id": "llm-pi-ai", "config": {"providers": {"durability-model": {
            "api": "openai-completions", "baseURL": values["STRUCTURED_BASE_URL"], "apiKeyEnv": "ADL_MODEL_KEY",
            "reasoning": "medium", "retryPolicy": {"mode": "normal", "maxRetries": 2},
            "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": True},
            "models": [{"id": model, "contextWindow": capacity.get("context_window_tokens", 128_000),
                        "maxTokens": OUTPUT_LIMIT, "reasoningEfforts": {"medium": "medium"}}],
        }}}},
        {"insert": [{"id": "durability-mcp", "name": "@deepseek-ai/dsh-mcp-client", "config": {
            "serverName": "durability", "transport": "streamable-http", "url": endpoint,
            "toolCallTimeoutMs": (TIMEOUT + 10) * 1_000, "failOnStartupError": True, "toolLoading": "eager",
        }}]},
    ))
    path = output / "cordis.json"
    path.write_text(json.dumps(patch, indent=2) + "\n", encoding="utf-8")
    return path


def _dsh_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_bytes().rpartition(b"\n")[0].splitlines() if line.startswith(b"{")]


@contextmanager
def _dsh_process(
    output: Path, stage: str, command: list[str], env: dict[str, str], message: str, session_id: str | None = None,
):
    with ExitStack() as resources:
        input_path = output / f"{stage}-input.txt"
        input_path.write_text(message, encoding="utf-8")
        source = resources.enter_context(input_path.open("rb"))
        stdout = resources.enter_context((output / f"{stage}.jsonl").open("wb"))
        stderr = resources.enter_context((output / f"{stage}.stderr.log").open("wb"))
        binding = ["--session-id", session_id] if session_id else []
        process = subprocess.Popen(
            [*command, *binding, "-"], cwd=output / "workspace", env=env, stdin=source, stdout=stdout, stderr=stderr,
        )
        try:
            yield process
        finally:
            if process.poll() is None:
                _stop_node(process)


def _stop_node(process: subprocess.Popen) -> None:
    process.kill()
    process.wait(timeout=8)


def record_dsh_completion(output: Path, recovery: Recovery) -> None:
    terminal = [
        DshFinalEvent.model_validate(event) for event in _dsh_events(output / "restart.jsonl")
        if event.get("type") == "final"
    ]
    recovery.final_outcomes = sum(event.reason is not None and event.reason.kind == "completed" for event in terminal)
    if terminal:
        latest = terminal[-1]
        recovery.recovered_session_id = latest.sessionId
        recovery.finish_reason = latest.reason.kind if latest.reason else None
        recovery.answer = latest.text


def deepseek_harness(
    destination: Destination, recovery: Recovery, endpoint: str, output: Path, question: str, model_env: Path,
) -> None:
    node = shutil.which("node")
    if node is None or not DSH_CLI.is_file():
        raise RuntimeError("Build the shared DeepSeek Harness checkout before running")
    revision = subprocess.check_output(("git", "-C", str(CHECKOUT), "rev-parse", "HEAD"), text=True).strip()
    if revision != DSH_REVISION:
        raise RuntimeError(f"DeepSeek Harness checkout must be {DSH_REVISION}; found {revision}")
    values = dotenv_values(model_env)
    profile = _dsh_profile(output, endpoint, values)
    (output / "workspace").mkdir()
    key = values.get("STRUCTURED_API_KEY")
    if not key:
        raise RuntimeError("No configured structured model credential")
    env = {key: os.environ[key] for key in ("Path", "PATH", "SystemRoot", "TEMP", "TMP", "COMSPEC", "APPDATA",
                                           "LOCALAPPDATA", "USERPROFILE", "HOME") if key in os.environ}
    env.update(DSH_HOME=str(output / "home"), ADL_MODEL_KEY=key, DSH_TELEMETRY_DISABLED="1")
    recovery.native.update(revision=revision, cli_sha256=sha256(DSH_CLI), model=values["STRUCTURED_MODEL"],
                           profile_sha256=sha256(profile), max_output_tokens=OUTPUT_LIMIT)
    command = [node, str(DSH_CLI), "--profile", "headless", "--patch", str(profile), "--json",
               "--permission-mode", "read-only", "--approval-policy", "never"]
    with _dsh_process(output, "first", command, env, question) as process:
        recovery.first_pid = process.pid
        await_write(destination, process.poll)
        sessions = [event["sessionId"] for event in _dsh_events(output / "first.jsonl") if event.get("type") == "session"]
        if len(sessions) != 1:
            raise RuntimeError("DeepSeek Harness did not expose exactly one original session identity")
        recovery.session_id = sessions[0]
        interrupt(destination, recovery, stop=lambda: _stop_node(process), poll=process.poll)
    with _dsh_process(output, "restart", command, env, CONTINUE, recovery.session_id) as process:
        recovery.recovered_pid = process.pid
        recovery.recovered_ns = perf_counter_ns()
        recovery.native["resume_exit"] = process.wait(timeout=TIMEOUT)
    record_dsh_completion(output, recovery)
