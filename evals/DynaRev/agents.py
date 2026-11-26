"""Drive the two production entry points while the public task is in flight."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import shutil
import subprocess
from time import monotonic, sleep
from uuid import uuid4

import httpx
from pydantic import BaseModel

from evals.conversation_http import product, stream_turn, turn_path, wait_for_product
from evals.run_deepseek_harness import CHECKOUT, sha256
from evals.Toolathlon.runner import container, postgres_url, product_environment
from personal_agent.adapters.web.routes.conversation import (
    ConversationTurnRequest, ConversationTurnSteerReceipt, ConversationTurnSteerRequest,
)
from personal_agent.application.conversation.service import submitted_turn_id
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

from .browser import BrowserEpisode, TOOL_DESCRIPTION, write_json

TIMEOUT = 600
OUTPUT_LIMIT = 32_768
DSH_REVISION = "2e39e70496aa02986ca6a820c5d497e816b69d7e"
CLI = CHECKOUT / "apps/cli/lib/bin.js"
HOST_ENV = ("Path", "PATH", "SystemRoot", "TEMP", "TMP", "COMSPEC", "APPDATA", "LOCALAPPDATA", "USERPROFILE")


class Terminal(BaseModel):
    session_id: str | None = None
    turn_id: str | None = None
    completed: bool = False
    answer: str = ""
    reason: str


def personal_agent(episode: BrowserEpisode, endpoint: str, model_env: Path, postgres_image: str) -> Terminal:
    output = episode.directory
    auth = uuid4().hex
    session = f"dynarev-{uuid4().hex}"
    principal = AuthenticatedPrincipal(tenant_id="dynarev", user_id="pilot")
    turn_id = submitted_turn_id(principal, session, episode.task.instance_id)
    server = {
        "server_id": "dynarev", "transport": "http", "endpoint": endpoint, "timeout_seconds": 150,
        "tools": [{
            "name": "dynarev.browse", "remote_name": "browse", "description": TOOL_DESCRIPTION,
            "semantic_domains": ["web"], "resource_types": ["page"], "operations": ["read"],
            "trust_level": "scoped", "credential_mode": "none", "data_egress_class": "none",
            "attestation_status": "pinned", "freshness_profile": "realtime",
            "output_contract": "browser_observation", "evidence_contract": "provider_output",
            "failure_semantics": "typed_failure", "side_effects": ["read_local"],
            "max_retries": 0, "timeout_seconds": 150,
        }],
    }
    with container(postgres_image, "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=toolathlon",
                   "--tmpfs", "/var/lib/postgresql:rw,size=256m") as database:
        env = product_environment(output, postgres_url(database), [server], model_env)
        env.update(
            PERSONAL_AGENT_API_KEYS=json.dumps({auth: principal.model_dump(mode="json")}),
            PERSONAL_AGENT_WORKSPACE_CHANGES="",
            PERSONAL_AGENT_E2E_TRACE_DIR=str(output / "e2e"),
            PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR=str(output / "product"),
            PERSONAL_AGENT_CONVERSATION_TOOLS='{"enabled_groups":["conversation_control","skills","extensions"]}',
            PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS="100",
            PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS="100",
            PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS="1600000",
            PERSONAL_AGENT_INTERACTION_MAX_CONCURRENCY="1",
        )
        with product(
            output, env, sdk_directory=output / "sdk", turn_stopping_endpoint=episode.completion_endpoint,
        ) as (base, process):
            if not wait_for_product(base, process, 45):
                raise RuntimeError("PersonalAgent Web failed readiness")

            def send(revision):
                body = ConversationTurnSteerRequest(text=revision.content, client_request_id=revision.revision_id)
                response = httpx.post(base + turn_path(turn_id) + "/steer",
                                      json=body.model_dump(mode="json"),
                                      headers={"Authorization": f"Bearer {auth}"}, timeout=12)
                write_json(output / f"{revision.revision_id}.http.json",
                           {"status_code": response.status_code, "body": response.json()})
                if response.status_code != 202:
                    return {"accepted": False, "status": response.status_code, "detail": response.json().get("detail")}
                ack = ConversationTurnSteerReceipt.model_validate_json(response.content)
                return {"accepted": (ack.turn_id, ack.session_id, ack.client_request_id)
                        == (turn_id, session, revision.revision_id), "status": response.status_code,
                        "turn_id": ack.turn_id}

            episode.send = send
            request = ConversationTurnRequest(session_id=session, text=episode.task.i0,
                                              client_request_id=episode.task.instance_id, create_session=True)
            write_json(output / "initial-request.json", request.model_dump(mode="json"))
            return personal_terminal(base, request, auth, output)


def personal_terminal(base: str, request: ConversationTurnRequest, auth: str, output: Path) -> Terminal:
    turn_id = None
    terminal = Terminal(session_id=request.session_id, reason="no_terminal")
    with stream_turn(base, request, timeout=TIMEOUT, api_key=auth) as response:
        response.raise_for_status()
        with (output / "events.sse").open("w", encoding="utf-8") as stream:
            event = ""
            for line in response.iter_lines():
                stream.write(line + "\n")
                if line.startswith("event: "):
                    event = line[7:]
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])
                turn_id = data.get("turn_id", turn_id)
                if event == "error":
                    terminal = terminal.model_copy(update={"reason": str(data)})
                if event == "done":
                    terminal = Terminal(session_id=data["session_id"], turn_id=turn_id,
                                        completed=data["disposition"] == "answer", answer=data["answer"],
                                        reason=data["disposition"])
    if turn_id:
        trace = httpx.get(base + turn_path(turn_id), headers={"Authorization": f"Bearer {auth}"}, timeout=15)
        if trace.is_success:
            (output / "turn-trace.json").write_bytes(trace.content)
    return terminal.model_copy(update={"turn_id": turn_id})


def harness_profile(episode: BrowserEpisode, endpoint: str, values: Mapping[str, str | None]) -> Path:
    output = episode.directory
    hidden = (
        "typert-loader", "tool-bash", "tool-pwsh", "tool-fs", "tool-fs-search", "tool-jobs", "tool-web",
        "tool-subagent", "tool-subagent-fork", "tool-subagent-control", "tool-agent-team", "tool-plugin-manager",
        "tool-skill", "tool-workflow", "llm-deepseek",
    )
    capacity = json.loads(values.get("STRUCTURED_MODEL_CAPACITY") or "{}")
    model = values["STRUCTURED_MODEL"]
    profile = [{"id": key, "disabled": True} for key in hidden]
    profile.extend([
        {"id": "agent-default-model", "config": {"provider": "dyna-model", "model": model}},
        {"id": "session-persistence-jsonl", "config": {"root": (output / "sessions").as_posix(), "compression": "none"}},
        {"id": "llm-pi-ai", "config": {"providers": {"dyna-model": {
            "api": "openai-completions", "baseURL": values["STRUCTURED_BASE_URL"], "apiKeyEnv": "DYNAREV_MODEL_KEY",
            "reasoning": "medium", "retryPolicy": {"mode": "normal", "maxRetries": 2},
            "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": True},
            "models": [{"id": model, "contextWindow": capacity.get("context_window_tokens", 128_000),
                        "maxTokens": OUTPUT_LIMIT, "reasoningEfforts": {"medium": "medium"}}],
        }}}},
        {"insert": [
            {"id": "dyna-mcp", "name": "@deepseek-ai/dsh-mcp-client", "config": {
                "serverName": "dynarev", "transport": "streamable-http", "url": endpoint,
                "toolCallTimeoutMs": 150_000, "failOnStartupError": True, "toolLoading": "eager",
            }},
            {"id": "dyna-steering", "name": Path(__file__).with_name("steering.mjs").as_posix(), "config": {
                "mailbox": (output / "steering").as_posix(),
                "llmPath": (CHECKOUT / "packages/llm/llm/lib/index.js").as_posix(),
                "completionEndpoint": episode.completion_endpoint,
            }},
        ]},
    ])
    path = output / "cordis.json"
    write_json(path, profile)
    return path


def harness_delivery(episode: BrowserEpisode) -> str | None:
    logs = tuple((episode.directory / "sessions").rglob("session.v4.jsonl"))
    lines = logs[0].read_text(encoding="utf-8").splitlines() if len(logs) == 1 else ()
    events = [json.loads(line) for line in lines]
    start = next((event for event in events if event.get("type") == "turn/start"), None)
    turn = start["data"]["turn"] if start is not None else None
    end = next((event["seq"] for event in events if event.get("type") == "turn/end"
                and event["data"]["turn"] == turn), None)
    messages = [
        (event["seq"], block.get("text"))
        for event in events if start is not None and event.get("type") == "user/message"
        and start["seq"] < event["seq"] and (end is None or event["seq"] < end)
        and event["data"].get("source", {}).get("kind") == "user"
        for block in event["data"]["content"] if block.get("type") == "text"
    ]
    episode.delivered.clear()
    for revision, attempt in zip(episode.task.revisions, episode.attempts, strict=False):
        evidence = next((seq for seq, text in messages if text == revision.content), None)
        attempt["user_event_seq"] = evidence
        if attempt["accepted"] and evidence is not None:
            episode.delivered.append(revision.revision_id)
        elif attempt["accepted"]:
            attempt.update(accepted=False, status="not_consumed_in_original_turn")
    return str(turn) if turn is not None else None


def deepseek_harness(episode: BrowserEpisode, endpoint: str, values: Mapping[str, str | None]) -> Terminal:
    output = episode.directory
    revision = subprocess.check_output(("git", "-C", str(CHECKOUT), "rev-parse", "HEAD"), text=True).strip()
    node = shutil.which("node")
    if revision != DSH_REVISION or not CLI.is_file() or node is None:
        raise RuntimeError(f"Need a source-built DeepSeek Harness checkout at {DSH_REVISION}")
    profile = harness_profile(episode, endpoint, values)
    write_json(output / "harness-version.json", {"commit": revision, "cli_sha256": sha256(CLI)})
    workspace = output / "workspace"
    workspace.mkdir()
    mailbox = output / "steering"
    mailbox.mkdir()
    prompt = output / "initial-request.txt"
    prompt.write_text(episode.task.i0, encoding="utf-8")
    env = {key: os.environ[key] for key in HOST_ENV if key in os.environ}
    env.update(DSH_HOME=str(output / "home"), DYNAREV_MODEL_KEY=values["STRUCTURED_API_KEY"],
               DSH_TELEMETRY_DISABLED="1")

    def send(revision):
        pending = mailbox / f"{revision.revision_id}.pending"
        write_json(pending, {"text": revision.content})
        pending.rename(pending.with_suffix(".request"))
        receipt = pending.with_suffix(".receipt")
        deadline = monotonic() + 10
        while not receipt.exists() and monotonic() < deadline:
            sleep(0.05)
        return json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else {
            "accepted": False, "status": "steer_receipt_timeout",
        }

    episode.send = send
    result = output / "harness.jsonl"
    with prompt.open("rb") as source, result.open("wb") as stdout, (output / "harness.stderr").open("wb") as stderr:
        status = subprocess.run(
            [node, str(CLI), "--profile", "headless", "--patch", str(profile), "--json",
             "--permission-mode", "read-only", "--approval-policy", "never", "-"],
            cwd=workspace, env=env, stdin=source, stdout=stdout, stderr=stderr, timeout=TIMEOUT, check=False,
        )
    events = [json.loads(line) for line in result.read_text(encoding="utf-8").splitlines() if line.startswith("{")]
    terminal = next((event for event in reversed(events) if event.get("type") == "final"), None)
    turn = harness_delivery(episode)
    if terminal is None:
        return Terminal(turn_id=turn, reason=f"process_exit_{status.returncode}_without_final")
    reason = (terminal.get("reason") or {}).get("kind")
    return Terminal(session_id=terminal["sessionId"], turn_id=turn, completed=reason == "completed",
                    answer=terminal.get("text", ""), reason=reason or "missing_finish_reason")
