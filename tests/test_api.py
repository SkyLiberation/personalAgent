from __future__ import annotations

import pytest
from pathlib import Path
from datetime import timedelta
from fastapi.testclient import TestClient
from psycopg import connect
from unittest.mock import MagicMock

from personal_agent.core.models import ReviewCard, local_now
from personal_agent.core.models import EntryInput
from personal_agent.review.delivery import DeliveryRouter
from personal_agent.review.models import DeliveryResult
from tests.conftest import POSTGRES_URL, stub_router_decision

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


@pytest.fixture
def api_client(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PERSONAL_AGENT_DATA_DIR", str(temp_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_POSTGRES_URL", POSTGRES_URL)
    monkeypatch.setenv("PERSONAL_AGENT_FEISHU_ENABLED", "false")
    from personal_agent.core import config_env as config_env_module
    monkeypatch.setattr(config_env_module, "load_dotenv", lambda override=True: False)

    from personal_agent.web.api import create_app
    app = create_app()
    app.state.service.intent_router._classify_with_llm = stub_router_decision
    app.state.review_digest_delivery_router = DeliveryRouter({"feishu": _FakeDigestProvider()})
    return TestClient(app)


class _FakeDigestProvider:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, target, message) -> DeliveryResult:
        self.sent.append((target.target_id, message.text))
        return DeliveryResult(ok=True, provider_message_id=f"fake-{target.target_id}")


class TestHealthEndpoint:
    def test_health_returns_200(self, api_client: TestClient):
        response = api_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_health_includes_graphiti_status(self, api_client: TestClient):
        response = api_client.get("/api/health")
        data = response.json()
        assert "graphiti" in data

    def test_frontend_dist_is_resolved_from_project_root(self):
        from personal_agent.web.api import _frontend_dist_dir

        project_root = Path(__file__).resolve().parents[1]
        assert _frontend_dist_dir() == project_root / "frontend" / "dist"


class TestResearchEndpoints:
    def test_subscription_crud_and_run_now(self, api_client: TestClient):
        created = api_client.post("/api/research/subscriptions", json={
            "name": "AI 日报",
            "topic": "AI",
            "instructions": "优先 Agent 和开源模型",
            "schedule": {
                "frequency": "daily",
                "schedule_time": "09:00",
                "timezone": "Asia/Shanghai",
                "weekdays": [0],
            },
            "delivery": {
                "channel": "feishu",
                "target_type": "chat_id",
                "target_id": "chat-1",
            },
        })
        assert created.status_code == 200
        subscription_id = created.json()["id"]

        listed = api_client.get("/api/research/subscriptions")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["id"] == subscription_id

        run = api_client.post(
            f"/api/research/subscriptions/{subscription_id}/run-now"
        )
        assert run.status_code == 200
        assert run.json()["status"] == "queued"

        deleted = api_client.delete(
            f"/api/research/subscriptions/{subscription_id}"
        )
        assert deleted.json() == {"ok": True}


class TestEntryStreamEndpoint:
    def test_ask_stream_entry_creates_langgraph_run_snapshot(self, api_client: TestClient):
        response = api_client.get(
            "/api/entry/stream",
            params={
                "text": "什么是API测试？",
                "user_id": "test-user",
                "session_id": "entry-stream-ask",
            },
        )

        assert response.status_code == 200
        assert "正在理解并执行请求" in response.text
        assert "event: done" in response.text
        assert response.text.count("event: done") == 1

        runs = api_client.get(
            "/api/entry/runs",
            params={"user_id": "test-user"},
        ).json()["items"]
        matching = [run for run in runs if run["session_id"] == "entry-stream-ask"]

        assert matching
        assert matching[0]["thread_id"] == "test-user:entry-stream-ask"
        assert matching[0]["intents"] == ["ask"]

    def test_solidify_stream_emits_steps_only_once(self, api_client: TestClient):
        api_client.get(
            "/api/entry/stream",
            params={
                "text": "什么是DNS",
                "user_id": "test-user",
                "session_id": "entry-stream-steps",
            },
        )
        response = api_client.get(
            "/api/entry/stream",
            params={
                "text": "把DNS相关讨论结论固化下来",
                "user_id": "test-user",
                "session_id": "entry-stream-steps",
            },
        )

        assert response.status_code == 200
        assert response.text.count("event: steps_projected") == 1
        assert "event: step_started" in response.text
        assert (
            "event: step_completed" in response.text
            or "event: step_failed" in response.text
        )
        assert response.text.index("event: steps_projected") < response.text.index("event: done")

    def test_capture_stream_shows_routing_and_captured_content_before_done(self, api_client: TestClient):
        response = api_client.get(
            "/api/entry/stream",
            params={
                "text": "记一下：DNS 将域名解析为 IP 地址。",
                "user_id": "test-user",
                "session_id": "entry-stream-capture",
            },
        )

        assert response.status_code == 200
        assert "event: intent" in response.text
        assert "event: tool_result" in response.text
        assert "DNS" in response.text
        assert response.text.index("event: intent") < response.text.index("event: done")
        assert response.text.index("event: tool_result") < response.text.index("event: done")

    def test_waiting_run_snapshot_exposes_confirmation_and_can_resume(self, api_client: TestClient):
        response = api_client.get(
            "/api/entry/stream",
            params={
                "text": "帮我",
                "user_id": "test-user",
                "session_id": "entry-stream-resume",
            },
        )

        assert response.status_code == 200
        assert "event: confirmation_required" in response.text

        runs = api_client.get(
            "/api/entry/runs",
            params={"user_id": "test-user"},
        ).json()["items"]
        run = next(item for item in runs if item["session_id"] == "entry-stream-resume")

        assert run["status"] == "waiting_confirmation"
        assert run["pending_confirmation"]["kind"] == "clarification_required"

        resumed = api_client.post(
            f"/api/entry/runs/{run['run_id']}/resume",
            json={
                "decision": "clarify",
                "user_id": "test-user",
                "text": "记一下：确认操作应在原对话中完成。",
            },
        )

        assert resumed.status_code == 200
        assert resumed.json()["run_status"] == "completed"


