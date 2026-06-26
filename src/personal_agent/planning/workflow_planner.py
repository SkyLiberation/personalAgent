"""Compile ordered semantic goals into a cross-workflow execution DAG."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.execution import ExecutionPlan, ExecutionStep, WorkflowTask
from personal_agent.kernel.contracts.workflow import WorkflowSpec
from personal_agent.kernel.prompts import get_prompt, render_prompt
from personal_agent.infra.structured_model import StructuredModelClient, StructuredModelRequest

if TYPE_CHECKING:
    from personal_agent.planning.router import Goal, RouterDecision


_LONGTERM_MUTATION_EFFECTS = {"write_longterm", "delete_longterm"}
_LONGTERM_READ_EFFECTS = {"read_longterm"}
_RETRIEVAL_ACTIONS = {"retrieve"}
_CONTINUATION_CUES = (
    "刚才",
    "上面",
    "上述",
    "前面",
    "之前",
    "继续",
    "接着",
    "再基于",
    "基于以上",
    "基于上文",
    "这个",
    "该内容",
    "该知识",
    "it",
    "this",
    "that",
    "above",
    "previous",
)


@dataclass(frozen=True, slots=True)
class _PlannedTask:
    task_id: str
    spec: WorkflowSpec


class GoalDependencyDecision(BaseModel):
    task_id: str
    depends_on: list[str] = Field(default_factory=list)
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class GoalDependencyPlan(BaseModel):
    decisions: list[GoalDependencyDecision] = Field(default_factory=list)


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
        dependency_model_client: StructuredModelClient | None = None,
    ) -> None:
        self._settings = settings
        self._workflow_definition_store = workflow_definition_store
        self._dependency_model_client = dependency_model_client

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
        selected_specs = [
            self._select_workflow(goal.intent, routing_key=routing_key)
            for goal in goals
        ]
        model_dependencies = self._plan_dependencies_with_model(
            goals,
            selected_specs,
            entry_text=entry_text,
        )
        task_dependencies_by_id = self._plan_task_dependencies(
            goals,
            selected_specs,
            model_dependencies,
        )
        sorted_goal_ids = self._topological_sort_task_ids(
            goal_ids,
            task_dependencies_by_id,
        )
        goal_by_id = {goal.goal_id: goal for goal in goals}
        spec_by_id = {
            goal.goal_id: spec
            for goal, spec in zip(goals, selected_specs, strict=False)
        }
        terminal_steps: dict[str, list[str]] = {}
        tasks: list[WorkflowTask] = []
        compiled_steps: list[ExecutionStep] = []

        for goal_id in sorted_goal_ids:
            goal = goal_by_id[goal_id]
            spec = spec_by_id[goal_id]
            task_input = goal.input.strip() or entry_text
            projected = spec.project()
            id_map = {
                step.step_id: (
                    f"{goal.goal_id}::{step.step_id}"
                    if namespace_steps else step.step_id
                )
                for step in projected
            }
            task_dependencies = task_dependencies_by_id[goal.goal_id]
            upstream = [
                step_id
                for task_id in task_dependencies
                for step_id in terminal_steps.get(task_id, [])
            ]

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
                depends_on=task_dependencies,
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

    def _infer_task_dependencies(
        self,
        goal: "Goal",
        spec: WorkflowSpec,
        prior_tasks: list[_PlannedTask],
        model_dependencies: list[str] | None = None,
    ) -> list[str]:
        prior_task_ids = [task.task_id for task in prior_tasks]
        dependencies: list[str] = list(model_dependencies or [])
        if prior_tasks and self._mentions_previous_result(goal.input):
            dependencies.append(prior_tasks[-1].task_id)

        latest_mutation = next(
            (
                task.task_id
                for task in reversed(prior_tasks)
                if self._mutates_longterm(task.spec)
            ),
            None,
        )
        if latest_mutation and (
            self._reads_longterm(spec)
            or self._mutates_longterm(spec)
            or spec.has_high_risk_side_effect
        ):
            dependencies.append(latest_mutation)

        return list(dict.fromkeys(dependencies))

    def _plan_dependencies_with_model(
        self,
        goals: list["Goal"],
        specs: list[WorkflowSpec],
        *,
        entry_text: str,
    ) -> dict[str, list[str]]:
        if self._dependency_model_client is None or len(goals) <= 1:
            return {}

        prompt = get_prompt("workflow_planner.dependencies.system")
        try:
            response = self._dependency_model_client.generate(
                StructuredModelRequest(
                    operation="workflow_planner_dependencies",
                    version=prompt.version,
                    messages=[
                        {"role": "system", "content": prompt.template},
                        {
                            "role": "user",
                            "content": render_prompt(
                                "workflow_planner.dependencies.user",
                                entry_text=entry_text,
                                goal_summaries=self._goal_summaries(goals, specs),
                            ),
                        },
                    ],
                    output_type=GoalDependencyPlan,
                    temperature=0,
                    max_tokens=1500,
                )
            )
        except Exception:
            return {}

        return self._validated_model_dependencies(goals, response.value)

    def _plan_task_dependencies(
        self,
        goals: list["Goal"],
        specs: list[WorkflowSpec],
        model_dependencies: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        dependencies: dict[str, list[str]] = {}
        planned_tasks: list[_PlannedTask] = []
        for goal, spec in zip(goals, specs, strict=False):
            dependencies[goal.goal_id] = self._infer_task_dependencies(
                goal,
                spec,
                planned_tasks,
                model_dependencies.get(goal.goal_id, []),
            )
            planned_tasks.append(_PlannedTask(task_id=goal.goal_id, spec=spec))
        return dependencies

    def _validated_model_dependencies(
        self,
        goals: list["Goal"],
        plan: GoalDependencyPlan,
    ) -> dict[str, list[str]]:
        goal_order = [goal.goal_id for goal in goals]
        known = set(goal_order)
        dependencies: dict[str, list[str]] = {goal_id: [] for goal_id in goal_order}
        for decision in plan.decisions:
            if decision.task_id not in dependencies:
                raise ValueError(
                    f"Task DAG references unknown task_id={decision.task_id!r}."
                )
            for dependency in decision.depends_on:
                if dependency not in known:
                    raise ValueError(
                        "Task DAG dependency "
                        f"{decision.task_id!r} -> {dependency!r} references an unknown task."
                    )
                if dependency == decision.task_id:
                    raise ValueError(
                        f"Task DAG contains self dependency for task_id={decision.task_id!r}."
                    )
                if dependency not in dependencies[decision.task_id]:
                    dependencies[decision.task_id].append(dependency)
        return dependencies

    def _topological_sort_task_ids(
        self,
        task_ids: list[str],
        dependencies: dict[str, list[str]],
    ) -> list[str]:
        known = set(task_ids)
        indeg = {task_id: 0 for task_id in task_ids}
        adj = {task_id: [] for task_id in task_ids}

        for task_id in task_ids:
            if task_id not in dependencies:
                raise ValueError(f"Task DAG missing dependencies for task_id={task_id!r}.")
            seen: set[str] = set()
            ordered_dependencies: list[str] = []
            for dependency in dependencies[task_id]:
                if dependency not in known:
                    raise ValueError(
                        "Task DAG dependency "
                        f"{task_id!r} -> {dependency!r} references an unknown task."
                    )
                if dependency == task_id:
                    raise ValueError(
                        f"Task DAG contains self dependency for task_id={task_id!r}."
                    )
                if dependency in seen:
                    continue
                seen.add(dependency)
                ordered_dependencies.append(dependency)
                indeg[task_id] += 1
                adj[dependency].append(task_id)
            dependencies[task_id] = ordered_dependencies

        q: deque[str] = deque(task_id for task_id in task_ids if indeg[task_id] == 0)
        result: list[str] = []
        while q:
            task_id = q.popleft()
            result.append(task_id)
            for dependent in adj[task_id]:
                indeg[dependent] -= 1
                if indeg[dependent] == 0:
                    q.append(dependent)

        if len(result) != len(task_ids):
            cyclic = [task_id for task_id in task_ids if indeg[task_id] > 0]
            raise ValueError(
                "Task DAG contains a dependency cycle involving "
                f"{', '.join(cyclic)}."
            )
        return result

    def _goal_summaries(
        self,
        goals: list["Goal"],
        specs: list[WorkflowSpec],
    ) -> str:
        lines: list[str] = []
        for index, (goal, spec) in enumerate(zip(goals, specs, strict=False), 1):
            side_effects = sorted(self._side_effects(spec))
            actions = [step.action_type for step in spec.steps]
            lines.append(
                "\n".join([
                    f"{index}. task_id={goal.goal_id}",
                    f"   intent={goal.intent}",
                    f"   input={goal.input}",
                    f"   workflow_id={spec.workflow_id}",
                    f"   actions={actions}",
                    f"   side_effects={side_effects}",
                    f"   reads_longterm={self._reads_longterm(spec)}",
                    f"   mutates_longterm={self._mutates_longterm(spec)}",
                    f"   high_risk={spec.has_high_risk_side_effect}",
                ])
            )
        return "\n".join(lines)

    def _mutates_longterm(self, spec: WorkflowSpec) -> bool:
        return bool(self._side_effects(spec).intersection(_LONGTERM_MUTATION_EFFECTS))

    def _reads_longterm(self, spec: WorkflowSpec) -> bool:
        side_effects = self._side_effects(spec)
        return (
            bool(side_effects.intersection(_LONGTERM_READ_EFFECTS))
            or any(step.action_type in _RETRIEVAL_ACTIONS for step in spec.steps)
        )

    def _side_effects(self, spec: WorkflowSpec) -> set[str]:
        return {
            effect
            for step in spec.steps
            for effect in step.side_effects
        }

    def _mentions_previous_result(self, text: str) -> bool:
        normalized = text.strip().lower()
        return bool(normalized) and any(cue in normalized for cue in _CONTINUATION_CUES)
