"""ASK-001 paired product baselines for one canonical Conversation answer owner."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from uuid import uuid4

import pytest

from evals.e2e_quality.test_product_capability_outcomes import (
    _knowledge_ingest,
    _record,
    live_web_search_process as _product_live_web_search_process,
)
from evals.e2e_quality.test_release_user_outcomes import _get_json, _post_json


pytestmark = pytest.mark.integration
pytest_plugins = (
    "evals.e2e_quality.test_release_user_outcomes",
    "evals.e2e_quality.test_product_capability_outcomes",
)
live_web_search_process = _product_live_web_search_process


def _conversation(server, *, conversation_id: str, user_id: str, text: str):
    return _post_json(
        f"{server.base_url}/api/conversation/turn",
        {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "messages": [{"role": "user", "content": text}],
        },
    )


def _trace(server, result, user_id: str):
    return _get_json(
        f"{server.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}?{urlencode({'user_id': user_id})}"
    )


def test_ask_001a_personal_only_answer_observes_quotes_and_conflict_without_web(
    live_web_search_process,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    owner_id = f"ask-001a-{uuid4().hex}"
    other_id = f"ask-001a-other-{uuid4().hex}"
    subject = f"Northstar-{uuid4().hex[:8]}"
    first_date = "2026-09-10"
    second_date = "2026-10-15"
    other_secret = f"other-secret-{uuid4().hex}"
    _knowledge_ingest(
        live_web_search_process,
        owner_id,
        f"{subject} 的生产迁移日期是 {first_date}。",
        source_type="document",
    )
    _knowledge_ingest(
        live_web_search_process,
        owner_id,
        f"{subject} 的生产迁移日期不是 {first_date}，而是 {second_date}。",
        source_type="document",
    )
    _knowledge_ingest(
        live_web_search_process,
        other_id,
        f"{subject} 的隐藏日期是 {other_secret}。",
        source_type="document",
    )
    before = _get_json(
        f"{live_web_search_process.base_url}/api/knowledge/claims?"
        + urlencode({"user_id": owner_id})
    )
    user_text = (
        f"只根据我保存的资料核对 {subject} 的生产迁移日期，逐项给出原文。"
        "冲突未解决就明确说冲突；不要上网，也不要保存你的回答。"
    )
    result = _conversation(
        live_web_search_process,
        conversation_id=f"conversation-{owner_id}",
        user_id=owner_id,
        text=user_text,
    )
    trace = _trace(live_web_search_process, result, owner_id)
    after = _get_json(
        f"{live_web_search_process.base_url}/api/knowledge/claims?"
        + urlencode({"user_id": owner_id})
    )
    serialized = json.dumps({"result": result, "trace": trace}, ensure_ascii=False)
    _record(
        trace_archive,
        request,
        "ASK-001A.product_http",
        {"user_text": user_text, "result": result, "trace": trace},
        profile="baseline+web_search",
    )

    assert result["disposition"] == "answer"
    assert first_date in result["message"]["content"]
    assert second_date in result["message"]["content"]
    assert "冲突" in result["message"]["content"]
    assert "evidence_span_id" in serialized
    assert "web_search" not in {
        item.get("capability_id") for item in trace["inputs"]
    }
    assert other_secret not in serialized
    assert len(after) == len(before)


def test_ask_001b_one_conversation_combines_personal_and_official_web_evidence(
    live_web_search_process,
    trace_archive,
    request: pytest.FixtureRequest,
) -> None:
    owner_id = f"ask-001b-{uuid4().hex}"
    other_id = f"ask-001b-other-{uuid4().hex}"
    project_code = f"Quartz-{uuid4().hex[:10]}"
    other_secret = f"other-secret-{uuid4().hex}"
    _knowledge_ingest(
        live_web_search_process,
        owner_id,
        (
            f"我的 {project_code} 项目正在评估 OpenAI Agents SDK，"
            "需要核对官方文档中的工具机制。"
        ),
        source_type="document",
    )
    _knowledge_ingest(
        live_web_search_process,
        other_id,
        other_secret,
        source_type="document",
    )
    before = _get_json(
        f"{live_web_search_process.base_url}/api/knowledge/claims?"
        + urlencode({"user_id": owner_id})
    )
    user_text = (
        "结合我保存的项目说明和 OpenAI 官方 Agents SDK 文档，告诉我项目代号，"
        "并说明 Agent 如何使用工具；两部分都逐项给来源。"
    )
    result = _conversation(
        live_web_search_process,
        conversation_id=f"conversation-{owner_id}",
        user_id=owner_id,
        text=user_text,
    )
    trace = _trace(live_web_search_process, result, owner_id)
    after = _get_json(
        f"{live_web_search_process.base_url}/api/knowledge/claims?"
        + urlencode({"user_id": owner_id})
    )
    serialized = json.dumps({"result": result, "trace": trace}, ensure_ascii=False)
    observed = {
        item.get("capability_id")
        for item in trace["inputs"]
        if item.get("status") == "succeeded"
    }
    _record(
        trace_archive,
        request,
        "ASK-001B.product_http",
        {"user_text": user_text, "result": result, "trace": trace},
        profile="baseline+web_search",
    )

    assert result["disposition"] == "answer"
    assert project_code in result["message"]["content"]
    assert {"personal_knowledge_context", "web_search"} <= observed
    assert "openai" in serialized.lower() and "http" in serialized.lower()
    assert other_secret not in serialized
    assert len(after) == len(before)