class TestDigestEndpoint:
    def test_digest_returns_data(self, api_client: TestClient):
        response = api_client.get("/api/digest", params={"user_id": "test-user"})
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "recent_notes" in data
        assert "due_reviews" in data


class TestReviewDigestManagementEndpoints:
    def test_create_list_and_update_digest_subscription(self, api_client: TestClient):
        created = api_client.post(
            "/api/review/digest/subscriptions",
            json={
                "id": "sub-api-1",
                "target_id": "chat-1",
                "schedule_time": "08:30",
                "timezone": "Asia/Shanghai",
            },
        )

        assert created.status_code == 200
        assert created.json()["id"] == "sub-api-1"
        assert created.json()["user_id"] == "default"

        listed = api_client.get("/api/review/digest/subscriptions")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["items"]] == ["sub-api-1"]

        patched = api_client.patch(
            "/api/review/digest/subscriptions/sub-api-1",
            json={"enabled": False, "schedule_time": "09:15"},
        )

        assert patched.status_code == 200
        assert patched.json()["enabled"] is False
        assert patched.json()["schedule_time"] == "09:15"

    def test_send_now_writes_digest_delivery(self, api_client: TestClient):
        service = api_client.app.state.service
        service.execute_capture("复习 Digest 通过飞书触达", source_type="text", user_id="default")
        api_client.post(
            "/api/review/digest/subscriptions",
            json={
                "id": "sub-api-send",
                "target_id": "chat-send",
            },
        )

        sent = api_client.post("/api/review/digest/subscriptions/sub-api-send/send-now")

        assert sent.status_code == 200
        payload = sent.json()
        assert payload["subscription_id"] == "sub-api-send"
        assert payload["delivered"] is True
        assert payload["delivery_id"]

        deliveries = api_client.get("/api/review/digest/deliveries")
        assert deliveries.status_code == 200
        items = deliveries.json()["items"]
        assert items[0]["subscription_id"] == "sub-api-send"
        assert items[0]["status"] == "sent"

    def test_send_now_is_idempotent_per_day(self, api_client: TestClient):
        api_client.post(
            "/api/review/digest/subscriptions",
            json={
                "id": "sub-api-idem",
                "target_id": "chat-idem",
            },
        )

        first = api_client.post("/api/review/digest/subscriptions/sub-api-idem/send-now")
        second = api_client.post("/api/review/digest/subscriptions/sub-api-idem/send-now")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["delivered"] is True
        assert second.json()["skipped"] is True
        assert first.json()["delivery_id"] == second.json()["delivery_id"]

    def test_missing_digest_subscription_returns_404(self, api_client: TestClient):
        response = api_client.patch(
            "/api/review/digest/subscriptions/missing",
            json={"enabled": False},
        )

        assert response.status_code == 404

    def test_list_review_cards_and_submit_feedback(self, api_client: TestClient):
        service = api_client.app.state.service
        capture = service.execute_capture("复习卡 API 反馈", source_type="text", user_id="default")
        card = ReviewCard(
            id="card-api-1",
            note_id=capture.note.id,
            prompt="复习卡 API 的反馈入口是什么？",
            answer_hint="/api/review/cards/{id}/feedback",
            interval_days=1,
            due_at=local_now() - timedelta(minutes=1),
        )
        service.memory.add_review(card)

        listed = api_client.get("/api/review/cards", params={"due_only": True})
        assert listed.status_code == 200
        assert "card-api-1" in {item["id"] for item in listed.json()["items"]}

        feedback = api_client.post(
            "/api/review/cards/card-api-1/feedback",
            json={"outcome": "remembered"},
        )

        assert feedback.status_code == 200
        assert feedback.json()["ok"] is True
        updated = service.memory.get_review("card-api-1", "default")
        assert updated is not None
        assert updated.interval_days == 2


