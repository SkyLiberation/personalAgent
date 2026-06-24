from __future__ import annotations

from dataclasses import dataclass, field

from personal_agent.agent.orchestration_models import StepExecutionState, StepRunState
from personal_agent.agent.workflow import WorkflowSpec


@dataclass(frozen=True, slots=True)
class WorkflowStateMigration:
    workflow_id: str
    from_version: str
    to_version: str
    step_mapping: dict[str, str] = field(default_factory=dict)


def migrate_step_execution(
    state: StepExecutionState,
    target_spec: WorkflowSpec,
    *,
    step_mapping: dict[str, str] | None = None,
) -> StepExecutionState:
    """Move reusable step state onto a target workflow definition.

    ``step_mapping`` maps target step ids to source step ids. Unmapped target
    steps start planned, while completed mapped steps keep results/artifacts.
    """
    mapping = dict(step_mapping or {})
    source_by_id = {step.step_id: step for step in state.steps}
    target_steps: list[StepRunState] = []
    migrated_results: dict[str, object] = {}

    for projected in target_spec.project():
        target = StepRunState.from_execution_step(projected)
        source_id = mapping.get(target.step_id, target.step_id)
        source = source_by_id.get(source_id)
        if source is not None and source.status == "completed":
            target.status = "completed"
            target.retry_count = source.retry_count
            target.input_artifact_id = source.input_artifact_id
            target.output_artifact_id = source.output_artifact_id
            target.output_label = source.output_label
            target.output_title = source.output_title
            target.output_preview = source.output_preview
            if source_id in state.results:
                migrated_results[target.step_id] = state.results[source_id]
        target_steps.append(target)

    first_pending = next(
        (index for index, step in enumerate(target_steps) if step.status != "completed"),
        len(target_steps),
    )
    return StepExecutionState(
        steps=target_steps,
        current_step_index=first_pending,
        results=migrated_results,
        aborted=False,
        retry_counts={},
    )


def reset_step_and_dependents(
    state: StepExecutionState,
    step_id: str,
) -> StepExecutionState:
    """Reset a step and all transitive dependents for a step-level fork."""
    by_id = {step.step_id: step for step in state.steps}
    if step_id not in by_id:
        raise ValueError(f"Unknown workflow step: {step_id}")

    reset_ids = {step_id}
    changed = True
    while changed:
        changed = False
        for step in state.steps:
            if step.step_id not in reset_ids and reset_ids.intersection(step.depends_on):
                reset_ids.add(step.step_id)
                changed = True

    steps: list[StepRunState] = []
    for original in state.steps:
        step = original.model_copy(deep=True)
        if step.step_id in reset_ids:
            step.status = "planned"
            step.retry_count = 0
            step.failure_reason = ""
            step.recoverable = True
            step.input_artifact_id = ""
            step.output_artifact_id = ""
            step.error_artifact_id = ""
            step.output_label = ""
            step.output_title = ""
            step.output_preview = ""
        steps.append(step)

    first_reset = min(index for index, step in enumerate(steps) if step.step_id in reset_ids)
    return StepExecutionState(
        steps=steps,
        current_step_index=first_reset,
        results={
            key: value for key, value in state.results.items() if key not in reset_ids
        },
        aborted=False,
        retry_counts={
            key: value for key, value in state.retry_counts.items() if key not in reset_ids
        },
    )
