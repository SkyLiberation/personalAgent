from __future__ import annotations

import pytest

from personal_agent.kernel.config import OpenAIConfig, ReflectionReplaySettings, Settings
from personal_agent.kernel.models import MemoryItem
from personal_agent.memory.facade import MemoryFacade
from personal_agent.governance.policy import PolicyEngine


class FakeLocalStore:
    """In-memory stand-in for PostgresMemoryStore covering memory_item ops."""

    def __init__(self) -> None:
        self.items: dict[str, MemoryItem] = {}
        self.search_calls: list[dict] = []

    def add_memory_item(self, item: MemoryItem) -> None:
        self.items[item.id] = item

    def get_memory_item(self, item_id: str, *, user_id: str | None = None) -> MemoryItem | None:
        item = self.items.get(item_id)
        if item is None:
            return None
        if user_id is not None and item.user_id != user_id:
            return None
        return item

    def list_memory_items(self, user_id, *, memory_type=None, status=None, limit=50):
        return self._filter(user_id, memory_type, status, limit)

    def search_memory_items(self, user_id, query, *, memory_type=None, status="confirmed", limit=5):
        self.search_calls.append(
            {"user_id": user_id, "query": query, "memory_type": memory_type, "status": status, "limit": limit}
        )
        return self._filter(user_id, memory_type, status, limit)

    def _filter(self, user_id, memory_type, status, limit):
        out = []
        statuses = status if isinstance(status, list) else ([status] if status else None)
        for item in self.items.values():
            if item.user_id != user_id:
                continue
            if memory_type and item.memory_type != memory_type:
                continue
            if statuses and item.status not in statuses:
                continue
            out.append(item)
        return out[:limit]


def _reflection(item_id: str, *, confidence: float = 0.5, status: str = "candidate", user_id: str = "u1") -> MemoryItem:
    return MemoryItem(
        id=item_id,
        memory_type="reflection",
        user_id=user_id,
        status=status,
        confidence=confidence,
        content="过往失败教训",
        applies_to=["ask"],
    )


@pytest.fixture
def facade() -> tuple[MemoryFacade, FakeLocalStore]:
    store = FakeLocalStore()
    return MemoryFacade(store, policy_engine=PolicyEngine()), store


class TestPromoteReflection:
    def test_success_raises_confidence_and_confirms_at_threshold(self, facade):
        fac, store = facade
        store.add_memory_item(_reflection("r1", confidence=0.5))
        # 0.5 -> 0.7 -> 0.9 (>=0.8 confirms)
        fac.promote_reflection("r1", user_id="u1", outcome="completed")
        assert store.items["r1"].status == "candidate"
        assert store.items["r1"].confidence == pytest.approx(0.7)
        fac.promote_reflection("r1", user_id="u1", outcome="completed")
        assert store.items["r1"].confidence == pytest.approx(0.9)
        assert store.items["r1"].status == "confirmed"

    def test_failure_lowers_confidence_and_rejects_at_floor(self, facade):
        fac, store = facade
        store.add_memory_item(_reflection("r2", confidence=0.5))
        # 0.5 -> 0.25 -> 0.0 (<=0.2 rejects)
        fac.promote_reflection("r2", user_id="u1", outcome="failed")
        assert store.items["r2"].status == "candidate"
        fac.promote_reflection("r2", user_id="u1", outcome="failed")
        assert store.items["r2"].status == "rejected"

    def test_terminal_status_is_not_revived(self, facade):
        fac, store = facade
        store.add_memory_item(_reflection("r3", confidence=0.0, status="rejected"))
        result = fac.promote_reflection("r3", user_id="u1", outcome="completed")
        assert result.status == "rejected"
        assert result.confidence == 0.0

    def test_missing_or_non_reflection_returns_none(self, facade):
        fac, store = facade
        assert fac.promote_reflection("nope", user_id="u1", outcome="completed") is None
        store.items["p1"] = MemoryItem(id="p1", memory_type="procedural", user_id="u1")
        assert fac.promote_reflection("p1", user_id="u1", outcome="completed") is None


