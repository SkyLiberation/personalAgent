"""Freeze and run the complete LongDS turn-14 generation stage.

--prepare invokes no model. --run requires a frozen, ready preparation and
consumes actual model choices through the production service and gateway.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from importlib.metadata import version
import json
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from time import monotonic
from typing import Literal, TypedDict
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
from zipfile import ZipFile

ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / "pyproject.toml").is_file() and (parent / "src/personal_agent").is_dir())
TOPIC = ROOT / ".tmp/loop-schema-redesign-20261024"
SOURCE = ROOT / ".tmp/usage-nonblocking-longds-20261024/l2-prefix-17"


def bind_launch_imports() -> Path:
    """A frozen copy must bind its selected source before importing packages."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--groups", default="both")
    for flag in ("--probe-source-root", "--materialize-source-root", "--execute-source-root"):
        parser.add_argument(flag, type=Path)
    early, _ = parser.parse_known_args()
    selected = early.probe_source_root or early.materialize_source_root or early.execute_source_root
    preparation = early.run or early.preflight
    if selected is None and preparation is not None:
        prepared = json.loads(preparation.read_bytes())
        selected = Path(prepared["baseline_code_root"] if early.groups == "baseline" else prepared["candidate_code_root"])
    selected = (selected or ROOT).resolve()
    if selected not in (ROOT.resolve(), (TOPIC / "baseline-code").resolve()):
        raise ValueError("启动源码不是本任务冻结的baseline或candidate根")
    sys.path.insert(0, str(selected))
    sys.path.insert(0, str(selected / "src"))
    return selected


LAUNCH_SOURCE_ROOT = bind_launch_imports()

from pydantic import BaseModel, ConfigDict, Field
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


class FrozenFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)


class HistoricalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_ref: str
    turn_index: int
    call_ids: tuple[str, ...]
    sdk_candidates: tuple[str, ...]
    control_operations: tuple[str, ...]
    protocol_exchange_count: int


class DatabaseTableFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    table: Literal["tool_idempotency_ledger", "tool_audit_events", "tool_policy_decisions"]
    rows: tuple[dict[str, object], ...]  # PostgreSQL-owned opaque row JSON.


class DatabaseFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    principal: AuthenticatedPrincipal
    conversation_id: str
    observed_at: datetime
    role_can_create_database: bool
    scoped_row_counts: dict[str, int]
    tables: tuple[DatabaseTableFixture, ...]
    source_database_identity_sha256: str
    business_rows: Literal[0] = 0


class StageClock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    anchor: datetime
    original_deadline: datetime
    original_wall_seconds_at_input: float
    start_boundary: Literal["first_actual_model_request"] = "first_actual_model_request"
    datetime_modules: tuple[str, ...] = (
        "personal_agent.application.conversation.service",
        "personal_agent.application.conversation.interaction_intent",
        "personal_agent.infra.python_execution.sandbox",
    )
    python_clock_parameter: str = "PythonExecutionService.__init__.clock"
    real_wallclock_reported_separately: Literal[True] = True
    production_clock_changed: Literal[False] = False


class Preparation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_class: Literal["offline_real_stage_preparation"] = "offline_real_stage_preparation"
    execution_ready: bool = False
    model_calls: Literal[0] = 0
    tool_executions: Literal[0] = 0
    planned_journeys_per_group: Literal[10] = 10
    prepared_groups: tuple[Literal["baseline", "candidate"], ...]
    known_token_limit: int = Field(default=60_000_000, strict=True, gt=0, le=60_000_000)
    wall_seconds: float = Field(default=129600, gt=0, le=129600, allow_inf_nan=False)
    source_run: str
    source_checkpoint: FrozenFile
    inventory: FrozenFile
    baseline_archive: FrozenFile
    baseline_code_root: str
    baseline_code_sha256: str
    candidate_code_root: str
    candidate_code_sha256: str
    candidate_source_hashes: dict[str, str]
    interpreter: str
    runtime_versions: dict[str, str]
    source_files: tuple[FrozenFile, ...]
    stage_clock: StageClock
    original_initial_budget: dict[str, int | float]
    original_configuration: dict[str, object]
    known_tokens_before_stage: int
    task_token_limit: int
    same_conversation_runs: int
    historical_decisions: tuple[HistoricalDecision, ...]
    active_python_candidate: str
    baseline_probe: dict[str, object]
    candidate_probe: dict[str, object]
    materialization: dict[str, dict[str, object]]
    database_fixture: FrozenFile
    launch_probe: FrozenFile | None = None
    reused_preparation: FrozenFile | None = None
    short_execution_root: str
    blockers: tuple[str, ...]
    limitation: str


class PreflightCaptured(BaseException):
    """The actual production request was materialized; no response is invented."""


class StageSeed(TypedDict):
    known_tokens: int
    run_count: int
    changes: list[dict[str, str | int]]
    original_trace_hashes: dict[str, str]
    active_decisions: int
    active_call_ids: tuple[str, ...]
    active_known_tokens: int
    initial_input_count: int


class ReplayClock:
    def __init__(self, anchor: datetime):
        self.anchor = anchor
        self.started: float | None = None

    def now(self, zone=UTC):
        elapsed = 0 if self.started is None else monotonic() - self.started
        return (self.anchor + timedelta(seconds=elapsed)).astimezone(zone)

    def start(self):
        if self.started is None:
            self.started = monotonic()


def bind_stage_clock(clock: ReplayClock) -> None:
    """Bind only the explicitly declared Offline environment clock owners."""
    import personal_agent.application.conversation.service as conversation
    import personal_agent.application.conversation.interaction_intent as intent
    import personal_agent.infra.python_execution.sandbox as sandbox
    from personal_agent.application.python_execution.service import PythonExecutionService

    class ReplayDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock.now(tz or UTC)
            return value if tz is not None else value.replace(tzinfo=None)

    conversation.datetime = ReplayDateTime
    intent.datetime = ReplayDateTime
    sandbox.datetime = ReplayDateTime
    original = PythonExecutionService.__init__

    def clock_bound_init(self, *args, **kwargs):
        kwargs.setdefault("clock", clock.now)
        original(self, *args, **kwargs)

    PythonExecutionService.__init__ = clock_bound_init


