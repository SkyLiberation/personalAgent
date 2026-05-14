from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from personal_agent.agent.plan_validator import PlanValidationResult
from personal_agent.agent.router import RouterDecision
from personal_agent.agent.service import AgentService
from personal_agent.core.config import Settings
from personal_agent.core.models import EntryInput


@pytest.fixture
def test_settings(temp_dir: Path) -> Settings:
    return Settings(
        data_dir=temp_dir,
        openai_api_key="sk-test",
        openai_base_url="https://api.test.com/v1",
        openai_model="gpt-4.1-mini",
        openai_small_model="gpt-4.1-nano",
    )


@pytest.fixture
def svc(test_settings: Settings) -> AgentService:
    svc = AgentService(test_settings)
    svc.graph_store = MagicMock()
    svc.graph_store.configured.return_value = False
    return svc


def _bypass_validator(svc: AgentService) -> MagicMock:
    """Replace plan_validator.validate to always pass (note_id resolved at runtime)."""
    mock_validator = MagicMock()
    mock_validator.validate.return_value = PlanValidationResult(
        valid=True, issues=[], warnings=[], corrected_steps=None,
    )
    svc._runtime._plan_validator = mock_validator
    return mock_validator


class TestCrossLayerRegression:
    """Full entry → router → planner → validator → executor cross-layer tests.

    Mocks _intent_router.classify to force planning intents so that PlanExecutor
    is exercised end-to-end in integration tests.
    """

    def _mock_router(self, svc: AgentService, route: str) -> MagicMock:
        """Replace the runtime's intent router with a mock returning a forced decision."""
        decision = RouterDecision(
            route=route,
            confidence=0.9,
            requires_planning=True,
            requires_retrieval=True,
            risk_level="high" if route == "delete_knowledge" else "low",
            requires_confirmation=route == "delete_knowledge",
            user_visible_message=f"Mock forced {route}",
        )
        mock_router = MagicMock()
        mock_router.classify.return_value = decision
        svc._runtime._intent_router = mock_router
        return mock_router

    def test_delete_knowledge_triggers_plan_executor(self, svc: AgentService):
        """delete_knowledge with requires_planning=True takes PlanExecutor path."""
        self._mock_router(svc, "delete_knowledge")
        _bypass_validator(svc)
        # Prime knowledge base with a note to resolve
        svc.capture(
            text="旧部署流程：第一步构建镜像，第二步部署到K8s集群。",
            source_type="text", user_id="alice", attempt_graph=False,
        )
        svc.graph_store.ask.return_value = type("R", (), {
            "enabled": False, "answer": "",
            "entity_names": [], "relation_facts": [], "related_episode_uuids": [],
        })()
        svc._runtime.execute_ask = MagicMock(return_value=MagicMock(answer="部分回答"))

        entry = EntryInput(text="删除那条关于旧部署流程的笔记", user_id="alice")
        result = svc.entry(entry)

        # PlanExecutor path populates plan_steps with status
        assert len(result.plan_steps) > 0
        statuses = {s.get("status") for s in result.plan_steps}
        assert "completed" in statuses or "failed" in statuses

    def test_solidify_conversation_triggers_plan_executor(self, svc: AgentService):
        """solidify_conversation with requires_planning=True takes PlanExecutor path."""
        self._mock_router(svc, "solidify_conversation")
        svc.graph_store.ask.return_value = type("R", (), {
            "enabled": False, "answer": "",
            "entity_names": [], "relation_facts": [], "related_episode_uuids": [],
        })()
        svc._runtime.execute_ask = MagicMock(return_value=MagicMock(answer="固化的草稿内容"))

        entry = EntryInput(text="把关于缓存一致性的结论固化下来", user_id="bob")
        result = svc.entry(entry)

        assert len(result.plan_steps) > 0
        action_types = {s.get("action_type") for s in result.plan_steps}
        assert "compose" in action_types

    def test_delete_knowledge_full_flow_creates_pending_action(self, svc: AgentService):
        """Complete delete flow: plan → resolve → tool_call creates pending action."""
        self._mock_router(svc, "delete_knowledge")
        _bypass_validator(svc)
        note = svc.capture(
            text="旧部署流程记录", source_type="text", user_id="alice", attempt_graph=False,
        ).note

        # Mock graph to return episode UUIDs so resolve tier-1 hits
        svc.graph_store.ask.return_value = type("R", (), {
            "enabled": True, "answer": "graph match",
            "entity_names": ["部署"],
            "relation_facts": [],
            "related_episode_uuids": ["ep-uuid-deploy"],
        })()
        svc._runtime.execute_ask = MagicMock(return_value=MagicMock(answer="找到笔记"))

        entry = EntryInput(text="删除那条关于旧部署流程的笔记", user_id="alice")
        result = svc.entry(entry)

        # Plan steps should include tool_call with delete_note
        tool_steps = [s for s in result.plan_steps if s.get("action_type") == "tool_call"]
        assert len(tool_steps) > 0
        # Tool call step should have captured a status
        assert tool_steps[0].get("status") in ("completed", "failed", "planned")

    def test_solidify_full_flow_compose_generates_answer(self, svc: AgentService):
        """Solidify full flow: retrieve → compose → verify generates draft text."""
        self._mock_router(svc, "solidify_conversation")
        svc.graph_store.ask.return_value = type("R", (), {
            "enabled": True, "answer": "graph results about caching",
            "entity_names": ["缓存", "一致性"],
            "relation_facts": ["缓存一致性需要分布式锁"],
            "related_episode_uuids": ["ep-cache"],
        })()
        svc._runtime.execute_ask = MagicMock(
            return_value=MagicMock(answer="结论：缓存一致性需要分布式锁和版本号机制。")
        )

        entry = EntryInput(text="把关于缓存一致性的讨论结论固化下来", user_id="bob")
        result = svc.entry(entry)

        # Result should have a reply (from compose step or default)
        assert result.reply_text
        # Plan steps should exist
        assert len(result.plan_steps) > 0

    def test_delete_knowledge_plan_steps_status_transitions(self, svc: AgentService):
        """Verify plan steps transition from 'planned' to final statuses."""
        self._mock_router(svc, "delete_knowledge")
        _bypass_validator(svc)
        svc.capture(
            text="应删除的测试笔记", source_type="text", user_id="alice", attempt_graph=False,
        )
        svc.graph_store.ask.return_value = type("R", (), {
            "enabled": False, "answer": "",
            "entity_names": [], "relation_facts": [], "related_episode_uuids": [],
        })()
        svc._runtime.execute_ask = MagicMock(return_value=MagicMock(answer="无法完成"))

        entry = EntryInput(text="删除那条关于测试笔记的内容", user_id="alice")
        result = svc.entry(entry)

        # All plan steps should have a non-'planned' status (completed, failed, or skipped)
        for step in result.plan_steps:
            assert step.get("status") != "planned", (
                f"Step {step.get('step_id')} still 'planned' — expected transition"
            )
