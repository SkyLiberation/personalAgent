from __future__ import annotations

import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from psycopg import connect
from unittest.mock import MagicMock

from personal_agent.core.models import EntryInput
from tests.conftest import POSTGRES_URL, stub_router_decision

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


@pytest.fixture
def api_client(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PERSONAL_AGENT_DATA_DIR", str(temp_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_POSTGRES_URL", POSTGRES_URL)
    monkeypatch.setenv("PERSONAL_AGENT_FEISHU_ENABLED", "false")
    from personal_agent.core import config as config_module
    monkeypatch.setattr(config_module, "load_dotenv", lambda override=True: False)

    from personal_agent.web.api import create_app
    app = create_app()
    app.state.service._intent_router._classify_with_llm = stub_router_decision
    return TestClient(app)


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
        assert matching[0]["intent"] == "ask"

    def test_solidify_stream_emits_plan_only_once(self, api_client: TestClient):
        api_client.get(
            "/api/entry/stream",
            params={
                "text": "什么是DNS",
                "user_id": "test-user",
                "session_id": "entry-stream-plan",
            },
        )
        response = api_client.get(
            "/api/entry/stream",
            params={
                "text": "把DNS相关讨论结论固化下来",
                "user_id": "test-user",
                "session_id": "entry-stream-plan",
            },
        )

        assert response.status_code == 200
        assert response.text.count("event: plan_created") == 1
        assert "event: plan_step_started" in response.text
        assert (
            "event: plan_step_completed" in response.text
            or "event: plan_step_failed" in response.text
        )
        assert response.text.index("event: plan_created") < response.text.index("event: done")

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


class TestNotesEndpoint:
    def test_list_notes(self, api_client: TestClient):
        service = api_client.app.state.service
        service._runtime.execute_capture("测试笔记1", source_type="text", user_id="test-user")
        response = api_client.get("/api/notes", params={"user_id": "test-user"})
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_list_notes_isolated_by_user(self, api_client: TestClient):
        service = api_client.app.state.service
        service._runtime.execute_capture("Alice的笔记", source_type="text", user_id="alice")
        service._runtime.execute_capture("Bob的笔记", source_type="text", user_id="bob")
        alice_notes = api_client.get("/api/notes", params={"user_id": "alice"}).json()
        bob_notes = api_client.get("/api/notes", params={"user_id": "bob"}).json()
        alice_titles = {n["title"] for n in alice_notes}
        bob_titles = {n["title"] for n in bob_notes}
        assert "Alice的笔记" in alice_titles
        assert "Bob的笔记" in bob_titles


class TestDebugEndpoints:
    def test_reset_database_clears_all_persisted_debug_data(self, api_client: TestClient, temp_dir: Path):
        service = api_client.app.state.service
        service.graph_store.clear_all_data = MagicMock(return_value=7)
        service._runtime.execute_capture("用户A笔记", source_type="text", user_id="reset-a")
        service._runtime.execute_capture("用户B笔记", source_type="text", user_id="reset-b")
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
        service.graph_store.clear_all_data.assert_called_once_with()
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


class TestToolsEndpoint:
    def test_list_tools(self, api_client: TestClient):
        response = api_client.get("/api/tools")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
