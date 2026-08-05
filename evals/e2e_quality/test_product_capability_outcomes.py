"""Release E2E journeys for application capability claims.

Every case enters through the separately running HTTP process.  Setup is also
performed through HTTP; PostgreSQL reads are used only for evidence capture in
the shared architecture helpers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Iterator
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from evals.e2e_quality.trace_archive import TraceArchive
from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _new_live_web_process,
    _post_json,
    _post_text_attachment,
    _require_live_dependencies,
    _yield_started_server,
)


pytestmark = pytest.mark.integration
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)


def _require_profile(value: object, message: str) -> None:
    if value:
        return
    if os.getenv("PERSONAL_AGENT_REQUIRE_LIVE_E2E", "").lower() in {"1", "true", "yes", "on"}:
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture(scope="module")
def live_web_search_process(
    server_temp_dir: Path,
) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    provider = settings.web_search.provider.strip().lower()
    _require_profile(
        settings.web_search_available,
        "web-search product E2E requires the configured provider API key",
    )
    overrides = {
        "PERSONAL_AGENT_WEB_SEARCH_PROVIDER": provider,
        "PERSONAL_AGENT_URL_CAPTURE_PROVIDER": "builtin",
    }
    overrides.update({
        "PERSONAL_AGENT_WEB_SEARCH_API_KEY": str(settings.web_search.api_key),
        "PERSONAL_AGENT_WEB_SEARCH_BASE_URL": str(
            settings.web_search.base_url or ""
        ),
    })
    yield from _yield_started_server(
        _new_live_web_process(server_temp_dir, settings, child_env_overrides=overrides)
    )


@pytest.fixture(scope="module")
def live_investigation_worker(
    server_temp_dir: Path,
    live_web_search_process: LiveWebProcess,
) -> Iterator[tuple[subprocess.Popen[bytes], Path]]:
    log_path = server_temp_dir / "investigation-worker.log"
    log_handle = log_path.open("ab")
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "personal_agent.adapters.cli.main",
            "worker",
            "--queue",
            "investigation",
            "--poll-seconds",
            "0.1",
        ),
        cwd=live_web_search_process.cwd,
        env=live_web_search_process.child_env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(
                    "Investigation worker exited during startup: "
                    + log_path.read_text(encoding="utf-8", errors="replace")
                )
            time.sleep(0.1)
        yield process, log_path
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        log_handle.close()


@pytest.fixture(scope="module")
def live_web_reader_process(
    server_temp_dir: Path,
) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    _require_profile(
        settings.firecrawl.api_key,
        "web-reader product E2E requires FIRECRAWL_API_KEY",
    )
    yield from _yield_started_server(_new_live_web_process(server_temp_dir, settings))


@pytest.fixture(scope="module")
def live_delivery_process(
    server_temp_dir: Path,
) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    _require_profile(
        settings.web_search_available,
        "scheduled-intelligence E2E requires the configured search provider key",
    )
    yield from _yield_started_server(_new_live_web_process(server_temp_dir, settings))


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    timeout: float = 300,
    expected_status: int = 200,
) -> object:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    with urlopen(request, timeout=timeout) as response:
        assert response.status == expected_status
        return json.loads(response.read().decode("utf-8"))


def _workspace_ingest(server: LiveWebProcess, workspace_id: str, text: str, **extra: object) -> dict:
    return _post_json(
        f"{server.base_url}/api/workspace/ingest-text",
        {
            "text": text,
            "user_id": workspace_id,
            "workspace_id": workspace_id,
            **extra,
        },
    )


def _workspace_ask(server: LiveWebProcess, workspace_id: str, question: str) -> dict:
    return _post_json(
        f"{server.base_url}/api/workspace/ask",
        {"question": question, "workspace_id": workspace_id, "limit": 8},
    )


def _record(
    archive: TraceArchive,
    request: pytest.FixtureRequest,
    case_id: str,
    trace: dict[str, object],
    *,
    profile: str,
) -> None:
    archive.update_environment({"product_release_matrix": True})
    archive.write_trace(
        nodeid=request.node.nodeid,
        case_id=case_id,
        trace={"capability_profile": profile, **trace},
    )


def _run_research(server: LiveWebProcess, user_id: str, topic: str) -> dict:
    result = _post_json(
        f"{server.base_url}/api/research/once",
        {
            "user_id": user_id,
            "topic": topic,
            "instructions": "优先官方来源，返回可解析来源；证据不足时明确限制。",
            "max_items": 3,
            "lookback_hours": 168,
        },
    )
    detail = _get_json(
        f"{server.base_url}/api/research/runs/{result['id']}?"
        + urlencode({"user_id": user_id})
    )
    assert isinstance(detail, dict)
    assert detail["run"]["status"] in {
        "completed_verified",
        "completed_with_limitations",
        "partial_no_supported_claims",
        "partial_budget_exhausted",
        "partial_low_yield",
    }
    assert detail["digest"] is not None
    return detail


def _prepare_delete(
    server: LiveWebProcess,
    *,
    user_id: str,
    note_id: str,
    idempotency_key: str,
    reason: str,
) -> dict[str, object]:
    return _post_json(
        f"{server.base_url}/api/notes/{note_id}/delete-commands",
        {
            "user_id": user_id,
            "workspace_id": user_id,
            "idempotency_key": idempotency_key,
            "reason": reason,
        },
    )


def _decide_delete(
    server: LiveWebProcess,
    operation: dict[str, object],
    *,
    user_id: str,
    decision: str,
    confirmation_ref: str = "",
) -> dict[str, object]:
    command = operation["command"]
    assert isinstance(command, dict)
    return _post_json(
        f"{server.base_url}/api/knowledge-delete-commands/{command['command_id']}/decision",
        {
            "user_id": user_id,
            "decision": decision,
            "command_digest": command["command_digest"],
            "confirmation_ref": confirmation_ref,
        },
    )


def _prepare_restore(
    server: LiveWebProcess,
    delete_operation: dict[str, object],
    *,
    user_id: str,
    idempotency_key: str,
    reason: str,
) -> dict[str, object]:
    delete_command = delete_operation["command"]
    assert isinstance(delete_command, dict)
    return _post_json(
        f"{server.base_url}/api/knowledge-delete-commands/"
        f"{delete_command['command_id']}/restore-commands",
        {
            "user_id": user_id,
            "workspace_id": user_id,
            "idempotency_key": idempotency_key,
            "reason": reason,
        },
    )


def _decide_restore(
    server: LiveWebProcess,
    operation: dict[str, object],
    *,
    user_id: str,
    decision: str,
    confirmation_ref: str = "",
) -> dict[str, object]:
    command = operation["command"]
    assert isinstance(command, dict)
    return _post_json(
        f"{server.base_url}/api/knowledge-restore-commands/{command['command_id']}/decision",
        {
            "user_id": user_id,
            "decision": decision,
            "command_digest": command["command_digest"],
            "confirmation_ref": confirmation_ref,
        },
    )


def test_product_e01_conversation_journey(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    user_id = f"product-e01-{uuid4().hex}"
    session_id = f"conversation-{uuid4().hex}"
    with pytest.raises(HTTPError) as missing_legacy_before:
        _get_json(f"{live_web_process.base_url}/api/entry/runs?" + urlencode({"user_id": user_id}))
    assert missing_legacy_before.value.code == 404
    first_messages = [{"role": "user", "content": "用一句话解释什么是幂等性。"}]
    first = _post_json(
        f"{live_web_process.base_url}/api/conversation/turn",
        {"conversation_id": session_id, "messages": first_messages},
    )
    assert first["disposition"] == "answer"
    assert str(first["message"]["content"]).strip()

    other_secret = f"other-conversation-{uuid4().hex}"
    _post_json(
        f"{live_web_process.base_url}/api/conversation/turn",
        {
            "conversation_id": f"other-{uuid4().hex}",
            "messages": [{"role": "user", "content": f"复述这个字符串：{other_secret}"}],
        },
    )

    clarification_messages = [
        *first_messages,
        first["message"],
        {"role": "user", "content": "帮我处理一下"},
    ]
    clarification = _post_json(
        f"{live_web_process.base_url}/api/conversation/turn",
        {"conversation_id": session_id, "messages": clarification_messages},
    )
    assert clarification["disposition"] == "clarification_required"
    assert str(clarification["message"]["content"]).strip()

    resumed = _post_json(
        f"{live_web_process.base_url}/api/conversation/turn",
        {
            "conversation_id": session_id,
            "messages": [
                *clarification_messages,
                clarification["message"],
                {"role": "user", "content": "解释数据库事务的原子性。"},
            ],
        },
    )
    with pytest.raises(HTTPError) as missing_legacy_after:
        _get_json(f"{live_web_process.base_url}/api/entry/runs?" + urlencode({"user_id": user_id}))
    assert missing_legacy_after.value.code == 404
    assert resumed["disposition"] == "answer"
    assert str(resumed["message"]["content"]).strip()
    assert other_secret not in json.dumps(resumed, ensure_ascii=False)
    assert not any(key in resumed for key in ("run_id", "task", "command", "completion_report"))
    _record(
        trace_archive,
        request,
        "E01.product_http",
        {
            "conversation_id": session_id,
            "first": first,
            "clarification": clarification,
            "resumed": resumed,
            "legacy_entry_runs_unavailable": True,
        },
        profile="baseline",
    )


def test_product_e02_grounded_workspace_ask(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    workspace_id = f"product-e02-{uuid4().hex}"
    other_workspace = f"product-e02-other-{uuid4().hex}"
    fact = f"Atlas-{uuid4().hex[:8]} 的发布窗口是周四 21:00。"
    secret = f"other-{uuid4().hex}"
    ingest = _workspace_ingest(live_web_process, workspace_id, fact, source_type="document")
    _workspace_ingest(live_web_process, other_workspace, secret, source_type="document")
    before = _get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )
    answer = _workspace_ask(live_web_process, workspace_id, "Atlas 的发布窗口是什么时候？")
    after = _get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )
    assert answer["citations"]
    assert answer["answer_claim_saved_count"] == 0
    assert len(before) == len(after)
    assert secret not in json.dumps(answer, ensure_ascii=False)
    _record(
        trace_archive,
        request,
        "E02.product_http",
        {"artifact": ingest["artifact"], "answer": answer, "claim_count": len(after)},
        profile="baseline",
    )


def test_product_e20_workspace_answer_has_independent_verification(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    workspace_id = f"product-e20-{uuid4().hex}"
    subject = f"Northstar-{uuid4().hex[:8]}"
    _workspace_ingest(
        live_web_process,
        workspace_id,
        f"{subject} 的生产迁移日期是 2026-09-10。",
        source_type="document",
    )
    _workspace_ingest(
        live_web_process,
        workspace_id,
        f"{subject} 的生产迁移日期不是 2026-09-10，而是 2026-10-15。",
        source_type="document",
    )
    before = _get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )
    answer = _workspace_ask(
        live_web_process,
        workspace_id,
        (
            f"核对工作区中关于 {subject} 生产迁移日期的材料。逐项列出候选结论和"
            "对应原文证据，明确冲突；冲突没有解决时，不要把核对结果标成已得到支持。"
        ),
    )
    after = _get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )
    verification = answer["verification"]
    cited_span_ids = {
        item["evidence_span_id"] for item in answer["citations"]
    }
    conflict_span_ids = {
        span_id
        for conflict in verification["conflicts"]
        for span_id in conflict["evidence_span_ids"]
    }
    _record(
        trace_archive,
        request,
        "E20.product_http",
        {
            "answer": answer,
            "claim_count_before": len(before),
            "claim_count_after": len(after),
        },
        profile="baseline",
    )

    assert verification["verdict"] == "needs_revision"
    assert verification["conclusion_status"] == "conflicted"
    assert verification["conflicts"]
    assert conflict_span_ids
    assert conflict_span_ids <= cited_span_ids
    assert len(before) == len(after)
    assert answer["answer_claim_saved_count"] == 0
    assert not any(
        key in answer
        for key in (
            "grounding_status",
            "evidence_coverage",
            "missing_sections",
            "answer_claim_grounded_count",
        )
    )


def test_product_e03_selected_upload_artifact_ask(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    user_id = f"product-e03-{uuid4().hex}"
    fact = f"上传资料中的校验口令是 amber-{uuid4().hex[:8]}。"
    response = _post_text_attachment(
        f"{live_web_process.base_url}/api/workspace/ingest-upload",
        filename="selected-artifact.txt",
        content=fact,
        fields={
            "user_id": user_id,
            "workspace_id": user_id,
        },
    )
    resource_ref = response["resource_ref"]
    ingest = response["ingest_result"]
    artifact = ingest["artifact"]
    answer = _workspace_ask(
        live_web_process,
        user_id,
        "只根据选中的附件回答校验口令，并说明来自附件。",
    )
    assert str(resource_ref["resource_id"]).startswith("art_")
    assert artifact["artifact_id"] == resource_ref["resource_id"]
    assert fact in artifact["text"]
    assert answer["citations"]
    assert fact.split("是 ", 1)[-1].rstrip("。") in str(answer["answer"])
    _record(
        trace_archive,
        request,
        "E03.product_http",
        {"resource_ref": resource_ref, "artifact": artifact, "answer": answer},
        profile="baseline",
    )


def test_product_e04_governed_delete_recovery(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    user_id = f"product-e04-{uuid4().hex}"
    ingested = _workspace_ingest(
        live_web_process,
        user_id,
        "这条知识只允许在确认后删除。",
        source_type="document",
    )
    note_id = str(ingested["knowledge_items"][0]["knowledge_item_id"])

    with pytest.raises(HTTPError) as cross_scope:
        _prepare_delete(
            live_web_process,
            user_id=f"attacker-{uuid4().hex}",
            note_id=note_id,
            idempotency_key="cross-scope",
            reason="unauthorized",
        )
    assert cross_scope.value.code == 404

    prepared = _prepare_delete(
        live_web_process,
        user_id=user_id,
        note_id=note_id,
        idempotency_key=f"delete-{note_id}",
        reason="confirmed obsolete knowledge",
    )
    command = prepared["command"]
    assert prepared["status"] == "awaiting_confirmation"
    assert prepared["receipt"] is None
    assert command["target_note_id"] == note_id
    assert command["reason"] == "confirmed obsolete knowledge"
    assert note_id in {
        item["id"] for item in _get_json(
            f"{live_web_process.base_url}/api/notes?" + urlencode({"user_id": user_id})
        )
    }

    live_web_process.restart()
    recovered = _get_json(
        f"{live_web_process.base_url}/api/knowledge-delete-commands/{command['command_id']}?"
        + urlencode({"user_id": user_id})
    )
    assert recovered["command"] == command
    assert recovered["status"] == "awaiting_confirmation"

    bad_digest_request = Request(
        f"{live_web_process.base_url}/api/knowledge-delete-commands/{command['command_id']}/decision",
        data=json.dumps({
            "user_id": user_id,
            "decision": "confirm",
            "command_digest": "0" * 64,
            "confirmation_ref": "release-user-confirmation",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(HTTPError) as digest_denied:
        urlopen(bad_digest_request, timeout=30)
    assert digest_denied.value.code == 409

    confirmed = _decide_delete(
        live_web_process,
        recovered,
        user_id=user_id,
        decision="confirm",
        confirmation_ref="release-user-confirmation",
    )
    replayed = _decide_delete(
        live_web_process,
        recovered,
        user_id=user_id,
        decision="confirm",
        confirmation_ref="release-user-confirmation",
    )
    assert confirmed["status"] == "executed"
    assert confirmed["receipt"] == replayed["receipt"]
    assert confirmed["receipt"]["command_digest"] == command["command_digest"]
    assert "events" not in replayed
    assert note_id not in {
        item["id"] for item in _get_json(
            f"{live_web_process.base_url}/api/notes?" + urlencode({"user_id": user_id})
        )
    }

    reject_ingest = _workspace_ingest(
        live_web_process,
        user_id,
        "这条知识必须保留。",
        source_type="document",
    )
    reject_note_id = str(reject_ingest["knowledge_items"][0]["knowledge_item_id"])
    rejected = _decide_delete(
        live_web_process,
        _prepare_delete(
            live_web_process,
            user_id=user_id,
            note_id=reject_note_id,
            idempotency_key=f"reject-{reject_note_id}",
            reason="user will reject",
        ),
        user_id=user_id,
        decision="reject",
    )
    assert rejected["status"] == "rejected"
    assert rejected["receipt"] is None
    assert reject_note_id in {
        item["id"] for item in _get_json(
            f"{live_web_process.base_url}/api/notes?" + urlencode({"user_id": user_id})
        )
    }
    _record(
        trace_archive,
        request,
        "E04.product_http",
        {
            "prepared": prepared,
            "recovered": recovered,
            "confirmed": confirmed,
            "replayed": replayed,
            "rejected": rejected,
            "cross_scope_denied": True,
            "digest_mismatch_denied": True,
        },
        profile="baseline",
    )


def test_product_e05_research_run_journey(
    live_web_search_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    detail = _run_research(
        live_web_search_process,
        f"product-e05-{uuid4().hex}",
        "Agent 工具协议最近的发展",
    )
    run = detail["run"]
    assert run["status"] in {"completed_verified", "completed_with_limitations"}
    assert detail["digest"] is not None
    assert detail["digest"]["items"]
    assert all(item["source_urls"] for item in detail["digest"]["items"])
    _record(
        trace_archive,
        request,
        "E05.product_http",
        {"research": detail},
        profile="baseline+web_search",
    )


def test_product_e08_ask_then_explicit_save(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    workspace_id = f"product-e08-{uuid4().hex}"
    _workspace_ingest(
        live_web_process,
        workspace_id,
        "SLO 预算用于衡量允许的错误量。",
        source_type="document",
    )
    before = _get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )
    answer = _workspace_ask(live_web_process, workspace_id, "SLO 预算有什么作用？")
    after_ask = _get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )
    assert len(after_ask) == len(before)
    saved = _post_json(
        f"{live_web_process.base_url}/api/workspace/solidify-conversation",
        {
            "user_id": workspace_id,
            "workspace_id": workspace_id,
            "messages": [
                {"role": "user", "content": "请保存结论：SLO 预算需要定期复核。"},
                {"role": "assistant", "content": answer["answer"]},
            ],
        },
    )
    assert saved["user_claim_count"] >= 1
    assert saved["rejected_assistant_claim_count"] == saved["assistant_candidate_count"]
    _record(
        trace_archive,
        request,
        "E08.product_http",
        {"ask": answer, "explicit_save": saved},
        profile="baseline",
    )


def _run_live_investigation_report_journey(
    live_web_search_process: LiveWebProcess,
    live_investigation_worker: tuple[subprocess.Popen[bytes], Path],
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
    *,
    evidence_id: str,
    goal_override: str | None = None,
    title: str = "Agent 协议变化调研",
    requirements_override: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    worker, worker_log_path = live_investigation_worker
    marker = uuid4().hex
    tenant_id = f"tenant-b03-{marker}"
    workspace_id = f"workspace-b03-{marker}"
    user_id = f"user-b03-{marker}"
    goal = goal_override or (
        "调研 2025-03-01 至 2025-06-30 公开发布的 MCP 与 A2A "
        "互操作规范版本或发布变化，至少比较两项；排除产品博客、非公开草案和没有正式发布说明的"
        f"实现代码；给出来源和局限。验收标记：{marker}。"
    )
    created = _request_json(
        f"{live_web_search_process.base_url}/api/investigation-projects",
        method="POST",
        expected_status=202,
        payload={
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "title": title,
            "goal": goal,
            "requirements": requirements_override or [{
                "requirement_id": "recent-protocol-changes",
                "statement": (
                    "比较至少两项指定时间窗口内公开发布的 MCP、A2A 或 "
                    "Agent-to-Agent 互操作规范版本或发布变化。"
                ),
                "acceptance_contract": (
                    "最终报告包含至少两项正式规范变化、来源、日期和明确局限，"
                    "并遵守排除项。"
                ),
            }],
            "budget": {
                "total_tokens": 300_000,
                "total_cost": 20,
                "max_tool_calls": 12,
                "max_agent_calls": 0,
                "max_plan_revisions": 4,
                "same_feedback_revision_limit": 1,
                "planning_tokens": 120_000,
                "execution_proposal_tokens": 40_000,
                "semantic_verification_tokens": 80_000,
                "synthesis_tokens": 60_000,
                "external_delegation_tokens": 0,
            },
            "idempotency_key": f"b03-{marker}",
        },
    )
    project_id = str(created["project_id"])
    query = urlencode({
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "user_id": user_id,
    })
    final_view = created
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if worker.poll() is not None:
            pytest.fail(
                "Investigation worker exited before terminal project state: "
                + worker_log_path.read_text(encoding="utf-8", errors="replace")
            )
        final_view = _get_json(
            f"{live_web_search_process.base_url}/api/investigation-projects/"
            f"{project_id}?{query}"
        )
        if final_view["state"] in {"completed", "failed", "cancelled", "paused"}:
            break
        time.sleep(1)

    worker_log = worker_log_path.read_text(encoding="utf-8", errors="replace")
    completion = final_view.get("completion_report")
    report_response = None
    report_error = None
    if final_view["state"] == "completed" and completion:
        try:
            report_response = _get_json(
                f"{live_web_search_process.base_url}/api/investigation-projects/"
                f"{project_id}/report?{query}"
            )
        except HTTPError as exc:
            report_error = {
                "status": exc.code,
                "body": exc.read().decode("utf-8", errors="replace"),
            }
    user_readable_report = (
        report_response.get("content")
        if isinstance(report_response, dict)
        else None
    )
    environment_failure_markers = (
        "structured parse failed",
        "ModelCallDeadlineExceeded",
        "provider call exceeded",
        "NOT_ENOUGH_BALANCE",
        "HTTP 401",
        "HTTP 402",
        "HTTP 429",
        "HTTP 432",
        "Error code: 503",
        "exceeds your plan's set usage limit",
        "local_overload",
    )
    failure_evidence = worker_log + json.dumps(final_view, ensure_ascii=False)
    environment_failed = any(
        marker in failure_evidence for marker in environment_failure_markers
    )
    delivered = bool(
        final_view["state"] == "completed"
        and completion
        and completion.get("final_artifact_ref")
        and isinstance(user_readable_report, str)
        and user_readable_report.strip()
    )
    accepted_plan = final_view.get("accepted_plan") or {}
    accepted_proposals = final_view.get("accepted_execution_proposals") or []
    proposal_keys = [
        (item["logical_subgoal_id"], item["subgoal_version"])
        for item in accepted_proposals
    ]
    repeated_proposal_keys = sorted({
        key for key in proposal_keys if proposal_keys.count(key) > 1
    })
    repair_observation = {
        "accepted_plan_version": int(accepted_plan.get("plan_version") or 0),
        "verification_wait_count": sum(
            item.get("reason") == "verification_repair"
            for item in final_view.get("waiting_reasons") or []
        ),
        "repair_execution_proposal_count": sum(
            int(item.get("plan_version") or 0) > 1
            for item in accepted_proposals
        ),
        "repeated_execution_proposal_keys": [list(key) for key in repeated_proposal_keys],
    }
    _record(
        trace_archive,
        request,
        evidence_id,
        {
            "natural_user_goal": goal,
            "created": created,
            "final_view": final_view,
            "worker_log_tail": worker_log[-20_000:],
            "environment_failed": environment_failed,
            "user_readable_report_present": bool(user_readable_report),
            "report_response": report_response,
            "report_error": report_error,
            "delivered": delivered,
            "repair_observation": repair_observation,
        },
        profile="baseline+web_search",
    )
    return {
        "goal": goal,
        "final_view": final_view,
        "environment_failed": environment_failed,
        "report_response": report_response,
        "delivered": delivered,
        "repair_observation": repair_observation,
    }


def test_e24_research_boundary_paired_baseline(
    live_web_search_process: LiveWebProcess,
    live_investigation_worker: tuple[subprocess.Popen[bytes], Path],
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    marker = uuid4().hex[:10]
    goal = (
        "调查 2025 年以来 MCP 与 A2A 互操作规范的公开变化，比较至少两项正式变化，"
        "说明机制、信任边界、生产采用风险、来源日期和局限，只使用可核验的官方来源。"
        f"验收标记：{marker}。"
    )
    research = _run_research(
        live_web_search_process,
        f"research-boundary-{marker}",
        goal,
    )
    conversation = _post_json(
        f"{live_web_search_process.base_url}/api/conversation/turn",
        {
            "conversation_id": f"conversation-boundary-{marker}",
            "user_id": f"conversation-boundary-{marker}",
            "messages": [{"role": "user", "content": goal}],
        },
    )
    conversation_trace = _get_json(
        f"{live_web_search_process.base_url}/api/conversation/runs/"
        f"{conversation['interaction_run_ref']}"
    )
    project = _run_live_investigation_report_journey(
        live_web_search_process,
        live_investigation_worker,
        trace_archive,
        request,
        evidence_id="E24.research_boundary_project",
        goal_override=goal,
        title="MCP 与 A2A 互操作规范对照",
        requirements_override=[{
            "requirement_id": "protocol-comparison",
            "statement": "比较至少两项 2025 年以来公开发布的 MCP 或 A2A 正式规范变化。",
            "acceptance_contract": (
                "报告覆盖机制、信任边界、生产采用风险、官方来源日期和明确局限。"
            ),
        }],
    )
    _record(
        trace_archive,
        request,
        "E24.research_boundary_comparison",
        {
            "natural_user_goal": goal,
            "research": research,
            "conversation": conversation,
            "conversation_trace": conversation_trace,
            "project": project,
        },
        profile="baseline+web_search",
    )
    assert research["run"]["status"] != "queued"
    assert conversation["disposition"] in {
        "answer", "clarification_required", "limitation", "failed"
    }
    assert project["environment_failed"] is False


def test_product_ip01_live_investigation_report(
    live_web_search_process: LiveWebProcess,
    live_investigation_worker: tuple[subprocess.Popen[bytes], Path],
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    journey = _run_live_investigation_report_journey(
        live_web_search_process,
        live_investigation_worker,
        trace_archive,
        request,
        evidence_id="IP01.product_http",
    )
    if journey["environment_failed"]:
        pytest.fail("live Investigation target failed at model/provider boundary")
    final_view = journey["final_view"]
    assert isinstance(final_view, dict)
    assert final_view["state"] == "completed"
    assert final_view["waiting_reasons"] == []
    observation = journey["repair_observation"]
    assert observation["repeated_execution_proposal_keys"] == []
    completion = final_view["completion_report"]
    assert completion["coverage"]["recent-protocol-changes"] == "verified"
    assert "unmet" not in completion["coverage"].values()
    assert final_view["commands"] == []
    report = journey["report_response"]
    assert isinstance(report, dict)
    content = str(report["content"])
    assert journey["delivered"]
    assert content.count("2025-") >= 2
    assert content.lower().count("http") >= 2
    assert "局限" in content or "limitation" in content.lower()
    assert "blog.modelcontextprotocol.io" not in content.lower()
    assert "developers.googleblog.com" not in content.lower()


def test_product_e23_durable_investigation_from_goal_entry(
    live_web_search_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    workspace_id = f"product-e23-{uuid4().hex}"
    goal = (
        "请在后台持续调查主流 Agent 协议最近一年的关键变化，覆盖协议机制、信任边界、"
        "生产采用风险和迁移建议，优先使用官方来源。完成后交付一份带逐项来源的中文报告。"
        "这项调查可以持续一段时间，我需要之后能查看进度、暂停或调整来源范围。"
    )
    assert all(
        term not in goal
        for term in ("InvestigationProject", "Workflow", "Tool", "Agent ID", "执行顺序")
    )
    started = _post_json(
        f"{live_web_search_process.base_url}/api/conversation/turn",
        {
            "conversation_id": workspace_id,
            "user_id": workspace_id,
            "messages": [{"role": "user", "content": goal}],
        },
    )
    initial_trace = _get_json(
        f"{live_web_search_process.base_url}/api/conversation/runs/"
        f"{started['interaction_run_ref']}"
    )
    _record(
        trace_archive,
        request,
        "E23.product_http",
        {"natural_user_goal": goal, "result": started, "trace": initial_trace},
        profile="baseline+web_search",
    )
    project_ref = started.get("project_reference")
    assert started["disposition"] == "background_started"
    assert isinstance(project_ref, dict)
    assert str(project_ref.get("project_id", "")).startswith("iprj_")
    query = urlencode({
        "tenant_id": project_ref["tenant_id"],
        "workspace_id": project_ref["workspace_id"],
        "user_id": project_ref["user_id"],
    })
    assert project_ref["workspace_id"] == workspace_id
    assert project_ref["user_id"] == workspace_id
    project = _get_json(
        f"{live_web_search_process.base_url}/api/investigation-projects/"
        f"{project_ref['project_id']}?{query}"
    )
    trace = _get_json(
        f"{live_web_search_process.base_url}/api/conversation/runs/"
        f"{started['interaction_run_ref']}"
    )
    assert project["project_id"] == project_ref["project_id"]
    assert project["state"] in {"planning", "active", "paused"}
    assert trace["project_reference"]["project_id"] == project_ref["project_id"]
    assert "completion_report" not in started


def test_product_e14_conversation_governed_save(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    workspace_id = f"product-e14-{uuid4().hex}"
    conclusion = f"SLO 预算复核标记 {uuid4().hex}"
    user_text = f"请保存结论：{conclusion}。保存前先让我确认。"
    before = _get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )

    prepared = _post_json(
        f"{live_web_process.base_url}/api/conversation/turn",
        {
            "conversation_id": workspace_id,
            "user_id": workspace_id,
            "messages": [{"role": "user", "content": user_text}],
        },
    )
    pending = prepared["pending_confirmation"]
    command = pending["command"]
    after_prepare = _get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )
    assert prepared["disposition"] == "confirmation_required"
    assert pending["status"] == "awaiting_confirmation"
    assert pending.get("receipt") is None
    assert command["source_message_indexes"] == [0]
    assert command["messages"] == [{"role": "user", "content": conclusion}]
    assert len(after_prepare) == len(before)

    live_web_process.restart()
    recovered_trace = _get_json(
        f"{live_web_process.base_url}/api/conversation/runs/"
        f"{prepared['interaction_run_ref']}"
    )
    assert recovered_trace["knowledge_save_operation"]["command"] == command
    assert recovered_trace["knowledge_save_operation"]["status"] == "awaiting_confirmation"

    decision_url = (
        f"{live_web_process.base_url}/api/conversation/runs/"
        f"{prepared['interaction_run_ref']}/knowledge-save-decision"
    )
    unauthorized_request = Request(
        decision_url,
        data=json.dumps({
            "user_id": f"attacker-{uuid4().hex}",
            "workspace_id": workspace_id,
            "decision": "confirm",
            "command_digest": command["command_digest"],
            "confirmation_ref": "e14-cross-scope",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(HTTPError) as cross_scope:
        urlopen(unauthorized_request, timeout=30)
    assert cross_scope.value.code == 404
    assert len(_get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )) == len(before)

    confirmed = _post_json(
        decision_url,
        {
            "user_id": workspace_id,
            "workspace_id": workspace_id,
            "decision": "confirm",
            "command_digest": command["command_digest"],
            "confirmation_ref": "e14-user-confirmation",
        },
    )
    after_first_confirm = _get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )
    replayed = _post_json(
        decision_url,
        {
            "user_id": workspace_id,
            "workspace_id": workspace_id,
            "decision": "confirm",
            "command_digest": command["command_digest"],
            "confirmation_ref": "e14-user-confirmation",
        },
    )
    after_confirm = _get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )
    before_claim_ids = {claim["claim_id"] for claim in before}
    saved_claims = [
        claim for claim in after_first_confirm
        if claim["claim_id"] not in before_claim_ids
    ]
    assert confirmed["status"] == "executed"
    assert confirmed["receipt"] == replayed["receipt"]
    assert confirmed["receipt"]["command_digest"] == command["command_digest"]
    assert saved_claims
    assert any(
        str(claim["statement"]).strip().rstrip("。") == conclusion
        for claim in saved_claims
    )
    assert not any(
        "请求保存" in str(claim["statement"])
        or "保存前" in str(claim["statement"])
        for claim in saved_claims
    )
    assert set(confirmed["receipt"]["claim_ids"]) == {
        claim["claim_id"] for claim in saved_claims
    }
    assert len(after_confirm) == len(after_first_confirm)

    _record(
        trace_archive,
        request,
        "E14.product_http",
        {
            "natural_user_text": user_text,
            "prepared": prepared,
            "recovered_trace": recovered_trace,
            "cross_scope_denied": True,
            "confirmed": confirmed,
            "replayed": replayed,
            "saved_claims": saved_claims,
            "claim_count_delta": len(after_first_confirm) - len(before),
            "replay_claim_count_delta": len(after_confirm) - len(after_first_confirm),
        },
        profile="baseline",
    )


def test_product_e22_governed_delete_from_goal_entry(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    workspace_id = f"product-e22-{uuid4().hex}"
    marker = uuid4().hex[:10]
    target_text = f"错误知识条目 {marker}：生产切换窗口是周一 09:00。"
    target = _workspace_ingest(
        live_web_process,
        workspace_id,
        target_text,
        source_type="document",
    )
    target_id = str(target["knowledge_items"][0]["knowledge_item_id"])
    other_workspace = f"other-{workspace_id}"
    other_secret = f"other-secret-{uuid4().hex}"
    _workspace_ingest(
        live_web_process,
        other_workspace,
        f"{other_secret} 必须保留。",
        source_type="document",
    )
    user_text = f"删除我刚才标记错误的那条知识：错误知识条目 {marker}。删除前让我确认。"
    assert all(term not in user_text for term in ("delete command", "Workflow", "Tool"))
    prepared = _post_json(
        f"{live_web_process.base_url}/api/conversation/turn",
        {
            "conversation_id": workspace_id,
            "user_id": workspace_id,
            "messages": [{"role": "user", "content": user_text}],
        },
    )
    initial_trace = _get_json(
        f"{live_web_process.base_url}/api/conversation/runs/"
        f"{prepared['interaction_run_ref']}"
    )
    _record(
        trace_archive,
        request,
        "E22.product_http",
        {
            "natural_user_goal": user_text,
            "target_id": target_id,
            "prepared": prepared,
            "trace": initial_trace,
        },
        profile="baseline",
    )
    pending = prepared.get("pending_confirmation")
    assert prepared["disposition"] == "confirmation_required"
    assert isinstance(pending, dict)
    assert pending["kind"] == "knowledge_delete"
    assert pending["operation"]["status"] == "awaiting_confirmation"
    command = pending["operation"]["command"]
    assert command["target_note_id"] == target_id
    assert other_secret not in json.dumps(prepared, ensure_ascii=False)
    assert target_id in {
        item["id"]
        for item in _get_json(
            f"{live_web_process.base_url}/api/notes?" + urlencode({"user_id": workspace_id})
        )
    }
    confirmed = _decide_delete(
        live_web_process,
        pending["operation"],
        user_id=workspace_id,
        decision="confirm",
        confirmation_ref="goal-entry-confirmation",
    )
    replayed = _decide_delete(
        live_web_process,
        pending["operation"],
        user_id=workspace_id,
        decision="confirm",
        confirmation_ref="goal-entry-confirmation",
    )
    assert confirmed["status"] == "executed"
    assert confirmed["receipt"] == replayed["receipt"]
    assert target_id not in {
        item["id"]
        for item in _get_json(
            f"{live_web_process.base_url}/api/notes?" + urlencode({"user_id": workspace_id})
        )
    }


def test_product_e09_multi_source_capture(
    live_web_reader_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    user_id = f"product-e09-{uuid4().hex}"
    text_marker = f"文本来源标记 {uuid4().hex}"
    text_result = _workspace_ingest(
        live_web_reader_process,
        user_id,
        text_marker,
        source_type="text",
    )
    conversation_marker = f"请保存会话结论 {uuid4().hex}"
    conversation_result = _post_json(
        f"{live_web_reader_process.base_url}/api/workspace/solidify-conversation",
        {
            "user_id": user_id,
            "workspace_id": user_id,
            "messages": [{"role": "user", "content": conversation_marker}],
        },
    )
    upload_marker = f"文件来源标记 {uuid4().hex}"
    upload_result = _post_text_attachment(
        f"{live_web_reader_process.base_url}/api/workspace/ingest-upload",
        filename="capture-source.txt",
        content=upload_marker,
        fields={
            "user_id": user_id,
            "workspace_id": user_id,
        },
    )
    url = os.getenv(
        "PERSONAL_AGENT_E2E_WEB_READER_URL",
        "https://example.com/",
    )
    url_result = _post_json(
        f"{live_web_reader_process.base_url}/api/workspace/ingest-url",
        {"url": url, "user_id": user_id, "workspace_id": user_id},
    )
    captured_text = str(url_result["ingest_result"]["artifact"]["text"]).strip()
    assert len(captured_text) >= 100
    normalized_captured_text = "\n".join(
        line.strip() for line in captured_text.splitlines() if line.strip()
    )
    notes = _get_json(
        f"{live_web_reader_process.base_url}/api/notes?" + urlencode({"user_id": user_id})
    )
    notes_by_id = {str(item["id"]): item for item in notes}
    artifacts = _get_json(
        f"{live_web_reader_process.base_url}/api/workspace/artifacts?"
        + urlencode({"workspace_id": user_id})
    )
    assert isinstance(artifacts, list)
    artifacts_by_id = {str(item["artifact_id"]): item for item in artifacts}
    text_artifact_id = str(text_result["artifact"]["artifact_id"])
    assert text_artifact_id
    assert str(text_result["artifact"]["text"]) == text_marker
    assert str(artifacts_by_id[text_artifact_id]["text"]) == text_marker
    conversation_ingest = conversation_result["ingest_result"]
    conversation_artifact = conversation_ingest["artifact"]
    conversation_artifact_id = str(conversation_artifact["artifact_id"])
    conversation_span_ids = {
        str(item["evidence_span_id"])
        for item in conversation_ingest["evidence_spans"]
    }
    conversation_item_ids = {
        str(item["knowledge_item_id"])
        for item in conversation_ingest["knowledge_items"]
    }
    assert conversation_artifact_id
    assert conversation_artifact["source_type"] == "conversation"
    assert conversation_marker in str(conversation_artifact["text"])
    assert conversation_span_ids
    assert all(
        str(item["artifact_id"]) == conversation_artifact_id
        for item in conversation_ingest["evidence_blocks"]
    )
    assert any(
        conversation_marker in str(item["text_span"])
        for item in conversation_ingest["evidence_spans"]
    )
    assert conversation_item_ids
    assert conversation_item_ids <= notes_by_id.keys()
    assert all(
        conversation_span_ids.intersection(
            str(span_id) for span_id in notes_by_id[item_id]["evidence_span_ids"]
        )
        for item_id in conversation_item_ids
    )
    assert upload_result["resource_ref"]["resource_id"]
    assert sum(
        str(item.get("artifact_id")) == text_artifact_id
        for item in artifacts
    ) == 1
    upload_artifacts = [
        item for item in artifacts
        if upload_marker in str(item.get("text", ""))
    ]
    url_artifacts = [
        item for item in artifacts
        if url in str(item.get("text", ""))
        and str(item.get("text", "")) == normalized_captured_text
    ]
    assert len(upload_artifacts) == 1
    assert len(url_artifacts) == 1
    assert str(url_artifacts[0]["source_type"]) == "link"
    assert "不要只保存 URL 或这条指令" not in str(url_artifacts[0]["text"])
    assert str(upload_artifacts[0]["source_type"]) == "note"
    assert str(conversation_artifact_id) in artifacts_by_id
    _record(
        trace_archive,
        request,
        "E09.product_http",
        {
            "text_artifact": text_result["artifact"],
            "conversation_artifact": conversation_artifact,
            "conversation_knowledge_item_ids": sorted(conversation_item_ids),
            "retrieved_artifact_ids": [
                str(upload_artifacts[0]["artifact_id"]),
                str(url_artifacts[0]["artifact_id"]),
            ],
            "upload": upload_result,
            "url_ingest": url_result,
            "retrievable_note_ids": [item["id"] for item in notes],
        },
        profile="baseline+web_reader",
    )


def test_product_e10_knowledge_lifecycle(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    workspace_id = f"product-e10-{uuid4().hex}"
    initial = _workspace_ingest(
        live_web_process,
        workspace_id,
        "Orion 的维护窗口是周三。",
        source_type="document",
    )
    old_claim = initial["claims"][0]
    corrected = _post_json(
        f"{live_web_process.base_url}/api/workspace/claims/{old_claim['claim_id']}/correct",
        {"corrected_statement": "Orion 的维护窗口是周四。", "user_id": workspace_id},
    )
    assert corrected["old_claim"]["state"] == "superseded"
    assert corrected["new_claim"]["state"] == "active"
    _workspace_ingest(
        live_web_process,
        workspace_id,
        "Orion 的维护窗口不是周四。",
        source_type="document",
    )
    relations = _get_json(
        f"{live_web_process.base_url}/api/workspace/relations?"
        + urlencode({"workspace_id": workspace_id})
    )
    note_id = str(initial["knowledge_items"][0]["knowledge_item_id"])
    delete_operation = _prepare_delete(
        live_web_process,
        user_id=workspace_id,
        note_id=note_id,
        idempotency_key=f"e10-delete-{note_id}",
        reason="lifecycle restore verification",
    )
    deleted = _decide_delete(
        live_web_process,
        delete_operation,
        user_id=workspace_id,
        decision="confirm",
        confirmation_ref="e10-delete-confirmation",
    )
    live_web_process.restart()
    restore_prepared = _prepare_restore(
        live_web_process,
        deleted,
        user_id=workspace_id,
        idempotency_key=f"e10-restore-{note_id}",
        reason="restore deleted knowledge and its claims",
    )
    restored = _decide_restore(
        live_web_process,
        restore_prepared,
        user_id=workspace_id,
        decision="confirm",
        confirmation_ref="e10-restore-confirmation",
    )
    replayed = _decide_restore(
        live_web_process,
        restore_prepared,
        user_id=workspace_id,
        decision="confirm",
        confirmation_ref="e10-restore-confirmation",
    )
    notes = _get_json(
        f"{live_web_process.base_url}/api/notes?" + urlencode({"user_id": workspace_id})
    )
    claims = _get_json(
        f"{live_web_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )
    assert restored["status"] == "executed"
    assert restored["receipt"] == replayed["receipt"]
    assert restored["receipt"]["restored_note_id"] == note_id
    assert set(restored["receipt"]["affected_claim_ids"]) <= {
        claim["claim_id"] for claim in claims
    }
    assert all(claim["state"] != "deleted" for claim in claims)
    assert sum(item["id"] == note_id for item in notes) == 1
    assert any(item["relation_type"] in {"supersede", "potential_conflict", "conflict"} for item in relations)
    with pytest.raises(HTTPError) as removed_snapshot_route:
        _post_json(
            f"{live_web_process.base_url}/api/memory/notes/{note_id}/restore",
            {"user_id": workspace_id, "snapshot_id": "legacy"},
        )
    assert removed_snapshot_route.value.code in {404, 405}
    _record(
        trace_archive,
        request,
        "E10.product_http",
        {
            "correction": corrected,
            "relations": relations,
            "delete": deleted,
            "restore_prepare": restore_prepared,
            "restore": restored,
            "restore_replay": replayed,
        },
        profile="baseline",
    )


def test_product_e11_review_feedback_journey(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    _workspace_ingest(
        live_web_process,
        "default",
        f"复习事实 {uuid4().hex}：幂等请求可安全重试。",
        source_type="document",
    )
    cards = _get_json(f"{live_web_process.base_url}/api/review/cards?due_only=true")
    assert cards["items"]
    card = cards["items"][0]
    feedback = _post_json(
        f"{live_web_process.base_url}/api/review/cards/{card['id']}/feedback",
        {"outcome": "remembered"},
    )
    live_web_process.restart()
    cards_after = _get_json(f"{live_web_process.base_url}/api/review/cards?due_only=true")
    assert feedback["state"] == "answered"
    assert card["id"] not in {item["id"] for item in cards_after["items"]}
    _record(
        trace_archive,
        request,
        "E11.product_http",
        {"review_card": card, "feedback": feedback, "after_restart": cards_after},
        profile="baseline",
    )


def test_product_e12_knowledge_maintenance_journey(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    workspace_id = f"product-e12-{uuid4().hex}"
    for text in (
        "Nova 默认启用缓存。",
        "Nova 默认关闭缓存。",
        "一个孤立事实是木星拥有大红斑。",
    ):
        _workspace_ingest(live_web_process, workspace_id, text, source_type="document")
    plan = _post_json(
        f"{live_web_process.base_url}/api/workspace/review-plan",
        {"workspace_id": workspace_id, "limit": 20},
    )
    projection = _post_json(
        f"{live_web_process.base_url}/api/workspace/graph-projections",
        {"workspace_id": workspace_id, "limit": 100},
    )
    assert plan["review_items"] or plan["knowledge_gaps"]
    assert projection["backlink_ok"] is True
    assert all(item["source_claim_id"] for item in projection["projections"])
    _record(
        trace_archive,
        request,
        "E12.product_http",
        {"maintenance_plan": plan, "graph_projection": projection},
        profile="baseline",
    )


def _scheduled_delivery_journey(server: LiveWebProcess) -> dict[str, object]:
    user_id = f"scheduled-{uuid4().hex}"
    target_id = user_id
    subscription = _post_json(
        f"{server.base_url}/api/research/subscriptions",
        {
            "user_id": user_id,
            "name": "Release scheduled intelligence",
            "topic": "Agent protocol releases",
            "instructions": "Use official sources and expose limitations.",
            "seed_queries": ["Agent protocol official release"],
            "max_items": 3,
            "delivery": {"channel": "in_app", "target_type": "user_id", "target_id": target_id},
        },
    )
    queued = _post_json(
        f"{server.base_url}/api/research/subscriptions/{subscription['id']}/run-now",
        {},
    )
    worker = subprocess.run(
        (
            sys.executable,
            "-m",
            "personal_agent.adapters.cli.main",
            "worker",
            "--queue",
            "research",
            "--max-tasks",
            "2",
            "--poll-seconds",
            "0.1",
        ),
        cwd=server.cwd,
        env=server.child_env,
        text=True,
        capture_output=True,
        timeout=600,
    )
    assert worker.returncode == 0, worker.stdout + worker.stderr
    detail = _get_json(
        f"{server.base_url}/api/research/runs/{queued['id']}?" + urlencode({"user_id": user_id})
    )
    deliveries = _get_json(
        f"{server.base_url}/api/research/deliveries?"
        + urlencode({"user_id": user_id, "subscription_id": subscription["id"]})
    )
    assert len(deliveries["items"]) == 1
    assert deliveries["items"][0]["status"] == "sent"
    feedback = _post_json(
        f"{server.base_url}/api/research/feedback",
        {"run_id": queued["id"], "subscription_id": subscription["id"], "action": "useful"},
    )
    return {
        "subscription": subscription,
        "run": detail,
        "feedback": feedback,
        "deliveries": deliveries,
        "worker_stdout": worker.stdout,
    }


def test_product_e13_scheduled_intelligence_journey(
    live_delivery_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    result = _scheduled_delivery_journey(live_delivery_process)
    run = result["run"]["run"]
    assert run["subscription_id"] == result["subscription"]["id"]
    assert result["run"]["digest"] is not None
    assert result["feedback"]["run_id"] == run["id"]
    _record(
        trace_archive,
        request,
        "E13.product_http",
        result,
        profile="baseline+web_search+delivery",
    )
