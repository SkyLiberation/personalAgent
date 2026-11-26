"""Goal contributions to the Conversation decision and history boundaries."""

from collections.abc import Sequence
from dataclasses import dataclass

from personal_agent.capabilities.contracts.model import ModelActionDefinition, ModelHistoryEntry, ModelToolExchange
from personal_agent.kernel.prompt_registry import PromptCatalog

from .analysis_tasks import AnalysisTaskHistory, GoalTaskCandidate, select_goal_task
from .goal_changes import GoalPatchCandidate, GoalPatchRejected, apply_goal_patch
from .goal_maintenance import (
    current_analysis_goal, goal_context, goal_decision_outcome, goal_feedback, goal_prepared, goal_tool_result,
)
from .goal_models import CurrentAnalysisGoal, GoalMaintenanceInvocation, GoalOperationRecord, SUBMIT_GOAL_PATCH
from .model_actions import goal_action_definition, goal_read_action_definition
from .models import ContinueTurnProposal, DecisionFeedback, FinalMessage, InteractionTrace


@dataclass(frozen=True, slots=True)
class GoalStep:
    trace: InteractionTrace
    history: AnalysisTaskHistory
    previous: tuple[InteractionTrace, ...]
    current: CurrentAnalysisGoal | None
    required: bool

    def actions(
        self, business: tuple[ModelActionDefinition, ...], *, available: bool, prompts: PromptCatalog,
    ) -> tuple[ModelActionDefinition, ...]:
        maintenance = ()
        if available:
            maintenance = (goal_action_definition(
                prompts, verification_enabled=self.trace.feature_flags_binding.goal_verification),)
            if self.current is not None:
                maintenance += (goal_read_action_definition(prompts),)
        if not self.required:
            return (*business, *maintenance)
        controls = tuple(action for action in business if action.kind in {"answer_result", "request_clarification"})
        return (*maintenance, *controls)

    def context(self, history: Sequence[ModelHistoryEntry], *, tools_available: bool,
                prompts: PromptCatalog) -> tuple[tuple[str, str], ...]:
        prompt = prompts.get("conversation.goal.context")
        visible_read = self._visible_read(history, prompts=prompts)
        entries = ((prompt.version, goal_context(self.trace, self.previous, prompts=prompts, visible_read=visible_read)),)
        if self.required and tools_available and self.trace.first_goal_operation is None:
            task_prompt = prompts.get("conversation.goal.task_selection")
            tasks = self.history.describe(self.trace, prompts=prompts)
            fallback = prompts.get("conversation.goal.task_none").template
            entries += ((task_prompt.version, task_prompt.render(tasks=tasks or fallback)),)
        return entries

    def _visible_read(self, history: Sequence[ModelHistoryEntry], *,
                      prompts: PromptCatalog) -> GoalOperationRecord | None:
        if self.current is None:
            return None
        # Only this turn's exchanges have no insertion position at this stage.
        receipts = {result.call_id: result.content for exchange in history
                    if isinstance(exchange, ModelToolExchange) and exchange.before_message_index is None
                    for result in exchange.results}
        for record in reversed(self.trace.goal_operations):
            if (record.operation == "read" and record.goal_ref == self.current.reference
                    and record.execution_control == self.current.execution_control
                    and record.call_id in receipts
                    and receipts[record.call_id] == goal_tool_result(record, prompts=prompts)):
                return record
        return None


class GoalModule:
    def step(self, trace: InteractionTrace, previous: tuple[InteractionTrace, ...]) -> GoalStep:
        history = AnalysisTaskHistory.from_turns(previous)
        selected = history.selected_turns(trace)
        current = current_analysis_goal(trace, selected)
        return GoalStep(trace, history, selected, current, not goal_prepared(trace, current))

    def admit(
        self, decision: ContinueTurnProposal | FinalMessage, *, trace: InteractionTrace,
        previous: tuple[InteractionTrace, ...], prompts: PromptCatalog, read_only_tools: frozenset[str],
    ) -> GoalMaintenanceInvocation | GoalOperationRecord | DecisionFeedback | None:
        return goal_decision_outcome(decision, trace=trace, previous=previous, prompts=prompts,
                                     read_only_tools=read_only_tools)

    def summary_goal(self, trace: InteractionTrace, previous: tuple[InteractionTrace, ...], *, prompts: PromptCatalog) -> str:
        return goal_context(trace, previous, prompts=prompts)

    def prepare_maintenance(
        self, invocation: GoalMaintenanceInvocation, *, trace: InteractionTrace,
        previous: tuple[InteractionTrace, ...], prompts: PromptCatalog,
    ) -> tuple[GoalTaskCandidate, GoalPatchCandidate] | DecisionFeedback:
        task = None
        try:
            task = select_goal_task(invocation.arguments, trace, previous)
            return task, apply_goal_patch(invocation.arguments, trace, task.current, previous=task.previous)
        except GoalPatchRejected as error:
            details = {
                "base_version": (task.current.reference.revision if task.current is not None else 0)
                    if task is not None else None,
                "item_id": error.item_id,
                "clarification_id": error.clarification_id,
            }
            if selection := invocation.arguments.task:
                details.update(task_action=selection.action, task_id=selection.task_id)
            return goal_feedback(invocation.call_id, error.reason, details, action_name=SUBMIT_GOAL_PATCH,
                                 prompts=prompts, evidence_path=error.evidence_path)
