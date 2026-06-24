from pathlib import Path

from personal_agent.agent.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.storage.postgres_memory_store import PostgresMemoryStore
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
    assert not (temp_dir / "notes.json").exists()