def seed_stage(group: str, data: Path, checkpoint_index: Path) -> StageSeed:
    """Project only completed historical decisions out of the active new Journal."""
    from pydantic import BaseModel
    from personal_agent.application.conversation.journal import FileInteractionJournal
    from personal_agent.application.conversation.models import InteractionTrace

    data.mkdir(parents=True, exist_ok=False)
    for name in ("uploads", "generated_artifacts"):
        shutil.copytree(SOURCE / "server-data" / name, data / name)
    heads = [Path(path) for path in load(checkpoint_index)]
    active_path = next(path for path in heads if path.name == "0010.json")
    active = load(active_path)
    journal = FileInteractionJournal(data / "interaction_runs")
    original_archive = data / "historical_originals"
    original_archive.mkdir()
    changes = []
    for path in heads:
        original = load(path)
        (original_archive / f"{original['interaction_run_ref']}.json").write_bytes(path.read_bytes())
        projected = dict(original)
        if group == "candidate" and path != active_path:
            if original["final_message"] is None:
                raise ValueError("只允许投影已完成历史run的旧模型控制记录")
            projected["model_decisions"] = []
            changes.append({"run_ref": original["interaction_run_ref"],
                            "field": "model_decisions", "original_records": len(original["model_decisions"]),
                            "origin_sha256": sha256(path.read_bytes()).hexdigest()})
        if group == "candidate" and path == active_path:
            from personal_agent.application.conversation.models import (
                ModelDecisionRecord, ModelRequestReference, ModelResponseReference, StoredModelRequest,
            )
            from personal_agent.capabilities.contracts.model import (
                ModelActionDefinition, ModelResponseRecord, StructuredModelRequest, sealed_context_projection_ref,
            )
            from personal_agent.application.python_execution.models import canonical_digest

            candidate_id = "c1b4b743a20e47b490863eab6279d717"
            captured = load(SOURCE / "sdk" / f"{candidate_id}.candidate.response.json")
            wire = load(SOURCE / "sdk" / f"{candidate_id}.candidate.request.json")
            expected_http = {key: value for key, value in wire.items() if key != "extra_body"}
            expected_http.update(wire.get("extra_body") or {})
            matching = [file for file in (SOURCE / "sdk").glob("*.http.request.json")
                        if load(file) == expected_http]
            if len(matching) != 1:
                raise ValueError("原Python模型响应的实际HTTP发送不能唯一定位")
            http = load(matching[0].with_name(matching[0].name.replace(".request.", ".response.")))
            definitions = []
            for item in wire["tools"]:
                function = item["function"]
                name = function["name"]
                if name == "control_prepare_final":
                    # A consumed historical metadata projection, never a resend.
                    # Its complete original 19-tool wire stays in historical-sdk.
                    continue
                kind = ("working_plan" if name == "control_working_plan" else
                        "agent" if name.startswith("agent_") else "tool")
                definitions.append(ModelActionDefinition(name=name, kind=kind, target_name=name.split("_", 1)[1],
                    description=function["description"], input_schema=function["parameters"], strict=function["strict"]))
            old = original["model_decisions"][0]
            request = StructuredModelRequest(operation=captured["operation"],
                version=original["context_composition"][0]["prompt_version"], messages=wire["messages"],
                output_type=BaseModel, kind="tool_calling", action_definitions=tuple(definitions),
                action_choice=wire["tool_choice"], max_tokens=wire["max_completion_tokens"],
                context_projection_ref=sealed_context_projection_ref(
                    purpose="agent_interaction_turn", messages=wire["messages"]),
                metadata={"component": "conversation_interaction_loop", "prompt_name": "conversation.action"})
            stored = StoredModelRequest.from_request(request)
            stored_text = stored.model_dump_json()
            observed = ModelResponseRecord.from_payload_json(invocation_id=candidate_id,
                attempt_id=http["transport"]["attempt_id"], operation=captured["operation"],
                request_digest=stored.request_digest, context_projection_ref=stored.context_projection_ref,
                provider_host=http["provider_host"], requested_model=wire["model"],
                payload_json=json.dumps(captured["response"], ensure_ascii=False),
                latency_ms=captured["wall_seconds"] * 1000)
            if without_nulls(observed.assistant_message.payload) != without_nulls(old["assistant"]["payload"]):
                raise ValueError("当前0010完整assistant不是该SDK实际响应")
            journal._write_request_original(original["interaction_run_ref"], candidate_id, stored_text)
            response_text = observed.model_dump_json()
            journal._write_response_original(original["interaction_run_ref"], candidate_id, 0,
                                             observed.attempt_id, response_text)
            reference = ModelRequestReference(invocation_id=candidate_id, operation=request.operation,
                consumer_key=stored.consumer_key,
                request_digest=stored.request_digest, content_digest=sha256(stored_text.encode()).hexdigest(),
                context_projection_ref=stored.context_projection_ref, output_type_name=stored.output_type_name,
                output_schema_digest=(canonical_digest(stored.output_schema) if stored.output_schema is not None else None),
                max_output_repairs=stored.max_output_repairs,
                kind=stored.kind)
            record = ModelDecisionRecord(invocation_id=candidate_id, operation=request.operation, request=reference,
                turn_index=old["turn_index"], input_start=old["input_start"],
                response_refs=(ModelResponseReference(invocation_id=candidate_id, attempt_id=observed.attempt_id,
                    sequence=0, content_digest=sha256(response_text.encode()).hexdigest()),),
                assistant=observed.assistant_message, protocol_exchanges=old["protocol_exchanges"],
                dispositions=old["dispositions"], blocked_by=old["blocked_by"], status="decoded", consumed=True)
            projected["model_decisions"] = [record.model_dump(mode="json")]
            changes.append({"run_ref": original["interaction_run_ref"], "field": "model_decisions",
                "adaptation": "same actual Python assistant; SDK originals and typed immutable references",
                "historical_wire_tools": len(wire["tools"]), "typed_consumed_request_tools": len(definitions),
                "metadata_projection": "remove unselected retired control_prepare_final; no resend compatibility claim",
                "sdk_candidate": candidate_id, "source_request_sha256": frozen(
                    SOURCE / "sdk" / f"{candidate_id}.candidate.request.json").sha256})
        validated = InteractionTrace.model_validate(projected)
        serialized = validated.model_dump(mode="json")
        if any(serialized[name] != value for name, value in original.items() if name != "model_decisions"):
            raise ValueError("只读历史投影改动了usage/执行/来源/messages/Final等原始事实")
        directory = data / "interaction_runs" / validated.interaction_run_ref
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{validated.revision:04}.json").write_text(validated.model_dump_json(indent=2), encoding="utf-8")
    restored = journal.get(active["interaction_run_ref"])
    known = journal.conversation_usage(restored).total_tokens
    if known != 14_613_580 or journal.execution_budget(restored).unsettled_action_ids:
        raise ValueError("阶段历史累计消费或已结算执行事实不同")
    return {"known_tokens": known, "run_count": len(heads), "changes": changes,
            "original_trace_hashes": {path.name: sha256(path.read_bytes()).hexdigest()
                                      for path in sorted(original_archive.iterdir())},
            "active_decisions": len(restored.model_decisions),
            "active_call_ids": restored.model_decisions[0].assistant.call_ids,
            "active_known_tokens": restored.usage.total_tokens, "initial_input_count": len(restored.inputs)}


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def frozen(path: Path) -> FrozenFile:
    raw = path.read_bytes()
    return FrozenFile(path=str(path.resolve()), sha256=sha256(raw).hexdigest(), bytes=len(raw))


def load(path: Path):
    return json.loads(path.read_bytes())


