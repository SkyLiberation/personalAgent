from __future__ import annotations

from datetime import UTC, datetime, timedelta
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from psycopg import connect
from unittest.mock import MagicMock

from personal_agent.application.review.delivery import DeliveryRouter
from personal_agent.kernel.contracts.research import ResearchRunDefinition, ResearchRunRecord
from personal_agent.kernel.contracts.review import DeliveryResult
from personal_agent.application.conversation import ConversationMessage, ConversationTurnView
from personal_agent.application.conversation.models import ProjectReference
from personal_agent.application.knowledge import Artifact
from tests.conftest import POSTGRES_URL

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


@pytest.fixture
def api_client(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PERSONAL_AGENT_DATA_DIR", str(temp_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_POSTGRES_URL", POSTGRES_URL)
    monkeypatch.setenv("PERSONAL_AGENT_FEISHU_ENABLED", "false")
    from personal_agent.kernel import config_env as config_env_module
    monkeypatch.setattr(config_env_module, "load_dotenv", lambda override=True: False)

    from personal_agent.adapters.web.api import create_app
    app = create_app()
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
        from personal_agent.adapters.web.api import _frontend_dist_dir

        project_root = Path(__file__).resolve().parents[1]
        assert _frontend_dist_dir() == project_root / "frontend" / "dist"


class TestResearchEndpoints:
    def test_run_once_preserves_explicit_user_in_auth_disabled_mode(
        self, api_client: TestClient, monkeypatch
    ):
        captured = {}

        def run_once(**kwargs):
            captured.update(kwargs)
            return ResearchRunRecord.create(ResearchRunDefinition(
                user_id=kwargs["user_id"],
                topic=kwargs["topic"],
                window_start=datetime.now(UTC) - timedelta(hours=1),
                window_end=datetime.now(UTC),
            ))

        monkeypatch.setattr(api_client.app.state.service, "run_research_once", run_once)
        response = api_client.post(
            "/api/research/once",
            json={"user_id": "alice", "topic": "Agent protocols"},
        )

        assert response.status_code == 200
        assert captured["user_id"] == "alice"
        assert response.json()["user_id"] == "alice"

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

    def test_explicit_subscription_owner_can_run_in_auth_disabled_mode(
        self, api_client: TestClient
    ):
        created = api_client.post(
            "/api/research/subscriptions",
            json={
                "user_id": "alice",
                "name": "Alice research",
                "topic": "Agent protocols",
                "delivery": {
                    "channel": "in_app",
                    "target_type": "user_id",
                    "target_id": "alice",
                },
            },
        )

        queued = api_client.post(
            f"/api/research/subscriptions/{created.json()['id']}/run-now"
        )

        assert created.json()["user_id"] == "alice"
        assert queued.status_code == 200
        assert queued.json()["user_id"] == "alice"


