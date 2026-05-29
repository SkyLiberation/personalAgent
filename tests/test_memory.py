from __future__ import annotations

from pathlib import Path

import pytest

from personal_agent.memory.facade import MemoryFacade
from personal_agent.storage.postgres_memory_store import PostgresMemoryStore
from tests.conftest import POSTGRES_URL

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


class TestMemoryFacade:
    @pytest.fixture
    def store(self, temp_dir: Path):
        return PostgresMemoryStore(temp_dir, POSTGRES_URL)

    @pytest.fixture
    def facade(self, store):
        return MemoryFacade(local_store=store)

    def test_bind_session_tracks_current_key(self, facade):
        facade.bind_session("user1", "session1")
        assert facade._session_key == "user1:session1"
        facade.bind_session("user1", "session1")
        assert facade._session_key == "user1:session1"
        facade.bind_session("user1", "session2")
        assert facade._session_key == "user1:session2"
