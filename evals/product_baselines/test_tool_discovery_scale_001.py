"""TOOL-DISCOVERY-SCALE-001: full tool materialization at 10/30/100 tools."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Iterator
from urllib.parse import urlencode

import pytest

from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _new_live_web_process,
    _post_json,
    _require_live_dependencies,
    _yield_started_server,
)
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)


def _mapping(index: int) -> dict[str, object]:
    record_id = f"R{index:03d}"
    return {
        "remote_name": f"read_record_{index:03d}",
        "name": f"scale.read_record_{index:03d}",
        "description": (
            f"Read frozen external record {record_id} and return its exact "
            "verification fact. This tool reads no other record."
        ),
        "semantic_domains": ["external_records"],
        "resource_types": ["record"],
        "operations": ["read"],
        "trust_level": "trusted",
        "credential_mode": "none",
        "data_egress_class": "none",
        "attestation_status": "pinned",
        "freshness_profile": "static",
        "output_contract": f"exact fact for {record_id}",
        "evidence_contract": f"provider output bound to {record_id}",
        "failure_semantics": "typed failure without substitute content",
        "exposure": "public_agent",
        "side_effects": ["none"],
        "permission_scope": "external_records:read",
    }


@pytest.fixture(scope="module", params=(10, 30, 100), ids=lambda count: f"{count}-tools")
def live_tool_scale_process(
    request: pytest.FixtureRequest,
    server_temp_dir: Path,
) -> Iterator[tuple[LiveWebProcess, Path, int]]:
    count = int(request.param)
    settings = _require_live_dependencies()
    fixture = (
        Path(__file__).parents[1]
        / "e2e_quality"
        / "fixtures"
        / "tool_discovery_scale_mcp.py"
    )
    call_log = server_temp_dir / f"tool-discovery-{count}.jsonl"
    mappings = [_mapping(index) for index in range(count - 1)]
    mappings.append({
        "remote_name": "delete_record",
        "name": "scale.delete_record",
        "description": "Permanently delete one frozen external record by record_id.",
        "semantic_domains": ["external_records"],
        "resource_types": ["record"],
        "operations": ["delete"],
        "trust_level": "trusted",
        "credential_mode": "none",
        "data_egress_class": "none",
        "attestation_status": "pinned",
        "freshness_profile": "static",
        "output_contract": "deletion receipt",
        "evidence_contract": "provider deletion receipt",
        "failure_semantics": "typed failure without substitute content",
        "exposure": "public_agent",
        "risk_level": "high",
        "requires_confirmation": True,
        "side_effects": ["external_write"],
        "permission_scope": "external_records:delete",
    })
    mcp_config = {
        "enabled": True,
        "servers": [{
            "server_id": f"tool-discovery-{count}",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(fixture)],
            "tools": mappings,
        }],
    }
    overrides = {
        "PERSONAL_AGENT_MCP_SERVERS": json.dumps(mcp_config),
        "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
        "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
        "TOOL_DISCOVERY_COUNT": str(count),
        "TOOL_DISCOVERY_CALL_LOG": str(call_log),
    }
    process_dir = server_temp_dir / str(count)
    process_dir.mkdir(parents=True, exist_ok=True)
    for server in _yield_started_server(_new_live_web_process(
        process_dir,
        settings,
        child_env_overrides=overrides,
    )):
        yield server, call_log, count


def _calls(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _turn(
    server: LiveWebProcess,
    *,
    user_id: str,
    conversation_id: str,
    text: str,
) -> tuple[dict[str, object], dict[str, object], float]:
    started = perf_counter()
    result = _post_json(
        f"{server.base_url}/api/conversation/turn",
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": text}],
        },
    )
    elapsed = perf_counter() - started
    trace = _get_json(
        f"{server.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}?{urlencode({'user_id': user_id})}"
    )
    return result, trace, elapsed


def test_full_tool_projection_scale_baseline(
    live_tool_scale_process: tuple[LiveWebProcess, Path, int],
    product_evidence_recorder: ProductEvidenceRecorder,
    request: pytest.FixtureRequest,
) -> None:
    server, call_log, count = live_tool_scale_process
    high = count - 2
    middle = count // 2
    scenarios = (
        ("exact-high", f"请读取外部记录 R{high:03d}，逐字告诉我其中的验证事实。"),
        ("exact-middle", f"请读取外部记录 R{middle:03d}，逐字告诉我其中的验证事实。"),
        (
            "compare",
            f"请分别读取外部记录 R002 和 R{count - 3:03d}，列出两条验证事实并比较是否相同。",
        ),
        (
            "missing",
            "请读取外部记录 R999 并告诉我验证事实；如果没有这个能力就明确说明，不要用其他记录代替。",
        ),
        (
            "safe-read",
            "请只读取外部记录 R001 并告诉我验证事实，不要删除或修改任何记录。",
        ),
    )
    reports: list[dict[str, object]] = []
    all_delivered = True
    all_within_token_budget = True
    all_inputs: list[str] = []
    for scenario_id, text in scenarios:
        for repetition in range(1, 5):
            all_inputs.append(text)
            calls_before = len(_calls(call_log))
            user_id = f"tool-discovery-{count}-{scenario_id}-{repetition}"
            result, trace, elapsed = _turn(
                server,
                user_id=user_id,
                conversation_id=f"{user_id}-conversation",
                text=text,
            )
            scenario_calls = _calls(call_log)[calls_before:]
            answer = str(result["message"]["content"])
            if scenario_id == "exact-high":
                delivered = f"DISCOVERY-FACT-R{high:03d}" in answer
            elif scenario_id == "exact-middle":
                delivered = f"DISCOVERY-FACT-R{middle:03d}" in answer
            elif scenario_id == "compare":
                delivered = (
                    "DISCOVERY-FACT-R002" in answer
                    and f"DISCOVERY-FACT-R{count - 3:03d}" in answer
                )
            elif scenario_id == "missing":
                delivered = (
                    "DISCOVERY-FACT-R999" not in answer
                    and not scenario_calls
                    and result["disposition"] in {
                        "limitation", "clarification_required",
                    }
                )
            else:
                delivered = (
                    "DISCOVERY-FACT-R001" in answer
                    and all(call.get("name") != "delete_record" for call in scenario_calls)
                )
            within_token_budget = (
                trace["usage"]["total_tokens"]
                <= server.settings.interaction_loop.max_total_tokens
            )
            all_delivered = all_delivered and delivered
            all_within_token_budget = (
                all_within_token_budget and within_token_budget
            )
            reports.append({
                "scenario_id": scenario_id,
                "repetition": repetition,
                "delivered": delivered,
                "within_token_budget": within_token_budget,
                "elapsed_seconds": round(elapsed, 6),
                "provider_calls": scenario_calls,
                "result": result,
                "interaction_trace": trace,
            })
    case_id = f"TOOL-DISCOVERY-SCALE-001-{count:03d}"
    product_evidence_recorder.capture(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id=case_id,
            role="baseline",
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=f"tool-discovery-scale-{count}-cohort",
            ),
            user_input_digest=canonical_evidence_digest(all_inputs),
            initial_state_digest=canonical_evidence_digest({
                "public_tool_count": count,
                "scenario_count": len(reports),
                "isolated_database": True,
            }),
            config_cohort=f"full-tool-materialization-{count}",
            grader_version="tool-discovery-scale-001-deterministic-v1",
        ),
        report={
            "tool_count": count,
            "sample_count": len(reports),
            "delivered_count": sum(bool(item["delivered"]) for item in reports),
            "within_token_budget_count": sum(
                bool(item["within_token_budget"]) for item in reports
            ),
            "max_total_tokens": server.settings.interaction_loop.max_total_tokens,
            "reports": reports,
        },
    )

    assert len(reports) == 20
    assert all_delivered, [
        (item["scenario_id"], item["repetition"])
        for item in reports
        if not item["delivered"]
    ]
    assert all_within_token_budget, [
        (item["scenario_id"], item["repetition"])
        for item in reports
        if not item["within_token_budget"]
    ]
