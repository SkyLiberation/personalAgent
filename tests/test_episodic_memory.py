from __future__ import annotations

from personal_agent.agent.episodic_memory import build_entry_episode, build_reflection_candidate
from personal_agent.agent.runtime_results import EntryResult
from personal_agent.core.models import EntryInput


def test_build_entry_episode_from_completed_run():
    result = EntryResult(
        intent="delete_knowledge",
        reason="删除知识。",
        reply_text="已删除笔记「Graphiti」。",
        run_id="run-123",
        thread_id="alice:s1",
        run_status="completed",
        execution_trace=["确认删除笔记", "调用 delete_note"],
        events=[
            {
                "event_id": "evt-1",
                "type": "intent_classified",
                "payload": {
                    "intent": "delete_knowledge",
                    "risk_level": "high",
                },
            },
            {
                "event_id": "evt-2",
                "type": "tool_result",
                "payload": {
                    "tool_name": "delete_note",
                    "output": {
                        "ok": True,
                        "data": {"note_id": "note-1"},
                    },
                },
            },
        ],
    )
    entry_input = EntryInput(text="删除 Graphiti 笔记", user_id="alice", session_id="s1")

    episode = build_entry_episode(result, entry_input)

    assert episode.id == "episode:run-123"
    assert episode.user_id == "alice"
    assert episode.session_id == "s1"
    assert episode.workflow == "delete_knowledge"
    assert episode.outcome == "completed"
    assert "delete_note" in episode.tool_refs
    assert "note-1" in episode.note_refs
    assert episode.decisions == ["识别意图为 delete_knowledge，风险 high"]


def test_build_entry_episode_records_open_item_for_confirmation():
    result = EntryResult(
        intent="delete_knowledge",
        reason="操作需要用户确认",
        reply_text="确认删除笔记「Graphiti」？",
        run_id="run-456",
        thread_id="alice:s1",
        run_status="waiting_confirmation",
        pending_confirmation={
            "message": "确认删除笔记「Graphiti」？",
            "note_id": "note-1",
        },
        events=[
            {
                "event_id": "evt-1",
                "type": "entry_started",
                "payload": {"text_preview": "删除 Graphiti 笔记"},
            }
        ],
    )

    episode = build_entry_episode(result)

    assert episode.outcome == "waiting_confirmation"
    assert episode.entry_text == "删除 Graphiti 笔记"
    assert episode.open_items == ["确认删除笔记「Graphiti」？"]


def test_failed_entry_builds_reflection_candidate():
    result = EntryResult(
        intent="delete_knowledge",
        reason="计划执行失败",
        reply_text="删除失败",
        run_id="run-failed",
        thread_id="alice:s1",
        run_status="failed",
        execution_trace=["检索候选", "resolve 失败"],
        events=[
            {
                "type": "step_failed",
                "payload": {"failure_reason": "未找到明确删除目标"},
            }
        ],
    )
    entry_input = EntryInput(text="删除旧 Graphiti 笔记", user_id="alice", session_id="s1")
    episode = build_entry_episode(result, entry_input)

    reflection = build_reflection_candidate(result, episode)

    assert reflection is not None
    assert reflection.id == "reflection:run-failed"
    assert reflection.memory_type == "reflection"
    assert reflection.status == "candidate"
    assert reflection.source_episode_ids == [episode.id]
    assert "未找到明确删除目标" in reflection.content
