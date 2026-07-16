"""Deterministic invariants for TaskContract and TaskRuntimeProjection."""

from __future__ import annotations

from personal_agent.runtime.contracts.task import TaskContract, TaskRuntimeProjection


class TaskContractValidator:
    def validate_runtime(self, task: TaskContract, runtime: TaskRuntimeProjection) -> None:
        goals = task.goal_graph.goals
        goal_ids = {item.goal_id for item in goals}
        if len(goal_ids) != len(goals):
            raise ValueError("goal ids must be unique")
        if set(runtime.goal_states) != goal_ids:
            raise ValueError("goal definition/runtime identities must match")
        hard_graph = {goal_id: set() for goal_id in goal_ids}
        for item in goals:
            seen: set[tuple[str, str]] = set()
            for dependency in item.dependencies:
                if dependency.dependency_goal_id not in goal_ids:
                    raise ValueError(
                        f"goal {item.goal_id} has unknown dependency {dependency.dependency_goal_id}"
                    )
                if dependency.dependency_goal_id == item.goal_id:
                    raise ValueError(f"goal {item.goal_id} cannot depend on itself")
                key = (dependency.dependency_goal_id, dependency.kind)
                if key in seen:
                    raise ValueError("duplicate goal dependency")
                seen.add(key)
                if dependency.blocks_execution:
                    hard_graph[item.goal_id].add(dependency.dependency_goal_id)
        _validate_acyclic(hard_graph)


def _validate_acyclic(graph: dict[str, set[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("blocking goal dependencies contain a cycle")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency_id in graph[node_id]:
            visit(dependency_id)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in graph:
        visit(node_id)


__all__ = ["TaskContractValidator"]
