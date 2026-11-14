"""Build the shared goal-compliance timeline from canonical Journal facts."""

from dataclasses import dataclass, field

from personal_agent.application.python_execution.models import ExecutePythonArgs
from personal_agent.capabilities.contracts.verification import VerificationEvent
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.contracts.tool_runtime import accepted_tool_request_digest
from personal_agent.kernel.prompt_registry import PromptCatalog
from .analysis_tasks import task_switch_turn

from .errors import ConversationOperationConflict
from .goal_models import CurrentAnalysisGoal
from .models import AcceptedPythonToolRequest, ActionGoalReview, ActionObservation, DecisionFeedback, InteractionTrace, SubmittedFinal
from .verification_context import verification_events


@dataclass(frozen=True)
class ActionHistoryEvent:
    action_id: str
    arguments: ExecutePythonArgs
    review: ActionGoalReview | None
    rejection: DecisionFeedback | None
    observation: ActionObservation | None
    stdout_ref: ResourceRef | None
    is_dependency: bool

@dataclass(frozen=True)
class AnswerHistoryEvent:
    submission: VerificationEvent
    delivered: bool


@dataclass
class GoalComplianceSection:
    goal: CurrentAnalysisGoal | None
    events: list[ActionHistoryEvent | AnswerHistoryEvent] = field(default_factory=list)


@dataclass(frozen=True)
class GoalComplianceTurn:
    number: int
    run_ref: str
    goals: list[GoalComplianceSection]
    completed: bool

    @property
    def has_bound_dependency(self) -> bool:
        return any(isinstance(event, ActionHistoryEvent) and event.is_dependency
                   for goal in self.goals for event in goal.events)


def project_goal_compliance_history(
    sources: tuple[InteractionTrace, ...], *, current: CurrentAnalysisGoal | None,
    pending_ids: frozenset[str], input_refs: frozenset[ResourceRef], prompts: PromptCatalog,
    pending_answer_id: str | None = None,
) -> tuple[GoalComplianceTurn, ...]:
    turns = []
    active = None
    for number, source in enumerate(sources, 1):
        current_turn = source is sources[-1]
        goals: list[GoalComplianceSection] = []
        answers = {item.submission_id: item for item in verification_events(source) if item.kind == "answer"}
        delivered_id = next(reversed(answers), None) if source.final_message is not None else None
        operations = {item.decision_turn: item for item in source.goal_operations if item.operation != "read"}
        reviews = {item.binding.action_id: item for item in source.action_goal_reviews}
        outputs = {item.action_id: item.receipt.stdout_ref for item in source.accepted_tool_requests
                   if isinstance(item, AcceptedPythonToolRequest) and item.receipt is not None}
        producers = {action_id for action_id, stdout in outputs.items() if stdout in input_refs}
        observations = {item.action_id: item for item in source.inputs if isinstance(item, ActionObservation)
                        and item.capability_id == "execute_python" and item.action_id in reviews.keys() | producers}
        rejections = {(item.decision_turn, item.action_id): item for item in source.inputs
                      if isinstance(item, DecisionFeedback) and item.reason_code == "action_goal_conflict"}
        displayed = set()
        scope = ExecutionScope(principal=source.principal, execution_id=source.interaction_run_ref,
                               thread_id=source.conversation_id)
        decisions = tuple(record for record in source.model_decisions if record.turn_index is not None)
        switch_turn = task_switch_turn(source)
        for index, record in enumerate(decisions):
            if record.turn_index < switch_turn:
                continue
            operation = operations.get(record.turn_index)
            if operation is not None:
                active = CurrentAnalysisGoal(reference=operation.goal_ref, goal=operation.goal,
                                              execution_control=operation.execution_control)
                if not goals or goals[-1].goal != active:
                    goals.append(GoalComplianceSection(active))
            for call in (record.assistant.payload.get("tool_calls") or ()) if record.assistant is not None else ():
                action_id = call["id"]
                if (action_id in displayed or (current_turn and action_id in pending_ids)
                        or (action_id not in reviews and action_id not in producers)):
                    continue
                review = reviews.get(action_id)
                rejection = rejections.get((record.turn_index, action_id))
                observation = observations.get(action_id)
                if review is None and observation is None:
                    continue
                arguments = ExecutePythonArgs.model_validate_json(call["function"]["arguments"], context=prompts)
                if review is not None:
                    digest = accepted_tool_request_digest(execution_scope=scope.model_copy(update={"task_id": action_id}),
                        action_id=action_id, tool_name="execute_python", arguments=arguments)
                    if digest != review.binding.request_digest:
                        continue
                    if active is None or review.binding.goal_ref != active.reference:
                        raise ConversationOperationConflict("historical action review differs from the goal active at submission")
                if active is None:
                    continue
                if not goals or goals[-1].goal != active:
                    goals.append(GoalComplianceSection(active))
                goals[-1].events.append(ActionHistoryEvent(
                    action_id, arguments, review, rejection, observation, outputs.get(action_id), action_id in producers,
                ))
                displayed.add(action_id)
            end = decisions[index + 1].input_start if index + 1 < len(decisions) else len(source.inputs)
            for item in source.inputs[record.input_start:end]:
                if isinstance(item, SubmittedFinal):
                    key = f"{source.interaction_run_ref}:{item.action_id}"
                    if not (current_turn and key == pending_answer_id):
                        _append_answer(goals, active, answers[key], delivered=key == delivered_id)
        final = answers.get(f"{source.interaction_run_ref}:delivered")
        if final is not None:
            _append_answer(goals, active, final, delivered=True)
        if current_turn and (not goals or goals[-1].goal != current):
            goals.append(GoalComplianceSection(current))
        turns.append(GoalComplianceTurn(number, source.interaction_run_ref, goals, source.final_message is not None))
    return tuple(turns)


def _append_answer(goals: list[GoalComplianceSection], active: CurrentAnalysisGoal | None,
                   answer: VerificationEvent, *, delivered: bool) -> None:
    if not goals or goals[-1].goal != active:
        goals.append(GoalComplianceSection(active))
    goals[-1].events.append(AnswerHistoryEvent(answer, delivered))
