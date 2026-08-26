"""TOOL-RESULT-CONTRACT-001: MCP result validity at the formal Conversation entry."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Iterator
from urllib.parse import urlencode
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
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)


@pytest.fixture(scope="module")
def live_result_contract_process(
    server_temp_dir: Path,
) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    fixture = (
        Path(__file__).parents[1]
        / "e2e_quality"
        / "fixtures"
        / "mcp_result_contract.py"
    )
    mcp_config = {
        "enabled": True,
        "servers": [{
            "server_id": "result-contract-fixture",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(fixture)],
            "tools": [{
                "remote_name": "lookup_account_limit",
                "name": "account_limits.lookup",
                "description": "Look up the provider-verified current limit for one account.",
                "resource_locator_arg": "account_id",
                "semantic_domains": ["account_limits"],
                "resource_types": ["account"],
                "operations": ["read"],
                "trust_level": "trusted",
                "credential_mode": "none",
                "data_egress_class": "none",
                "attestation_status": "pinned",
                "freshness_profile": "realtime",
                "output_contract": "verified account limit",
                "evidence_contract": "provider result bound to account_id",
                "failure_semantics": "typed failure without substitute content",
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string"},
                        "verified_limit": {"type": "integer"},
                    },
                    "required": ["account_id", "verified_limit"],
                    "additionalProperties": False,
                },
                "exposure": "public_agent",
                "side_effects": ["none"],
                "permission_scope": "account_limits:read",
            }],
        }],
    }
    overrides = {
        "PERSONAL_AGENT_MCP_SERVERS": json.dumps(mcp_config),
        "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
        "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
    }
    yield from _yield_started_server(_new_live_web_process(
        server_temp_dir,
        settings,
        child_env_overrides=overrides,
    ))


def test_malformed_mcp_result_cannot_be_reported_as_verified_fact(
    live_result_contract_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    request: pytest.FixtureRequest,
) -> None:
    user_id = "tool-result-contract-001-user"
    user_input = (
        "请查询账户 WRONG_TYPE 当前经过服务方验证的额度。"
        "如果服务方没有返回合格的已验证额度，请明确说明无法确认，不要猜测。"
    )
    result = _post_json(
        f"{live_result_contract_process.base_url}/api/conversation/turn",
        {
            "user_id": user_id,
            "conversation_id": f"tool-result-contract-001-{uuid4().hex}",
            "messages": [{
                "role": "user",
                "content": user_input,
            }],
        },
    )
    trace = _get_json(
        f"{live_result_contract_process.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}?{urlencode({'user_id': user_id})}"
    )
    role = product_evidence_role("TOOL-RESULT-CONTRACT-001")
    product_evidence_recorder.capture(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id="TOOL-RESULT-CONTRACT-001",
            role=role,
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=user_id,
            ),
            user_input_digest=canonical_evidence_digest(user_input),
            initial_state_digest=canonical_evidence_digest({
                "isolated_database": True,
                "account_id": "WRONG_TYPE",
                "provider_result": "wrong_type",
            }),
            config_cohort=(
                "production-composition+frozen-mcp+output-validation-" + role
            ),
            grader_version="tool-result-contract-001-deterministic-v1",
        ),
        report={"result": result, "interaction_trace": trace},
    )

    answer = str(result["message"]["content"])
    assert any(term in answer for term in ("无法确认", "无法验证", "返回无效", "结果不合格"))
    assert any(
        item.get("kind") == "tool_result"
        and item.get("status") == "failed"
        and isinstance(item.get("payload"), dict)
        and item["payload"].get("ok") is False
        for item in trace["inputs"]
    )
