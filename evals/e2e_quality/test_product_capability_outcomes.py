"""Release E2E journeys for product and composite capability claims.

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
    _new_github_mcp_web_process,
    _new_live_web_process,
    _new_notion_mcp_web_process,
    _post_json,
    _post_text_attachment,
    _require_live_dependencies,
    _yield_started_server,
    test_e16_http_process_reads_github_through_real_mcp_gateway as _profile_e16,
    test_e17_http_process_delegates_to_real_a2a_and_verifies_parent_result as _profile_e17,
    test_e18_http_process_reads_notion_through_real_mcp_gateway as _profile_e18,
    test_e19_http_process_mcp_capability_unavailable_fails_closed as _profile_e19,
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
    _require_profile(
        settings.web_search.api_key,
        "web-search product E2E requires PERSONAL_AGENT_WEB_SEARCH_API_KEY",
    )
    overrides = {
        "PERSONAL_AGENT_WEB_SEARCH_PROVIDER": settings.web_search.provider,
        "PERSONAL_AGENT_WEB_SEARCH_API_KEY": str(settings.web_search.api_key),
        "PERSONAL_AGENT_WEB_SEARCH_BASE_URL": str(settings.web_search.base_url or ""),
    }
    yield from _yield_started_server(
        _new_live_web_process(server_temp_dir, settings, child_env_overrides=overrides)
    )


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
        settings.web_search.api_key,
        "scheduled-intelligence E2E requires PERSONAL_AGENT_WEB_SEARCH_API_KEY",
    )
    yield from _yield_started_server(_new_live_web_process(server_temp_dir, settings))


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    timeout: float = 300,
) -> object:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    with urlopen(request, timeout=timeout) as response:
        assert response.status == 200
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
            "authorization_digest": command["authorization_digest"],
            "execution_command_digest": command["execution_command_digest"],
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
            "authorization_digest": command["authorization_digest"],
            "execution_command_digest": command["execution_command_digest"],
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
            "authorization_digest": "0" * 64,
            "execution_command_digest": command["execution_command_digest"],
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
    assert confirmed["receipt"]["execution_command_digest"] == command["execution_command_digest"]
    assert [event["event_type"] for event in replayed["events"]].count("executed") == 1
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
    assert run["status"] in {
        "completed_verified",
        "completed_with_limitations",
        "partial_no_supported_claims",
        "partial_budget_exhausted",
        "partial_low_yield",
    }
    if detail["digest"] is not None:
        assert all(item["source_urls"] for item in detail["digest"]["items"])
    _record(
        trace_archive,
        request,
        "E05.product_http",
        {"research": detail},
        profile="baseline+web_search",
    )


def test_product_e06_mcp_read_extension(
    live_web_process: LiveWebProcess,
    server_temp_dir: Path,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    # Each profile is a real production assembly, but they run sequentially so
    # one E2E journey cannot overload the shared model provider with idle peers.
    live_web_process.stop()
    try:
        github_server = _new_github_mcp_web_process(
            server_temp_dir / "e06-github-mcp",
            live_web_process.settings,
        )
        for running_server in _yield_started_server(github_server):
            _profile_e16(running_server, trace_archive, request)

        notion_server = _new_notion_mcp_web_process(
            server_temp_dir / "e06-notion-mcp",
            live_web_process.settings,
        )
        for running_server in _yield_started_server(notion_server):
            _profile_e18(running_server, trace_archive, request)

        live_web_process.start()
        _profile_e19(live_web_process, trace_archive, request)
    finally:
        if live_web_process.process is None:
            live_web_process.start()
    _record(
        trace_archive,
        request,
        "E06.product_http",
        {
            "github_read_completed": True,
            "notion_read_completed": True,
            "capability_unavailable_confirmed": True,
        },
        profile="baseline+github_mcp+notion_mcp",
    )


def test_product_e07_a2a_research_delegation(
    live_a2a_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    _profile_e17(live_a2a_web_process, trace_archive, request)
    _record(
        trace_archive,
        request,
        "E07.product_http",
        {"real_a2a_artifact_completed": True},
        profile="baseline+gpt_researcher_a2a",
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


def test_composite_c01_personal_research_analyst(
    live_web_search_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    workspace_id = f"composite-c01-{uuid4().hex}"
    _workspace_ingest(
        live_web_search_process,
        workspace_id,
        "本地资料只记录 MCP 负责工具连接。",
        source_type="document",
    )
    local_answer = _workspace_ask(live_web_search_process, workspace_id, "Agent 协议有哪些最新变化？")
    research = _run_research(live_web_search_process, workspace_id, "Agent 协议最新变化")
    before_save = _get_json(
        f"{live_web_search_process.base_url}/api/workspace/claims?"
        + urlencode({"workspace_id": workspace_id})
    )
    saved = _post_json(
        f"{live_web_search_process.base_url}/api/workspace/solidify-conversation",
        {
            "user_id": workspace_id,
            "workspace_id": workspace_id,
            "messages": [{"role": "user", "content": "确认保存结论：外部研究需要与个人资料分开标注。"}],
        },
    )
    assert local_answer["answer_claim_saved_count"] == 0
    assert research["run"]["status"] != "queued"
    assert saved["user_claim_count"] >= 1
    _record(
        trace_archive,
        request,
        "C01.composite_http",
        {"grounded_ask": local_answer, "research": research, "claims_before_save": before_save, "save": saved},
        profile="baseline+web_search",
    )


def test_composite_c02_continuous_knowledge_steward(
    live_delivery_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    result = _scheduled_delivery_journey(live_delivery_process)
    assert result["run"]["digest"] is not None
    _record(
        trace_archive,
        request,
        "C02.composite_http",
        result,
        profile="baseline+web_search+delivery",
    )


def test_composite_c03_personalized_learning_agent(
    live_web_search_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    workspace_id = "default"
    _workspace_ingest(
        live_web_search_process,
        workspace_id,
        f"学习事实 {uuid4().hex}：向量检索使用嵌入相似度。",
        source_type="document",
    )
    cards = _get_json(f"{live_web_search_process.base_url}/api/review/cards?due_only=true")
    card = cards["items"][0]
    feedback = _post_json(
        f"{live_web_search_process.base_url}/api/review/cards/{card['id']}/feedback",
        {"outcome": "forgotten"},
    )
    research = _run_research(live_web_search_process, workspace_id, "向量检索的最新最佳实践")
    assert feedback["state"] == "due"
    assert research["run"]["status"] != "queued"
    _record(
        trace_archive,
        request,
        "C03.composite_http",
        {"review_card": card, "feedback": feedback, "research": research},
        profile="baseline+web_search",
    )


def test_composite_c04_expert_collaboration_agent(
    live_a2a_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    _profile_e17(live_a2a_web_process, trace_archive, request)
    _record(
        trace_archive,
        request,
        "C04.composite_http",
        {"delegation_and_parent_synthesis_completed": True},
        profile="baseline+gpt_researcher_a2a",
    )
