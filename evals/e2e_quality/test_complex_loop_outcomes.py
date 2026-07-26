"""Release E2E journeys for the canonical ordinary-interaction loop."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import Thread
import time
from typing import Iterator
from urllib.error import URLError
from uuid import uuid4

import pytest

from evals.e2e_quality.test_product_capability_outcomes import _record, _workspace_ingest
from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _new_live_web_process,
    _post_json,
    _require_live_dependencies,
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


def test_l01_http_observation_revises_working_plan(
    live_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = f"l01-{uuid4().hex[:8]}"
    result = _conversation(
        live_web_process,
        conversation_id=f"conversation-{marker}",
        text=(
            "先调用 list_recent_notes 观察当前知识，再根据真实 ToolResult 回答有多少条；"
            "不要在工具结果返回前回答。"
        ),
    )
    trace = _trace(live_web_process, str(result["interaction_run_ref"]))
    inputs = list(trace["inputs"])

    assert result["disposition"] == "answer"
    assert str(result["message"]["content"]).strip()
    assert any(item["kind"] == "tool_result" for item in inputs)
    assert trace["working_plans"]
    _record(trace_archive, request, "L01.complex_loop_http", {"result": result, "trace": trace}, profile="baseline")


def test_l02_http_independent_reads_use_safe_concurrency(
    live_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = f"l02-{uuid4().hex[:8]}"
    result = _conversation(
        live_web_process,
        conversation_id=f"conversation-{marker}",
        text=(
            "在同一轮并行调用两个互不依赖的只读能力：list_recent_notes(limit=3) 和 "
            "inspect_knowledge_gaps(user_id='default')；收到两个结果后综合回答。"
        ),
    )
    trace = _trace(live_web_process, str(result["interaction_run_ref"]))

    assert result["disposition"] == "answer"
    assert any(len(batch) == 2 for batch in trace["concurrent_batches"])
    assert len(trace["inputs"]) >= 2
    _record(trace_archive, request, "L02.complex_loop_http", {"result": result, "trace": trace}, profile="baseline")


def test_l03_http_process_restart_rebuilds_from_committed_facts(
    live_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = uuid4().hex[:8]
    run_ref = f"irun_l03_{marker}"
    conversation_id = f"conversation-l03-{marker}"
    seeded = _workspace_ingest(
        live_web_process,
        "default",
        f"L03 恢复验证事实 {marker}：该知识用于正式入口崩溃恢复测试。",
        source_type="document",
    )
    text = (
        "先调用 list_recent_notes(limit=2)，读取结果后再调用 get_note 检查其中一个引用，"
        "最后回答；每一步必须等待上一 Observation。"
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
    assert committed is not None, "did not observe an intermediate committed interaction fact"
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
            "before": committed,
            "result": result,
            "recovered": recovered,
            "request_errors": errors,
        },
        profile="baseline",
    )
    assert result["disposition"] in {"answer", "limitation"}
    assert tuple(recovered["execution_order"][:len(before_order)]) == before_order
    assert any(plan["revision_reason"] == "context_rebuild" for plan in recovered["working_plans"])


def test_l04_http_manager_synthesizes_bounded_specialist_artifact(
    live_a2a_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = f"l04-{uuid4().hex[:8]}"
    result = _conversation(
        live_a2a_web_process,
        conversation_id=f"conversation-{marker}",
        text=(
            "委托 gpt_researcher 只研究 A2A delegation grant 的最小安全边界，"
            "接收其 Artifact 后由你综合最终回答，不要把远端 completed 当作父目标自动完成。"
        ),
    )
    trace = _trace(live_a2a_web_process, str(result["interaction_run_ref"]))
    _record(trace_archive, request, "L04.complex_loop_http", {"result": result, "trace": trace}, profile="baseline+gpt_researcher_a2a")

    assert result["disposition"] == "answer"
    artifacts = [item for item in trace["inputs"] if item["kind"] == "agent_artifact"]
    assert len(artifacts) == 1
    assert artifacts[0]["status"] == "succeeded"
    excerpt = artifacts[0]["payload"]["artifacts"][0]["content_excerpt"]
    assert "data:" not in excerpt
    assert "[DONE]" not in excerpt
    assert "Cancellation requested" not in excerpt
    assert str(result["message"]["content"]).strip()


def test_l05_http_budget_exhaustion_fails_closed(
    live_budget_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = f"l05-{uuid4().hex[:8]}"
    result = _conversation(
        live_budget_web_process,
        conversation_id=f"conversation-{marker}",
        text="调用 list_recent_notes(limit=2) 后再回答；不得跳过 Observation。",
    )
    trace = _trace(live_budget_web_process, str(result["interaction_run_ref"]))

    assert result["disposition"] == "limitation"
    assert "未生成替代答案" in str(result["message"]["content"])
    assert trace["inputs"]
    _record(trace_archive, request, "L05.complex_loop_http", {"result": result, "trace": trace}, profile="baseline")


def test_l06_http_verifier_feedback_revises_result(
    live_web_process: LiveWebProcess,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    marker = f"l06-{uuid4().hex[:8]}"
    result = _conversation(
        live_web_process,
        conversation_id=f"conversation-{marker}",
        text=(
            "草稿是“系统已经完成所有写入”。成功标准是“不得声称发生任何未观察到的写入”。"
            "先用 verify_interaction_draft 验证该草稿，收到 needs_revision 后修订；"
            "再用相同成功标准验证精确终稿，收到 passed 后原样回答；"
            "不得改写 verifier 的执行事实。"
        ),
    )
    trace = _trace(live_web_process, str(result["interaction_run_ref"]))
    verifier_results = [
        item for item in trace["inputs"]
        if item["kind"] == "tool_result" and item["capability_id"] == "verify_interaction_draft"
    ]
    _record(trace_archive, request, "L06.complex_loop_http", {"result": result, "trace": trace}, profile="baseline")

    assert result["disposition"] == "answer"
    assert len(verifier_results) >= 2
    assert verifier_results[0]["payload"]["data"]["verdict"] == "needs_revision"
    final_receipt = verifier_results[-1]["payload"]["data"]
    assert final_receipt["verdict"] == "passed"
    final_message = str(result["message"]["content"]).strip()
    assert final_receipt["verified_draft"] == final_message
    assert final_receipt["draft_digest"] == sha256(final_message.encode("utf-8")).hexdigest()
