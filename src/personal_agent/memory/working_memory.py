from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class _Step:
    content: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class WorkingMemory:
    """Session-scoped in-memory store for the current agent task.

    Tracks task goals, recent reasoning steps, cached tool results,
    and a rolling conversation summary.  All data is ephemeral — it
    lives only for the lifetime of the AgentService instance.
    """

    def __init__(self, max_steps: int = 20, max_tool_cache: int = 10) -> None:
        self._max_steps = max_steps
        self._max_tool_cache = max_tool_cache
        self.task_goal: str | None = None
        self.conversation_summary: str | None = None
        self._steps: deque[_Step] = deque(maxlen=max_steps)
        self._tool_cache: dict[str, object] = {}

    def set_goal(self, goal: str) -> None:
        self.task_goal = goal

    def clear_goal(self) -> None:
        self.task_goal = None

    def add_step(self, content: str) -> None:
        self._steps.append(_Step(content=content))

    def recent_steps(self, limit: int = 6) -> list[str]:
        items = list(self._steps)[-limit:]
        return [item.content for item in items]

    def cache_tool_result(self, name: str, data: object) -> None:
        self._tool_cache[name] = data
        if len(self._tool_cache) > self._max_tool_cache:
            oldest = next(iter(self._tool_cache))
            del self._tool_cache[oldest]

    def get_cached_result(self, name: str) -> object | None:
        return self._tool_cache.get(name)

    def set_conversation_summary(self, summary: str) -> None:
        self.conversation_summary = summary

    def context_snapshot(self) -> str:
        """Build a compact context string for inclusion in LLM prompts."""
        parts: list[str] = []
        if self.task_goal:
            parts.append(f"当前任务目标：{self.task_goal}")
        if self.conversation_summary:
            parts.append(f"会话摘要：{self.conversation_summary}")
        steps = self.recent_steps(limit=6)
        if steps:
            parts.append("最近推理步骤：\n" + "\n".join(f"- {s}" for s in steps))
        return "\n\n".join(parts) if parts else ""

    def reset(self) -> None:
        self.task_goal = None
        self.conversation_summary = None
        self._steps.clear()
        self._tool_cache.clear()
