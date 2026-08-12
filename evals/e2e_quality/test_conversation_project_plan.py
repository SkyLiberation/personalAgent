"""PLAN-001 product baseline: control one durable project from its Conversation."""

from __future__ import annotations

import json
import time
from urllib.parse import urlencode
from uuid import uuid4

import pytest

from evals.e2e_quality.measurements import measurement_from_interaction_trace
from evals.e2e_quality.test_product_capability_outcomes import (
    _record,
    live_investigation_worker as _live_investigation_worker_fixture,  # noqa: F401
    live_web_search_process as _live_web_search_process_fixture,  # noqa: F401
)
from evals.e2e_quality.test_release_user_outcomes import _get_json, _post_json


pytestmark = pytest.mark.integration
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)


def test_plan_001_same_conversation_reads_steers_and_recovers_its_project(
    live_web_search_process,
    live_investigation_worker,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    owner_id = f"plan-001-{uuid4().hex}"
    conversation_id = f"conversation-{owner_id}"
    goal = (
        "请在后台持续调查主流 Agent 协议最近一年的关键变化，先给我一个计划。"
        "重点覆盖协议机制、信任边界和迁移建议，优先使用官方来源。"
        "我之后会在这里查看进度并调整尚未开始的要求。"
    )
    started = _post_json(
        f"{live_web_search_process.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "user_id": owner_id,
            "messages": [{"role": "user", "content": goal}],
        },
    )
    assert started["disposition"] == "background_started"
    project_ref = started["project_reference"]
    query = urlencode({
        "tenant_id": project_ref["tenant_id"],
        "user_id": project_ref["user_id"],
    })
    project_url = (
        f"{live_web_search_process.base_url}/api/investigation-projects/"
        f"{project_ref['project_id']}?{query}"
    )
    project = _get_json(project_url)
    deadline = time.monotonic() + 120
    while project.get("accepted_plan") is None and time.monotonic() < deadline:
        time.sleep(0.25)
        project = _get_json(project_url)
    assert project.get("accepted_plan") is not None

    progress_question = "现在的计划和进度是什么？请不要启动第二项调查。"
    progress = _post_json(
        f"{live_web_search_process.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "user_id": owner_id,
            "messages": [{"role": "user", "content": progress_question}],
        },
    )
    progress_trace = _get_json(
        f"{live_web_search_process.base_url}/api/conversation/runs/"
        f"{progress['interaction_run_ref']}?{urlencode({'user_id': owner_id})}"
    )
    answer = str(progress["message"]["content"])
    plan_version = str(project["accepted_plan"]["plan_version"])
    assert progress["disposition"] == "answer"
    assert project_ref["project_id"] in json.dumps(progress_trace, ensure_ascii=False)
    assert plan_version in answer
    assert project["state"] in answer
    assert progress.get("project_reference", {}).get("project_id") != ""

    steering_text = "调整尚未开始的要求：增加一节部署兼容性分析，并继续原来的调查。"
    steering_messages = [{"role": "user", "content": steering_text}]
    steered = _post_json(
        f"{live_web_search_process.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "user_id": owner_id,
            "messages": steering_messages,
        },
    )
    steered_trace = _get_json(
        f"{live_web_search_process.base_url}/api/conversation/runs/"
        f"{steered['interaction_run_ref']}?{urlencode({'user_id': owner_id})}"
    )
    assert any(
        item.get("capability_id") == "steer_investigation_project"
        and item.get("status") == "succeeded"
        for item in steered_trace["inputs"]
    )
    assert steered["project_reference"]["project_id"] == project_ref["project_id"]

    live_web_search_process.restart()
    resumed_question = "服务重启后，继续告诉我刚才那项调查的计划版本和进度。"
    resumed = _post_json(
        f"{live_web_search_process.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "user_id": owner_id,
            "messages": [{"role": "user", "content": resumed_question}],
        },
    )
    resumed_trace = _get_json(
        f"{live_web_search_process.base_url}/api/conversation/runs/"
        f"{resumed['interaction_run_ref']}?{urlencode({'user_id': owner_id})}"
    )
    assert resumed["disposition"] == "answer"
    assert resumed["project_reference"]["project_id"] == project_ref["project_id"]
    assert project_ref["project_id"] in json.dumps(resumed_trace, ensure_ascii=False)
    assert any(
        item.get("capability_id") == "investigation_project_context"
        and item.get("status") == "succeeded"
        for item in resumed_trace["inputs"]
    )
    _record(
        trace_archive,
        request,
        "PLAN-001.product_http",
        {
            "goal": goal,
            "progress_question": progress_question,
            "started": started,
            "authoritative_project": project,
            "progress": progress,
            "progress_trace": progress_trace,
            "steering_text": steering_text,
            "steered": steered,
            "steered_trace": steered_trace,
            "resumed_question": resumed_question,
            "resumed": resumed,
            "resumed_trace": resumed_trace,
        },
        profile="baseline+web_search",
        measurement=measurement_from_interaction_trace(resumed_trace),
    )
