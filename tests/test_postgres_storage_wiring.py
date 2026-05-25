from pathlib import Path

from personal_agent.agent.service import AgentService
from personal_agent.core.config import Settings
from personal_agent.storage.postgres_cross_session_store import PostgresCrossSessionStore
from personal_agent.storage.postgres_memory_store import PostgresMemoryStore
from personal_agent.storage.postgres_pending_action_store import PostgresPendingActionStore
import pytest
from tests.conftest import POSTGRES_URL

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


def test_agent_service_uses_postgres_business_stores_when_configured(temp_dir: Path):
    service = AgentService(
        Settings(
            data_dir=temp_dir,
            postgres_url=POSTGRES_URL,
        )
    )

    assert isinstance(service.store, PostgresMemoryStore)
    assert isinstance(service.pending_action_store, PostgresPendingActionStore)
    assert isinstance(service._cross_session, PostgresCrossSessionStore)
    assert not (temp_dir / "notes.json").exists()
    assert not (temp_dir / "pending_actions.json").exists()
    assert not (temp_dir / "cross_session.json").exists()
