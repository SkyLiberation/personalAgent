"""Conversation HTTP and DeepSeek SDK adapters for one continuous Marathon session."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from contextlib import contextmanager
import json
import tarfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values
import httpx
from pydantic import BaseModel, Field

from evals.conversation_http import product, stream_turn, turn_path, wait_for_product
from evals.deepseek_runtime import native_runtime, write_profile
from evals.longDS.retrieval_capture_audit import SdkResponseObservation
from evals.longDS.run_longds_harness import write_record
from evals.Toolathlon.runner import container, postgres_url, product_environment
from personal_agent.adapters.web.routes.conversation import ConversationTurnRequest
from personal_agent.application.bash_execution.models import (
    BashExecutionAuthorization,
    BashWorkspaceBinding,
)
from personal_agent.infra.bash_execution.deployment import BashExecutionDeploymentConfig
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


WORKSPACE = "/workspace/marathon/work"
WINDOW = 1_000_000
TURN_TIMEOUT = 1_500
MAX_STEPS = 100
MAX_OUTPUT = 32_768
TASK_TOKENS = 600_000_000
MEMORY_MB = 1024
PROVIDER = "marathon-minimax"


class Delivery(BaseModel):
    number: int
    answer: str = ""
    completed: bool = False
    reason: str = "no_terminal"
    terminal: bool = False
    model_requests: int = 0
    tokens: int = 0
    peak_input: int | None = None
    compaction_events: dict[str, int] = Field(default_factory=dict)


def extract_host_workspace(seed: Path, directory: Path) -> Path:
    directory.mkdir()
    with tarfile.open(seed, "r") as archive:
        archive.extractall(directory, filter="data")
    return directory / "work"


@contextmanager
def personal(
    output: Path,
    host_workspace: Path,
    model_env: Path,
    db_image: str,
    *,
    workspace: str = WORKSPACE,
    skill_root: Path | None = None,
    user_skill_home: Path | None = None,
    project_skill_root: Path | None = None,
    apply_benchmark_flags: bool = True,
):
    auth = uuid4().hex
    session_id = f"marathon-{uuid4().hex}"
    principal = AuthenticatedPrincipal(tenant_id=session_id, user_id="solver")
    authorization = BashExecutionAuthorization(
        authorized_principal=principal,
        conversation_id=session_id,
        turn_timeout_seconds=TURN_TIMEOUT,
        max_total_tokens=TASK_TOKENS,
        max_execution_seconds=212 * TURN_TIMEOUT,
        allow_network=False,
        hidden_directories=(Path(__file__).resolve().parents[2], output.parent.resolve()),
        workspace=BashWorkspaceBinding(
            mcp_server_id="marathon-files",
            host_path=host_workspace,
            root=workspace,
        ),
    )
    deployment = output / "bash-deployment.json"
    deployment.write_text(
        BashExecutionDeploymentConfig(
            authorization=authorization,
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    with container(
        db_image,
        "-p",
        "127.0.0.1::5432",
        "-e",
        "POSTGRES_PASSWORD=toolathlon",
        "--tmpfs",
        "/var/lib/postgresql:rw,size=256m",
    ) as database:
        env = product_environment(
            output,
            postgres_url(database),
            [
                {
                    "server_id": "marathon-files",
                    "endpoint": "http://127.0.0.1:1",
                    "tools": [],
                },
            ],
            model_env,
            bash_deployment=deployment,
            apply_benchmark_flags=apply_benchmark_flags,
        )
        for name in (
            "MODEL",
            "PROVIDER",
            "BASE_URL",
            "API_KEY",
            "MODEL_CAPACITY",
            "EXTRA_BODY",
        ):
            if value := env.get("STRUCTURED_" + name):
                env["OPENAI_" + name] = value
        env.update(
            PERSONAL_AGENT_API_KEYS=json.dumps(
                {auth: principal.model_dump(mode="json")}
            ),
            PERSONAL_AGENT_PROMPT_LANGUAGE="en",
            PERSONAL_AGENT_WORKSPACE_CHANGES="",
            PERSONAL_AGENT_WEB_SEARCH_ALLOWED_DOMAINS="marathon-offline.invalid",
            PERSONAL_AGENT_POLICY_DENY_SCOPES="network:read",
            PERSONAL_AGENT_CONVERSATION_TOOLS='{"enabled_groups":["bash","conversation_control"]}',
            PERSONAL_AGENT_E2E_TRACE_DIR=str(output / "e2e"),
            PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR=str(output / "evidence"),
            PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS=str(MAX_STEPS),
            PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS=str(MAX_STEPS),
            PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS="10000000",
            PERSONAL_AGENT_INTERACTION_MAX_CONCURRENCY="1",
        )
        env.pop("PERSONAL_AGENT_SKILL_ROOT", None)
        env.pop("PERSONAL_AGENT_SKILL_SCOPES", None)
        if skill_root is not None:
            env["PERSONAL_AGENT_SKILL_ROOT"] = str(skill_root)
        if user_skill_home or project_skill_root:
            identity = principal.model_dump(mode="json")
            env["PERSONAL_AGENT_SKILL_SCOPES"] = json.dumps({
                "users": [{"principal": identity, "home": str(user_skill_home)}] if user_skill_home else [],
                "projects": [{"principal": identity, "session_id": session_id,
                              "root": str(project_skill_root)}] if project_skill_root else [],
            })
        if skill_root or user_skill_home or project_skill_root:
            env["PERSONAL_AGENT_CONVERSATION_TOOLS"] = json.dumps(
                {"enabled_groups": ["bash", "conversation_control", "skills"]}
            )
        with product(output, env, sdk_directory=output / "sdk") as (base, process):
            if not wait_for_product(base, process, 60):
                raise RuntimeError("Conversation Web failed readiness; see web.log")
            seen: set[Path] = set()
            sent: set[Path] = set()
            summaries: set[str] = set()
            pruning: set[tuple[str, int]] = set()

            def submit(number: int, prompt: str) -> Delivery:
                delivery = personal_turn(output, base, auth, session_id, number, prompt)
                responses = set((output / "sdk").glob("*.candidate.response.json"))
                usage = []
                for path in responses - seen:
                    item = SdkResponseObservation.model_validate_json(path.read_bytes())
                    if item.completed and item.response and item.response.usage:
                        usage.append(item.response.usage)
                seen.update(responses)
                requests = set((output / "sdk").glob("*.http.request.json"))
                delivery.model_requests = len(requests - sent)
                sent.update(requests)
                delivery.tokens = sum(item.known_tokens for item in usage)
                delivery.peak_input = max(
                    (u.prompt_tokens for u in usage if u.prompt_tokens is not None),
                    default=None,
                )
                trace = output / f"turn-{number:03}.trace.json"
                if trace.is_file():
                    value = json.loads(trace.read_bytes())
                    summary = value.get("history_compaction")
                    if summary and summary["snapshot_digest"] not in summaries:
                        summaries.add(summary["snapshot_digest"])
                        delivery.compaction_events["history_compaction"] = 1
                    boundaries = {
                        (item["run_ref"], item["through_step"])
                        for item in value.get("history_tool_pruning", [])
                    }
                    if new := boundaries - pruning:
                        delivery.compaction_events["history_tool_pruning"] = len(new)
                        pruning.update(new)
                return delivery

            yield submit


def personal_turn(
    output: Path, base: str, auth: str, session: str, number: int, prompt: str
) -> Delivery:
    prefix = output / f"turn-{number:03}"
    request = ConversationTurnRequest(
        session_id=session,
        text=prompt,
        client_request_id=f"marathon-{number}",
        create_session=number == 1,
    )
    write_record(prefix.with_suffix(".request.json"), request.model_dump(mode="json"))
    delivery = Delivery(number=number)
    turn_id = None
    with stream_turn(base, request, timeout=TURN_TIMEOUT, api_key=auth) as response:
        response.raise_for_status()
        with prefix.with_suffix(".sse").open("w", encoding="utf-8") as log:
            event = ""
            for line in response.iter_lines():
                log.write(line + "\n")
                if line.startswith("event: "):
                    event = line[7:]
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])
                turn_id = data.get("turn_id", turn_id)
                if event == "done":
                    if data["session_id"] != session:
                        raise ValueError("Web response changed the Marathon session")
                    delivery = Delivery(
                        number=number,
                        terminal=True,
                        completed=data["disposition"] == "answer",
                        answer=data["answer"],
                        reason=data["disposition"],
                    )
                elif event == "error":
                    delivery.reason = str(data)
    if turn_id:
        trace = httpx.get(
            base + turn_path(turn_id),
            headers={"Authorization": f"Bearer {auth}"},
            timeout=60,
        )
        trace.raise_for_status()
        prefix.with_suffix(".trace.json").write_bytes(trace.content)
    return delivery


def harness_usage(events: Iterable[dict]) -> tuple[int, int | None]:
    """Read true provider usage from native assistant settlements and summaries."""
    inputs: list[int] = []
    total = 0
    for event in events:
        kind = event["type"]
        if kind not in {"assistant/message", "assistant/attempt", "compaction/summary"}:
            continue
        data = event.get("data") or {}
        usage = data.get("usage")
        if usage is None and kind in {"assistant/message", "assistant/attempt"}:
            for record in reversed(data.get("stream", [])):
                chunk = record.get("chunk", record)
                if chunk.get("type") == "usage":
                    usage = chunk.get("usage")
                    break
        if not usage:
            continue
        context = sum(
            usage.get(k, 0) or 0
            for k in ("inputTokens", "cacheReadTokens", "cacheWriteTokens")
        )
        inputs.append(context)
        total += usage.get("totalTokens") or (
            context + (usage.get("outputTokens") or 0)
        )
    return total, max(inputs, default=None)


@contextmanager
def harness(
    output: Path, image: str, sdk_source: Path, model_env: Path, volume: str,
    *, workspace: str = WORKSPACE, skill_root: Path | None = None,
):
    env = dotenv_values(model_env)
    base_url, model, key = (
        env.get(f"STRUCTURED_{name}") for name in ("BASE_URL", "MODEL", "API_KEY")
    )
    if not base_url or not model or not key or not urlsplit(base_url).hostname:
        raise ValueError(
            "The model file must supply STRUCTURED_BASE_URL, STRUCTURED_MODEL and STRUCTURED_API_KEY"
        )
    profile = write_profile(
        output / "profile", workspace=workspace, provider=PROVIDER, model=model, base_url=base_url,
        persona=f"You are a coding assistant. Use Bash in {workspace} to do the user's work.",
        window=WINDOW, output_limit=MAX_OUTPUT, step_limit=MAX_STEPS, skill=skill_root is not None,
        file_tools=False,
    )
    mount_root = workspace.rsplit("/", 1)[0]
    mounts = [f"type=volume,source={volume},target={mount_root},volume-nocopy"]
    if skill_root is not None:
        mounts.append(f"type=bind,source={skill_root},target=/dsh-skills,readonly")
    with native_runtime(
        output, profile, sdk_source / "python/sdk/src", image=image, workspace=workspace,
        mounts=tuple(mounts), provider=PROVIDER, model=model, provider_key=key,
        output_limit=MAX_OUTPUT, timeout=TURN_TIMEOUT, memory_mb=MEMORY_MB,
    ) as (driver, sandbox):
        session = driver.start_session(f"marathon-{uuid4().hex}")

        def submit(number: int, prompt: str) -> Delivery:
            result = session.run(prompt)
            counts = Counter(event["type"] for event in result.events)
            tokens, peak = harness_usage(result.events)
            write_record(
                output / f"turn-{number:03}.json",
                {
                    "session_id": result.session_id,
                    "events": result.events,
                    "finish_reason": result.finish_reason,
                },
            )
            return Delivery(
                number=number,
                answer=result.final_response or "",
                completed=result.finish_reason == "completed"
                and bool(result.final_response.strip()),
                reason=result.finish_reason or "no_terminal",
                terminal=bool(result.finish_reason),
                model_requests=counts["step/start"],
                tokens=tokens,
                peak_input=peak,
                compaction_events={k: v for k, v in counts.items() if "compact" in k},
            )

        yield submit, sandbox
