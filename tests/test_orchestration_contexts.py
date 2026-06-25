from __future__ import annotations

from dataclasses import fields

from personal_agent.orchestration.orchestration_contexts import (
    DirectAnswerContext,
    GraphContexts,
    PlanningContext,
    ReactContext,
    RoutingContext,
    SummaryContext,
    StepExecutionContext,
)


def _field_names(model) -> set[str]:
    return {item.name for item in fields(model)}


def test_graph_context_is_only_an_assembly_boundary():
    assert _field_names(GraphContexts) == {
        "routing",
        "planning",
        "direct_answer",
        "steps",
        "react",
    }


def test_routing_context_cannot_access_execution_capabilities():
    names = _field_names(RoutingContext)
    assert names == {"settings", "memory", "intent_router", "compress_context"}
    assert "tool_executor" not in names
    assert "workflow_planner" not in names
    assert "execute_capture" not in names


def test_planning_context_contains_only_compilation_capabilities():
    assert _field_names(PlanningContext) == {
        "workflow_planner",
        "step_projection_validator",
    }


def test_direct_answer_context_cannot_access_workflow_capabilities():
    names = _field_names(DirectAnswerContext)
    assert "tool_executor" not in names
    assert "replanner" not in names
    assert "workflow_planner" not in names
    assert names == {"settings", "compress_context"}


def test_step_and_react_contexts_have_distinct_boundaries():
    step_names = _field_names(StepExecutionContext)
    react_names = _field_names(ReactContext)

    assert "replanner" in step_names
    assert "ask_run_context_store" in step_names
    assert "summary" in step_names
    assert "direct_answer" in step_names
    assert "policy_engine" not in step_names
    assert react_names == {"settings", "tool_executor", "policy_engine"}


def test_summary_context_contains_only_summary_capabilities():
    assert _field_names(SummaryContext) == {
        "summarize_chat",
        "load_thread_messages",
    }
