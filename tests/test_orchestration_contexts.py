from __future__ import annotations

from dataclasses import fields

from personal_agent.orchestration.orchestration_contexts import (
    DirectAnswerContext,
    ExecutiveContext,
    GraphContexts,
    ReactContext,
    RoutingContext,
    StepExecutionContext,
    SummaryContext,
)


def _field_names(model) -> set[str]:
    return {item.name for item in fields(model)}


def test_graph_context_is_only_an_assembly_boundary():
    assert _field_names(GraphContexts) == {
        "routing", "executive", "direct_answer", "steps", "react",
    }


def test_routing_context_cannot_access_execution_capabilities():
    assert _field_names(RoutingContext) == {
        "settings", "memory", "intent_router", "compress_context",
    }


def test_executive_context_separates_decision_from_execution():
    names = _field_names(ExecutiveContext)
    assert {"goal_interpreter", "controller", "decision_validator"}.issubset(names)
    assert {"ledger_projector", "goal_verifier", "completion_verifier"}.issubset(names)
    assert "replanner" not in names


def test_direct_answer_context_has_no_governed_execution_capabilities():
    assert _field_names(DirectAnswerContext) == {
        "settings", "compress_context", "model_client",
    }


def test_step_and_react_contexts_have_distinct_boundaries():
    step_names = _field_names(StepExecutionContext)
    react_names = _field_names(ReactContext)
    assert "replanner" not in step_names
    assert "agent_gateway" in step_names
    assert react_names == {
        "settings", "tool_executor", "policy_engine", "model_client", "structured_client",
    }


def test_summary_context_contains_only_summary_capabilities():
    assert _field_names(SummaryContext) == {"summarize_chat", "load_thread_messages"}
