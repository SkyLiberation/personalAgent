from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import START, StateGraph

from personal_agent.agent.orchestration_graph import _build_checkpointer
from personal_agent.core.config import Settings
from scripts.export_thread_checkpoints import (
    _asset_output_path,
    collect_thread_checkpoints,
)


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
    assert payload["format"] == "state_timeline"
    assert payload["checkpoint_count"] >= 1
    latest = payload["checkpoints"][0]
    assert set(latest) == {"step", "source", "timestamp", "checkpoint_id", "state"}
    assert latest["state"]["value"] == "start-done"
    assert "channel_versions" not in latest
    assert "pending_writes" not in latest


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


def test_build_checkpointer_supports_sqlite_backend(temp_dir):
    checkpointer = _build_checkpointer(
        Settings(
            langgraph_checkpoint_backend="sqlite",
            langgraph_checkpoint_path=str(temp_dir / "checkpoints.sqlite"),
        )
    )

    try:
        assert isinstance(checkpointer, SqliteSaver)
    finally:
        checkpointer.conn.close()
