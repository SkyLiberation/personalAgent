"""MEMORY-RETRIEVAL-SCALE-001: fixed candidate-window product baseline."""

from __future__ import annotations

from time import perf_counter
from urllib.parse import urlencode

import pytest

from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _post_json,
)
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from personal_agent.application.knowledge import KnowledgeService
from personal_agent.infra.storage.postgres_knowledge_store import (
    PostgresKnowledgeStore,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)

_CASE_ID = "MEMORY-RETRIEVAL-SCALE-001"
_USER_ID = "memory-retrieval-scale-001-user"
_OWNER_ID = f"personal-agent:{_USER_ID}"
_FACT_COUNT = 1_000
_TARGET_CODE = "SCALE-TARGET-1000-7Q9X"
_QUESTION = (
    "请只根据我保存的个人资料回答：蓝鲸档案 R1000 的当前校验码是什么？"
    "请给出原文依据；没有检索到就明确说没有，不要猜测。"
)


def _seed_scale_corpus(server: LiveWebProcess) -> tuple[float, int]:
    postgres_url = server.child_env.get("PERSONAL_AGENT_POSTGRES_URL")
    assert postgres_url, "Web E2E child process must declare its Postgres URL"
    lines = [f"蓝鲸档案 R1000 的当前校验码是 {_TARGET_CODE}。"]
    lines.extend(
        f"填充档案 F{index:04d} 的归档序号是 SCALE-FILLER-{index:04d}。"
        for index in range(1, _FACT_COUNT)
    )
    started = perf_counter()
    result = KnowledgeService(PostgresKnowledgeStore(postgres_url)).ingest_text(
        "\n".join(lines),
        user_id=_USER_ID,
        owner_id=_OWNER_ID,
        source_type="text",
        source_ref="memory-retrieval-scale-001-fixture",
        created_by="user",
        extract_claim_limit=_FACT_COUNT + 20,
    )
    return perf_counter() - started, len(result.claims)


def test_oldest_relevant_fact_survives_one_thousand_claims(
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    request: pytest.FixtureRequest,
) -> None:
    ingest_seconds, claim_count = _seed_scale_corpus(live_web_process)
    started = perf_counter()
    result = _post_json(
        f"{live_web_process.base_url}/api/conversation/turn",
        {
            "user_id": _USER_ID,
            "conversation_id": "memory-retrieval-scale-001-conversation",
            "messages": [{"role": "user", "content": _QUESTION}],
        },
    )
    end_to_end_seconds = perf_counter() - started
    trace = _get_json(
        f"{live_web_process.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}?{urlencode({'user_id': _USER_ID})}"
    )
    answer = str(result["message"]["content"])
    target_materialized = any(
        item.get("kind") == "context_evidence"
        and _TARGET_CODE in str(item.get("payload"))
        for item in trace["inputs"]
    )
    role = product_evidence_role(_CASE_ID)
    product_evidence_recorder.capture(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id=_CASE_ID,
            role=role,
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=_USER_ID,
            ),
            user_input_digest=canonical_evidence_digest(_QUESTION),
            initial_state_digest=canonical_evidence_digest({
                "fact_count": _FACT_COUNT,
                "target_position": "oldest",
                "target_code": _TARGET_CODE,
                "isolated_database": True,
            }),
            config_cohort=(
                "production-postgres+current-list-claims-window+" + role
            ),
            grader_version="memory-retrieval-scale-001-deterministic-v1",
        ),
        report={
            "fact_count": _FACT_COUNT,
            "created_claim_count": claim_count,
            "ingest_seconds": round(ingest_seconds, 6),
            "end_to_end_seconds": round(end_to_end_seconds, 6),
            "target_materialized": target_materialized,
            "result": result,
            "interaction_trace": trace,
        },
    )

    assert claim_count >= _FACT_COUNT
    assert result["disposition"] == "answer"
    assert _TARGET_CODE in answer
    assert target_materialized
