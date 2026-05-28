from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from time import sleep

import pytest

from personal_agent.memory.facade import MemoryFacade
from personal_agent.storage.ask_history_store import AskHistoryStore
from personal_agent.storage.postgres_memory_store import PostgresMemoryStore
from tests.conftest import POSTGRES_URL

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


class TestMemoryFacade:
    @pytest.fixture
    def store(self, temp_dir: Path):
        return PostgresMemoryStore(temp_dir, POSTGRES_URL)

    @pytest.fixture
    def ask_history(self):
        return AskHistoryStore(postgres_url=POSTGRES_URL)

    @pytest.fixture
    def facade(self, store, ask_history):
        return MemoryFacade(local_store=store, ask_history_store=ask_history)

    def test_bind_session_tracks_current_key(self, facade):
        facade.bind_session("user1", "session1")
        assert facade._session_key == "user1:session1"
        facade.bind_session("user1", "session1")
        assert facade._session_key == "user1:session1"
        facade.bind_session("user1", "session2")
        assert facade._session_key == "user1:session2"

    def test_record_turn_appends_history(self, facade):
        facade.record_turn("user1", "sess1", "问题？", "答案。")
        turns = facade.ask_history.list_history("user1", limit=10, session_id="sess1")
        assert len(turns) == 1
        assert turns[0].question == "问题？"
        assert turns[0].answer == "答案。"

    def test_record_turn_with_same_record_id_is_idempotent(self, facade):
        facade.record_turn("user1", "sess1", "问题？", "答案。", record_id="entry:run-1")
        facade.record_turn("user1", "sess1", "问题？", "答案。", record_id="entry:run-1")

        turns = facade.ask_history.list_history("user1", limit=10, session_id="sess1")
        assert len(turns) == 1

    def test_load_conversation_hints_with_no_history(self, facade):
        result = facade.load_conversation_hints("user1", "sess1")
        assert result == ""

    def test_load_conversation_hints_with_history(self, facade):
        facade.record_turn("user1", "sess1", "Q1", "A1")
        facade.record_turn("user1", "sess1", "Q2", "A2")
        summary = facade.load_conversation_hints("user1", "sess1")
        assert "Q1" in summary
        assert "A1" in summary
        assert "Q2" in summary
        assert summary.index("Q1") < summary.index("Q2")
        assert "历史助手回复（待核验）" in summary
        assert "不是事实证据" in summary

class TestAskHistoryStore:
    def test_schema_initialization_is_serialized(self, monkeypatch):
        store = AskHistoryStore(postgres_url=POSTGRES_URL)
        schema_started = Event()
        release_schema = Event()
        connections = 0

        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def execute(self, _query):
                schema_started.set()
                assert release_schema.wait(timeout=2)

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def cursor(self):
                return FakeCursor()

            def commit(self):
                return None

        def connect():
            nonlocal connections
            connections += 1
            return FakeConnection()

        monkeypatch.setattr(store, "_connect", connect)
        first = Thread(target=store.ensure_schema)
        second = Thread(target=store.ensure_schema)
        first.start()
        assert schema_started.wait(timeout=2)
        second.start()
        sleep(0.05)

        assert connections == 1
        release_schema.set()
        first.join(timeout=2)
        second.join(timeout=2)
        assert not first.is_alive()
        assert not second.is_alive()
        assert connections == 1
