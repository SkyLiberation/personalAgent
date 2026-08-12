"""CTX-001 baseline: long observations across a natural Conversation journey."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Iterator
from uuid import uuid4

import pytest

from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _new_live_web_process,
    _post_json,
    _require_live_dependencies,
    _yield_started_server,
)
from evals.e2e_quality.trace_archive import TraceArchive
from personal_agent.application.conversation.observation_bounds import (
    MAX_OBSERVATION_PAYLOAD_CHARS,
)


pytestmark = pytest.mark.integration
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)


@pytest.fixture(scope="module")
def context_facts() -> dict[str, str]:
    return {
        name: f"{name.lower()}-{uuid4().hex}"
        for name in ("ALPHA", "BETA", "GAMMA")
    }


@pytest.fixture(scope="module")
def live_context_web_process(
    server_temp_dir: Path,
    context_facts: dict[str, str],
) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    fixture = Path(__file__).parent / "fixtures" / "frozen_document_mcp.py"
    mcp_config = {
        "enabled": True,
        "servers": [{
            "server_id": "frozen-documents",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(fixture)],
            "tools": [{
                "remote_name": "read_document",
                "name": "frozen_documents.read",
                "description": (
                    "Read the complete exact text of frozen comparison document "
                    "ALPHA, BETA, or GAMMA by document_id."
                ),
                "resource_locator_arg": "document_id",
                "semantic_domains": ["frozen_documents"],
                "resource_types": ["document"],
                "operations": ["read"],
                "trust_level": "trusted",
                "credential_mode": "none",
                "data_egress_class": "none",
                "attestation_status": "pinned",
                "freshness_profile": "static",
                "output_contract": "exact frozen document text",
                "evidence_contract": "provider output bound to document_id",
                "failure_semantics": "typed failure without substitute content",
                "exposure": "public_agent",
                "side_effects": ["none"],
                "permission_scope": "frozen_documents:read",
            }],
        }],
    }
    overrides = {
        "PERSONAL_AGENT_MCP_SERVERS": json.dumps(mcp_config),
        "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
        "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
        **{
            f"CTX_E2E_FACT_{name}": fact
            for name, fact in context_facts.items()
        },
    }
    yield from _yield_started_server(
        _new_live_web_process(
            server_temp_dir,
            settings,
            child_env_overrides=overrides,
        )
    )


def test_long_conversation_retains_correction_and_early_document_evidence(
    live_context_web_process: LiveWebProcess,
    context_facts: dict[str, str],
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    conversation_id = f"ctx-001-{uuid4().hex}"
    old_threshold = f"old-{uuid4().hex}"
    corrected_threshold = f"new-{uuid4().hex}"
    messages: list[dict[str, str]] = [{
        "role": "user",
        "content": f"后续比较先使用阈值 {old_threshold}。",
    }, {
        "role": "user",
        "content": (
            f"更正：阈值改为 {corrected_threshold}，{old_threshold} 已作废。"
            "后续结论只能使用新阈值。"
        ),
    }, {
        "role": "user",
        "content": (
            "现在读取冻结资料 ALPHA、BETA、GAMMA。每份资料中都有一行 "
            "CTX-EVIDENCE，请逐字提取那一行的口令。最终答案必须列出三个资料编号、"
            "各自口令和当前阈值，并说明这些值来自实际读取的资料；不要猜测或省略。"
        ),
    }]
    result = _post_json(
        f"{live_context_web_process.base_url}/api/conversation/turn",
        {"conversation_id": conversation_id, "messages": messages},
    )
    trace = _get_json(
        f"{live_context_web_process.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}"
    )
    trace_archive.write_trace(
        nodeid=request.node.nodeid,
        case_id="CTX-001.baseline",
        trace={
            "conversation_id": conversation_id,
            "facts": context_facts,
            "old_threshold": old_threshold,
            "corrected_threshold": corrected_threshold,
            "result": result,
            "interaction_trace": trace,
        },
    )

    answer = str(result["message"]["content"])
    assert result["disposition"] == "answer"
    assert f"当前阈值：{corrected_threshold}" in answer
    assert all(fact in answer for fact in context_facts.values())
    assert all(name in answer for name in context_facts)

    tool_results = [
        item for item in trace["inputs"]
        if item.get("kind") == "tool_result"
    ]
    assert all(
        any(
            item.get("capability_id") == "read_action_output"
            and fact in json.dumps(item.get("payload"), ensure_ascii=False)
            for item in tool_results
        )
        for fact in context_facts.values()
    )
    assert all(
        len(json.dumps(item["payload"], ensure_ascii=False, default=str))
        <= MAX_OBSERVATION_PAYLOAD_CHARS * 1.2
        for item in tool_results
    )