class TestSearchMultiStatus:
    def test_list_status_returns_both_candidate_and_confirmed(self, facade):
        fac, store = facade
        store.add_memory_item(_reflection("c1", status="candidate"))
        store.add_memory_item(_reflection("c2", status="confirmed"))
        store.add_memory_item(_reflection("c3", status="rejected"))
        found = fac.search_memory_items(
            "u1", "教训", memory_type="reflection", status=["candidate", "confirmed"], limit=10
        )
        ids = {i.id for i in found}
        assert ids == {"c1", "c2"}


class TestReplanReflectionInjection:
    @pytest.fixture
    def replanner(self):
        from personal_agent.agent.replanner import Replanner

        # No LLM configured -> _replan_with_llm short-circuits; we test prompt build instead.
        return Replanner(Settings(openai=OpenAIConfig(api_key="", base_url="", model="", small_model="")))

    def test_reflections_render_into_replanner_prompt(self):
        from personal_agent.kernel.prompts import render_prompt
        from personal_agent.agent.replanner import _clip_reflection

        item = _reflection("r1", confidence=0.6)
        summary = _clip_reflection(item)
        assert "conf=0.60" in summary
        prompt = render_prompt(
            "replanner.user",
            intent="ask", steps_summary="s", failed_step_id="f",
            failed_action_type="retrieve", error="e", reflections=summary, obs_summary="无",
        )
        assert "过往失败教训" in prompt
        assert "教训" in prompt  # the reflection guidance line is present

    def test_replan_accepts_reflections_arg(self, replanner):
        from personal_agent.agent.execution_models import ExecutionStep

        steps = [
            ExecutionStep(step_id="s1", action_type="retrieve", description="检索", status="failed"),
        ]
        # Should not raise when reflections are passed; falls back to heuristic.
        result = replanner.replan(steps, steps[0], "err", {}, "ask", reflections=[_reflection("r1")])
        assert result is not None


class TestPromotionTrigger:
    def test_record_entry_episode_promotes_applied_reflections(self):
        from personal_agent.application.episodic_memory import _promote_applied_reflections
        from personal_agent.kernel.models import MemoryEpisode

        store = FakeLocalStore()
        fac = MemoryFacade(store, policy_engine=PolicyEngine())
        store.add_memory_item(_reflection("r1", confidence=0.7))

        class _Result:
            applied_reflection_ids = ["r1"]

        episode = MemoryEpisode(
            id="e1", user_id="u1", session_id="s", thread_id="t", run_id="run1",
            workflow="ask", title="t", summary="s", outcome="completed", entry_text="q",
        )
        _promote_applied_reflections(fac, _Result(), episode, Settings())
        # completed -> 0.7 + 0.2 = 0.9 >= 0.8 -> confirmed
        assert store.items["r1"].status == "confirmed"

    def test_disabled_flag_skips_promotion(self):
        from personal_agent.application.episodic_memory import _promote_applied_reflections
        from personal_agent.kernel.models import MemoryEpisode

        store = FakeLocalStore()
        fac = MemoryFacade(store, policy_engine=PolicyEngine())
        store.add_memory_item(_reflection("r1", confidence=0.7))

        class _Result:
            applied_reflection_ids = ["r1"]

        episode = MemoryEpisode(
            id="e1", user_id="u1", session_id="s", thread_id="t", run_id="run1",
            workflow="ask", title="t", summary="s", outcome="completed", entry_text="q",
        )
        disabled = Settings(reflection_replay=ReflectionReplaySettings(enabled=False))
        _promote_applied_reflections(fac, _Result(), episode, disabled)
        # unchanged
        assert store.items["r1"].confidence == pytest.approx(0.7)
        assert store.items["r1"].status == "candidate"
