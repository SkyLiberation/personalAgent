"""End-to-end eval for the solidify / clarification / resume flow.

This is the regression net for the real-world failure we hit: a user asks a
question, then says "把这个知识固化下来" (solidify this knowledge), the router
asks for clarification, and the user's supplemental reply must resume the run
to completion. Every hop is covered at two levels:

  * runtime level  — AgentRuntime.execute_entry / resume_entry directly
  * HTTP/SSE level — the same flow over /api/entry/stream + /api/entry/runs/{id}/resume

The router LLM is replaced by ``stub_router_decision`` (see evals/conftest.py)
so routing is deterministic and does not depend on a live model endpoint.

Tests are split into two tiers:

  * Fast contract tests — assert the interrupt + SSE ``confirmation_required``
    event + ``/resume`` request contract. These cover the original frontend bug
    ("clarify 补充后前端无反应") and run in seconds because they stop at the
    HITL pause, before any knowledge ingestion.
  * ``@pytest.mark.slow`` completion tests — actually resume into capture/solidify,
    which drives Graphiti's multi-round ``add_episode`` ingestion (entity +
    edge extraction over Neo4j). These are correctness-complete but minute-scale,
    so they are opt-in.

Run fast tier (default):
    uv run pytest evals/test_solidify_clarify_flow.py -v -m "not slow"
Run everything (needs healthy LLM + Neo4j, allow several minutes):
    uv run pytest evals/test_solidify_clarify_flow.py -v
"""

from __future__ import annotations

import pytest

from personal_agent.kernel.models import EntryInput

# These flows require a running Postgres; reuse the shared cleanup fixture.
pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


class TestClarifyInterruptContract:
    """Fast tier: the HITL pause + resume contract, stopping before ingestion.

    This is the precise surface the frontend depends on and the regression net
    for the clarify-then-no-response bug.
    """

    def test_solidify_routes_without_forcing_clarify(self, runtime):
        """'固化下来' is a clear instruction → routes to solidify, no clarify gate."""
        result = runtime.execute_entry(
            EntryInput(
                text="把这个知识固化下来",
                user_id="eval-user",
                session_id="eval-solidify-direct",
            )
        )
        assert result.intents and result.intents[-1] == "solidify_conversation"
        # A clear solidify request must not stall on clarification.
        assert result.pending_confirmation is None

    def test_vague_request_triggers_clarify_interrupt(self, runtime):
        """Vague '帮我' → run pauses with a clarification interrupt, not silent done."""
        interrupted = runtime.execute_entry(
            EntryInput(
                text="帮我",
                user_id="eval-user",
                session_id="eval-clarify-interrupt",
            )
        )
        # The run must pause for clarification, not silently complete.
        assert interrupted.run_status == "waiting_confirmation"
        assert interrupted.pending_confirmation is not None
        assert interrupted.pending_confirmation["kind"] == "clarification_required"
        assert interrupted.run_id

        # The clarification event must come after intent classification.
        event_types = [event["type"] for event in interrupted.events]
        assert "clarification_required" in event_types
        assert event_types.index("intent_classified") < event_types.index(
            "clarification_required"
        )

    def test_resume_reject_cancels_run(self, runtime):
        """Rejecting a clarification interrupt must not route into capture_text."""
        interrupted = runtime.execute_entry(
            EntryInput(
                text="帮我",
                user_id="eval-user",
                session_id="eval-clarify-reject",
            )
        )
        assert interrupted.run_status == "waiting_confirmation"

        resumed = runtime.resume_entry(
            run_id=interrupted.run_id or "",
            thread_id=interrupted.thread_id or "",
            decision="reject",
            user_id="eval-user",
            text="",
        )
        # A rejected run terminates; it must not have routed into capture_text.
        assert "capture_text" not in resumed.intents


class TestClarifyInterruptContractHttp:
    """Fast tier over HTTP/SSE — the exact surface the browser frontend uses."""

    def _latest_run(self, api_client, session_id: str, user_id: str = "eval-user"):
        runs = api_client.get(
            "/api/entry/runs", params={"user_id": user_id}
        ).json()["items"]
        return next(item for item in runs if item["session_id"] == session_id)

    def test_clarify_stream_emits_confirmation_required(self, api_client):
        """SSE must emit confirmation_required and expose a resumable waiting run.

        This is the decisive event the frontend listens for to render the
        clarification input box — the root of the original "no response" bug.
        """
        session_id = "eval-http-clarify"
        stream = api_client.get(
            "/api/entry/stream",
            params={"text": "帮我", "user_id": "eval-user", "session_id": session_id},
        )
        assert stream.status_code == 200
        assert "event: confirmation_required" in stream.text

        run = self._latest_run(api_client, session_id)
        assert run["status"] == "waiting_confirmation"
        assert run["pending_confirmation"]["kind"] == "clarification_required"

    def test_resume_rejects_unknown_run(self, api_client):
        """Resuming a non-existent run must 404, not hang or 500."""
        resumed = api_client.post(
            "/api/entry/runs/does-not-exist/resume",
            json={"decision": "clarify", "user_id": "eval-user", "text": "x"},
        )
        assert resumed.status_code == 404

    def test_resume_clarify_requires_text(self, api_client):
        """A clarify decision without supplemental text must 400."""
        session_id = "eval-http-clarify-notext"
        api_client.get(
            "/api/entry/stream",
            params={"text": "帮我", "user_id": "eval-user", "session_id": session_id},
        )
        run = self._latest_run(api_client, session_id)
        resumed = api_client.post(
            f"/api/entry/runs/{run['run_id']}/resume",
            json={"decision": "clarify", "user_id": "eval-user", "text": "   "},
        )
        assert resumed.status_code == 400


@pytest.mark.slow
class TestClarifyResumeCompletion:
    """Slow tier: resume all the way to completion, driving real ingestion.

    These assert the full flow finishes and routes correctly. They are minute-scale
    because resuming into capture_text triggers Graphiti's multi-round add_episode
    ingestion (entity/edge extraction over Neo4j), so they are opt-in via -m slow.
    """

    def test_clarify_resume_completes_into_capture(self, runtime):
        """Supplemental text resumes the paused run through to completion."""
        interrupted = runtime.execute_entry(
            EntryInput(
                text="帮我",
                user_id="eval-user",
                session_id="eval-clarify-resume-complete",
            )
        )
        assert interrupted.run_status == "waiting_confirmation"

        resumed = runtime.resume_entry(
            run_id=interrupted.run_id or "",
            thread_id=interrupted.thread_id or "",
            decision="clarify",
            user_id="eval-user",
            text="记一下：澄清补充后应继续执行并完成。",
            option_id="capture",
        )
        assert resumed.run_status == "completed"
        assert resumed.intents and resumed.intents[-1] == "capture_text"
        assert resumed.reply_text

    def test_clarify_stream_resume_completes_http(self, api_client):
        """Over HTTP: POST /resume with clarify text drives the run to completed."""
        session_id = "eval-http-clarify-complete"
        api_client.get(
            "/api/entry/stream",
            params={"text": "帮我", "user_id": "eval-user", "session_id": session_id},
        )
        runs = api_client.get(
            "/api/entry/runs", params={"user_id": "eval-user"}
        ).json()["items"]
        run = next(item for item in runs if item["session_id"] == session_id)

        resumed = api_client.post(
            f"/api/entry/runs/{run['run_id']}/resume",
            json={
                "decision": "clarify",
                "user_id": "eval-user",
                "text": "记一下：补充信息通过 /resume 提交后流程应完成。",
            },
        )
        assert resumed.status_code == 200
        assert resumed.json()["run_status"] == "completed"
