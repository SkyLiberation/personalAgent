"""Deterministic same-session runtime gate (real LangGraph/Postgres, stub router)."""

from __future__ import annotations

import pytest

from .dataset import default_cases_path, load_cases
from .runner import execute_conversation

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


def _case(case_id: str):
    return next(case for case in load_cases(default_cases_path()) if case.id == case_id)


def test_two_entries_share_thread_and_retain_first_turn(runtime):
    case = _case("conv-001")
    run = execute_conversation(
        runtime,
        case,
        user_id="conversation-runtime",
        session_id="conversation-runtime-basic",
    )
    assert len({turn.thread_id for turn in run.turns}) == 1
    assert run.turns[1].retained_context_refs == [0]
    assert all(turn.reached_terminal for turn in run.turns)


def test_clarification_resumes_original_run(runtime):
    case = _case("conv-003")
    run = execute_conversation(
        runtime,
        case,
        user_id="conversation-runtime",
        session_id="conversation-runtime-resume",
    )
    interrupted, resumed = run.turns
    assert interrupted.outcome == "clarify"
    assert resumed.outcome == "ready"
    assert resumed.run_id == interrupted.run_id == resumed.resumed_from_run_id
    assert resumed.thread_id == interrupted.thread_id
    assert resumed.intents == ["ask"]
    assert resumed.reached_terminal


def test_rejected_clarification_terminates_without_side_effect(runtime):
    case = _case("conv-004")
    run = execute_conversation(
        runtime,
        case,
        user_id="conversation-runtime",
        session_id="conversation-runtime-reject",
    )
    assert run.turns[-1].reached_terminal
    assert run.turns[-1].intents == []
    assert run.final_note_delta == 0
