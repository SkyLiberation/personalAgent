"""Real-environment Golden flow for automatic knowledge consolidation (stateful).

This is the Phase-2 (DB-dependent) golden flow described in
``docs/golden-set-design.md`` §3.0 / §6. Unlike the self-contained orchestration
cases (你好 / 删除 / 总结), consolidation's correctness is *defined on data that
already exists in the store*. So each case first SEEDS notes, then runs the full
``execute_entry`` pipeline (router → planning → step execution → tool) and
asserts the real side effect.

Per §6, only a real-LLM, real-pipeline run is a Golden Test, so this builds a
real ``AgentService`` from the environment (real router LLM) and skips cleanly
when the router LLM / Postgres is unconfigured — no stub router.

What this covers that nothing else does:

  * ``tests/test_agent_flows.py`` exercises the USE CASE directly
    (``service.execute_consolidate(topic=...)``) — never through the
    router/planner/step graph, never real routing.
  * ``evals/orchestration_quality`` scores route/terminal but its thin
    projection cannot express the supersede side effect, and it has no seed
    mechanism.

This is the only place the WHOLE orchestration path for consolidation runs
against seeded DB state, including the production no-hang invariant (a run that
proceeds past planning must reach a terminal state) and the supersede backlink.
Each case uses a unique ``user_id`` per invocation for isolation (§6.2). Routing
for the clear phrasing "整理成综述" is covered by the Router Golden.

Run:
    uv run pytest evals/test_consolidate_knowledge_flow.py -v
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from personal_agent.core.models import EntryInput
from tests.note_factory import make_note

from .orchestration_quality.real_runner import build_real_service

_SERVICE = build_real_service()
_SKIP_REASON = (
    "router LLM/Postgres not configured "
    "(set ROUTER_*/OPENAI_* + PERSONAL_AGENT_POSTGRES_URL)"
)

_TERMINAL = {"completed", "failed"}


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def _seed_note(service, *, note_id: str, title: str, content: str, user_id: str) -> None:
    service.store.add_note(
        make_note(
            id=note_id,
            title=title,
            content=content,
            summary=title,
            user_id=user_id,
        )
    )


@pytest.mark.skipif(_SERVICE is None, reason=_SKIP_REASON)
class TestConsolidateKnowledgeGolden:
    """Real env: seed notes, then drive consolidation through the real pipeline."""

    def test_consolidates_seeded_topic_notes_through_full_pipeline(self):
        """Two seeded notes on one topic → run routes to consolidate_knowledge,
        reaches a terminal state, and the sources are superseded by the new
        synthesis note with a backlink."""
        user_id = _unique("consolidate")
        suffix = uuid4().hex[:8]
        id_a, id_b = f"vec-a-{suffix}", f"vec-b-{suffix}"
        _seed_note(
            _SERVICE,
            note_id=id_a,
            title="向量检索 基础",
            content="向量检索把文本编码成向量后做相似度匹配，是语义检索的基础。",
            user_id=user_id,
        )
        _seed_note(
            _SERVICE,
            note_id=id_b,
            title="向量检索 重排序",
            content="向量检索召回后用更强的重排序模型做精排，提升命中质量。",
            user_id=user_id,
        )

        result = _SERVICE.execute_entry(
            EntryInput(
                text="把关于向量检索的多条笔记整理成综述",
                user_id=user_id,
                session_id=_unique("consolidate-happy"),
            )
        )

        # Routed to consolidation and the run did not hang (no-hang invariant).
        assert result.intents and result.intents[-1] == "consolidate_knowledge"
        assert result.run_status in _TERMINAL

        # The seeded sources are superseded by a single new synthesis note.
        old_a = _SERVICE.memory.get_note(id_a, user_id=user_id)
        old_b = _SERVICE.memory.get_note(id_b, user_id=user_id)
        assert old_a.version.status == "superseded"
        assert old_b.version.status == "superseded"
        assert old_a.version.superseded_by_note_id == old_b.version.superseded_by_note_id
        summary_id = old_a.version.superseded_by_note_id
        assert summary_id and summary_id not in {id_a, id_b}

        # The synthesis note is current and back-links to both sources.
        summary = _SERVICE.memory.get_note(summary_id, user_id=user_id)
        assert summary.version.status == "current"
        assert {id_a, id_b}.issubset(set(summary.version.supersedes_note_ids))

    def test_single_source_does_not_supersede_but_still_terminates(self):
        """Only one related note exists → consolidation declines ("至少两条"),
        yet the run still terminates cleanly and the lone note is untouched."""
        user_id = _unique("consolidate-solo")
        solo_id = f"solo-{uuid4().hex[:8]}"
        _seed_note(
            _SERVICE,
            note_id=solo_id,
            title="图数据库 入门",
            content="图数据库以节点和边建模关系，适合多跳查询。",
            user_id=user_id,
        )

        result = _SERVICE.execute_entry(
            EntryInput(
                text="把关于图数据库的笔记整理成综述",
                user_id=user_id,
                session_id=_unique("consolidate-solo"),
            )
        )

        # Still routes and still terminates — declining is not hanging.
        assert result.intents and result.intents[-1] == "consolidate_knowledge"
        assert result.run_status in _TERMINAL

        # The single note must NOT be superseded (graceful "< 2 sources").
        solo = _SERVICE.memory.get_note(solo_id, user_id=user_id)
        assert solo.version.status == "current"
        assert solo.version.superseded_by_note_id is None
