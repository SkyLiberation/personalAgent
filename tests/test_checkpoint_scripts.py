from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import START, StateGraph

from personal_agent.agent.orchestration_graph import _build_checkpointer
from personal_agent.kernel.config import Settings
from scripts.export_thread_checkpoints import (
    _asset_output_path,
    collect_thread_checkpoints,
)
from tests.conftest import POSTGRES_URL

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


class SampleState(TypedDict):
    value: str


def _sample_checkpoint_history() -> tuple[MemorySaver, str]:
    checkpointer = MemorySaver()
    builder = StateGraph(SampleState)
    builder.add_node("set_value", lambda state: {"value": state["value"] + "-done"})
    builder.add_edge(START, "set_value")
    graph = builder.compile(checkpointer=checkpointer)
    thread_id = "user:session:run-1"

    graph.invoke({"value": "start"}, {"configurable": {"thread_id": thread_id}})
    return checkpointer, thread_id


def test_collect_thread_checkpoints_exports_readable_state_timeline():
    checkpointer, thread_id = _sample_checkpoint_history()

    payload = collect_thread_checkpoints(checkpointer, thread_id)

    assert payload["thread_id"] == thread_id
    assert payload["current_checkpoint_schema_version"] == "step_execution_v2"
    assert payload["format"] == "state_timeline"
    assert payload["checkpoint_count"] >= 1
    latest = payload["checkpoints"][0]
    assert set(latest) == {
        "checkpoint_schema_version",
        "step",
        "source",
        "timestamp",
        "checkpoint_id",
        "step_execution",
        "state",
    }
    assert latest["checkpoint_schema_version"] == "unknown"
    assert latest["step_execution"]["step_count"] == 0
    assert latest["state"]["value"] == "start-done"
    assert "channel_versions" not in latest
    assert "pending_writes" not in latest


def test_collect_thread_checkpoints_marks_step_execution_schema():
    class FakeTuple:
        config = {}
        metadata = {"step": 1, "source": "loop"}
        parent_config = None
        pending_writes = []
        checkpoint = {
            "ts": "2026-01-01T00:00:00Z",
            "id": "ckpt-1",
            "channel_values": {
                "step_execution": {
                    "steps": [
                        {"step_id": "a", "status": "completed"},
                        {"step_id": "b", "status": "failed"},
                    ],
                    "current_step_index": 1,
                    "results": {"a": {"ok": True}},
                    "aborted": False,
                }
            },
        }

    class FakeCheckpointer:
        def list(self, _config):
            return [FakeTuple()]

    payload = collect_thread_checkpoints(FakeCheckpointer(), "thread-1")
    latest = payload["checkpoints"][0]

    assert latest["checkpoint_schema_version"] == "step_execution_v2"
    assert latest["step_execution"] == {
        "schema_version": "step_execution_v2",
        "step_count": 2,
        "current_step_index": 1,
        "aborted": False,
        "result_keys": ["a"],
        "statuses": {"completed": 1, "failed": 1},
    }


def test_collect_thread_checkpoints_marks_legacy_plan_schema():
    class FakeTuple:
        config = {}
        metadata = {}
        parent_config = None
        pending_writes = []
        checkpoint = {
            "ts": "2026-01-01T00:00:00Z",
            "id": "old-ckpt",
            "channel_values": {"plan": {"steps": []}},
        }

    class FakeCheckpointer:
        def list(self, _config):
            return [FakeTuple()]

    payload = collect_thread_checkpoints(FakeCheckpointer(), "thread-1")
    latest = payload["checkpoints"][0]

    assert latest["checkpoint_schema_version"] == "legacy_plan_v1"
    assert latest["step_execution"]["schema_version"] == "legacy_plan_v1"


def test_collect_thread_checkpoints_can_export_raw_tuple_data():
    checkpointer, thread_id = _sample_checkpoint_history()

    payload = collect_thread_checkpoints(checkpointer, thread_id, raw=True)

    assert payload["format"] == "raw"
    latest = payload["checkpoints"][0]
    assert latest["checkpoint"]["channel_values"]["value"] == "start-done"
    assert "channel_versions" in latest["checkpoint"]
    assert "pending_writes" in latest


def test_collect_thread_checkpoints_includes_multiple_runs_in_one_thread():
    checkpointer = MemorySaver()
    builder = StateGraph(SampleState)
    builder.add_node("set_value", lambda state: {"value": state["value"] + "-done"})
    builder.add_edge(START, "set_value")
    graph = builder.compile(checkpointer=checkpointer)
    thread_id = "user:session"

    graph.invoke({"value": "first"}, {"configurable": {"thread_id": thread_id}})
    graph.invoke({"value": "second"}, {"configurable": {"thread_id": thread_id}})

    payload = collect_thread_checkpoints(checkpointer, thread_id)
    values = [item["state"].get("value") for item in payload["checkpoints"]]

    assert "first-done" in values
    assert "second-done" in values


def test_raw_output_uses_separate_asset_name():
    assert _asset_output_path("u:s:r").name == "checkpoints-u_s_r.json"
    assert _asset_output_path("u:s:r", raw=True).name == "checkpoints-u_s_r-raw.json"


def test_build_checkpointer_uses_postgres():
    checkpointer = _build_checkpointer(Settings(postgres_url=POSTGRES_URL))

    try:
        assert isinstance(checkpointer, PostgresSaver)
    finally:
        checkpointer.conn.close()
