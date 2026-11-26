"""Run fresh sessions on the project Web app and official DeepSeek SDK."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel

from evals.conversation_http import WebSettingsSnapshot, product, submit_turn, turn_path, wait_for_product
from evals.deepseek_runtime import KEY_ENV, native_runtime
from evals.longDS.run_longds_harness import write_record
from evals.run_deepseek_harness import CHECKOUT, SDK_SOURCE
from evals.Toolathlon.runner import container, postgres_url, product_environment
from personal_agent.adapters.web.routes.conversation import ConversationTurnRequest, ConversationTurnResponse
from personal_agent.kernel.contracts.goal import ConversationGoalMode
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

from .data import Question
from .retrieval import DOCUMENT_DESCRIPTION, SEARCH_DESCRIPTION

STEPS = 40
TIMEOUT = 600
OUTPUT_LIMIT = 32_768
TOKEN_LIMIT = 2_000_000
PROVIDER = "browsecomp-model"
DSH_REVISION = "4b399c39a6d1479cd84ca591b4d7c88e24d38a96"
TOOLS = {"search": SEARCH_DESCRIPTION, "get_document": DOCUMENT_DESCRIPTION}


class ModelSettings(BaseModel):
    model: str
    base_url: str
    context_window: int

    @classmethod
    def from_env(cls, values: Mapping[str, str | None]) -> ModelSettings:
        model = values.get("STRUCTURED_MODEL")
        base_url = values.get("STRUCTURED_BASE_URL")
        if not model or not base_url or not urlsplit(base_url).hostname:
            raise ValueError("Expected STRUCTURED_MODEL and STRUCTURED_BASE_URL")
        capacity = json.loads(values.get("STRUCTURED_MODEL_CAPACITY") or "{}")
        return cls(model=model, base_url=base_url,
                   context_window=capacity.get("context_window_tokens", 128_000))


class Delivery(BaseModel):
    session_id: str | None = None
    answer: str = ""
    completed: bool = False
    reason: str
    model_steps: int | None = None
    tools_used: tuple[str, ...] = ()
    error: str | None = None


def product_mcp(port: int) -> dict:
    return {
        "server_id": "browsecomp", "endpoint": f"http://127.0.0.1:{port}/mcp",
        "timeout_seconds": 90,
        "tools": [
            {
                "name": f"browsecomp.{name}", "remote_name": name, "description": description,
                "semantic_domains": ["docs"], "resource_types": ["document"], "operations": ["read"],
                "trust_level": "scoped", "credential_mode": "none", "data_egress_class": "none",
                "attestation_status": "pinned", "freshness_profile": "static",
                "output_contract": "browsecomp_corpus", "evidence_contract": "provider_output",
                "failure_semantics": "typed_failure", "side_effects": ["read_local"],
                "timeout_seconds": 90,
            }
            for name, description in TOOLS.items()
        ],
    }


def personal(question: Question, output: Path, port: int, model_env: Path, model: ModelSettings) -> Delivery:
    auth = uuid4().hex
    session = f"browsecomp-{uuid4().hex}"
    principal = AuthenticatedPrincipal(tenant_id=session, user_id="solver")
    write_record(output / "mcp.json", product_mcp(port))
    with container("pgvector/pgvector:pg17", "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=toolathlon",
                   "--tmpfs", "/var/lib/postgresql:rw,size=256m") as database:
        env = product_environment(output, postgres_url(database), [product_mcp(port)], model_env)
        env.update(
            PERSONAL_AGENT_API_KEYS=json.dumps({auth: principal.model_dump(mode="json")}),
            PERSONAL_AGENT_CONVERSATION_GOAL_MODE=ConversationGoalMode.DISABLED.value,
            PERSONAL_AGENT_PROMPT_LANGUAGE="en",
            PERSONAL_AGENT_WORKSPACE_CHANGES="",
            PERSONAL_AGENT_POLICY_DENY_SCOPES="network:read",
            PERSONAL_AGENT_WEB_SEARCH_ALLOWED_DOMAINS="browsecomp-offline.invalid",
            PERSONAL_AGENT_E2E_TRACE_DIR=str(output / "e2e"),
            PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR=str(output / "product"),
            PERSONAL_AGENT_CONVERSATION_TOOLS='{"enabled_groups":["conversation_control","extensions"]}',
            PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS=str(STEPS),
            PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS="unlimited",
            PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS=str(TOKEN_LIMIT),
            PERSONAL_AGENT_INTERACTION_MAX_CONCURRENCY="1",
        )
        with product(output, env, sdk_directory=output / "sdk") as (base, process):
            if not wait_for_product(base, process, 60):
                raise RuntimeError("PersonalAgent Web exited before readiness")
            settings = WebSettingsSnapshot.model_validate_json((output / "web-settings.json").read_bytes())
            if settings.conversation_goal_mode != ConversationGoalMode.DISABLED:
                raise ValueError("The Web process did not disable Conversation Goal")
            if settings.budget.max_tool_calls is not None:
                raise ValueError("The Web process has an independent tool call limit")
            if (settings.structured.model, settings.structured.provider_host) != (model.model, urlsplit(model.base_url).hostname):
                raise ValueError("The Web process selected a different chat model")
            request = ConversationTurnRequest(session_id=session, text=question.query,
                                              client_request_id=question.query_id, create_session=True)
            write_record(output / "request.json", request.model_dump(mode="json"))
            written = submit_turn(base, request, timeout=TIMEOUT, api_key=auth).raise_for_status()
            (output / "turn-response.json").write_bytes(written.content)
            turn = ConversationTurnResponse.model_validate_json(written.content)
            response = httpx.get(base + turn_path(turn.turn_id), headers={"Authorization": f"Bearer {auth}"},
                                 timeout=30).raise_for_status()
            (output / "turn-trace.json").write_bytes(response.content)
    return personal_delivery(output)


def personal_delivery(output: Path) -> Delivery:
    request = ConversationTurnRequest.model_validate_json((output / "request.json").read_bytes())
    turn = ConversationTurnResponse.model_validate_json((output / "turn-response.json").read_bytes())
    if turn.session_id != request.session_id:
        raise ValueError("Conversation answered for the wrong session")
    requests = list((output / "sdk").glob("*.http.request.json"))
    inventories = [
        {tool["function"]["name"] for tool in json.loads(path.read_bytes()).get("tools", ())}
        for path in requests
    ]
    controls = {"control_working_plan", "control_request_clarification", "control_report_turn_status"}
    expected_prefixes = tuple(f"tool_browsecomp_{name}_" for name in TOOLS)
    has_retrieval = any(
        all(any(name.startswith(prefix) for name in inventory) for prefix in expected_prefixes)
        for inventory in inventories
    )
    unexpected = {name for inventory in inventories for name in inventory
                  if name not in controls and not name.startswith(expected_prefixes)}
    if not has_retrieval or unexpected:
        raise ValueError(f"Unexpected PersonalAgent tool inventory: retrieval={has_retrieval}, extra={unexpected}")
    return Delivery(session_id=turn.session_id, answer=turn.message.content, completed=turn.disposition == "answer",
                    reason=turn.disposition, model_steps=len(requests))


def write_harness_profile(directory: Path, port: int, model: ModelSettings) -> Path:
    directory.mkdir()
    step_limit = CHECKOUT.parents[1] / "longDS/harness_step_limit.mjs"
    (directory / "step-limit.mjs").write_bytes(step_limit.read_bytes())
    rows = [
        *({"id": name, "disabled": True} for name in (
            "llm-deepseek", "tool-fs", "tool-working-directory", "persistent-bash", "persistent-pwsh",
            "terminal-bash", "terminal-pwsh", "mcp-resources",
        )),
        {"id": "sessions", "config": {"root": "/dsh-records/sessions", "compression": "none"}},
        {"insert": [
            {"id": "llm-pi-ai", "name": "@deepseek-ai/dsh-llm-pi-ai", "config": {"providers": {PROVIDER: {
                "api": "openai-completions", "baseURL": model.base_url, "apiKeyEnv": KEY_ENV,
                "reasoning": "medium", "retryPolicy": {"mode": "normal", "maxRetries": 2},
                "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": True},
                "models": [{"id": model.model, "contextWindow": model.context_window,
                            "maxTokens": OUTPUT_LIMIT, "reasoningEfforts": {"medium": "medium"}}],
            }}}},
            {"id": "browsecomp-mcp", "name": "@deepseek-ai/dsh-mcp-client", "config": {
                "serverName": "browsecomp", "transport": "streamable-http",
                "url": f"http://host.docker.internal:{port}/mcp", "toolCallTimeoutMs": 90_000,
                "failOnStartupError": True, "toolLoading": "eager",
            }},
            {"id": "step-limit", "name": "/dsh-config/step-limit.mjs", "config": {"limit": STEPS}},
        ]},
    ]
    path = directory / "cordis.json"
    write_record(path, rows)
    return path


def harness(question: Question, output: Path, port: int, values: Mapping[str, str | None],
            model: ModelSettings, image: str) -> Delivery:
    revision = subprocess.check_output(
        ("git", "-C", str(CHECKOUT), "rev-parse", "HEAD"), text=True,
    ).strip()
    if revision != DSH_REVISION:
        raise ValueError(f"Expected DeepSeek SDK checkout {DSH_REVISION}, found {revision}")
    key = values.get("STRUCTURED_API_KEY")
    if not key:
        raise ValueError("Expected STRUCTURED_API_KEY")
    profile = write_harness_profile(output / "profile", port, model)
    workspace = output / "workspace"
    workspace.mkdir()
    write_record(output / "sdk-identity.json", {"source_revision": revision, "image": image})
    with native_runtime(
        output, profile, SDK_SOURCE, image=image, workspace="/workspace",
        mounts=(f"type=bind,source={workspace},target=/workspace,readonly",),
        provider=PROVIDER, model=model.model, provider_key=key,
        output_limit=OUTPUT_LIMIT, timeout=TIMEOUT, memory_mb=768,
    ) as (driver, container_name):
        subprocess.run(
            ("docker", "exec", container_name, "sh", "-ec", "test -z \"$(ls -A /workspace)\""),
            check=True, timeout=15,
        )
        session = driver.start_session(f"browsecomp-{uuid4().hex}")
        result = session.run(question.query)
        write_record(output / "turn.json", {
            "session_id": result.session_id, "events": result.events, "finish_reason": result.finish_reason,
        })
        inventories = [
            {tool["name"] for tool in event["data"]["header"]["tools"]}
            for event in result.events if event["type"] == "request/header"
        ]
        expected = {f"mcp__browsecomp__{name}" for name in TOOLS}
        if not inventories or any(inventory != expected for inventory in inventories):
            raise ValueError(f"Unexpected DeepSeek Harness tool inventory: {inventories}")
        return Delivery(
            session_id=result.session_id, answer=result.final_response or "",
            completed=result.finish_reason == "completed" and bool(result.final_response.strip()),
            reason=result.finish_reason or "no_terminal",
            model_steps=sum(event["type"] == "step/start" for event in result.events),
            tools_used=tuple(event["data"]["name"] for event in result.events if event["type"] == "tool/call"),
        )
