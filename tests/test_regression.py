from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from personal_agent.kernel.config import OpenAIConfig, Settings
from personal_agent.kernel.models import EntryInput
from personal_agent.orchestration.service import AgentService
from personal_agent.planning.task_analyzer import Goal, ResourceHint, TaskAnalysis
from tests.conftest import POSTGRES_URL

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


@pytest.fixture
def svc(temp_dir: Path) -> AgentService:
    service = AgentService(Settings(
        data_dir=temp_dir,
        postgres_url=POSTGRES_URL,
        openai=OpenAIConfig(api_key=None, base_url=None, model="gpt-4.1-mini"),
    ))
    service.graph_store = MagicMock()
    service.graph_store.configured.return_value = False
    return service


def _force_route(service: AgentService, route: str) -> None:
    kind, domain, resource_types, operations = {
        "delete_knowledge": ("external_state", "knowledge", ["note"], ["delete"]),
        "capture_text": ("external_state", "knowledge", ["text"], ["ingest"]),
        "solidify_conversation": ("external_state", "conversation", ["thread"], ["ingest"]),
        "ask": ("response", "knowledge", ["note"], ["search", "read"]),
    }.get(route, ("response", "", [], []))
    analyzer = MagicMock()
    analyzer.analyze.return_value = TaskAnalysis(user_goal=f"Mock input for {route}", goals=[Goal(
        goal_id="goal_1",
        result_contract=kind,
        side_effect_intent="mutation" if kind == "external_state" else "none",
        description=f"Mock input for {route}",
        resource_hints=[ResourceHint(
            semantic_domain=domain,
            resource_types=resource_types,
            operations=operations,
        )] if domain else [],
    )])
    service.runtime._task_analyzer = analyzer
    service.runtime._graph_contexts = replace(
        service.runtime.graph_contexts,
        routing=replace(service.runtime.graph_contexts.routing, task_analyzer=analyzer),
    )


def _event_types(result) -> list[str]:
    return [event["type"] for event in result.events]


def test_delete_is_a_governed_procedure_not_a_top_level_step_plan(
    svc: AgentService,
    monkeypatch,
):
    _force_route(svc, "delete_knowledge")
    note = svc.execute_capture(
        text="旧部署流程记录",
        source_type="text",
        user_id="alice",
    ).note
    monkeypatch.setattr(
        "personal_agent.orchestration.orchestration_nodes._helpers._structured_llm_respond",
        lambda *_args, **_kwargs: (
            '{"thought":"定位已有笔记","done":true,'
            f'"result":{{"note_id":"{note.id}"}}}}'
        ),
    )
    monkeypatch.setattr(
        "personal_agent.orchestration.orchestration_nodes._helpers._react_llm_native",
        lambda *_args, **_kwargs: type("R", (), {
            "done": True,
            "thought": "定位已有笔记",
            "result": {"note_id": note.id},
            "tool_name": None,
            "tool_input": None,
            "native_call_id": None,
            "parse_failed": False,
        })(),
    )
    svc.graph_store.ask.return_value = type("R", (), {
        "enabled": True,
        "answer": "graph match",
        "entity_names": ["部署"],
        "relation_facts": [],
        "related_episode_uuids": ["ep-deploy"],
    })()

    result = svc.entry(EntryInput(
        text="删除那条关于旧部署流程的笔记",
        user_id="alice",
        session_id="delete-protocol",
    ))

    assert result.plan is None
    assert result.run_status == "blocked_approval"
    assert result.pending_confirmation
    assert "procedure_started" in _event_types(result)
    assert "confirmation_required" in _event_types(result)
    assert "goal_graph_compiled" in _event_types(result)


def test_solidify_without_source_dialogue_stops_without_fabricating_a_note(
    svc: AgentService,
):
    _force_route(svc, "solidify_conversation")

    result = svc.entry(EntryInput(
        text="把关于缓存一致性的结论固化下来",
        user_id="bob",
        session_id="solidify-empty",
    ))

    execution_types = {
        event.get("payload", {}).get("execution_event", {}).get("event_type")
        for event in result.events
    }
    assert result.run_status == "completed"
    assert "procedure_started" in _event_types(result)
    assert "step_failed" in _event_types(result)
    assert "task_terminated" in execution_types
    assert not svc.memory.list_notes("bob")


def test_procedure_failure_is_observed_before_executive_stop(svc: AgentService):
    _force_route(svc, "solidify_conversation")

    result = svc.entry(EntryInput(
        text="固化一段并不存在的对话",
        user_id="bob",
        session_id="solidify-order",
    ))

    event_types = _event_types(result)
    assert event_types.index("step_failed") < event_types.index("action_outcome")
    assert event_types.index("action_outcome") < event_types.index("run_completed")
    decisions = [
        event["payload"]["decision"]["action"]
        for event in result.events
        if event["type"] == "executive_decision"
    ]
    assert decisions[-1] == "stop"


def test_procedure_steps_never_remain_planned_at_a_terminal_boundary(svc: AgentService):
    _force_route(svc, "solidify_conversation")

    result = svc.entry(EntryInput(
        text="固化一段并不存在的对话",
        user_id="bob",
        session_id="solidify-terminal",
    ))

    started = {
        event["payload"].get("step_id")
        for event in result.events
        if event["type"] == "step_started" and event["payload"].get("step_id") != "__steps__"
    }
    terminal = {
        event["payload"].get("step_id")
        for event in result.events
        if event["type"] in {"step_completed", "step_failed"}
    }
    assert started
    assert started.issubset(terminal)