def freeze_database_fixture(path: Path, checkpoint_index: Path) -> DatabaseFixture:
    import psycopg
    from psycopg import sql
    from personal_agent.kernel.config import Settings
    from evals.product_baselines.run_longds import _environment

    heads = [load(Path(item)) for item in load(checkpoint_index)]
    active = next(item for item in heads if item["final_message"] is None)
    principal = AuthenticatedPrincipal.model_validate(active["principal"])
    env = _environment(Settings.from_env(), path.parent, principal=principal, api_key="offline-preparation", port=0,
                       authorization_file=SOURCE / "python-deployment.json")
    tables = []
    counts = {}
    governed = {"tool_idempotency_ledger", "tool_audit_events", "tool_policy_decisions"}
    with psycopg.connect(env["PERSONAL_AGENT_POSTGRES_URL"], autocommit=True) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        allowed = connection.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]
        identity = connection.execute("SELECT current_database(), inet_server_addr()::text, inet_server_port()").fetchone()
        columns = {}
        for table, column in connection.execute(
                "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"):
            columns.setdefault(table, set()).add(column)
        for table, names in sorted(columns.items()):
            if "owner_id" in names:
                where = sql.SQL("owner_id::text = %s")
                parameters = (principal.principal_id,)
            elif "thread_id" in names:
                if "run_id" in names:
                    where = sql.SQL("thread_id::text = %s OR run_id::text = ANY(%s)")
                    parameters = (active["conversation_id"], [item["interaction_run_ref"] for item in heads])
                else:
                    where = sql.SQL("thread_id::text = %s")
                    parameters = (active["conversation_id"],)
            elif "run_id" in names:
                where = sql.SQL("run_id::text = ANY(%s)")
                parameters = ([item["interaction_run_ref"] for item in heads],)
            elif "user_id" in names:
                where = sql.SQL("user_id::text = %s")
                parameters = (principal.user_id,)
            else:
                continue
            records = [row[0] for row in connection.execute(sql.SQL(
                "SELECT to_jsonb(k) FROM {} k WHERE {}").format(sql.Identifier("public", table), where), parameters)]
            counts[table] = len(records)
            if table in governed:
                tables.append(DatabaseTableFixture(table=table, rows=tuple(records)))
            elif records:
                raise ValueError(f"发现尚未恢复的同scope持久业务事实：{table}；禁止空库替代")
    if not allowed:
        raise PermissionError("当前本机PG角色没有CREATE DATABASE权限")
    fixture = DatabaseFixture(principal=principal, conversation_id=active["conversation_id"], observed_at=datetime.now(UTC),
        role_can_create_database=allowed, scoped_row_counts=counts, tables=tuple(tables),
        source_database_identity_sha256=sha256(json_bytes(identity)).hexdigest())
    path.write_text(fixture.model_dump_json(indent=2), encoding="utf-8")
    return fixture


def isolate_database(env: dict[str, str], fixture_path: Path) -> dict[str, str]:
    import psycopg
    from psycopg import sql

    fixture = DatabaseFixture.model_validate(load(fixture_path))
    if not fixture.role_can_create_database:
        raise PermissionError("准备时未取得创建独立evaluation database的权限证据")
    source_url = env["PERSONAL_AGENT_POSTGRES_URL"]
    name = "loop_p1_" + uuid4().hex[:20]
    with psycopg.connect(source_url, autocommit=True) as connection:
        allowed = connection.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]
        if not allowed:
            raise PermissionError("实际执行角色无创建本实验数据库的权限")
        if connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            raise ValueError("本实验新数据库名称已存在，禁止覆盖或复用")
        connection.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    parsed = urlsplit(source_url)
    env["PERSONAL_AGENT_POSTGRES_URL"] = urlunsplit((parsed.scheme, parsed.netloc, "/" + name, parsed.query, ""))
    env["LOOP_SCHEMA_DATABASE_FIXTURE"] = str(fixture_path)
    env["LOOP_SCHEMA_DATABASE_NAME"] = name
    return {"name": name, "host": parsed.hostname, "port": parsed.port,
            "new_database": True, "original_database_changed": False, "fixture_sha256": frozen(fixture_path).sha256}


def restore_governance_fixture(service, path: Path) -> None:
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb

    fixture = DatabaseFixture.model_validate(load(path))
    store = service.tool_governance_store
    store.ensure_schema()
    with psycopg.connect(store.postgres_url) as connection:
        for table in fixture.tables:
            if connection.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table.table))).fetchone()[0]:
                raise ValueError("本样本治理账本不是新库空表，禁止覆盖")
            for row in table.rows:
                connection.execute(sql.SQL("INSERT INTO {} SELECT * FROM jsonb_populate_record(NULL::{}, %s)").format(
                    sql.Identifier(table.table), sql.Identifier(table.table)), (Jsonb(row),))
            if table.table in {"tool_audit_events", "tool_policy_decisions"}:
                sequence = connection.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table.table,)).fetchone()[0]
                if sequence and table.rows:
                    highest = max(int(row["id"]) for row in table.rows)
                    connection.execute("SELECT setval(%s, %s, true)", (sequence, highest))


def code_identity(root: Path) -> tuple[str, dict[str, str]]:
    hashes = {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
              for path in sorted((root / "src").rglob("*.py"))}
    if not hashes:
        raise ValueError("源代码身份没有生产 Python 文件")
    return sha256(json_bytes(hashes)).hexdigest(), hashes


