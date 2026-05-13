"""Regression evaluation for planner → validator → executor → replanner flows.

Each case simulates a plan execution failure and asserts that the replanner
produces intent-appropriate recovery steps.  These are lightweight unit-level
evaluations that do not require LLM or infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from personal_agent.agent.planner import DefaultTaskPlanner, PlanStep
from personal_agent.agent.replanner import Replanner
from personal_agent.core.config import Settings


@dataclass
class ReplanEvalCase:
    id: str
    description: str
    intent: str
    original_steps: list[PlanStep]
    failed_step_id: str
    error: str
    # Expected properties of the revised plan
    expect_revised: bool = True
    expected_action_types: list[str] = field(default_factory=list)
    forbidden_action_types: list[str] = field(default_factory=list)


def _make_steps_for_intent(intent: str, settings: Settings | None = None) -> list[PlanStep]:
    """Generate heuristic steps for a given intent."""
    planner = DefaultTaskPlanner(settings or Settings())
    return planner.fallback_plan(intent)


def _make_replanner() -> Replanner:
    return Replanner(Settings())


# ---- Evaluation cases ----

EVAL_CASES: list[ReplanEvalCase] = [
    # --- delete_knowledge ---
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
        description="delete_knowledge: tool_call (del-4) fails → compose (del-5) kept",
        intent="delete_knowledge",
        original_steps=_make_steps_for_intent("delete_knowledge"),
        failed_step_id="del-4",
        error="DeleteNoteTool: note_id not found",
        expect_revised=True,
        expected_action_types=["compose"],
    ),
    # --- solidify_conversation ---
    ReplanEvalCase(
        id="replan-sol-retrieve-fails",
        description="solidify_conversation: retrieve (sol-1) fails → sol-3/sol-4 kept (indirect deps), no salvage needed",
        intent="solidify_conversation",
        original_steps=_make_steps_for_intent("solidify_conversation"),
        failed_step_id="sol-1",
        error="RuntimeError: no conversation history",
        expect_revised=True,
        expected_action_types=["verify", "tool_call"],
    ),
    ReplanEvalCase(
        id="replan-sol-compose-fails",
        description="solidify_conversation: compose (sol-2) fails → sol-4 tool_call kept (indirect dep)",
        intent="solidify_conversation",
        original_steps=_make_steps_for_intent("solidify_conversation"),
        failed_step_id="sol-2",
        error="OpenAIError: model unavailable",
        expect_revised=True,
        expected_action_types=["tool_call"],
    ),
    # --- ask ---
    ReplanEvalCase(
        id="replan-ask-retrieve-fails",
        description="ask: retrieve fails → salvage compose replaces filtered verify",
        intent="ask",
        original_steps=_make_steps_for_intent("ask"),
        failed_step_id="ask-1",
        error="GraphitiError: timeout",
        expect_revised=True,
        expected_action_types=["compose"],
    ),
    ReplanEvalCase(
        id="replan-ask-compose-fails",
        description="ask: compose fails after successful retrieve → new salvage compose added",
        intent="ask",
        original_steps=_make_steps_for_intent("ask"),
        failed_step_id="ask-2",
        error="OpenAIError: rate limit",
        expect_revised=True,
        expected_action_types=["compose"],
    ),
    # --- capture ---
    ReplanEvalCase(
        id="replan-cap-tool-fails",
        description="capture: tool_call (cap-1) fails → cap-3 verify kept (indirect dep) + salvage compose",
        intent="capture_text",
        original_steps=_make_steps_for_intent("capture_text"),
        failed_step_id="cap-1",
        error="CaptureTextTool: empty content",
        expect_revised=True,
        expected_action_types=["verify", "compose"],
    ),
    # --- unknown (generic fallback) ---
    ReplanEvalCase(
        id="replan-unknown-fallback",
        description="unknown intent: any step fails → generic salvage",
        intent="unknown",
        original_steps=_make_steps_for_intent("unknown"),
        failed_step_id="unk-1",
        error="Exception: unknown error",
        expect_revised=False,
    ),
]


def test_replan_delete_knowledge_retrieve_fails() -> None:
    """delete_knowledge: retrieve failure produces compose recovery."""
    case = EVAL_CASES[0]
    _eval_case(case)


def test_replan_delete_knowledge_delete_fails() -> None:
    """delete_knowledge: delete failure still produces compose."""
    case = EVAL_CASES[1]
    _eval_case(case)


def test_replan_solidify_retrieve_fails() -> None:
    """solidify_conversation: retrieve failure produces compose."""
    case = EVAL_CASES[2]
    _eval_case(case)


def test_replan_solidify_compose_fails() -> None:
    """solidify_conversation: compose failure keeps remaining steps."""
    case = EVAL_CASES[3]
    _eval_case(case)


def test_replan_ask_retrieve_fails() -> None:
    """ask: retrieve failure adds salvage compose."""
    case = EVAL_CASES[4]
    _eval_case(case)


def test_replan_ask_compose_fails() -> None:
    """ask: compose failure adds new compose."""
    case = EVAL_CASES[5]
    _eval_case(case)


def test_replan_capture_tool_fails() -> None:
    """capture: tool_call failure adds salvage compose."""
    case = EVAL_CASES[6]
    _eval_case(case)


def test_replan_unknown_fallback() -> None:
    """unknown intent: no recovery possible."""
    case = EVAL_CASES[7]
    _eval_case(case)


def test_planner_heuristic_covers_all_replan_intents() -> None:
    """All intents that enter replanner should have heuristic fallback plans."""
    intents = [
        "delete_knowledge",
        "solidify_conversation",
        "ask",
        "capture_text",
        "capture_link",
        "capture_file",
        "summarize_thread",
        "direct_answer",
        "unknown",
    ]
    planner = DefaultTaskPlanner(Settings())
    for intent in intents:
        steps = planner.fallback_plan(intent)
        assert len(steps) > 0, f"intent={intent!r} has no heuristic plan"
        for s in steps:
            assert s.step_id, f"intent={intent!r} step missing step_id"
            assert s.action_type in (
                "retrieve", "tool_call", "compose", "verify", "resolve"
            ), f"intent={intent!r} step {s.step_id} has invalid action_type={s.action_type!r}"


def test_heuristic_plans_no_duplicate_ids() -> None:
    """Heuristic plans should never have duplicate step_ids."""
    planner = DefaultTaskPlanner(Settings())
    for intent in (
        "delete_knowledge", "solidify_conversation", "ask",
        "capture_text", "summarize_thread", "direct_answer",
    ):
        steps = planner.fallback_plan(intent)
        ids = [s.step_id for s in steps]
        assert len(ids) == len(set(ids)), f"intent={intent!r} has duplicate step_ids: {ids}"


# ---- helpers ----

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
