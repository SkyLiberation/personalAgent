from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from personal_agent.infra.storage.audit_redaction import redact_audit_payload
from personal_agent.infra.storage.postgres_tool_governance_store import PostgresToolGovernanceStore
from personal_agent.tools.base import ToolArtifact, ToolInvocationEvent
from personal_agent.governance.gateway import ToolGatewayContext
from personal_agent.kernel.contracts.scope import interaction_execution_scope
from tests.conftest import POSTGRES_URL

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


def _audit_event(
    *,
    tool_name: str = "external_publish",
    user_id: str = "u1",
    ok: bool = True,
    risk_level: str = "high",
    side_effects: list[str] | None = None,
    error: str | None = None,
    side_effect_id: str | None = "idem-1",
    confirmed: bool = True,
) -> ToolInvocationEvent:
    return ToolInvocationEvent(
        thread_id="t1",
        run_id="r1",
        user_id=user_id,
        tool_name=tool_name,
        tool_call_id="call-1",
        execution_mode="direct",
        input={"note_id": "note-9", "content": "敏感内容", "confirmed": confirmed},
        output=ToolArtifact(ok=ok, data="result-payload", error=error),
        artifact_ok=ok,
        error=error,
        confirmed=confirmed,
        risk_level=risk_level,
        requires_confirmation=True,
        side_effects=side_effects or ["delete_longterm"],
        permission_scope="memory:delete",
        side_effect_id=side_effect_id,
    )


class TestRedaction:
    def test_default_redaction_masks_content_and_output(self):
        payload = _audit_event().model_dump(mode="json")
        redacted = redact_audit_payload(payload, reveal=False)
        assert redacted["input"]["content"].startswith("<redacted:")
        assert redacted["input"]["note_id"].startswith("<redacted:")
        assert redacted["output"]["data"].startswith("<redacted:")
        # Governance shape stays visible.
        assert redacted["tool_name"] == "external_publish"
        assert redacted["risk_level"] == "high"
        assert redacted["confirmed"] is True

    def test_reveal_returns_payload_unchanged(self):
        payload = _audit_event().model_dump(mode="json")
        revealed = redact_audit_payload(payload, reveal=True)
        assert revealed["input"]["content"] == "敏感内容"
        assert revealed["output"]["data"] == "result-payload"


class TestGovernanceStoreQueries:
    @pytest.fixture
    def store(self) -> PostgresToolGovernanceStore:
        store = PostgresToolGovernanceStore(POSTGRES_URL)
        store.ensure_schema()
        return store

    def test_record_and_query_redacts_by_default(self, store: PostgresToolGovernanceStore):
        store.record(_audit_event(user_id="alice"))
        events = store.query_audit_events(user_id="alice")
        assert len(events) == 1
        evt = events[0]
        assert evt["tool_name"] == "external_publish"
        assert evt["confirmed"] is True
        assert evt["risk_level"] == "high"
        assert evt["payload"]["input"]["content"].startswith("<redacted:")

    def test_query_reveal_exposes_raw_payload(self, store: PostgresToolGovernanceStore):
        store.record(_audit_event(user_id="alice"))
        events = store.query_audit_events(user_id="alice", reveal=True)
        assert events[0]["payload"]["input"]["content"] == "敏感内容"

    def test_query_filters_by_risk_and_tool(self, store: PostgresToolGovernanceStore):
        store.record(_audit_event(user_id="bob", tool_name="external_publish", risk_level="high"))
        store.record(
            _audit_event(
                user_id="bob",
                tool_name="graph_search",
                risk_level="low",
                side_effects=["read_local"],
                side_effect_id=None,
            )
        )
        high = store.query_audit_events(user_id="bob", risk_level="high")
        assert {e["tool_name"] for e in high} == {"external_publish"}

    def test_record_and_query_policy_decision(self, store: PostgresToolGovernanceStore):
        store.record_policy_decision(
            {
                "action": "tool_call",
                "effect": "deny",
                "rule": "override.deny_tool",
                "tool_name": "external_publish",
                "user_id": "carol",
                "risk_level": "high",
            }
        )
        decisions = store.query_policy_decisions(user_id="carol", effect="deny")
        assert len(decisions) == 1
        assert decisions[0]["rule"] == "override.deny_tool"

    def test_trace_idempotency_combines_ledger_and_events(self, store: PostgresToolGovernanceStore):
        ctx = ToolGatewayContext(
            execution_scope=interaction_execution_scope(
                tenant_id="tenant-1",
                workspace_id="workspace-1",
                user_id="dave",
                execution_id="r1",
                thread_id="t1",
            ),
            execution_mode="direct",
            tool_call_id="call-1",
        )
        store.reserve("idem-trace", context=ctx, tool_name="external_publish")
        store.commit("idem-trace")
        store.record(_audit_event(user_id="dave", side_effect_id="idem-trace"))

        trace = store.trace_idempotency("idem-trace")
        assert trace is not None
        assert trace["ledger"]["status"] == "committed"
        assert trace["ledger"]["user_id"] == "tenant-1:dave"
        assert len(trace["events"]) == 1

    def test_idempotency_store_persists_committed_receipt(self, store: PostgresToolGovernanceStore):
        ctx = ToolGatewayContext(
            execution_scope=interaction_execution_scope(
                tenant_id="tenant-1",
                workspace_id="workspace-1",
                user_id="receipt-user",
                execution_id="run-receipt",
                thread_id="thread-receipt",
            ),
            execution_mode="invocation_batch",
            tool_call_id="call-receipt",
        )
        receipt = {"ok": True, "data": {"note_id": "note-1"}, "evidence": []}

        assert store.reserve("idem-receipt", context=ctx, tool_name="capture_text")
        store.commit("idem-receipt", receipt)

        assert store.get_receipt("idem-receipt") == receipt
        assert not store.reserve("idem-receipt", context=ctx, tool_name="capture_text")

    def test_trace_idempotency_missing_returns_none(self, store: PostgresToolGovernanceStore):
        assert store.trace_idempotency("nope") is None

    def test_audit_metrics_counts_deletes_and_failures(self, store: PostgresToolGovernanceStore):
        store.record(_audit_event(user_id="erin", ok=True))
        store.record(_audit_event(user_id="erin", ok=False, error="boom"))
        store.record_policy_decision(
            {"action": "tool_call", "effect": "deny", "rule": "r", "user_id": "erin"}
        )
        metrics = store.audit_metrics(window_hours=24)
        assert metrics["total_invocations"] == 2
        assert metrics["high_risk_invocations"] == 2
        assert metrics["deletes"] == 2
        assert metrics["delete_failures"] == 1
        assert metrics["failures"] == 1
        assert metrics["policy_denials"] == 1

    def test_audit_metrics_flags_duplicate_side_effects(self, store: PostgresToolGovernanceStore):
        store.record(
            _audit_event(
                user_id="frank",
                ok=False,
                error="工具 external_publish 的确认动作已执行过或正在执行（idempotency_key=idem-1）。",
            )
        )
        metrics = store.audit_metrics(window_hours=24)
        assert metrics["duplicate_side_effects"] == 1


