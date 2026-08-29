"""Release E2E journeys for the canonical ordinary-interaction loop."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
from threading import Thread
import time
from typing import Iterator
from urllib.error import URLError
from uuid import uuid4

import pytest

from evals.e2e_quality.test_product_capability_outcomes import _knowledge_ingest, _record
from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _new_live_web_process,
    _post_json,
    _require_live_dependencies,
    _yield_live_a2a_web_process,
    _yield_started_server,
)


pytestmark = pytest.mark.integration
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)


def _conversation(
    server: LiveWebProcess,
    *,
    conversation_id: str,
    text: str,
    interaction_run_ref: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "conversation_id": conversation_id,
        "messages": [{"role": "user", "content": text}],
    }
    if interaction_run_ref is not None:
        payload["interaction_run_ref"] = interaction_run_ref
    return _post_json(f"{server.base_url}/api/conversation/turn", payload)


def _trace(server: LiveWebProcess, run_ref: str) -> dict[str, object]:
    return _get_json(f"{server.base_url}/api/conversation/runs/{run_ref}")


def _capture_memory_text(
    server: LiveWebProcess,
    *,
    user_id: str,
    text: str,
) -> dict[str, object]:
    return _post_json(
        f"{server.base_url}/api/tools/capture_text/execute",
        {
            "tenant_id": "personal-agent",
            "user_id": user_id,
            "kwargs": {
                "text": text,
                "user_id": user_id,
                "source_type": "text",
            },
        },
    )


def _assert_natural_user_text(text: str, *internal_terms: str) -> None:
    assert all(term not in text for term in internal_terms)


@pytest.fixture(scope="module")
def live_budget_web_process(
    server_temp_dir: Path,
) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    server = _new_live_web_process(
        server_temp_dir,
        settings,
        child_env_overrides={"PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS": "1"},
    )
    yield from _yield_started_server(server)


@pytest.fixture(scope="module")
def live_a2a_web_process(server_temp_dir: Path) -> Iterator[LiveWebProcess]:
    yield from _yield_live_a2a_web_process(server_temp_dir)


def test_l01_http_natural_recall_uses_observed_personal_knowledge(
    live_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = f"l01-{uuid4().hex[:8]}"
    project_name = f"Orchid-{marker}"
    expected_code = f"cobalt-{uuid4().hex[:10]}"
    other_user_id = f"other-{marker}"
    other_code = f"scarlet-{uuid4().hex[:10]}"
    with ThreadPoolExecutor(max_workers=2) as executor:
        seeded_future = executor.submit(
            _knowledge_ingest,
            live_web_process,
            "default",
            (
                f"我为项目 {project_name} 记录的验收颜色代号是 {expected_code}。"
                "这是项目验收时需要回忆的个人知识。"
            ),
        )
        other_seeded_future = executor.submit(
            _knowledge_ingest,
            live_web_process,
            other_user_id,
            (
                f"另一个用户为项目 {project_name} 保存的验收颜色代号是 {other_code}。"
                "该信息不属于 default 用户。"
            ),
        )
        seeded = seeded_future.result()
        other_seeded = other_seeded_future.result()
    assert expected_code in str(seeded["artifact"]["text"])
    assert other_code in str(other_seeded["artifact"]["text"])
    assert any(
        expected_code in str(span["text_span"])
        for span in seeded["evidence_spans"]
    )
    assert any(
        other_code in str(span["text_span"])
        for span in other_seeded["evidence_spans"]
    )

    user_text = f"我之前记下的 {project_name} 项目验收颜色代号是什么？"
    _assert_natural_user_text(
        user_text,
        "list_recent_notes",
        "get_note",
        "find_similar_notes",
        "ToolResult",
    )
    result = _conversation(
        live_web_process,
        conversation_id=f"conversation-{marker}",
        text=user_text,
    )
    trace = _trace(live_web_process, str(result["interaction_run_ref"]))
    inputs = list(trace["inputs"])
    observed_tool_results = [
        item
        for item in inputs
        if item["kind"] == "tool_result" and item["status"] == "succeeded"
    ]
    supporting_observations = [
        item
        for item in observed_tool_results
        if expected_code in json.dumps(item["payload"], ensure_ascii=False)
    ]
    final_message = str(result["message"]["content"]).strip()

    _record(
        trace_archive,
        request,
        "L01.complex_loop_http",
        {
            "seeded": seeded,
            "other_scope_seeded": other_seeded,
            "natural_user_text": user_text,
            "result": result,
            "trace": trace,
        },
        profile="baseline",
    )
    assert result["disposition"] == "answer"
    assert expected_code in final_message
    assert other_code not in final_message
    assert other_code not in json.dumps(trace, ensure_ascii=False)
    assert supporting_observations
    assert trace["execution_order"]
    assert "working_plans" not in trace


def test_l07_http_conversation_save_is_recalled_in_a_new_conversation(
    live_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = f"l01b-{uuid4().hex[:8]}"
    first_conversation_id = f"conversation-save-{marker}"
    second_conversation_id = f"conversation-recall-{marker}"
    project_name = f"Juniper-{marker}"
    expected_code = f"amber-{uuid4().hex[:10]}"
    save_text = (
        f"请记住：{project_name} 项目的验收颜色代号是 {expected_code}。"
        "保存前先让我确认。"
    )
    prepared = _conversation(
        live_web_process,
        conversation_id=first_conversation_id,
        text=save_text,
    )
    pending = prepared["pending_confirmation"]
    assert prepared["disposition"] == "confirmation_required"
    assert pending["status"] == "awaiting_confirmation"

    confirmed = _post_json(
        f"{live_web_process.base_url}/api/conversation/runs/"
        f"{prepared['interaction_run_ref']}/knowledge-save-decision",
        {
            "decision": "confirm",
            "confirmation_ref": f"{marker}-confirmation",
        },
    )
    assert confirmed["status"] == "executed"

    recall_text = f"我之前记下的 {project_name} 项目验收颜色代号是什么？"
    recalled = _conversation(
        live_web_process,
        conversation_id=second_conversation_id,
        text=recall_text,
    )
    trace = _trace(live_web_process, str(recalled["interaction_run_ref"]))
    final_message = str(recalled["message"]["content"]).strip()
    _record(
        trace_archive,
        request,
        "L07.conversation_save_cross_conversation_recall",
        {
            "save_text": save_text,
            "prepared": prepared,
            "confirmed": confirmed,
            "recall_text": recall_text,
            "recalled": recalled,
            "trace": trace,
        },
        profile="baseline",
    )
    assert recalled["disposition"] == "answer"
    assert expected_code in final_message
    assert any(
        expected_code in json.dumps(item["payload"], ensure_ascii=False)
        for item in trace["inputs"]
        if (
            item["kind"] == "context_evidence"
            and item["capability_id"] == "personal_knowledge_context"
            and item["status"] == "succeeded"
        )
    )


def test_l02_http_independent_reads_use_safe_concurrency(
    live_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = f"l02-{uuid4().hex[:8]}"
    recent_marker = f"Quartz-{uuid4().hex[:10]}"
    seeded = _capture_memory_text(
        live_web_process,
        user_id="default",
        text=f"我刚记录的 {marker} 项目观察代号是 {recent_marker}。",
    )
    assert seeded["ok"] is True
    user_text = (
        "请根据我的知识库，分别概括我最近记录的内容，并告诉我当前有没有明显的"
        "知识缺口、孤立信息或冲突。"
    )
    _assert_natural_user_text(
        user_text,
        "list_recent_notes",
        "inspect_knowledge_gaps",
        "ToolResult",
        "并行调用",
    )
    result = _conversation(
        live_web_process,
        conversation_id=f"conversation-{marker}",
        text=user_text,
    )
    trace = _trace(live_web_process, str(result["interaction_run_ref"]))
    final_message = str(result["message"]["content"]).strip()
    observed_capabilities = {
        str(item["capability_id"])
        for item in trace["inputs"]
        if item["kind"] == "tool_result" and item["status"] == "succeeded"
    }

    _record(
        trace_archive,
        request,
        "L02.complex_loop_http",
        {
            "seeded": seeded,
            "natural_user_text": user_text,
            "result": result,
            "trace": trace,
        },
        profile="baseline",
    )
    assert result["disposition"] == "answer"
    assert recent_marker in final_message
    assert any(word in final_message for word in ("缺口", "冲突", "孤立", "没有发现"))
    assert {"list_recent_notes", "inspect_knowledge_gaps"} <= observed_capabilities
    assert any(len(batch) == 2 for batch in trace["concurrent_batches"])
    assert len(trace["inputs"]) >= 2


def test_l03_http_process_restart_rebuilds_from_committed_facts(
    live_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = uuid4().hex[:8]
    run_ref = f"irun_l03_{marker}"
    conversation_id = f"conversation-l03-{marker}"
    project_name = f"Harbor-l03-{marker}"
    expected_code = f"indigo-{uuid4().hex[:10]}"
    other_code = f"orange-{uuid4().hex[:10]}"
    seeded = _capture_memory_text(
        live_web_process,
        user_id="default",
        text=f"我为 {project_name} 保存的完整验收记录中，颜色代号是 {expected_code}。",
    )
    other_seeded = _capture_memory_text(
        live_web_process,
        user_id=f"other-l03-{marker}",
        text=f"另一个用户的 {project_name} 颜色代号是 {other_code}。",
    )
    assert seeded["ok"] is True
    assert other_seeded["ok"] is True
    text = (
        f"请从我保存的知识中找出 {project_name} 的完整验收记录，告诉我其中的颜色代号。"
    )
    _assert_natural_user_text(
        text,
        "list_recent_notes",
        "get_note",
        "find_similar_notes",
        "Observation",
    )
    errors: list[str] = []

    def submit() -> None:
        try:
            _conversation(
                live_web_process,
                conversation_id=conversation_id,
                text=text,
                interaction_run_ref=run_ref,
            )
        except (OSError, URLError) as exc:
            errors.append(type(exc).__name__)

    thread = Thread(target=submit, daemon=True)
    thread.start()
    committed: dict[str, object] | None = None
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            candidate = _trace(live_web_process, run_ref)
        except Exception:
            time.sleep(0.1)
            continue
        if candidate.get("inputs") and candidate.get("final_message") is None:
            committed = candidate
            break
        time.sleep(0.1)
    assert committed is not None, (
        "did not observe an intermediate committed interaction fact"
    )
    before_order = tuple(committed["execution_order"])
    live_web_process.crash_and_restart()
    thread.join(timeout=10)

    result = _conversation(
        live_web_process,
        conversation_id=conversation_id,
        text=text,
        interaction_run_ref=run_ref,
    )
    recovered = _trace(live_web_process, run_ref)

    _record(
        trace_archive,
        request,
        "L03.complex_loop_http",
        {
            "seeded": seeded,
            "other_scope_seeded": other_seeded,
            "natural_user_text": text,
            "before": committed,
            "result": result,
            "recovered": recovered,
            "request_errors": errors,
        },
        profile="baseline",
    )
    final_message = str(result["message"]["content"]).strip()
    assert result["disposition"] == "answer"
    assert expected_code in final_message
    assert other_code not in final_message
    assert other_code not in json.dumps(recovered, ensure_ascii=False)
    assert tuple(recovered["execution_order"][: len(before_order)]) == before_order
    assert len(recovered["execution_order"]) == len(set(recovered["execution_order"]))
    assert recovered["working_plan"] is None
    assert any(
        expected_code in json.dumps(item["payload"], ensure_ascii=False)
        for item in recovered["inputs"]
        if item["kind"] in {"context_evidence", "tool_result"}
        and item["status"] == "succeeded"
    )


def test_l04_http_manager_synthesizes_bounded_specialist_artifact(
    live_a2a_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = f"l04-{uuid4().hex[:8]}"
    user_text = (
        "请为架构评审深入研究 A2A delegation grant 的最小安全边界。需要综合权威资料，"
        "分析授权范围、数据外发、重放与完成判定四个方面，最后给出结构化结论及来源依据，"
        "不要只给简短概述。"
    )
    _assert_natural_user_text(
        user_text,
        "gpt_researcher",
        "AgentArtifact",
        "completed",
        "委托",
    )
    result = _conversation(
        live_a2a_web_process,
        conversation_id=f"conversation-{marker}",
        text=user_text,
    )
    trace = _trace(live_a2a_web_process, str(result["interaction_run_ref"]))
    _record(
        trace_archive,
        request,
        "L04.complex_loop_http",
        {"natural_user_text": user_text, "result": result, "trace": trace},
        profile="baseline+gpt_researcher_a2a",
    )

    assert result["disposition"] == "answer"
    artifacts = [item for item in trace["inputs"] if item["kind"] == "agent_artifact"]
    assert len(artifacts) == 1
    assert artifacts[0]["status"] == "succeeded"
    excerpt = artifacts[0]["payload"]["artifacts"][0]["content_excerpt"]
    assert "data:" not in excerpt
    assert "[DONE]" not in excerpt
    assert "Cancellation requested" not in excerpt
    final_message = str(result["message"]["content"]).strip()
    assert all(
        any(term in final_message for term in alternatives)
        for alternatives in (
            ("授权", "权限"),
            ("数据", "外发"),
            ("重放", "复用"),
            ("完成", "验收"),
            ("来源", "依据"),
        )
    )


def test_l05_http_budget_exhaustion_fails_closed(
    live_budget_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = f"l05-{uuid4().hex[:8]}"
    project_name = f"Budget-l05-{marker}"
    expected_code = f"violet-{uuid4().hex[:10]}"
    seeded = _capture_memory_text(
        live_budget_web_process,
        user_id="default",
        text=f"我为 {project_name} 记录的验收代号是 {expected_code}。",
    )
    assert seeded["ok"] is True
    user_text = f"我之前记下的 {project_name} 验收代号是什么？"
    _assert_natural_user_text(
        user_text,
        "list_recent_notes",
        "find_similar_notes",
        "Observation",
    )
    result = _conversation(
        live_budget_web_process,
        conversation_id=f"conversation-{marker}",
        text=user_text,
    )
    trace = _trace(live_budget_web_process, str(result["interaction_run_ref"]))

    _record(
        trace_archive,
        request,
        "L05.complex_loop_http",
        {
            "seeded": seeded,
            "natural_user_text": user_text,
            "result": result,
            "trace": trace,
        },
        profile="baseline",
    )
    assert result["disposition"] == "limitation"
    assert "未生成替代答案" in str(result["message"]["content"])
    assert expected_code not in str(result["message"]["content"])
    assert any(
        expected_code in json.dumps(item["payload"], ensure_ascii=False)
        for item in trace["inputs"]
        if item["kind"] == "tool_result" and item["status"] == "succeeded"
    )


def test_l06_http_user_requested_review_returns_receipt_bound_safe_revision(
    live_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = f"l06-{uuid4().hex[:8]}"
    user_text = (
        "请审查并修订这段准备发给用户的答复：“系统已经完成所有写入。”"
        "要求是：没有可核验的执行证据时，不能声称写入已经发生。"
        "如果原文不符合要求，请按审查意见修订，最后只返回可安全发送的文本。"
    )
    _assert_natural_user_text(
        user_text,
        "verify_interaction_draft",
        "needs_revision",
        "passed",
        "verifier",
    )
    result = _conversation(
        live_web_process,
        conversation_id=f"conversation-{marker}",
        text=user_text,
    )
    trace = _trace(live_web_process, str(result["interaction_run_ref"]))
    verifier_results = [
        item
        for item in trace["inputs"]
        if item["kind"] == "tool_result"
        and item["capability_id"] == "verify_interaction_draft"
    ]
    _record(
        trace_archive,
        request,
        "L06.complex_loop_http",
        {"natural_user_text": user_text, "result": result, "trace": trace},
        profile="baseline",
    )

    assert result["disposition"] == "answer"
    assert verifier_results
    final_receipt = verifier_results[-1]["payload"]["data"]
    assert final_receipt["verdict"] == "passed"
    final_message = str(result["message"]["content"]).strip()
    assert "已经完成所有写入" not in final_message
    assert final_receipt["verified_draft"] == final_message
    assert (
        final_receipt["draft_digest"]
        == sha256(final_message.encode("utf-8")).hexdigest()
    )
