"""Formal foreground-delegation versus background-continuation product baseline."""

from __future__ import annotations

from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse

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
from evals.product_baselines.test_agent_perf_delegate_001 import (
    delegation_request_text,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)

_CASE_ID = "INTERACTION-INTENT-DELEGATION-BOUNDARY-001"
_GRADER_VERSION = "interaction-intent-delegation-boundary-user-outcome-v1"
_REQUEST_TEXT = delegation_request_text(16)


@pytest.fixture(scope="module")
def foreground_delegation_web_process(server_temp_dir) -> LiveWebProcess:
    settings = _require_live_dependencies()
    server = _new_live_web_process(
        server_temp_dir,
        settings,
        child_env_overrides={
            "PERSONAL_AGENT_MCP_SERVERS": '{"enabled":false}',
            "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
            "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
            "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED": "false",
            "PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS": "1",
            "PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS": "0",
            "PERSONAL_AGENT_INTERACTION_MAX_AGENT_CALLS": "0",
        },
    )
    yield from _yield_started_server(server)


def _turn(
    server: LiveWebProcess,
    *,
    user_id: str,
    conversation_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = _post_json(
        f"{server.base_url}/api/conversation/turn",
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": _REQUEST_TEXT}],
            "interaction_mode": "auto",
        },
    )
    trace = _get_json(
        f"{server.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}?{urlencode({'user_id': user_id})}"
    )
    return result, trace


def _config_cohort(server: LiveWebProcess) -> str:
    settings = server.settings
    return canonical_evidence_digest({
        "structured_model": settings.structured.model,
        "structured_provider_host": urlparse(
            settings.structured.base_url or ""
        ).hostname,
        "structured_output_transport": settings.structured.output_transport,
        "intent_contract": "interaction_intent:v2",
        "interaction_mode": "auto",
        "max_model_turns": 1,
        "max_tool_calls": 0,
        "max_agent_calls": 0,
        "gpt_researcher_a2a_enabled": False,
        "formal_entrypoint": "POST /api/conversation/turn",
    })


@pytest.mark.parametrize("repetition", range(1, 21), ids=lambda value: f"run-{value}")
def test_explicit_delegation_remains_in_the_current_response_boundary(
    foreground_delegation_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    repetition: int,
) -> None:
    user_id = f"intent-delegation-boundary-{repetition:02d}"
    entry_error: dict[str, Any] | None = None
    try:
        result, trace = _turn(
            foreground_delegation_web_process,
            user_id=user_id,
            conversation_id=f"intent-delegation-boundary-{repetition:02d}",
        )
    except (HTTPError, URLError, TimeoutError) as error:
        result = {}
        trace = {}
        entry_error = {
            "type": type(error).__name__,
            "status": getattr(error, "code", None),
            "message": str(error),
        }

    background_feedback = [
        item
        for item in trace.get("inputs", ())
        if isinstance(item, dict)
        and item.get("kind") == "decision_feedback"
        and item.get("action_id") == "background-continuation"
        and item.get("reason_code") == "capability_missing"
    ]
    message = str(result.get("message", {}).get("content", ""))
    misclassified_as_background = bool(background_feedback) or (
        "后台任务" in message and "没有启动后台工作" in message
    )
    foreground_boundary_preserved = (
        entry_error is None and not misclassified_as_background
    )
    report = {
        "case_id": _CASE_ID,
        "repetition": repetition,
        "natural_user_text": _REQUEST_TEXT,
        "expected_delivery_boundary": "foreground_current_response",
        "environment_capability_boundary": {
            "agent_calls_allowed": 0,
            "tool_calls_allowed": 0,
            "model_turns_allowed": 1,
            "expected_truthful_outcome": (
                "current-conversation limitation, never background-continuation limitation"
            ),
        },
        "result": result,
        "interaction_trace": trace,
        "entry_error": entry_error,
        "result_metrics": {
            "foreground_boundary_preserved": foreground_boundary_preserved,
            "misclassified_as_background": misclassified_as_background,
            "background_feedback_count": len(background_feedback),
            "disposition": result.get("disposition"),
            "usage": trace.get("usage"),
        },
    }
    initial_state = {
        "isolated_user": True,
        "agent_calls_allowed": 0,
        "tool_calls_allowed": 0,
        "model_turns_allowed": 1,
        "background_work": 0,
    }
    product_evidence_recorder.capture(
        nodeid=(
            "evals/product_baselines/"
            "test_interaction_intent_delegation_boundary_001.py::"
            "test_explicit_delegation_remains_in_the_current_response_boundary"
        ),
        identity=ProductEvidenceIdentity(
            case_id=_CASE_ID,
            role=product_evidence_role(_CASE_ID),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=user_id,
            ),
            user_input_digest=canonical_evidence_digest(_REQUEST_TEXT),
            initial_state_digest=canonical_evidence_digest(initial_state),
            config_cohort=_config_cohort(foreground_delegation_web_process),
            grader_version=_GRADER_VERSION,
        ),
        report=report,
    )
    assert foreground_boundary_preserved, report["result_metrics"]
