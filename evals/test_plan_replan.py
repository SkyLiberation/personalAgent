"""Regression evaluation for planner → validator → executor → replanner flows.

Each case simulates a plan execution failure and asserts that the replanner
produces intent-appropriate recovery steps.  These are lightweight unit-level
evaluations that do not require LLM or infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from personal_agent.planning.replanner import Replanner
from personal_agent.orchestration.step_projector import ExecutionStep
from personal_agent.planning.workflow import WORKFLOW_REGISTRY
from personal_agent.kernel.config import Settings


@dataclass
class ReplanEvalCase:
    id: str
    description: str
    intent: str
    original_steps: list[ExecutionStep]
    failed_step_id: str
    error: str
    # Expected properties of the revised plan
    expect_revised: bool = True
    expected_action_types: list[str] = field(default_factory=list)
    forbidden_action_types: list[str] = field(default_factory=list)


def _make_steps_for_intent(intent: str, settings: Settings | None = None) -> list[ExecutionStep]:
    """Project deterministic steps for an intent from the workflow registry.

    Replaces the removed ``DefaultTaskPlanner.fallback_plan``; the replanner
    under test consumes ``ExecutionStep`` projections produced here.
    """
    return WORKFLOW_REGISTRY.project(intent)


def _make_replanner() -> Replanner:
    return Replanner(Settings())


# ---- Evaluation cases ----

EVAL_CASES: list[ReplanEvalCase] = [
    # --- delete_knowledge (projected: del-1 retrieve, del-2 resolve, del-3 tool_call, del-4 compose) ---
    ReplanEvalCase(
        id="replan-del-retrieve-fails",
        description="delete_knowledge: retrieve step fails → salvage compose added to remaining valid steps",
        intent="delete_knowledge",
        original_steps=_make_steps_for_intent("delete_knowledge"),
        failed_step_id="del-1",
        error="GraphitiError: Neo4j unreachable",
        expect_revised=True,
        expected_action_types=["compose"],
        forbidden_action_types=[],
    ),
    ReplanEvalCase(
        id="replan-del-delete-fails",
        description="delete_knowledge: tool_call (del-3) fails → salvage compose kept",
        intent="delete_knowledge",
        original_steps=_make_steps_for_intent("delete_knowledge"),
        failed_step_id="del-3",
        error="DeleteNoteTool: note_id not found",
        expect_revised=True,
        expected_action_types=["compose"],
    ),
    # --- solidify_conversation (projected: sol-1 compose, sol-2 tool_call) ---
    ReplanEvalCase(
        id="replan-sol-compose-fails",
        description="solidify_conversation: compose (sol-1) fails → sol-2 filtered (dep), salvage compose added",
        intent="solidify_conversation",
        original_steps=_make_steps_for_intent("solidify_conversation"),
        failed_step_id="sol-1",
        error="OpenAIError: model unavailable",
        expect_revised=True,
        expected_action_types=["compose"],
    ),
    # --- ask (projected: ask-retrieve, ask-compose, ask-verify) ---
    ReplanEvalCase(
        id="replan-ask-retrieve-fails",
        description="ask: retrieve fails → salvage compose for the remaining plan",
        intent="ask",
        original_steps=_make_steps_for_intent("ask"),
        failed_step_id="ask-retrieve",
        error="GraphitiError: timeout",
        expect_revised=True,
        expected_action_types=["compose"],
    ),
    ReplanEvalCase(
        id="replan-ask-compose-fails",
        description="ask: compose fails after successful retrieve → new salvage compose added",
        intent="ask",
        original_steps=_make_steps_for_intent("ask"),
        failed_step_id="ask-compose",
        error="OpenAIError: rate limit",
        expect_revised=True,
        expected_action_types=["compose"],
    ),
]


def test_replan_delete_knowledge_retrieve_fails() -> None:
    """delete_knowledge: retrieve failure produces compose recovery."""
    case = EVAL_CASES[0]
    _eval_case(case)


def test_replan_delete_knowledge_delete_fails() -> None:
    """delete_knowledge: delete (tool_call) failure still produces compose."""
    _eval_case(_case("replan-del-delete-fails"))


def test_replan_solidify_compose_fails() -> None:
    """solidify_conversation: compose failure keeps remaining tool_call."""
    _eval_case(_case("replan-sol-compose-fails"))


def test_replan_ask_retrieve_fails() -> None:
    """ask: retrieve failure adds salvage compose."""
    _eval_case(_case("replan-ask-retrieve-fails"))


def test_replan_ask_compose_fails() -> None:
    """ask: compose failure adds new compose."""
    _eval_case(_case("replan-ask-compose-fails"))


def test_projected_intents_have_steps() -> None:
    """Intents that enter the step-projection replanner must project steps."""
    for intent in ("delete_knowledge", "solidify_conversation", "ask"):
        steps = WORKFLOW_REGISTRY.project(intent)
        assert len(steps) > 0, f"intent={intent!r} projects no steps"
        for s in steps:
            assert s.step_id, f"intent={intent!r} step missing step_id"
            assert s.action_type in (
                "retrieve", "tool_call", "compose", "verify", "resolve"
            ), f"intent={intent!r} step {s.step_id} has invalid action_type={s.action_type!r}"


def test_projected_plans_no_duplicate_ids() -> None:
    """Projected plans should never have duplicate step_ids."""
    for intent in ("delete_knowledge", "solidify_conversation", "ask"):
        steps = WORKFLOW_REGISTRY.project(intent)
        ids = [s.step_id for s in steps]
        assert len(ids) == len(set(ids)), f"intent={intent!r} has duplicate step_ids: {ids}"


# ---- helpers ----

def _case(case_id: str) -> ReplanEvalCase:
    return next(c for c in EVAL_CASES if c.id == case_id)


def _eval_case(case: ReplanEvalCase) -> None:
    replanner = _make_replanner()

    # Mark the failed step as failed (others remain "planned")
    for s in case.original_steps:
        if s.step_id == case.failed_step_id:
            s.status = "failed"
        else:
            s.status = "planned"

    revised = replanner._replan_heuristic(
        case.original_steps,
        next(s for s in case.original_steps if s.step_id == case.failed_step_id),
        case.error,
        intent=case.intent,
    )

    if case.expect_revised:
        assert revised is not None, f"{case.id}: expected revised steps but got None"
        assert len(revised) > 0, f"{case.id}: expected non-empty revised steps"
    else:
        if revised is not None:
            assert len(revised) == 0, f"{case.id}: expected None/empty but got {len(revised)} steps"

    if case.expected_action_types and revised:
        actual_actions = [s.action_type for s in revised]
        for expected in case.expected_action_types:
            assert expected in actual_actions, (
                f"{case.id}: expected action_type={expected!r} in revised steps, "
                f"got {actual_actions}"
            )

    if case.forbidden_action_types and revised:
        actual_actions = [s.action_type for s in revised]
        for forbidden in case.forbidden_action_types:
            assert forbidden not in actual_actions, (
                f"{case.id}: unexpected action_type={forbidden!r} in revised steps"
            )
