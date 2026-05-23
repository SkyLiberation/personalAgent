from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import START, StateGraph

from personal_agent.agent.orchestration_graph import _build_checkpointer
from personal_agent.core.config import Settings
from scripts.export_thread_checkpoints import collect_thread_checkpoints


class SampleState(TypedDict):
    value: str


def test_collect_thread_checkpoints_exports_complete_thread_history():
    checkpointer = MemorySaver()
    builder = StateGraph(SampleState)
    builder.add_node("set_value", lambda state: {"value": state["value"] + "-done"})
    builder.add_edge(START, "set_value")
    graph = builder.compile(checkpointer=checkpointer)
    thread_id = "user:session:run-1"

    graph.invoke({"value": "start"}, {"configurable": {"thread_id": thread_id}})

    payload = collect_thread_checkpoints(checkpointer, thread_id)

    assert payload["thread_id"] == thread_id
    assert payload["checkpoint_count"] >= 1
    latest = payload["checkpoints"][0]
    assert set(latest) == {
        "config",
        "checkpoint",
        "metadata",
        "parent_config",
        "pending_writes",
    }
    assert latest["checkpoint"]["channel_values"]["value"] == "start-done"


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
