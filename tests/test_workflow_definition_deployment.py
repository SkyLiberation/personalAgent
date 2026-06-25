from __future__ import annotations

from dataclasses import replace

import pytest

from personal_agent.planning.workflow import WORKFLOW_REGISTRY
from personal_agent.infra.storage.postgres_workflow_definition_store import (
    PostgresWorkflowDefinitionStore,
)
from tests.conftest import stub_router_decision


@pytest.fixture
def runtime(settings, clean_postgres_business_tables):
    from personal_agent.orchestration.runtime import AgentRuntime
    from personal_agent.memory.graphiti.store import GraphitiStore
    from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore

    runtime = AgentRuntime(
        settings=settings,
        store=PostgresMemoryStore(settings.data_dir, settings.postgres_url),
        graph_store=GraphitiStore(settings),
    )
    runtime._intent_router._classify_with_llm = stub_router_decision
    return runtime


def test_workflow_definition_store_syncs_registry(postgres_url, clean_postgres_business_tables):
    store = PostgresWorkflowDefinitionStore(postgres_url)

    count = store.sync_registry(WORKFLOW_REGISTRY)
    definitions = store.list_definitions()
    ask = store.select_active_spec("ask", registry=WORKFLOW_REGISTRY)

    assert count >= 1
    assert any(item["workflow_id"] == "ask" for item in definitions)
    assert ask is not None
    assert ask.workflow_id == "ask"
    assert ask.version == "v1"


def test_workflow_deployment_can_disable_projection(postgres_url, clean_postgres_business_tables):
    store = PostgresWorkflowDefinitionStore(postgres_url)
    store.sync_registry(WORKFLOW_REGISTRY)

    deployment = store.set_deployment(
        "direct_answer",
        stable_version="v1",
        status="disabled",
    )
    selected = store.select_active_spec("direct_answer", registry=WORKFLOW_REGISTRY)

    assert deployment.status == "disabled"
    assert selected is None


def test_workflow_deployment_requires_passing_eval_gate(postgres_url, clean_postgres_business_tables):
    store = PostgresWorkflowDefinitionStore(postgres_url)
    store.sync_registry(WORKFLOW_REGISTRY)

    try:
        store.set_deployment("ask", stable_version="v1")
    except ValueError as exc:
        assert "eval gate" in str(exc)
    else:
        raise AssertionError("deployment should be blocked without eval")

    failed = store.record_eval_run(
        workflow_id="ask",
        version="v1",
        suite="default",
        passed=False,
        score=0.2,
        metrics={"recall": 0.2},
    )
    assert failed.passed is False
    assert store.get_eval_gate_status("ask", "v1")["passed"] is False

    passed = store.record_eval_run(
        workflow_id="ask",
        version="v1",
        suite="default",
        passed=True,
        score=0.95,
        metrics={"recall": 0.95},
        report={"cases": 30},
    )
    deployment = store.set_deployment("ask", stable_version="v1")

    assert passed.passed is True
    assert deployment.stable_version == "v1"
    assert store.get_eval_gate_status("ask", "v1")["eval_run_id"] == passed.eval_run_id


def test_workflow_deployment_can_be_forced_for_dev(postgres_url, clean_postgres_business_tables):
    store = PostgresWorkflowDefinitionStore(postgres_url)
    store.sync_registry(WORKFLOW_REGISTRY)

    deployment = store.set_deployment(
        "ask",
        stable_version="v1",
        require_eval_gate=False,
    )

    assert deployment.workflow_id == "ask"
    assert deployment.status == "stable"


def test_runtime_exposes_synced_workflow_definitions(runtime):
    definitions = runtime.list_workflow_definitions()
    deployment = runtime.get_workflow_deployment("ask")

    assert any(item["workflow_id"] == "ask" for item in definitions)
    assert deployment is not None
    assert deployment.stable_version == "v1"


def test_runtime_exposes_eval_gate(runtime):
    status = runtime.get_workflow_eval_gate_status("ask", "v1")
    assert status["passed"] is False
    assert status["status"] == "missing"

    run = runtime.record_workflow_eval_run(
        "ask",
        "v1",
        passed=True,
        score=1.0,
        metrics={"smoke": 1.0},
    )
    status = runtime.get_workflow_eval_gate_status("ask", "v1")

    assert run.passed is True
    assert status["passed"] is True


def test_canary_deployment_uses_stable_routing_bucket(
    postgres_url, clean_postgres_business_tables,
):
    store = PostgresWorkflowDefinitionStore(postgres_url)
    store.sync_registry(WORKFLOW_REGISTRY)
    ask_v2 = replace(WORKFLOW_REGISTRY.select("ask"), version="v2")
    store.record_definitions([ask_v2])
    store.set_deployment(
        "ask",
        stable_version="v1",
        status="canary",
        canary_version="v2",
        canary_percent=50,
        require_eval_gate=False,
    )

    versions = {
        store.select_active_spec(
            "ask",
            registry=WORKFLOW_REGISTRY,
            routing_key=f"user-{index}",
        ).version
        for index in range(100)
    }
    same_a = store.select_active_spec(
        "ask", registry=WORKFLOW_REGISTRY, routing_key="stable-user"
    )
    same_b = store.select_active_spec(
        "ask", registry=WORKFLOW_REGISTRY, routing_key="stable-user"
    )

    assert versions == {"v1", "v2"}
    assert same_a.version == same_b.version


def test_eval_policy_requires_all_suites_and_thresholds(
    postgres_url, clean_postgres_business_tables,
):
    store = PostgresWorkflowDefinitionStore(postgres_url)
    store.sync_registry(WORKFLOW_REGISTRY)
    store.set_eval_policy(
        "ask",
        required_suites=[
            {"suite": "smoke", "min_score": 0.9},
            {
                "suite": "retrieval",
                "metric_thresholds": {"recall": 0.8, "faithfulness": 0.85},
            },
        ],
    )
    store.record_eval_run(
        workflow_id="ask",
        version="v1",
        suite="smoke",
        passed=True,
        score=0.95,
    )
    store.record_eval_run(
        workflow_id="ask",
        version="v1",
        suite="retrieval",
        passed=True,
        score=0.9,
        metrics={"recall": 0.82, "faithfulness": 0.7},
    )

    blocked = store.evaluate_deployment_gate("ask", "v1")
    assert blocked["passed"] is False

    store.record_eval_run(
        workflow_id="ask",
        version="v1",
        suite="retrieval",
        passed=True,
        score=0.9,
        metrics={"recall": 0.82, "faithfulness": 0.9},
    )
    passed = store.evaluate_deployment_gate("ask", "v1")

    assert passed["passed"] is True
    assert len(passed["suites"]) == 2


def test_workflow_dry_run_projects_without_execution(runtime):
    result = runtime.dry_run_workflow(intent="capture_text", routing_key="u1")

    assert result["valid"] is True
    assert result["workflow_id"] == "capture_text"
    assert result["workflow_version"] == "v1"
    assert result["steps"][0]["tool_name"] == "capture_text"
