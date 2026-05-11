from __future__ import annotations

import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PERSONAL_AGENT_DATA_DIR", str(temp_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_GRAPHITI_ENABLED", "false")
    monkeypatch.setenv("PERSONAL_AGENT_POSTGRES_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_FEISHU_ENABLED", "false")

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


class TestCaptureEndpoint:
    def test_capture_text_returns_note(self, api_client: TestClient):
        response = api_client.post(
            "/api/capture",
            json={"text": "API测试采集内容", "source_type": "text", "user_id": "test-user"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["note"]["title"]
        assert data["note"]["content"]
        assert data["note"]["user_id"] == "test-user"

    def test_capture_empty_text_rejected(self, api_client: TestClient):
        response = api_client.post(
            "/api/capture",
            json={"text": "", "source_type": "text"},
        )
        assert response.status_code == 422


class TestAskEndpoint:
    def test_ask_returns_answer(self, api_client: TestClient):
        # Seed a note so there's something to search
        api_client.post(
            "/api/capture",
            json={"text": "API测试知识点", "source_type": "text", "user_id": "test-user"},
        )
        response = api_client.post(
            "/api/ask",
            json={"question": "什么是API测试？", "user_id": "test-user", "session_id": "test-session"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert data["session_id"] == "test-session"

    def test_ask_empty_question_rejected(self, api_client: TestClient):
        response = api_client.post(
            "/api/ask",
            json={"question": "", "user_id": "test-user"},
        )
        assert response.status_code == 422


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
        api_client.post(
            "/api/capture",
            json={"text": "测试笔记1", "source_type": "text", "user_id": "test-user"},
        )
        response = api_client.get("/api/notes", params={"user_id": "test-user"})
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_list_notes_isolated_by_user(self, api_client: TestClient):
        api_client.post(
            "/api/capture",
            json={"text": "Alice的笔记", "source_type": "text", "user_id": "alice"},
        )
        api_client.post(
            "/api/capture",
            json={"text": "Bob的笔记", "source_type": "text", "user_id": "bob"},
        )
        alice_notes = api_client.get("/api/notes", params={"user_id": "alice"}).json()
        bob_notes = api_client.get("/api/notes", params={"user_id": "bob"}).json()
        alice_titles = {n["title"] for n in alice_notes}
        bob_titles = {n["title"] for n in bob_notes}
        assert "Alice的笔记" in alice_titles
        assert "Bob的笔记" in bob_titles


class TestAskHistoryEndpoint:
    def test_list_ask_history(self, api_client: TestClient):
        api_client.post(
            "/api/capture",
            json={"text": "历史测试", "source_type": "text", "user_id": "test-user"},
        )
        api_client.post(
            "/api/ask",
            json={"question": "历史测试问题", "user_id": "test-user", "session_id": "s1"},
        )
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
        api_client.post(
            "/api/capture",
            json={"text": "待删除笔记", "source_type": "text", "user_id": "reset-test"},
        )
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
