"""Compile ordered semantic goals into a cross-workflow execution DAG."""

from __future__ import annotations

from typing import TYPE_CHECKING

from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.execution import ExecutionPlan, ExecutionStep, WorkflowTask

if TYPE_CHECKING:
    from personal_agent.planning.router import RouterDecision


class WorkflowPlanner:
    """The single framework component that decides how goals are executed.

    Workflow topology, tools, risk and confirmation policy come exclusively
    from the selected WorkflowSpec. Router output contributes only goal
    semantics and order.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        workflow_definition_store: object | None = None,
    ) -> None:
        self._settings = settings
        self._workflow_definition_store = workflow_definition_store

    def plan(
        self,
        decision: RouterDecision,
        *,
        entry_text: str,
        routing_key: str = "",
    ) -> tuple[ExecutionPlan, list[ExecutionStep]]:
        goals = decision.goals
        goal_ids = [goal.goal_id for goal in goals]
        if len(set(goal_ids)) != len(goal_ids):
            raise ValueError("Planner requires unique goal_id values.")
        namespace_steps = len(goals) > 1
        terminal_steps: dict[str, list[str]] = {}
        tasks: list[WorkflowTask] = []
        compiled_steps: list[ExecutionStep] = []

        for index, goal in enumerate(goals):
            previous_goal = goals[index - 1] if index > 0 else None
            spec = self._select_workflow(goal.intent, routing_key=routing_key)
            task_input = goal.input.strip() or entry_text
            projected = spec.project()
            id_map = {
                step.step_id: (
                    f"{goal.goal_id}::{step.step_id}"
                    if namespace_steps else step.step_id
                )
                for step in projected
            }
            upstream = (
                terminal_steps.get(previous_goal.goal_id, [])
                if previous_goal is not None
                else []
            )

            for step in projected:
                local_dependencies = [id_map[dep] for dep in step.depends_on]
                if not local_dependencies:
                    local_dependencies = list(upstream)
                step.step_id = id_map[step.step_id]
                step.depends_on = local_dependencies
                step.task_id = goal.goal_id
                step.task_intent = goal.intent
                step.task_input = task_input
                compiled_steps.append(step)

            task_step_ids = [step.step_id for step in projected]
            depended_ids = {
                dependency
                for step in projected
                for dependency in step.depends_on
                if dependency in task_step_ids
            }
            terminal_steps[goal.goal_id] = (
                [step_id for step_id in task_step_ids if step_id not in depended_ids]
                if projected else list(upstream)
            )
            tasks.append(WorkflowTask(
                task_id=goal.goal_id,
                intent=goal.intent,
                input=task_input,
                depends_on=[previous_goal.goal_id] if previous_goal is not None else [],
                workflow_id=spec.workflow_id,
                workflow_version=spec.version,
                step_ids=task_step_ids,
            ))

        return ExecutionPlan(tasks=tasks), compiled_steps

    def project_workflow(
        self,
        intent,
        *,
        routing_key: str = "",
    ) -> list[ExecutionStep]:
        """Project one workflow for administration, dry-run and tests."""
        return self._select_workflow(intent, routing_key=routing_key).project()

    def _select_workflow(self, intent, *, routing_key: str):
        from personal_agent.planning.workflow import WORKFLOW_REGISTRY

        spec = WORKFLOW_REGISTRY.select(intent)
        if self._workflow_definition_store is None:
            return spec
        selected = self._workflow_definition_store.select_active_spec(
            intent,
            registry=WORKFLOW_REGISTRY,
            routing_key=routing_key,
        )
        if selected is None:
            raise ValueError(f"Workflow deployment is disabled for intent={intent!r}.")
        return selected