class TestNotesEndpoint:
    def test_list_notes(self, api_client: TestClient):
        service = api_client.app.state.service
        service.execute_capture("测试笔记1", source_type="text", user_id="test-user")
        response = api_client.get("/api/notes", params={"user_id": "test-user"})
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_list_notes_isolated_by_user(self, api_client: TestClient):
        service = api_client.app.state.service
        service.execute_capture("Alice的笔记", source_type="text", user_id="alice")
        service.execute_capture("Bob的笔记", source_type="text", user_id="bob")
        alice_notes = api_client.get("/api/notes", params={"user_id": "alice"}).json()
        bob_notes = api_client.get("/api/notes", params={"user_id": "bob"}).json()
        alice_titles = {n["title"] for n in alice_notes}
        bob_titles = {n["title"] for n in bob_notes}
        assert "Alice的笔记" in alice_titles
        assert "Bob的笔记" in bob_titles

    def test_restore_deleted_note_from_snapshot(self, api_client: TestClient):
        service = api_client.app.state.service
        captured = service.execute_capture("DNS 是域名系统", source_type="text", user_id="restore-user")
        note_id = captured.note.id

        deleted = api_client.delete("/api/notes/{note_id}".format(note_id=note_id), params={"user_id": "restore-user"})

        assert deleted.status_code == 200
        snapshot_id = deleted.json()["snapshot_id"]
        assert snapshot_id
        listed_after_delete = api_client.get("/api/notes", params={"user_id": "restore-user"}).json()
        assert all(item["id"] != note_id for item in listed_after_delete)

        restored = api_client.post(
            f"/api/memory/notes/{note_id}/restore",
            json={
                "user_id": "restore-user",
                "snapshot_id": snapshot_id,
                "idempotency_key": f"restore:{snapshot_id}",
            },
        )

        assert restored.status_code == 200
        data = restored.json()["data"]
        assert data["restored_note_id"] == note_id
        listed_after_restore = api_client.get("/api/notes", params={"user_id": "restore-user"}).json()
        assert any(item["id"] == note_id for item in listed_after_restore)


class TestDebugEndpoints:
    def test_reset_database_clears_all_persisted_debug_data(self, api_client: TestClient, temp_dir: Path):
        service = api_client.app.state.service
        service.graph_store.clear_all_data = MagicMock(return_value=7)
        service.execute_capture("用户A笔记", source_type="text", user_id="reset-a")
        service.execute_capture("用户B笔记", source_type="text", user_id="reset-b")
        service.execute_entry(EntryInput(text="你好", user_id="reset-a", session_id="checkpoint"))
        uploads_dir = temp_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        (uploads_dir / "orphan.txt").write_text("debug", encoding="utf-8")
        with connect(POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE TABLE IF NOT EXISTS debug_extra_rows (id INTEGER)")
                cur.execute("INSERT INTO debug_extra_rows (id) VALUES (1)")
            conn.commit()

        response = api_client.post(
            "/api/debug/reset-database",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted_notes"] >= 2
        assert data["deleted_checkpoints"] >= 1
        assert data["deleted_checkpoint_migrations"] >= 1
        assert data["truncated_postgres_tables"] >= 7
        assert data["deleted_postgres_rows"] >= data["deleted_notes"]
        assert data["deleted_upload_files"] == 1
        assert data["deleted_graph_nodes"] == 7
        service.graph_store.clear_all_data.assert_called_once()
        assert "preserve_group_ids" in service.graph_store.clear_all_data.call_args.kwargs
        assert not (uploads_dir / "orphan.txt").exists()

        with connect(POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                for table in (
                    "knowledge_notes",
                    "review_cards",
                    "checkpoints",
                    "checkpoint_blobs",
                    "checkpoint_writes",
                    "debug_extra_rows",
                ):
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    assert cur.fetchone()[0] == 0
                cur.execute("SELECT COUNT(*) FROM checkpoint_migrations")
                assert cur.fetchone()[0] >= 1
                cur.execute("DROP TABLE debug_extra_rows")
            conn.commit()

    def test_reset_database_protects_eval_graph_manifest_groups(
        self,
        api_client: TestClient,
        temp_dir: Path,
    ):
        from personal_agent.agent.runtime_admin import _protected_eval_graph_group_ids

        service = api_client.app.state.service
        manifest_dir = temp_dir / "evals" / "open_ragbench" / "results"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "graphiti_manifest.json").write_text(
            """
            {
              "user_id": "ragbench_eval_cached",
              "graphiti_group_prefix": "personal-agent",
              "episode_to_note_id": {"episode-1": "note-1"}
            }
            """,
            encoding="utf-8",
        )
        (manifest_dir / "other_manifest.json").write_text(
            """
            {
              "user_id": "other_prefix_eval",
              "graphiti_group_prefix": "other-prefix",
              "episode_to_note_id": {"episode-2": "note-2"}
            }
            """,
            encoding="utf-8",
        )

        protected_groups = _protected_eval_graph_group_ids(
            service.settings,
            graph_store=service.graph_store,
            project_root=temp_dir,
        )

        assert protected_groups == ["personal-agent-ragbench_eval_cached"]


class TestToolsEndpoint:
    def test_list_tools(self, api_client: TestClient):
        response = api_client.get("/api/tools")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