class TestEntryStreamEndpoint:
    def test_stream_reports_background_execution_failure_as_sse(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_conversation(*_args, **_kwargs):
            raise RuntimeError("internal provider detail")

        monkeypatch.setattr(api_client.app.state.service, "converse", fail_conversation)

        response = api_client.get(
            "/api/entry/stream",
            params={
                "text": "执行请求",
                "user_id": "test-user",
                "session_id": "entry-stream-error",
            },
        )

        assert response.status_code == 200
        assert "event: error" in response.text
        assert "conversation_execution_failed" in response.text
        assert "internal provider detail" not in response.text

    def test_stream_uses_conversation_without_creating_langgraph_run(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        def converse(
            *,
            conversation_id,
            messages,
            principal,
            source_platform,
        ):
            assert conversation_id == "entry-stream-ask"
            assert messages[-1].content == "什么是API测试？"
            assert principal.user_id == "test-user"
            assert principal.tenant_id == "personal-agent"
            assert source_platform == "web"
            return ConversationTurnView(
                interaction_run_ref="irun-stream",
                conversation_id=conversation_id,
                disposition="answer",
                message=ConversationMessage(role="assistant", content="API测试验证接口行为。"),
            )

        monkeypatch.setattr(api_client.app.state.service, "converse", converse)
        legacy_runs = api_client.get("/api/entry/runs", params={"user_id": "test-user"})
        response = api_client.get(
            "/api/entry/stream",
            params={
                "text": "什么是API测试？",
                "user_id": "test-user",
                "session_id": "entry-stream-ask",
            },
        )

        assert response.status_code == 200
        assert "正在处理请求" in response.text
        assert "event: done" in response.text
        assert response.text.count("event: done") == 1
        assert "irun-stream" in response.text
        assert legacy_runs.status_code == 404
        assert api_client.get("/api/entry/runs", params={"user_id": "test-user"}).status_code == 404

    def test_stream_exposes_project_reference_for_progress_ui(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        def converse(**kwargs):
            return ConversationTurnView(
                interaction_run_ref="irun-project-stream",
                conversation_id=kwargs["conversation_id"],
                disposition="background_started",
                message=ConversationMessage(role="assistant", content="后台调查已创建。"),
                project_reference=ProjectReference(
                    project_id="iprj_stream",
                    tenant_id="personal-agent",
                    user_id="test-user",
                    state="planning",
                    title="协议调查",
                    goal="生成带来源的报告",
                ),
            )

        monkeypatch.setattr(api_client.app.state.service, "converse", converse)
        response = api_client.get(
            "/api/entry/stream",
            params={
                "text": "在后台调查协议变化",
                "user_id": "test-user",
                "session_id": "entry-stream-project",
            },
        )

        assert response.status_code == 200
        assert '"disposition": "background_started"' in response.text
        assert '"project_id": "iprj_stream"' in response.text


class TestConversationEndpoint:
    def test_direct_turn_returns_typed_message_without_durable_run(
        self, api_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        def converse(
            *, conversation_id, messages, interaction_run_ref=None,
            principal, source_platform,
        ):
            assert interaction_run_ref is None
            assert conversation_id == "conversation-1"
            assert messages[-1].content == "解释幂等性"
            assert principal.user_id == "default"
            assert principal.tenant_id == "personal-agent"
            assert source_platform == "web"
            return ConversationTurnView(
                interaction_run_ref="irun-test",
                conversation_id=conversation_id,
                disposition="answer",
                message=ConversationMessage(role="assistant", content="重复调用产生相同效果。"),
            )

        monkeypatch.setattr(api_client.app.state.service, "converse", converse)
        legacy_runs = api_client.get("/api/entry/runs", params={"user_id": "default"})
        response = api_client.post(
            "/api/conversation/turn",
            json={
                "conversation_id": "conversation-1",
                "messages": [{"role": "user", "content": "解释幂等性"}],
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "interaction_run_ref": "irun-test",
            "conversation_id": "conversation-1",
            "disposition": "answer",
            "message": {"role": "assistant", "content": "重复调用产生相同效果。"},
        }
        assert legacy_runs.status_code == 404
        assert api_client.get("/api/entry/runs", params={"user_id": "default"}).status_code == 404

    def test_direct_turn_rejects_non_user_terminal_message(self, api_client: TestClient):
        response = api_client.post(
            "/api/conversation/turn",
            json={
                "conversation_id": "conversation-1",
                "messages": [{"role": "assistant", "content": "上一条回答"}],
            },
        )

        assert response.status_code == 422


class TestKnowledgeCaptureEndpoints:
    def test_upload_uses_one_resource_and_knowledge_artifact_identity(
        self,
        api_client: TestClient,
    ) -> None:
        response = api_client.post(
            "/api/knowledge/ingest-upload",
            data={"user_id": "alice"},
            files={"file": ("fact.txt", b"Atlas window is Friday 20:00.", "text/plain")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["resource_ref"]["resource_id"] == body["ingest_result"]["artifact"]["artifact_id"]
        assert "Atlas window" in body["ingest_result"]["artifact"]["text"]
        assert api_client.post(
            "/api/entry/upload",
            files={"file": ("legacy.txt", b"legacy", "text/plain")},
        ).status_code in {404, 405}

    def test_url_capture_enters_knowledge_without_generic_entry_task(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            api_client.app.state.context.capture_service,
            "capture_text_from_url",
            lambda url: f"Captured from {url}: canonical body",
        )
        response = api_client.post(
            "/api/knowledge/ingest-url",
            json={
                "url": "https://example.com/source",
                "user_id": "alice",
            },
        )

        assert response.status_code == 200
        artifact = response.json()["ingest_result"]["artifact"]
        assert artifact["source_ref"] == "https://example.com/source"
        assert artifact["source_type"] == "link"
        assert api_client.get("/api/entry/runs", params={"user_id": "alice"}).status_code == 404


class TestGovernedKnowledgeDelete:
    def test_confirmed_command_executes_once_and_receipt_binds_server_command(
        self,
        api_client: TestClient,
    ) -> None:
        user_id = "delete-owner"
        ingested = api_client.post(
            "/api/knowledge/ingest-text",
            json={
                "text": "Atlas 的维护窗口是周五。",
                "user_id": user_id,
                "source_type": "document",
            },
        ).json()
        note_id = ingested["knowledge_items"][0]["knowledge_item_id"]
        prepared = api_client.post(
            f"/api/notes/{note_id}/delete-commands",
            json={
                "user_id": user_id,
                "reason": "obsolete",
                "idempotency_key": "delete-atlas-once",
            },
        )
        assert prepared.status_code == 200
        operation = prepared.json()
        assert operation["status"] == "awaiting_confirmation"
        assert operation["receipt"] is None
        assert any(item["id"] == note_id for item in api_client.get(
            "/api/notes", params={"user_id": user_id}
        ).json())

        command = operation["command"]
        obsolete_client_digest = api_client.post(
            f"/api/knowledge-delete-commands/{command['command_id']}/decision",
            json={
                "user_id": user_id,
                "decision": "confirm",
                "command_digest": "0" * 64,
                "confirmation_ref": "user-confirmation-1",
            },
        )
        assert obsolete_client_digest.status_code == 422
        assert any(item["id"] == note_id for item in api_client.get(
            "/api/notes", params={"user_id": user_id}
        ).json())

        decision = {
            "user_id": user_id,
            "decision": "confirm",
            "confirmation_ref": "user-confirmation-1",
        }
        first = api_client.post(
            f"/api/knowledge-delete-commands/{command['command_id']}/decision",
            json=decision,
        )
        replay = api_client.post(
            f"/api/knowledge-delete-commands/{command['command_id']}/decision",
            json=decision,
        )
        assert first.status_code == 200, first.text
        assert replay.status_code == 200, replay.text
        assert first.json()["status"] == "executed"
        assert first.json()["receipt"] == replay.json()["receipt"]
        assert first.json()["receipt"]["command_digest"] == command["command_digest"]
        assert "events" not in replay.json()
        assert note_id not in {
            item["id"] for item in api_client.get(
                "/api/notes", params={"user_id": user_id}
            ).json()
        }

    def test_rejected_or_cross_scope_command_never_deletes(
        self,
        api_client: TestClient,
    ) -> None:
        user_id = "delete-reject-owner"
        ingested = api_client.post(
            "/api/knowledge/ingest-text",
            json={
                "text": "保留这条知识。",
                "user_id": user_id,
            },
        ).json()
        note_id = ingested["knowledge_items"][0]["knowledge_item_id"]
        denied = api_client.post(
            f"/api/notes/{note_id}/delete-commands",
            json={
                "user_id": "other-user",
                "idempotency_key": "cross-scope-delete",
            },
        )
        assert denied.status_code == 404

        operation = api_client.post(
            f"/api/notes/{note_id}/delete-commands",
            json={
                "user_id": user_id,
                "idempotency_key": "reject-delete",
            },
        ).json()
        command = operation["command"]
        rejected = api_client.post(
            f"/api/knowledge-delete-commands/{command['command_id']}/decision",
            json={
                "user_id": user_id,
                "decision": "reject",
            },
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["receipt"] is None
        assert any(item["id"] == note_id for item in api_client.get(
            "/api/notes", params={"user_id": user_id}
        ).json())


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
        service.execute_capture("复习卡 API 反馈", source_type="text", user_id="default")

        listed = api_client.get("/api/review/cards", params={"due_only": True})
        assert listed.status_code == 200
        cards = listed.json()["items"]
        assert cards
        card_id = cards[0]["id"]

        feedback = api_client.post(
            f"/api/review/cards/{card_id}/feedback",
            json={"outcome": "remembered"},
        )

        assert feedback.status_code == 200
        assert feedback.json()["ok"] is True
        updated = service.knowledge_service.store.list_review_items(
            "personal-agent:default", state="answered", limit=100,
        )
        assert card_id in {item.review_item_id for item in updated}


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

    def test_restore_uses_delete_receipt_and_replays_exactly_once(
        self,
        api_client: TestClient,
    ) -> None:
        user_id = "restore-user"
        ingested = api_client.post(
            "/api/knowledge/ingest-text",
            json={
                "text": "DNS 是域名系统。",
                "user_id": user_id,
                "source_type": "document",
            },
        ).json()
        note_id = ingested["knowledge_items"][0]["knowledge_item_id"]
        claim_ids = {
            claim["claim_id"] for claim in ingested["claims"]
            if claim["claim_id"] in ingested["knowledge_items"][0]["claim_ids"]
        }
        prepared_delete = api_client.post(
            f"/api/notes/{note_id}/delete-commands",
            json={
                "user_id": user_id,
                "idempotency_key": "delete-before-restore",
            },
        ).json()
        delete_command = prepared_delete["command"]
        deleted = api_client.post(
            f"/api/knowledge-delete-commands/{delete_command['command_id']}/decision",
            json={
                "user_id": user_id,
                "decision": "confirm",
                "confirmation_ref": "delete-confirmation",
            },
        ).json()
        assert deleted["status"] == "executed"
        assert all(item["id"] != note_id for item in api_client.get(
            "/api/notes", params={"user_id": user_id}
        ).json())

        cross_scope = api_client.post(
            f"/api/knowledge-delete-commands/{delete_command['command_id']}/restore-commands",
            json={
                "user_id": "other-user",
                "idempotency_key": "cross-scope-restore",
            },
        )
        assert cross_scope.status_code == 404

        prepared_restore = api_client.post(
            f"/api/knowledge-delete-commands/{delete_command['command_id']}/restore-commands",
            json={
                "user_id": user_id,
                "idempotency_key": "restore-dns-once",
                "reason": "user requested restoration",
            },
        )
        assert prepared_restore.status_code == 200, prepared_restore.text
        operation = prepared_restore.json()
        assert operation["status"] == "awaiting_confirmation"
        restore_command = operation["command"]
        decision = {
            "user_id": user_id,
            "decision": "confirm",
            "confirmation_ref": "restore-confirmation",
        }
        first = api_client.post(
            f"/api/knowledge-restore-commands/{restore_command['command_id']}/decision",
            json=decision,
        )
        replay = api_client.post(
            f"/api/knowledge-restore-commands/{restore_command['command_id']}/decision",
            json=decision,
        )
        assert first.status_code == 200, first.text
        assert replay.status_code == 200, replay.text
        assert first.json()["receipt"] == replay.json()["receipt"]
        assert first.json()["receipt"]["restored_note_id"] == note_id
        assert set(first.json()["receipt"]["affected_claim_ids"]) == claim_ids
        assert first.json()["receipt"]["command_digest"] == restore_command["command_digest"]
        assert "events" not in replay.json()
        assert any(item["id"] == note_id for item in api_client.get(
            "/api/notes", params={"user_id": user_id}
        ).json())
        claims = api_client.get(
            "/api/knowledge/claims", params={"user_id": user_id}
        ).json()
        assert all(
            claim["state"] != "deleted"
            for claim in claims
            if claim["claim_id"] in claim_ids
        )
        assert api_client.post(
            f"/api/memory/notes/{note_id}/restore",
            json={"user_id": user_id, "snapshot_id": "legacy"},
        ).status_code in {404, 405}
        assert api_client.post(
            "/api/memory/delete-snapshots/legacy/restore",
            json={"user_id": user_id},
        ).status_code in {404, 405}


class TestKnowledgeArtifactsEndpoint:
    def test_lists_only_requested_knowledge_and_source_type(self, api_client: TestClient):
        store = api_client.app.state.service.knowledge_service.store
        expected = Artifact(
            owner_id="personal-agent:artifact-api",
            user_id="artifact-api",
            source_type="conversation",
            content_hash="expected-hash",
            text="canonical conversation content",
        )
        store.save_artifact(expected)
        store.save_artifact(Artifact(
            owner_id="personal-agent:artifact-api",
            user_id="artifact-api",
            source_type="text",
            content_hash="other-type-hash",
            text="other source type",
        ))
        store.save_artifact(Artifact(
            owner_id="personal-agent:other-knowledge",
            user_id="other-knowledge",
            source_type="conversation",
            content_hash="other-knowledge-hash",
            text="other knowledge",
        ))

        response = api_client.get(
            "/api/knowledge/artifacts",
            params={"user_id": "artifact-api", "source_type": "conversation"},
        )

        assert response.status_code == 200
        assert [item["artifact_id"] for item in response.json()] == [expected.artifact_id]
        assert response.json()[0]["text"] == "canonical conversation content"


class TestDebugEndpoints:
    def test_reset_database_clears_all_persisted_debug_data(self, api_client: TestClient, temp_dir: Path):
        service = api_client.app.state.service
        service.graph_store.clear_all_data = MagicMock(return_value=7)
        service.execute_capture("用户A笔记", source_type="text", user_id="reset-a")
        service.execute_capture("用户B笔记", source_type="text", user_id="reset-b")
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
        from personal_agent.orchestration.runtime_admin import _protected_eval_graph_group_ids

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


class TestRemovedWorkspaceContract:
    def test_workspace_route_and_partition_fields_are_rejected(
        self,
        api_client: TestClient,
    ):
        assert api_client.post(
            "/api/workspace/ask",
            json={"question": "legacy", "workspace_id": "legacy"},
        ).status_code == 405
        assert api_client.post(
            "/api/knowledge/ask",
            json={"question": "legacy", "workspace_id": "legacy"},
        ).status_code == 405
        assert api_client.post(
            "/api/tools/search_knowledge/execute",
            json={
                "tenant_id": "personal-agent",
                "user_id": "default",
                "owner_id": "legacy",
                "kwargs": {"query": "legacy"},
            },
        ).status_code == 422