@pytest.fixture
def admin_client(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PERSONAL_AGENT_DATA_DIR", str(temp_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_POSTGRES_URL", POSTGRES_URL)
    monkeypatch.setenv("PERSONAL_AGENT_FEISHU_ENABLED", "false")
    monkeypatch.setenv(
        "PERSONAL_AGENT_API_KEYS",
        '{"user-key":{"tenant_id":"tenant-1","user_id":"alice"}}',
    )
    monkeypatch.setenv(
        "PERSONAL_AGENT_ADMIN_API_KEYS",
        '{"admin-key":{"tenant_id":"tenant-1","user_id":"root"}}',
    )
    from personal_agent.kernel import config_env as config_env_module
    monkeypatch.setattr(config_env_module, "load_dotenv", lambda override=True: False)

    from personal_agent.adapters.web.api import create_app
    app = create_app()
    return TestClient(app)


class TestAuditApiGate:
    def test_missing_key_rejected(self, admin_client: TestClient):
        resp = admin_client.get("/api/audit/metrics")
        assert resp.status_code == 401

    def test_regular_user_cannot_access_metrics(self, admin_client: TestClient):
        resp = admin_client.get("/api/audit/metrics", headers={"X-API-Key": "user-key"})
        assert resp.status_code == 403

    def test_admin_can_access_metrics(self, admin_client: TestClient):
        resp = admin_client.get("/api/audit/metrics", headers={"X-API-Key": "admin-key"})
        assert resp.status_code == 200
        body = resp.json()
        assert "metrics" in body
        assert "alerts" in body

    def test_regular_user_cannot_reset_debug_database(
        self,
        admin_client: TestClient,
    ):
        resp = admin_client.post(
            "/api/debug/reset-database",
            headers={"X-API-Key": "user-key"},
        )

        assert resp.status_code == 403

    def test_direct_tool_endpoint_rejects_principal_scope_spoofing(
        self,
        admin_client: TestClient,
    ):
        resp = admin_client.post(
            "/api/tools/search_knowledge/execute",
            headers={"X-API-Key": "user-key"},
            json={
                "tenant_id": "tenant-1",
                "workspace_id": "workspace-a",
                "user_id": "bob",
                "kwargs": {"query": "secret"},
            },
        )

        assert resp.status_code == 404

    def test_regular_user_events_scoped_to_self_and_redacted(self, admin_client: TestClient):
        service = admin_client.app.state.service
        store = service.tool_governance_store
        store.record(_audit_event(user_id="alice"))
        store.record(_audit_event(user_id="bob"))

        # Regular user cannot widen to another user; reveal is ignored.
        resp = admin_client.get(
            "/api/audit/events",
            params={"user_id": "bob", "reveal": True},
            headers={"X-API-Key": "user-key"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["redacted"] is True
        assert all(e["user_id"] == "alice" for e in body["items"])

    def test_admin_can_reveal_and_cross_user(self, admin_client: TestClient):
        service = admin_client.app.state.service
        service.tool_governance_store.record(_audit_event(user_id="bob"))
        resp = admin_client.get(
            "/api/audit/events",
            params={"user_id": "bob", "reveal": True},
            headers={"X-API-Key": "admin-key"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["redacted"] is False
        assert body["items"][0]["payload"]["input"]["content"] == "敏感内容"

    def test_admin_trace_by_idempotency(self, admin_client: TestClient):
        service = admin_client.app.state.service
        service.tool_governance_store.record(_audit_event(user_id="alice", side_effect_id="idem-x"))
        resp = admin_client.get(
            "/api/audit/events/by-idempotency/idem-x",
            headers={"X-API-Key": "admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["idempotency_key"] == "idem-x"