def extract_baseline(archive: Path, destination: Path) -> None:
    """Extract only into this task's fixed engineering isolation directory."""
    allowed = (TOPIC / "baseline-code").resolve()
    if destination.resolve() != allowed:
        raise ValueError("baseline代码只可解压到本专题独占baseline-code目录")
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive) as zipped:
        for entry in zipped.infolist():
            relative = PurePosixPath(entry.filename)
            target = destination.joinpath(*relative.parts).resolve()
            if (relative.is_absolute() or ".." in relative.parts
                    or not target.is_relative_to(allowed)
                    or ((entry.external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError("baseline代码快照含越界路径或符号链接")
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            original = zipped.read(entry)
            if target.exists():
                if target.read_bytes() != original:
                    raise ValueError(f"已有baseline工程文件不同：{entry.filename}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original)
    # The start-of-implementation archive omitted pyproject; the original run
    # independently sealed the same file and hash, so restore that exact copy.
    original_project = SOURCE / "source-snapshot/pyproject.toml"
    original_hash = load(SOURCE / "source-hashes.json")["pyproject.toml"]
    if sha256(original_project.read_bytes()).hexdigest() != original_hash:
        raise ValueError("原运行的pyproject身份不符")
    target = destination / "pyproject.toml"
    if target.exists() and target.read_bytes() != original_project.read_bytes():
        raise ValueError("baseline已有pyproject不等于原封存版本")
    if not target.exists():
        target.write_bytes(original_project.read_bytes())


def without_nulls(value):
    if isinstance(value, dict):
        return {key: without_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [without_nulls(item) for item in value]
    return value


def run_probe(source_root: Path, checkpoint_index: Path, output: Path) -> dict[str, object]:
    env = {**os.environ, "PYTHONPATH": str(source_root / "src"),
           "PYTHON_DOTENV_DISABLED": "1", "PYTHONUTF8": "1"}
    result = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--probe-source-root", str(source_root),
         "--checkpoint-index", str(checkpoint_index), "--output", str(output)],
        cwd=source_root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    output.with_suffix(".log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        return {"imported": False, "exit_code": result.returncode,
                "log": str(output.with_suffix('.log')), "model_calls": 0}
    return load(output)


def materialize(source_root: Path, checkpoint_index: Path, output: Path, *, group: str,
                data: Path, clock_file: Path) -> None:
    from personal_agent.application.conversation.models import ConversationMessage
    from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
    from personal_agent.kernel.config import Settings
    from personal_agent.adapters.web.context import build_web_app_context
    from personal_agent.infra.structured_model import OpenAIModelClient

    stage_clock = StageClock.model_validate(load(clock_file))
    seed = seed_stage(group, data, checkpoint_index)
    clock = ReplayClock(stage_clock.anchor)
    bind_stage_clock(clock)
    settings = Settings.from_env()
    if settings.data_dir.resolve() != data.resolve():
        raise ValueError("正式Composition Root没有使用本组独立数据目录")
    from evals.product_baselines.run_longds import _configuration
    if _configuration(settings) != load(SOURCE / "configuration.json"):
        raise ValueError("实际模型/推理/容量/预算/回答装配与封存profile不同")
    context = build_web_app_context(settings, logging.getLogger(__name__))
    service = context.service
    restore_governance_fixture(service, Path(os.environ["LOOP_SCHEMA_DATABASE_FIXTURE"]))
    actual = service.runtime._conversation_service
    delegate = actual._model_client
    captured = []
    started_at = datetime.now(UTC)

    class CaptureBeforeGeneration:
        def generate(self, request, **kwargs):
            # Capture a complete production request; never return a fake result.
            wire = OpenAIModelClient(settings.structured)._chat_kwargs(request)
            captured.append((request, wire))
            raise PreflightCaptured()

    actual._model_client = CaptureBeforeGeneration()
    entry = load(SOURCE / "turn-14.request.json")
    try:
        try:
            service.converse(conversation_id=entry["conversation_id"],
                messages=[ConversationMessage.model_validate(row) for row in entry["messages"]],
                principal=AuthenticatedPrincipal.model_validate(load(SOURCE / "python-deployment.json")["authorization"]["authorized_principal"]),
                interaction_run_ref=entry["interaction_run_ref"], interaction_mode=entry["interaction_mode"],
                input_artifact_refs=tuple(actual._journal.get(entry["interaction_run_ref"]).input_artifact_refs))
        except PreflightCaptured:
            pass
    finally:
        actual._model_client = delegate
    if len(captured) != 1:
        raise ValueError("未到达唯一首个真实生产请求物化边界")
    request, wire = captured[0]
    wire_file = output.with_name(group + ".first-request.json")
    wire_file.write_bytes(json_bytes(wire))
    original = load(SOURCE / "sdk/c16db4bc30c74188bd057c2a13ff5639.candidate.request.json")
    original_python = load(SOURCE / "sdk/c1b4b743a20e47b490863eab6279d717.candidate.response.json")
    history = request.model_history
    python_preserved = bool(history and without_nulls(history[-1].assistant.payload) == without_nulls(
        original_python["response"]["choices"][0]["message"]))
    tool_result_preserved = bool(history and history[-1].results
        and history[-1].results[0].call_id == seed["active_call_ids"][0])
    budget_line = next(line for line in wire["messages"][0]["content"].splitlines()
                       if '"wall_seconds_at_input"' in line and "{" in line)
    budget, _ = json.JSONDecoder().raw_decode(budget_line[budget_line.index("{"):])
    report = {"materialized": True, "group": group, "code_root": str(source_root),
        "operation": request.operation, "model_calls": 0, "tool_executions": 0, "seed": seed,
        "first_request": frozen(wire_file).model_dump(mode="json"),
        "baseline_wire_unchanged": wire == original if group == "baseline" else None,
        "changed_wire_keys": [key for key in sorted(set(wire) | set(original)) if wire.get(key) != original.get(key)],
        "initial_budget": budget, "stage_time": clock.now().isoformat(), "real_started_at": started_at.isoformat(),
        "real_completed_at": datetime.now(UTC).isoformat(), "history_exchanges": len(history),
        "actual_python_assistant_preserved": python_preserved, "actual_python_result_paired": tool_result_preserved,
        "gateway_type": f"{type(actual._tool_port).__module__}.{type(actual._tool_port).__qualname__}",
        "database_name": os.environ["LOOP_SCHEMA_DATABASE_NAME"],
        "ready": request.operation == "agent_interaction_turn" and python_preserved and tool_result_preserved
                 and budget["wall_seconds_at_input"] == stage_clock.original_wall_seconds_at_input
                 and (group != "baseline" or wire == original)}
    output.write_bytes(json_bytes(report))


def execute_sample(source_root: Path, checkpoint_index: Path, output: Path, *, group: str,
                   data: Path, clock_file: Path, known_token_limit: int, wall_seconds: float,
                   expected_first_request: Path) -> None:
    """Consume actual model choices through the production service and gateway."""
    import httpx
    from personal_agent.application.conversation.models import ConversationMessage, SubmittedFinal
    from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
    from personal_agent.kernel.config import Settings
    from personal_agent.adapters.web.context import build_web_app_context
    from personal_agent.infra.structured_model import OpenAIModelClient
    from evals.product_baselines.retrieval_acceptance_server import install_acceptance_observer
    from evals.product_baselines.run_longds import _configuration, _usage

    output.mkdir(parents=True, exist_ok=False)
    install_acceptance_observer(output / "sdk")
    stage_clock = StageClock.model_validate(load(clock_file))
    seed = seed_stage(group, data, checkpoint_index)
    clock = ReplayClock(stage_clock.anchor)
    bind_stage_clock(clock)
    settings = Settings.from_env()
    if _configuration(settings) != load(SOURCE / "configuration.json"):
        raise ValueError("执行配置不同于准备时的原封存profile")
    context = build_web_app_context(settings, logging.getLogger(__name__))
    service = context.service
    restore_governance_fixture(service, Path(os.environ["LOOP_SCHEMA_DATABASE_FIXTURE"]))
    before_send = OpenAIModelClient._create_chat_completion
    observed_http_send = httpx.Client.send
    provider_host = urlsplit(settings.structured.base_url or "").hostname
    wall_started = monotonic()
    actual_started = datetime.now(UTC)
    stop_line = None
    entry = load(SOURCE / "turn-14.request.json")

    def clocked_http_send(self, request, *args, **kwargs):
        if request.url.host == provider_host:
            clock.start()
        return observed_http_send(self, request, *args, **kwargs)

    def bounded_real_send(self, client, operation, kwargs, **execution_kwargs):
        # Unknown usage is recorded, never used as a stop condition.
        _, known, _ = _usage(output / "sdk")
        live_trace = service.runtime._conversation_service._journal.get(entry["interaction_run_ref"])
        known = max(known, max(0, live_trace.usage.total_tokens - seed["active_known_tokens"]))
        nonlocal stop_line
        if known >= known_token_limit or monotonic() - wall_started >= wall_seconds:
            stop_line = "known_token_limit" if known >= known_token_limit else "task_wall_limit"
            raise RuntimeError("Offline阶段已到预声明成本/时间边界，未发送下一请求")
        if clock.started is None and kwargs != load(expected_first_request):
            raise ValueError("实际首次发送不等于冻结preflight，未发送模型请求")
        return before_send(self, client, operation, kwargs, **execution_kwargs)

    OpenAIModelClient._create_chat_completion = bounded_real_send
    httpx.Client.send = clocked_http_send
    error_type = None
    result = None
    try:
        result = service.converse(conversation_id=entry["conversation_id"],
            messages=[ConversationMessage.model_validate(row) for row in entry["messages"]],
            principal=AuthenticatedPrincipal.model_validate(load(SOURCE / "python-deployment.json")["authorization"]["authorized_principal"]),
            interaction_run_ref=entry["interaction_run_ref"], interaction_mode=entry["interaction_mode"],
            input_artifact_refs=tuple(service.runtime._conversation_service._journal.get(entry["interaction_run_ref"]).input_artifact_refs))
    except Exception as error:
        error_type = type(error).__name__
        (output / "failure.json").write_bytes(json_bytes({"exception_type": error_type,
            "reason_code": getattr(error, "reason_code", None), "failure_stage": getattr(error, "failure_stage", None),
            "evaluation_stop": stop_line}))
    finally:
        OpenAIModelClient._create_chat_completion = before_send
        httpx.Client.send = observed_http_send
    trace = service.conversation_trace(entry["interaction_run_ref"],
        principal=AuthenticatedPrincipal.model_validate(load(SOURCE / "python-deployment.json")["authorization"]["authorized_principal"]))
    if result is not None:
        (output / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (output / "trace.json").write_text(trace.model_dump_json(indent=2), encoding="utf-8")
    submissions = [item for item in trace.inputs if isinstance(item, SubmittedFinal)]
    submitted_and_consumed = bool(submissions and trace.final_message is not None
                                 and trace.final_message == submissions[-1].final)
    physical, sdk_known, unknown = _usage(output / "sdk")
    committed_known = max(0, trace.usage.total_tokens - seed["active_known_tokens"])
    known = max(sdk_known, committed_known)
    new_records = [record for record in trace.model_decisions
                   if record.turn_index is not None and record.turn_index > 1]
    new_feedback = [item for item in trace.inputs[seed["initial_input_count"]:] if getattr(item, "kind", None) == "decision_feedback"]
    report = {"evidence_class": "offline_real_stage_continuous_generation", "group": group,
        "code_root": str(source_root), "seed": seed, "passed": submitted_and_consumed,
        "database_name": os.environ["LOOP_SCHEMA_DATABASE_NAME"],
        "full_candidate_reached_actual_completion": submitted_and_consumed,
        "returned_disposition": result.disposition if result is not None else None,
        "exception_type": error_type, "evaluation_stop": stop_line,
        "physical_model_requests": physical, "known_tokens": known, "unknown_usage_attempts": unknown,
        "captured_sdk_known_tokens": sdk_known, "committed_new_known_tokens": committed_known,
        "committed_provider_usage_complete": trace.usage.provider_usage_complete,
        "stage_clock_anchor": stage_clock.anchor.isoformat(), "stage_clock_completed": clock.now().isoformat(),
        "real_started_at": actual_started.isoformat(), "real_completed_at": datetime.now(UTC).isoformat(),
        "real_wall_seconds": monotonic() - wall_started,
        "new_native_decisions": len(new_records), "new_feedback_reasons": [item.reason_code for item in new_feedback],
        "native_statuses": [getattr(record, "status", None) for record in new_records],
        "normal_other_tools_rejected_by_grader": False,
        "limitation": "真实历史阶段的连续Offline生成，不是新完整Product E2E或语义评分。"}
    (output / "report.json").write_bytes(json_bytes(report))
    (output / "checksums.json").write_bytes(json_bytes({path.relative_to(output).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*")) if path.is_file() and path.name != "checksums.json"}))


def validate_preparation(preparation: Path, groups: tuple[str, ...], *, require_launch: bool = True) -> Preparation:
    prepared = Preparation.model_validate(load(preparation))
    if not prepared.execution_ready:
        raise ValueError("准备未达到执行准入，禁止启动付费生成")
    for name, digest in load(preparation.parent / "checksums.json").items():
        if sha256((preparation.parent / name).read_bytes()).hexdigest() != digest:
            raise ValueError("准备归档校验和不符")
    if prepared.reused_preparation is not None:
        origin = Path(prepared.reused_preparation.path)
        if frozen(origin) != prepared.reused_preparation:
            raise ValueError("复用物化证据的原准备身份不同")
        for name, digest in load(origin.parent / "checksums.json").items():
            if sha256((origin.parent / name).read_bytes()).hexdigest() != digest:
                raise ValueError("复用准备的归档校验和不符")
    if Path(__file__).read_bytes() != (preparation.parent / "runner-source.py").read_bytes():
        raise ValueError("runner已变化，必须重新prepare冻结身份")
    if (str(Path(sys.executable).resolve()) != prepared.interpreter
            or {name: version(name) for name in prepared.runtime_versions} != prepared.runtime_versions):
        raise ValueError("解释器/依赖版本不同于冻结环境")
    for item in (*prepared.source_files, prepared.inventory, prepared.baseline_archive):
        if frozen(Path(item.path)) != item:
            raise ValueError("封存准备输入发生变化")
    for group in groups:
        if group not in prepared.prepared_groups:
            raise ValueError("该准备没有冻结所请求组")
        root = Path(prepared.baseline_code_root if group == "baseline" else prepared.candidate_code_root)
        expected = prepared.baseline_code_sha256 if group == "baseline" else prepared.candidate_code_sha256
        if code_identity(root)[0] != expected:
            raise ValueError("组代码身份已变化，须重新prepare，不可混入旧分母")
    if require_launch:
        if prepared.launch_probe is None or frozen(Path(prepared.launch_probe.path)) != prepared.launch_probe:
            raise ValueError("冻结副本尚无有效启动探针，不启动生成")
        if load(Path(prepared.launch_probe.path)).get("ready") is not True:
            raise ValueError("冻结副本启动探针未通过")
    return prepared


def launch_probe(preparation: Path, output: Path, groups: tuple[str, ...]) -> None:
    """Import the real selected packages from a frozen copy, forbidding HTTP."""
    import httpx

    prepared = validate_preparation(preparation, groups, require_launch=False)
    if Path(prepared.candidate_code_root).resolve() != ROOT.resolve():
        raise ValueError("冻结副本的仓库路径不同于准备原件")
    expected = Path(prepared.baseline_code_root if groups == ("baseline",) else prepared.candidate_code_root).resolve()
    if LAUNCH_SOURCE_ROOT != expected:
        raise ValueError("控制进程没有绑定本组冻结源码")
    original_send, original_async_send = httpx.Client.send, httpx.AsyncClient.send
    attempts = 0

    def reject_http(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("启动探针禁止HTTP发送")

    async def reject_async_http(*args, **kwargs):
        reject_http(*args, **kwargs)

    httpx.Client.send, httpx.AsyncClient.send = reject_http, reject_async_http
    try:
        import evals.product_baselines.run_longds as longds
        import personal_agent.application.conversation.service as conversation
        package_files = {"evals.product_baselines.run_longds": str(Path(longds.__file__).resolve()),
            "personal_agent.application.conversation.service": str(Path(conversation.__file__).resolve())}
        if any(not Path(path).is_relative_to(expected) for path in package_files.values()):
            raise ValueError("控制进程导入了另一组的评测或生产包")
    finally:
        httpx.Client.send, httpx.AsyncClient.send = original_send, original_async_send
    output.write_bytes(json_bytes({"ready": attempts == 0, "groups": groups, "repo_root": str(ROOT),
        "topic": str(TOPIC), "source": str(SOURCE), "launch_source_root": str(LAUNCH_SOURCE_ROOT),
        "package_files": package_files, "http_attempts": attempts, "model_calls": 0, "samples": 0,
        "runner_sha256": sha256(Path(__file__).read_bytes()).hexdigest()}))


def generation_limits(prepared: Preparation, known_token_limit: int | None,
                      wall_seconds: float | None) -> tuple[int, float]:
    tokens = prepared.known_token_limit if known_token_limit is None else known_token_limit
    seconds = prepared.wall_seconds if wall_seconds is None else wall_seconds
    if type(tokens) is not int or not 0 < tokens <= prepared.known_token_limit:
        raise ValueError("组级known-token-limit只允许收紧冻结上限")
    if not 0 < seconds <= prepared.wall_seconds:
        raise ValueError("组级wall-seconds只允许收紧冻结上限")
    return tokens, seconds


def run_generation(preparation: Path, output: Path, groups: tuple[str, ...], *,
                   known_token_limit: int | None = None, wall_seconds: float | None = None) -> None:
    """Execute only after an explicit --run command against frozen preparation."""
    prepared = validate_preparation(preparation, groups)
    token_cap, wall_cap = generation_limits(prepared, known_token_limit, wall_seconds)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    index = preparation.parent / "checkpoint-index.json"
    clock_file = preparation.parent / "stage-clock.json"
    actual_start = monotonic()
    short_root = ROOT / ".tmp/loop-p1-20261024" / uuid4().hex[:8]
    known = 0
    rows = []
    for group in groups:
        root = Path(prepared.baseline_code_root if group == "baseline" else prepared.candidate_code_root)
        for sample in range(1, 11):
            if known >= token_cap or monotonic() - actual_start >= wall_cap:
                break
            sample_out = output / f"{group}-{sample:02}"
            data = short_root / ("b" if group == "baseline" else "c") / str(sample)
            env = execution_environment(root, data, sample_out, fixture_path=Path(prepared.database_fixture.path))
            process = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                "--execute-source-root", str(root), "--checkpoint-index", str(index), "--group", group,
                "--data", str(data), "--clock-file", str(clock_file), "--output", str(sample_out),
                "--known-token-limit", str(token_cap - known),
                "--wall-seconds", str(wall_cap - (monotonic() - actual_start)),
                "--expected-first-request", str(preparation.parent / f"{group}.first-request.json")],
                cwd=root, env=env, capture_output=True, text=True, encoding="utf-8")
            (output / f"{group}-{sample:02}.log").write_text(process.stdout + process.stderr, encoding="utf-8")
            if not (sample_out / "report.json").exists():
                raise RuntimeError("真实阶段执行未形成报告；保留失败身份，禁止自动补样")
            row = load(sample_out / "report.json")
            rows.append(row)
            known += row["known_tokens"]
            (output / "running.json").write_bytes(json_bytes({"completed": len(rows), "known_tokens": known,
                "known_token_limit": token_cap, "wall_seconds_limit": wall_cap,
                "passed": sum(bool(item["passed"]) for item in rows)}))
    summary = {"evidence_class": "offline_real_stage_continuous_generation_group", "groups": groups,
        "preparation": frozen(preparation).model_dump(mode="json"),
        "known_token_limit": token_cap, "wall_seconds_limit": wall_cap,
        "planned_per_group": 10, "completed": len(rows), "known_tokens": known, "samples": rows,
        "passed": sum(bool(row["passed"]) for row in rows), "unexecuted": 10 * len(groups) - len(rows),
        "real_wall_seconds": monotonic() - actual_start, "release_eligible": False}
    (output / "report.json").write_bytes(json_bytes(summary))


def run_materialization(source_root: Path, checkpoint_index: Path, output: Path, *, group: str,
                        data: Path, clock_file: Path) -> dict[str, object]:
    env = execution_environment(source_root, data, output.parent)
    result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--materialize-source-root",
        str(source_root), "--group", group, "--checkpoint-index", str(checkpoint_index),
        "--data", str(data), "--clock-file", str(clock_file), "--output", str(output)],
        cwd=source_root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    output.with_suffix(".log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        return {"materialized": False, "exit_code": result.returncode,
                "log": str(output.with_suffix('.log')), "model_calls": 0}
    return load(output)


def execution_environment(source_root: Path, data: Path, output: Path, *, fixture_path: Path | None = None) -> dict[str, str]:
    from personal_agent.kernel.config import Settings
    from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
    from evals.product_baselines.run_longds import _environment

    settings = Settings.from_env()
    entry = load(SOURCE / "python-deployment.json")
    principal = AuthenticatedPrincipal.model_validate(entry["authorization"]["authorized_principal"])
    env = _environment(settings, output, principal=principal, api_key="offline-phase-preflight", port=0,
                       authorization_file=SOURCE / "python-deployment.json")
    original = load(SOURCE / "configuration.json")
    env.update(PYTHONPATH=os.pathsep.join((str(source_root / "src"), str(source_root))),
               PERSONAL_AGENT_DATA_DIR=str(data), PYTHONUTF8="1",
               PERSONAL_AGENT_ANSWER_RESULT=json.dumps(original["answer_result"]),
               STRUCTURED_MODEL=original["structured"]["model"], OPENAI_MODEL=original["openai"]["model"],
               STRUCTURED_EXTRA_BODY=json.dumps(original["structured"]["extra_body"]),
               STRUCTURED_OUTPUT_TRANSPORT=original["structured"]["output_transport"],
               STRUCTURED_MODEL_CAPACITY=json.dumps(original["structured"]["capacity"]),
               OPENAI_MODEL_CAPACITY=json.dumps(original["openai"]["capacity"]),
               PERSONAL_AGENT_STRUCTURED_TIMEOUT_SECONDS=str(original["structured"]["timeout_seconds"]),
               PERSONAL_AGENT_STRUCTURED_MAX_RETRIES=str(original["structured"]["max_retries"]),
               PERSONAL_AGENT_OPENAI_TIMEOUT_SECONDS=str(original["openai"]["timeout_seconds"]),
               PERSONAL_AGENT_OPENAI_MAX_RETRIES=str(original["openai"]["max_retries"]))
    for key, value in original["budget"].items():
        env["PERSONAL_AGENT_INTERACTION_" + key.upper()] = str(value)
    fixture_path = fixture_path or output / "database-fixture.json"
    database_identity = isolate_database(env, fixture_path)
    identity_path = (output.parent / (output.name + ".database.json")
                     if fixture_path.parent != output else output / (data.name + ".database.json"))
    identity_path.write_bytes(json_bytes(database_identity))
    return env


def probe(source_root: Path, checkpoint_index: Path, output: Path) -> None:
    # This subprocess imports one code identity and only validates actual files.
    import personal_agent.application.conversation.models as models

    if not Path(models.__file__).resolve().is_relative_to((source_root / "src").resolve()):
        raise ValueError("子进程未加载指定源码身份")
    rows = []
    for path_text in load(checkpoint_index):
        path = Path(path_text)
        try:
            trace = models.InteractionTrace.model_validate_json(path.read_bytes())
        except ValueError as error:
            errors = getattr(error, "errors", lambda: [])()
            rows.append({"path": str(path), "valid": False, "error_type": type(error).__name__,
                         "errors": [{"loc": list(row["loc"]), "type": row["type"]} for row in errors]})
        else:
            rows.append({"path": str(path), "valid": True, "decisions": len(trace.model_decisions)})
    output.write_bytes(json_bytes({"imported": True, "model_calls": 0, "tool_executions": 0,
                                  "all_checkpoints_valid": all(row["valid"] for row in rows), "checkpoints": rows}))


def seal_preparation(report: Preparation, output: Path) -> Preparation:
    """Seal the runner and check that exact frozen copy without model HTTP."""
    (output / "preflight.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (output / "runner-source.py").write_bytes(Path(__file__).read_bytes())
    changed = [item.path for item in report.source_files if frozen(Path(item.path)) != item]
    if changed:
        raise ValueError("准备期间封存输入发生变化")
    if "candidate" in report.prepared_groups and code_identity(ROOT)[0] != report.candidate_code_sha256:
        raise ValueError("准备期间candidate源码发生变化，不能冻结同一身份")
    (output / "checksums.json").write_bytes(json_bytes({path.relative_to(output).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*")) if path.is_file() and path.name != "checksums.json"}))
    if report.execution_ready:
        launch_output = output / "launch-probe.json"
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHON_DOTENV_DISABLED": "1"}
        env.pop("PYTHONPATH", None)
        result = subprocess.run([sys.executable, "-B", str(output / "runner-source.py"), "--launch-probe",
            "--preflight", str(output / "preflight.json"), "--groups",
            report.prepared_groups[0] if len(report.prepared_groups) == 1 else "both",
            "--output", str(launch_output)],
            cwd=Path(report.baseline_code_root) if report.prepared_groups == ("baseline",) else ROOT,
            env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        (output / "launch-probe.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode or not launch_output.exists() or load(launch_output).get("ready") is not True:
            report = report.model_copy(update={"execution_ready": False,
                "blockers": (*report.blockers, "冻结副本启动探针未通过；0模型/0样本，不计生成分母。")})
        else:
            report = report.model_copy(update={"launch_probe": frozen(launch_output)})
        (output / "preflight.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        (output / "checksums.json").write_bytes(json_bytes({path.relative_to(output).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in sorted(output.rglob("*")) if path.is_file() and path.name != "checksums.json"}))
    return report


def refresh_preparation(preparation: Path, output: Path, groups: tuple[str, ...], *,
                        known_token_limit: int | None, wall_seconds: float | None) -> Preparation:
    """Reuse unchanged materialization after a runner-only stop-line change."""
    previous = Preparation.model_validate(load(preparation))
    if not previous.execution_ready or previous.launch_probe is None:
        raise ValueError("仅可复用已有启动证明且ready的准备")
    for name, digest in load(preparation.parent / "checksums.json").items():
        if sha256((preparation.parent / name).read_bytes()).hexdigest() != digest:
            raise ValueError("被复用准备的归档校验和不符")
    if (frozen(Path(previous.launch_probe.path)) != previous.launch_probe
            or load(Path(previous.launch_probe.path)).get("ready") is not True):
        raise ValueError("被复用准备的启动证明不符")
    if (str(Path(sys.executable).resolve()) != previous.interpreter
            or {name: version(name) for name in previous.runtime_versions} != previous.runtime_versions):
        raise ValueError("解释器/依赖已变化，不能复用原物化")
    runner = Path(__file__).resolve()
    source_files = []
    for item in (*previous.source_files, previous.inventory, previous.baseline_archive):
        if Path(item.path).resolve() == runner:
            source_files.append(frozen(runner))
        elif frozen(Path(item.path)) != item:
            raise ValueError("生产源码、采集helper或原件已变化，不能仅刷新Harness")
        elif item in previous.source_files:
            source_files.append(item)
    for group in groups:
        if group not in previous.prepared_groups:
            raise ValueError("复用准备没有该组的完整物化证据")
        root = Path(previous.baseline_code_root if group == "baseline" else previous.candidate_code_root)
        expected = previous.baseline_code_sha256 if group == "baseline" else previous.candidate_code_sha256
        if code_identity(root)[0] != expected:
            raise ValueError("生产源码身份变化，不能仅刷新Harness")
    token_cap, wall_cap = generation_limits(previous, known_token_limit, wall_seconds)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name in ("checkpoint-index.json", "stage-clock.json", "database-fixture.json"):
        shutil.copyfile(preparation.parent / name, output / name)
    for group in groups:
        for suffix in (".first-request.json", "-materialization.json", "-materialization.log", "-probe.json", "-probe.log"):
            path = preparation.parent / (group + suffix)
            shutil.copyfile(path, output / path.name)
    report = previous.model_copy(update={
        "prepared_groups": groups, "known_token_limit": token_cap, "wall_seconds": wall_cap,
        "source_files": tuple(source_files), "database_fixture": frozen(output / "database-fixture.json"),
        "reused_preparation": frozen(preparation), "launch_probe": None,
        "limitation": "仅刷新Harness及组级停止线；复用原准备的完整物化和隔离数据库事实，未重新装配、复制数据库或调用模型。"})
    return seal_preparation(report, output)


def prepare(output: Path, inventory_path: Path, *, groups: tuple[str, ...] = ("baseline", "candidate"),
            known_token_limit: int | None = None, wall_seconds: float | None = None) -> Preparation:
    token_cap = 60_000_000 if known_token_limit is None else known_token_limit
    wall_cap = 129600 if wall_seconds is None else wall_seconds
    if not 0 < token_cap <= 60_000_000 or not 0 < wall_cap <= 129600:
        raise ValueError("准备停止线只允许收紧原60M/36小时上限")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    inventory = load(inventory_path)
    sources = []
    for item in inventory["sources"].values():
        identity = frozen(ROOT / item["path"])
        if identity.sha256 != item["sha256"] or identity.bytes != item["bytes"]:
            raise ValueError("真实阶段清单与实际输入不同")
        sources.append(identity)
    checkpoint = ROOT / inventory["sources"]["pre_decision_checkpoint"]["path"]
    trace = load(checkpoint)
    wire = load(ROOT / inventory["sources"]["original_decision_request"]["path"])
    budgets = []
    for message in wire["messages"]:
        if message["role"] != "system":
            continue
        for line in (message.get("content") or "").splitlines():
            if '"wall_seconds_at_input"' in line and "{" in line:
                budget, _ = json.JSONDecoder().raw_decode(line[line.index("{"):])
                budgets.append(budget)
    if len(budgets) != 1:
        raise ValueError("原SDK首决策时间预算不能唯一定位")
    deadline = datetime.fromisoformat(trace["run_deadline_at"].replace("Z", "+00:00"))
    clock = StageClock(anchor=deadline - timedelta(seconds=budgets[0]["wall_seconds_at_input"]),
                       original_deadline=deadline, original_wall_seconds_at_input=budgets[0]["wall_seconds_at_input"])
    archive = TOPIC / "before-working-tree.zip"
    baseline_root = TOPIC / "baseline-code"
    extract_baseline(archive, baseline_root)
    baseline_digest, _ = code_identity(baseline_root)
    candidate_digest, candidate_hashes = code_identity(ROOT)
    for group in groups:
        owner = baseline_root if group == "baseline" else ROOT
        sources.extend(frozen(path) for path in sorted((owner / "evals/product_baselines").glob("*.py"))
                       if not path.name.startswith("test_"))
        catalog = owner / "evals/e2e_quality/evidence_catalog.py"
        if catalog.exists():
            sources.append(frozen(catalog))
    heads = []
    sdk = {}
    sdk_originals = output / "historical-sdk"
    sdk_originals.mkdir()
    for path in sorted((SOURCE / "sdk").glob("*.candidate.response.json")):
        captured = load(path)
        request_path = path.with_name(path.name.replace(".response.", ".request."))
        for original_path in (path, request_path):
            sources.append(frozen(original_path))
            (sdk_originals / original_path.name).write_bytes(original_path.read_bytes())
        for choice in captured.get("response", {}).get("choices", []):
            assistant = choice.get("message")
            if assistant:
                key = json_bytes(without_nulls(assistant))
                sdk.setdefault(key, []).append(path)
    decisions = []
    known = 0
    active_python = []
    for directory in sorted((SOURCE / "server-data/interaction_runs").iterdir()):
        candidates = sorted(directory.glob("*.json"))
        if not candidates:
            continue
        head = checkpoint if directory.name == trace["interaction_run_ref"] else candidates[-1]
        actual = load(head)
        if actual["conversation_id"] != trace["conversation_id"] or actual["principal"] != trace["principal"]:
            continue
        heads.append(head)
        sources.append(frozen(head))
        known += actual["usage"]["total_tokens"]
        for record in actual["model_decisions"]:
            payload = record["assistant"]["payload"]
            matches = sdk.get(json_bytes(without_nulls(payload)), [])
            call_ids = tuple(call["id"] for call in payload.get("tool_calls") or [])
            decisions.append(HistoricalDecision(run_ref=actual["interaction_run_ref"],
                turn_index=record["turn_index"], call_ids=call_ids,
                sdk_candidates=tuple(str(path.resolve()) for path in matches),
                control_operations=tuple(item["operation"] for item in record["dispositions"]),
                protocol_exchange_count=len(record["protocol_exchanges"])))
            if head == checkpoint:
                active_python.extend(matches)
            for path in matches:
                sources.extend((frozen(path), frozen(path.with_name(path.name.replace(".response.", ".request.")))))
    if len(active_python) != 1:
        raise ValueError("0010的完整真实Python模型响应不能唯一定位")
    index = output / "checkpoint-index.json"
    index.write_bytes(json_bytes([str(path.resolve()) for path in heads]))
    baseline_probe = (run_probe(baseline_root, index, output / "baseline-probe.json")
                      if "baseline" in groups else {"not_selected": True})
    candidate_probe = (run_probe(ROOT, index, output / "candidate-probe.json")
                       if "candidate" in groups else {"not_selected": True})
    clock_file = output / "stage-clock.json"
    clock_file.write_text(clock.model_dump_json(indent=2), encoding="utf-8")
    database_fixture = output / "database-fixture.json"
    freeze_database_fixture(database_fixture, index)
    execution_root = ROOT / ".tmp/loop-p1-20261024" / uuid4().hex[:8]
    materialization = {group: run_materialization(baseline_root if group == "baseline" else ROOT,
        index, output / f"{group}-materialization.json", group=group,
        data=execution_root / ("b" if group == "baseline" else "c"), clock_file=clock_file) for group in groups}
    deployment = load(SOURCE / "python-deployment.json")
    source_config = load(SOURCE / "configuration.json")
    for path in (SOURCE / "python-deployment.json", SOURCE / "configuration.json", SOURCE / "server.log"):
        sources.append(frozen(path))
    for directory in (SOURCE / "server-data/uploads", SOURCE / "server-data/generated_artifacts"):
        sources.extend(frozen(path) for path in sorted(directory.iterdir()) if path.is_file())
    sources.extend((frozen(ROOT / "pyproject.toml"), frozen(baseline_root / "pyproject.toml")))
    blockers = []
    if any(len(row.sdk_candidates) != 1 for row in decisions):
        blockers.append("存在不能唯一关联SDK原件的历史决策，禁止猜补调用身份。")
    if "baseline" in groups and not baseline_probe.get("all_checkpoints_valid"):
        blockers.append("baseline代码不能直接读取源检查点，须先解决实际契约差异。")
    for group, result in materialization.items():
        if not result.get("ready"):
            blockers.append(f"{group}真实首请求物化尚未通过，见{group}-materialization.json/log。")
    if blockers:
        blockers.append("准入未通过时不提供猜造生成结果或可运行声明。")
    unique_sources = {item.path: item for item in sources}
    report = Preparation(execution_ready=not blockers, prepared_groups=groups,
        known_token_limit=token_cap, wall_seconds=wall_cap,
        source_run=trace["interaction_run_ref"], source_checkpoint=frozen(checkpoint),
        inventory=frozen(inventory_path), baseline_archive=frozen(archive), baseline_code_root=str(baseline_root),
        baseline_code_sha256=baseline_digest, candidate_code_root=str(ROOT), candidate_code_sha256=candidate_digest,
        candidate_source_hashes=candidate_hashes, interpreter=str(Path(sys.executable).resolve()),
        runtime_versions={name: version(name) for name in ("pydantic", "openai", "httpx")},
        source_files=tuple(unique_sources.values()), stage_clock=clock,
        original_initial_budget=budgets[0], original_configuration=source_config,
        known_tokens_before_stage=known, task_token_limit=deployment["authorization"]["max_total_tokens"],
        same_conversation_runs=len(heads), historical_decisions=tuple(decisions),
        active_python_candidate=str(active_python[0]), baseline_probe=baseline_probe, candidate_probe=candidate_probe,
        materialization=materialization, short_execution_root=str(execution_root), blockers=tuple(blockers),
        database_fixture=frozen(database_fixture),
        limitation="仅准备和原件类型准入，模型/工具调用为0；无生成结果、连续阶段通过或Product E2E主张。")
    return seal_preparation(report, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", type=Path, help="显式执行已经冻结且ready的preflight.json；此操作调用真实模型")
    mode.add_argument("--launch-probe", action="store_true", help="冻结副本的0HTTP启动检查")
    mode.add_argument("--probe-source-root", type=Path, help=argparse.SUPPRESS)
    mode.add_argument("--materialize-source-root", type=Path, help=argparse.SUPPRESS)
    mode.add_argument("--execute-source-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--inventory", type=Path, default=TOPIC / "stage-inventory.json")
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--checkpoint-index", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--group", choices=("baseline", "candidate"), help=argparse.SUPPRESS)
    parser.add_argument("--data", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--clock-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--groups", choices=("baseline", "candidate", "both"), default="both")
    parser.add_argument("--known-token-limit", type=int, help="组级新增已知tokens上限，只允许收紧冻结上限")
    parser.add_argument("--wall-seconds", type=float, help="组级真实墙钟秒数上限，只允许收紧冻结上限")
    parser.add_argument("--expected-first-request", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.prepare:
        groups = ("baseline", "candidate") if args.groups == "both" else (args.groups,)
        if args.preflight is not None:
            result = refresh_preparation(args.preflight.resolve(), args.output, groups,
                known_token_limit=args.known_token_limit, wall_seconds=args.wall_seconds)
        else:
            result = prepare(args.output, args.inventory.resolve(), groups=groups,
                known_token_limit=args.known_token_limit, wall_seconds=args.wall_seconds)
        print(json.dumps({"execution_ready": result.execution_ready, "model_calls": result.model_calls,
            "same_conversation_runs": result.same_conversation_runs, "historical_decisions": len(result.historical_decisions),
            "blockers": len(result.blockers), "preflight": str(args.output / 'preflight.json')}, ensure_ascii=False))
    elif args.run is not None:
        groups = ("baseline", "candidate") if args.groups == "both" else (args.groups,)
        run_generation(args.run.resolve(), args.output, groups,
            known_token_limit=args.known_token_limit, wall_seconds=args.wall_seconds)
    elif args.launch_probe:
        if args.preflight is None:
            parser.error("启动探针需要--preflight")
        groups = ("baseline", "candidate") if args.groups == "both" else (args.groups,)
        launch_probe(args.preflight.resolve(), args.output, groups)
    elif args.probe_source_root is not None:
        if args.checkpoint_index is None:
            parser.error("内部probe需要--checkpoint-index")
        probe(args.probe_source_root.resolve(), args.checkpoint_index, args.output)
    elif args.materialize_source_root is not None:
        if any(value is None for value in (args.checkpoint_index, args.group, args.data, args.clock_file)):
            parser.error("内部materialize需要固定group/data/clock/checkpoint-index")
        materialize(args.materialize_source_root.resolve(), args.checkpoint_index, args.output,
                    group=args.group, data=args.data, clock_file=args.clock_file)
    else:
        if any(value is None for value in (args.checkpoint_index, args.group, args.data, args.clock_file,
                                           args.known_token_limit, args.wall_seconds, args.expected_first_request)):
            parser.error("内部execute缺少冻结配置/输入")
        execute_sample(args.execute_source_root.resolve(), args.checkpoint_index, args.output,
            group=args.group, data=args.data, clock_file=args.clock_file,
            known_token_limit=args.known_token_limit, wall_seconds=args.wall_seconds,
            expected_first_request=args.expected_first_request)


if __name__ == "__main__":
    main()
