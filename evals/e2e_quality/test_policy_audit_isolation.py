"""AUD-001: real conversation, authorization and per-application audit ownership."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from typing import Any, Iterator
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from pydantic import BaseModel, ConfigDict
import pytest

from evals.e2e_quality.trace_archive import TraceArchive
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    canonical_evidence_digest,
)
from personal_agent.application.conversation import ConversationTurnView
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

CASE_ID = "AUD-001"
QUESTION = "请帮我计算 17 加 25，直接告诉我结果。"
OWNER = AuthenticatedPrincipal(tenant_id="audit-e2e", user_id="owner")
OTHER = AuthenticatedPrincipal(tenant_id="audit-e2e", user_id="other")
KEYS = {
    "owner": "audit-local-owner",
    "other": "audit-local-other",
    "admin": "audit-local-admin",
}
ROOT = Path(__file__).resolve().parents[2]


class HttpFact(BaseModel):
    method: str
    path: str
    caller: str
    status: int
    payload: Any  # Externally owned HTTP response, validated at its reading boundary.


class PolicyRow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str
    effect: str
    rule: str
    user_id: str | None
    resource: str | None
    run_id: str | None


class AuditOutcome(BaseModel):
    user_result_met: bool | None = None
    owner_read_allowed: bool | None = None
    foreign_read_rejected: bool | None = None
    ordinary_audit_rejected: bool | None = None
    owner_read_denials: int | None = None
    primary_denials: list[PolicyRow] = []
    secondary_denials: list[PolicyRow] = []
    audit_isolated: bool | None = None
    facts: list[HttpFact] = []
    duration_seconds: float = 0
    failure_category: str | None = None


@dataclass(frozen=True)
class AuditProcess:
    base_url: str
    config_digest: str


def _database_url(connection: dict[str, str], name: str) -> str:
    auth = quote(connection.get("user", ""), safe="")
    if connection.get("password"):
        auth += ":" + quote(connection["password"], safe="")
    host = connection.get("host", "127.0.0.1")
    port = connection.get("port", "5432")
    return urlunsplit(
        (
            "postgresql",
            f"{auth}@{host}:{port}",
            "/" + name,
            "connect_timeout=3&sslmode=disable",
            "",
        )
    )


@contextmanager
def audit_process(
    trace_archive: TraceArchive,
    *,
    journal_snapshot: Path | None = None,
) -> Iterator[AuditProcess]:
    """Own fresh databases for this journey instead of cleaning a shared database."""
    settings = Settings.from_env()
    if not settings.structured.api_key or not settings.structured.base_url:
        pytest.fail("AUD-001 requires the configured real model")
    configured = os.getenv("PERSONAL_AGENT_E2E_POSTGRES_URL") or settings.postgres_url
    if not configured:
        pytest.fail("AUD-001 requires real local PostgreSQL")
    connection = conninfo_to_dict(configured)
    if connection.get("host") not in {"localhost", "127.0.0.1"}:
        pytest.fail("AUD-001 only creates isolated databases on local PostgreSQL")
    names = tuple("pa_audit_" + uuid4().hex[:16] for _ in range(2))
    urls = tuple(_database_url(connection, name) for name in names)
    created: list[str] = []
    process: subprocess.Popen[str] | None = None
    config = {
        "model": settings.structured.model,
        "provider": urlsplit(settings.structured.base_url).hostname,
        "transport": settings.structured.output_transport,
        "model_timeout_seconds": settings.structured.timeout_seconds,
        "max_model_turns": 8,
        "max_total_tokens": 80_000,
        "isolated_databases": 2,
        "same_process": True,
        "prompt_source": "production",
    }
    env = dict(os.environ)
    env.update(
        {
            "PYTHON_DOTENV_DISABLED": "true",
            "PYTHONIOENCODING": "utf-8",
            "PERSONAL_AGENT_POSTGRES_URL": urls[0],
            "AUDIT_E2E_SECONDARY_POSTGRES_URL": urls[1],
            "PERSONAL_AGENT_DATA_DIR": str(trace_archive.run_dir / "primary-data"),
            "PERSONAL_AGENT_API_KEYS": json.dumps(
                {KEYS["owner"]: OWNER.model_dump(), KEYS["other"]: OTHER.model_dump()}
            ),
            "PERSONAL_AGENT_ADMIN_API_KEYS": json.dumps(
                {KEYS["admin"]: {"tenant_id": "audit-e2e", "user_id": "admin"}}
            ),
            "PERSONAL_AGENT_FEISHU_ENABLED": "false",
            "PERSONAL_AGENT_RESEARCH_SCHEDULER_ENABLED": "false",
            "PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_ENABLED": "false",
            "PERSONAL_AGENT_KNOWLEDGE_GAP_SCHEDULER_ENABLED": "false",
            "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED": "false",
            "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
            "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
            "PERSONAL_AGENT_MCP_SERVERS": "{}",
            "PERSONAL_AGENT_LANGSMITH_ENABLED": "false",
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
            "PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS": "8",
            "PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS": "80000",
        }
    )
    source_hashes = {
        p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT / "src/personal_agent").rglob("*.py"))
    }
    (trace_archive.run_dir / "source-identity.json").write_text(
        json.dumps(source_hashes, indent=2), encoding="utf-8"
    )
    trace_archive.update_environment(
        {
            "audit_profile": config,
            "sample_plan": {"baseline": 1, "target": 1},
            "production_substitutes": [],
        }
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    log_path = trace_archive.run_dir / "server.log"
    if journal_snapshot is not None:
        shutil.copytree(
            journal_snapshot,
            trace_archive.run_dir / "primary-data/interaction_runs",
        )
    try:
        with psycopg.connect(configured, autocommit=True) as admin:
            for name in names:
                admin.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
                )
                created.append(name)
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "evals.e2e_quality.policy_audit_server",
                    str(port),
                ],
                cwd=ROOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                deadline = time.monotonic() + 45
                with httpx.Client(timeout=2) as client:
                    while True:
                        if process.poll() is not None:
                            pytest.fail(
                                "AUD-001 production server exited; inspect server.log"
                            )
                        try:
                            if all(
                                client.get(
                                    base_url + part + "/api/health",
                                    headers={
                                        "Authorization": "Bearer " + KEYS["owner"]
                                    },
                                ).status_code
                                == 200
                                for part in ("/primary", "/secondary")
                            ):
                                break
                        except httpx.TransportError:
                            pass
                        if time.monotonic() >= deadline:
                            pytest.fail(
                                "AUD-001 production server startup exceeded 45 seconds"
                            )
                        time.sleep(0.1)
                yield AuditProcess(base_url, canonical_evidence_digest(config))
            finally:
                if process.poll() is None and process.stdin is not None:
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                    # The HTTP result may already be a timeout while a real model
                    # call is still finishing. Never kill that call or its database.
                    process.wait()
    finally:
        with psycopg.connect(configured, autocommit=True) as admin:
            for name in created:
                if not name.startswith("pa_audit_") or len(name) != 25:
                    raise RuntimeError("unexpected isolated database identity")
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(name)
                    )
                )
        (trace_archive.run_dir / "database-lifecycle.json").write_text(
            json.dumps(
                {
                    "created": created,
                    "removed": created,
                    "existing_business_database_mutated": False,
                }
            ),
            encoding="utf-8",
        )


@pytest.fixture(autouse=True)
def clean_e2e_database(trace_archive: TraceArchive) -> Iterator[AuditProcess]:
    """Each journey owns real databases and the production app lifecycle."""
    with audit_process(trace_archive) as server:
        yield server


def test_aud_001_policy_audit_stays_with_its_runtime(
    clean_e2e_database: AuditProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    server = clean_e2e_database
    role = os.getenv("PERSONAL_AGENT_PRODUCT_EVIDENCE_ROLE", "target")
    identity = ProductEvidenceIdentity(
        case_id=CASE_ID,
        role=role,
        evidence_class="product_e2e",
        formal_entrypoint="POST /api/conversation/turn; GET /api/conversation/runs/{run}; GET /api/audit/policy-decisions",
        principal=OWNER,
        user_input_digest=canonical_evidence_digest(QUESTION),
        initial_state_digest=canonical_evidence_digest(
            {
                "empty_databases": 2,
                "principals": [OWNER.model_dump(), OTHER.model_dump()],
            }
        ),
        config_cohort=server.config_digest,
        grader_version="audit-http-outcome-v2",
    )
    outcome = AuditOutcome()
    started = time.monotonic()

    def call(
        client: httpx.Client, method: str, path: str, caller: str, **kwargs: Any
    ) -> HttpFact:
        response = client.request(
            method,
            server.base_url + path,
            headers={"Authorization": "Bearer " + KEYS[caller]},
            **kwargs,
        )
        fact = HttpFact(
            method=method,
            path=path,
            caller=caller,
            status=response.status_code,
            payload=response.json(),
        )
        outcome.facts.append(fact)
        return fact

    def rows(fact: HttpFact) -> list[PolicyRow]:
        if fact.status != 200:
            raise RuntimeError("administrator policy query failed")
        return [PolicyRow.model_validate(item) for item in fact.payload["items"]]

    try:
        with httpx.Client(timeout=360) as client:
            turn = call(
                client,
                "POST",
                "/primary/api/conversation/turn",
                "owner",
                json={
                    "conversation_id": "audit-journey-001",
                    "messages": [{"role": "user", "content": QUESTION}],
                },
            )
            if turn.status != 200:
                pytest.fail(f"自然对话未交付，HTTP {turn.status}")
            view = ConversationTurnView.model_validate(turn.payload)
            outcome.user_result_met = view.disposition == "answer" and bool(
                re.search(r"(?<!\d)42(?!\d)|四十二", view.message.content)
            )
            run = view.interaction_run_ref
            path = f"/primary/api/conversation/runs/{run}"
            outcome.owner_read_allowed = (
                call(client, "GET", path, "owner").status == 200
            )
            query = "/api/audit/policy-decisions"
            params = {"run_id": run, "action": "conversation_trace_read"}
            outcome.owner_read_denials = len(
                rows(call(client, "GET", "/primary" + query, "admin", params=params))
            )
            outcome.foreign_read_rejected = (
                call(client, "GET", path, "other").status == 404
            )
            outcome.ordinary_audit_rejected = (
                call(client, "GET", "/primary" + query, "other", params=params).status
                == 403
            )
            outcome.primary_denials = rows(
                call(client, "GET", "/primary" + query, "admin", params=params)
            )
            outcome.secondary_denials = rows(
                call(client, "GET", "/secondary" + query, "admin", params=params)
            )
            expected = PolicyRow(
                action="conversation_trace_read",
                effect="deny",
                rule="conversation_run_scope_mismatch",
                user_id=OTHER.principal_id,
                resource=run,
                run_id=run,
            )
            outcome.audit_isolated = (
                outcome.primary_denials == [expected] and not outcome.secondary_denials
            )
            assert outcome.owner_read_allowed, "owner 必须仍能读取同次运行"
            assert outcome.owner_read_denials == 0, "正常读取不得产生拒绝审计"
            assert outcome.foreign_read_rejected, "其他主体不得读取运行"
            assert outcome.ordinary_audit_rejected, "普通主体不得查询管理员审计"
            assert outcome.audit_isolated, "拒绝记录必须只进入产生该决定的应用"
            assert outcome.user_result_met, "审计检查点不能替代自然计算任务的交付"
    except BaseException as exc:
        outcome.failure_category = type(exc).__name__
        raise
    finally:
        outcome.duration_seconds = round(time.monotonic() - started, 3)
        trace_archive.write_trace(
            nodeid=request.node.nodeid,
            case_id=CASE_ID,
            trace=outcome.model_dump(mode="json"),
            product_evidence=identity,
        )
