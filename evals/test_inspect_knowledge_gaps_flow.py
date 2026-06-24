"""Real-environment Golden flow for proactive knowledge-gap inspection (stateful).

The Phase-2 (DB-dependent) sibling of ``test_consolidate_knowledge_flow.py``
(see ``docs/golden-set-design.md`` §3.0 / §6). Per §6 only a real-LLM, real-
pipeline run counts as a Golden Test, so this builds a real ``AgentService``
from the environment (real router LLM, real planning, real step execution) and
skips cleanly when the router LLM / Postgres is unconfigured.

Gap *detection* is defined on data already in the store: without notes that
actually conflict (or an isolated graph entity) ``inspect()`` only ever returns
"no gaps". So each case first SEEDS the condition, then runs the full
``execute_entry`` pipeline and asserts the gap surfaced end-to-end.

What this covers that nothing else does:

  * ``tests/test_knowledge_gap_analyzer.py`` unit-tests the detector against a
    fake memory/graph — never through the router/planner/step graph, never real.
  * ``evals/router_quality`` scores only that "检查缺口" classifies to
    ``inspect_knowledge_gaps``; it never executes the inspection.

Detection of a *potential_conflict* is deterministic: two recent notes whose
titles share ≥2 tokens but whose ``title + summary`` have opposite negation
polarity. We seed exactly that under a unique ``user_id`` per invocation, which
isolates each run from other notes and from any residual graph (``get_topology``
is user-scoped, so a fresh user sees an empty graph → no isolated-entity noise).
Routing for these clear, in-vocabulary phrasings is covered by the Router Golden
("检查一下我的知识缺口" → inspect_knowledge_gaps).

Run:
    uv run pytest evals/test_inspect_knowledge_gaps_flow.py -v
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from personal_agent.kernel.models import EntryInput
from tests.note_factory import make_note

from .orchestration_quality.real_runner import build_real_service

_SERVICE = build_real_service()
_SKIP_REASON = (
    "router LLM/Postgres not configured "
    "(set ROUTER_*/OPENAI_* + PERSONAL_AGENT_POSTGRES_URL)"
)

_TERMINAL = {"completed", "failed"}
# Deterministic header from ``insight.service.format_knowledge_gaps`` when ≥1 gap
# exists. The per-gap question may be LLM-rephrased; this header never is.
_GAPS_HEADER = "我在整理你的知识库时发现"
_NO_GAPS_TEXT = "当前没有检测到明显的知识孤岛或潜在冲突。"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def _seed_note(service, *, note_id: str, title: str, summary: str, user_id: str) -> None:
    service.store.add_note(
        make_note(
            id=note_id,
            title=title,
            content=summary,
            summary=summary,
            user_id=user_id,
        )
    )


@pytest.mark.skipif(_SERVICE is None, reason=_SKIP_REASON)
class TestInspectKnowledgeGapsGolden:
    """Real env: seed the gap condition, then inspect through the real pipeline."""

    def test_surfaces_seeded_conflict_through_full_pipeline(self):
        """Two notes with the same subject but opposite polarity → run routes to
        inspect_knowledge_gaps, reaches a terminal state, and the report surfaces
        the potential conflict."""
        user_id = _unique("gap-conflict")
        note_id = uuid4().hex[:8]
        # Shared title tokens ("数据库选型", "PostgreSQL"); opposite polarity in
        # the summary (note_b carries the negation "不").
        _seed_note(
            _SERVICE,
            note_id=f"db-pro-{note_id}",
            title="数据库选型 PostgreSQL",
            summary="团队应该采用 PostgreSQL 作为主数据库。",
            user_id=user_id,
        )
        _seed_note(
            _SERVICE,
            note_id=f"db-con-{note_id}",
            title="数据库选型 PostgreSQL",
            summary="团队不应该采用 PostgreSQL 作为主数据库。",
            user_id=user_id,
        )

        result = _SERVICE.execute_entry(
            EntryInput(
                text="检查一下我的知识缺口",
                user_id=user_id,
                session_id=_unique("gap-conflict"),
            )
        )

        # Routed to inspection and the run did not hang.
        assert result.intents and result.intents[-1] == "inspect_knowledge_gaps"
        assert result.run_status in _TERMINAL

        # The detector fired end-to-end: the report carries the gaps header and is
        # not the empty-state message.
        assert _GAPS_HEADER in result.reply_text
        assert _NO_GAPS_TEXT not in result.reply_text

    def test_no_conflict_reports_clean_and_still_terminates(self):
        """Same subject but SAME polarity → not a conflict. The run still routes
        and terminates, and the report is the clean empty-state message."""
        user_id = _unique("gap-clean")
        note_id = uuid4().hex[:8]
        _seed_note(
            _SERVICE,
            note_id=f"clean-a-{note_id}",
            title="数据库选型 PostgreSQL",
            summary="团队应该采用 PostgreSQL 作为主数据库。",
            user_id=user_id,
        )
        _seed_note(
            _SERVICE,
            note_id=f"clean-b-{note_id}",
            title="数据库选型 PostgreSQL",
            summary="团队应该优先采用 PostgreSQL 并配好备份。",
            user_id=user_id,
        )

        result = _SERVICE.execute_entry(
            EntryInput(
                text="检查一下我的知识缺口",
                user_id=user_id,
                session_id=_unique("gap-clean"),
            )
        )

        assert result.intents and result.intents[-1] == "inspect_knowledge_gaps"
        assert result.run_status in _TERMINAL

        # No conflict (same polarity) and an empty user-scoped graph → clean report.
        assert _NO_GAPS_TEXT in result.reply_text
        assert _GAPS_HEADER not in result.reply_text
