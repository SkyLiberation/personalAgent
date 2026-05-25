from __future__ import annotations

import pytest
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PERSONAL_AGENT_DATA_DIR", str(temp_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_POSTGRES_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_FEISHU_ENABLED", "false")
    monkeypatch.setenv("PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv(
        "PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_PATH",
        str(temp_dir / "langgraph_checkpoints.sqlite"),
    )

    from personal_agent.core import config as config_module
    monkeypatch.setattr(config_module, "load_dotenv", lambda override=True: False)

    from personal_agent.web.api import create_app
    app = create_app()
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
        assert "event: plan_step_completed" in response.text
        assert response.text.index("event: plan_created") < response.text.index("event: done")


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


class TestAskHistoryEndpoint:
    def test_list_ask_history(self, api_client: TestClient):
        service = api_client.app.state.service
        service._runtime.execute_ask("历史测试问题", user_id="test-user", session_id="s1")
        response = api_client.get(
            "/api/ask-history", params={"user_id": "test-user", "session_id": "s1"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) >= 1

    def test_ask_history_empty_for_new_user(self, api_client: TestClient):
        response = api_client.get(
            "/api/ask-history", params={"user_id": "no-such-user"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []


class TestDebugEndpoints:
    def test_reset_user_data(self, api_client: TestClient):
        service = api_client.app.state.service
        service._runtime.execute_capture("待删除笔记", source_type="text", user_id="reset-test")
        response = api_client.post(
            "/api/debug/reset-user-data",
            json={"user_id": "reset-test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "reset-test"
        assert data["deleted_notes"] >= 1
        # Verify notes are gone
        notes = api_client.get("/api/notes", params={"user_id": "reset-test"}).json()
        assert len(notes) == 0


class TestToolsEndpoint:
    def test_list_tools(self, api_client: TestClient):
        response = api_client.get("/api/tools")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

