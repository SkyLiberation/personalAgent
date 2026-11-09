"""Project and bind a batch of actual Python proposals for goal compliance."""
from collections.abc import Callable
from dataclasses import dataclass
import json

from pydantic import create_model

from personal_agent.capabilities.contracts.model import (
    ModelCapacityCheck, ModelCapacityRefused, StructuredModelRequest, sealed_context_projection_ref,
)
from personal_agent.capabilities.contracts.verification import (
    ActionGoalAssessment, ActionGoalDecision, ActionGoalJudgment, GoalComplianceAnswerContext,
)
from personal_agent.capabilities.contracts.verification_prompt import (
    GOAL_COMPLIANCE_OPERATION, goal_compliance_answer_request, goal_compliance_messages, verification_judgment_text,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.contracts.tool_runtime import accepted_tool_request_digest
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.application.artifacts.models import resolve_artifact_ref
from personal_agent.application.python_execution.models import PROGRAM_MAX_BYTES, ExecutePythonArgs

from .goal_compliance_history import ActionHistoryEvent, GoalComplianceTurn, project_goal_compliance_history
from .errors import ConversationOperationConflict
from .goal_models import CurrentAnalysisGoal
from .models import (
    ActionGoalBinding, ActionGoalReview, ArtifactSourceInput, InteractionTrace,
)
from .ports import InteractionArtifactPort
from .verification_context import verification_events

ACTION_GOAL_PROMPT = "interaction_verification.action_goal"
COMPLIANCE_PROMPT = "interaction_verification.compliance"
_HISTORICAL_GOAL_EXCERPT = 600
_RECENT_COMPLETE_TURNS = 2


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class PendingPythonReview:
    binding: ActionGoalBinding
    arguments: ExecutePythonArgs

    @classmethod
    def create(cls, scope: ExecutionScope, arguments: ExecutePythonArgs,
               allowed_refs: tuple[ResourceRef, ...], goal: CurrentAnalysisGoal,
               *, prompts: PromptCatalog) -> "PendingPythonReview":
        action_id = scope.task_id
        if not action_id:
            raise ConversationOperationConflict("Python goal review requires an action scope")
        refs = tuple(resolve_artifact_ref(item.resource_id, allowed_refs, principal=scope.principal,
                                          prompts=prompts) for item in arguments.input_files)
        return cls(ActionGoalBinding(
            action_id=action_id, goal_ref=goal.reference, input_refs=refs,
            request_digest=accepted_tool_request_digest(execution_scope=scope, action_id=action_id,
                                                       tool_name="execute_python", arguments=arguments),
            prompt_version=prompts.get(ACTION_GOAL_PROMPT).version,
        ), arguments)


@dataclass(frozen=True)
class PreparedActionGoalRequest:
    request: StructuredModelRequest[ActionGoalAssessment]
    compacted_through: int


def _render_turn(turn: GoalComplianceTurn, *, compacted: bool, prompts: PromptCatalog) -> str:
    groups = []
    for group in turn.goals:
        objective = group.goal.goal.objective if group.goal is not None else prompts.get(
            "interaction_verification.answer.goal_unavailable").template
        if compacted:
            objective = objective[:_HISTORICAL_GOAL_EXCERPT]
        events = []
        for event in group.events:
            if isinstance(event, ActionHistoryEvent):
                events.append(prompts.render(f"{COMPLIANCE_PROMPT}.history_action",
                    action=_json(event.context(compacted=compacted))))
            else:
                submission = event.submission
                events.append(prompts.render(f"{COMPLIANCE_PROMPT}.history_answer", submission_id=submission.submission_id,
                    disposition=submission.disposition, delivered=_json(event.delivered), draft=submission.content))
                if submission.verdict is not None:
                    events.append(prompts.render("interaction_verification.history.judgment",
                        submission_id=submission.submission_id,
                        judgment=verification_judgment_text(submission.verdict, prompts=prompts)))
        groups.append(prompts.render(f"{COMPLIANCE_PROMPT}.history_goal",
            revision=group.goal.reference.revision if group.goal is not None else "—",
            objective=objective, events="\n\n".join(events)))
    body = prompts.render(f"{COMPLIANCE_PROMPT}.history_turn",
        user_turn=turn.number, goals="\n\n".join(groups))
    if compacted:
        body += "\n\n" + prompts.get(f"{COMPLIANCE_PROMPT}.history_compacted").template
    return body


def _render_history(turns: tuple[GoalComplianceTurn, ...], through: int, *, prompts: PromptCatalog) -> tuple[str, ...]:
    return tuple(_render_turn(turn, compacted=(turn.number <= through and turn.completed
                 and not turn.has_bound_dependency and turn is not turns[-1]), prompts=prompts)
                 for turn in turns if turn.goals)


def _capacity_measurement(request: StructuredModelRequest, measure_capacity: Callable) -> tuple[int, int, ModelCapacityRefused | None]:
    refusal = None
    try:
        check = measure_capacity(request)
    except ModelCapacityRefused as error:
        if error.reason_code != "context_capacity_exceeded" or error.check is None:
            raise
        check, refusal = error.check, error
    if check is None:
        return 0, 1, None
    return (check.estimated_input_tokens + check.output_reserve_tokens + check.protocol_reserve_tokens,
            check.context_window_tokens, refusal)


def _fit_history(turns: tuple[GoalComplianceTurn, ...], through: int, render: Callable[[int], StructuredModelRequest],
                 measure_capacity: Callable[[StructuredModelRequest], ModelCapacityCheck | None],
                 ) -> tuple[StructuredModelRequest, int]:
    request = render(through)
    size, window, refusal = _capacity_measurement(request, measure_capacity)
    candidates = tuple(turn for turn in turns[:-1] if turn.completed)[:-_RECENT_COMPLETE_TURNS]
    for turn in candidates:
        if size < window:
            break
        if turn.number <= through or turn.has_bound_dependency:
            continue
        candidate = render(turn.number)
        candidate_size, _, candidate_refusal = _capacity_measurement(candidate, measure_capacity)
        if candidate_size < size:
            request, through, size, refusal = candidate, turn.number, candidate_size, candidate_refusal
    if refusal is not None:
        raise refusal
    return request, through


def answer_goal_context(goal: CurrentAnalysisGoal | None, draft: str, sources: tuple[InteractionTrace, ...], *,
                        prompts: PromptCatalog,
                        measure_capacity: Callable[[StructuredModelRequest], ModelCapacityCheck | None],
                        ) -> tuple[GoalComplianceAnswerContext, int]:
    trace = sources[-1]
    events = verification_events(trace)
    if not events or events[-1].kind != "answer" or events[-1].content != draft or events[-1].disposition is None:
        raise ConversationOperationConflict("goal compliance requires the actual current answer")
    pending = events[-1]
    if pending.disposition == "answer":
        verified, unverified = pending.verified_goal, pending.unverified_goal
        objective = (verified.verified_draft if verified is not None else
                     unverified.content if unverified is not None else None)
        if (goal is None or goal.goal.objective != objective
                or trace.feature_flags_binding.goal_verification != (verified is not None)):
            raise ConversationOperationConflict("answer verification requires the goal bound to the submitted draft")
    turns = project_goal_compliance_history(sources, current=goal, pending_ids=frozenset(),
        input_refs=frozenset(), pending_answer_id=pending.submission_id, prompts=prompts)

    def context_at(through: int) -> GoalComplianceAnswerContext:
        return GoalComplianceAnswerContext(rounds=_render_history(turns, through, prompts=prompts),
            submission_id=pending.submission_id, disposition=pending.disposition)

    _, through = _fit_history(turns, max(source.goal_compliance_history_compacted_through for source in sources),
        lambda n: goal_compliance_answer_request(context_at(n), draft, prompts=prompts), measure_capacity)
    return context_at(through), through


def action_goal_request(goal: CurrentAnalysisGoal, batch: tuple[PendingPythonReview, ...],
                        sources: tuple[InteractionTrace, ...], *, prompts: PromptCatalog,
                        artifacts: InteractionArtifactPort | None = None,
                        measure_capacity: Callable[[StructuredModelRequest], ModelCapacityCheck | None],
                        ) -> PreparedActionGoalRequest:
    prompt = prompts.get(ACTION_GOAL_PROMPT)
    refs = frozenset(ref for item in batch for ref in item.binding.input_refs)
    metadata = {item.resource.resource_ref: item.resource for source in sources for item in source.inputs
                if isinstance(item, ArtifactSourceInput) and item.resource.resource_ref in refs}
    actions = []
    source_budget = PROGRAM_MAX_BYTES
    for slot, pending in enumerate(batch, start=1):
        files = []
        for binding, ref in zip(pending.arguments.input_files, pending.binding.input_refs, strict=True):
            file = {"name": binding.name, "resource_id": ref.resource_id, "revision": ref.revision}
            resource = metadata.get(ref)
            if resource is not None:
                file.update(filename=resource.filename, content_type=resource.content_type)
            if binding.name.lower().endswith(".py"):
                if artifacts is None:
                    file["source_status"] = "unavailable"
                else:
                    try:
                        if resource is None:
                            resource = artifacts.resource_item(ref, principal=ref.owner, owner=ref.owner)
                        if resource.size_bytes > source_budget:
                            file["source_status"] = "over_budget"
                        else:
                            source_code = artifacts.read_text(ref, principal=ref.owner, owner=ref.owner)
                            source_budget -= resource.size_bytes
                            file["source_code"] = source_code
                    except (OSError, PermissionError, ValueError):
                        file["source_status"] = "unavailable"
            files.append(file)
        actions.append({"slot": f"a{slot}", "action_id": pending.binding.action_id, "tool_name": "execute_python",
                        "code": pending.arguments.code, "input_files": files})
    turns = project_goal_compliance_history(sources, current=goal, input_refs=refs, prompts=prompts,
                                          pending_ids=frozenset(item.binding.action_id for item in batch))
    output = create_model(
        "ActionGoalAssessment", __base__=ActionGoalAssessment,
        **{f"a{slot}": (ActionGoalDecision, ...) for slot in range(1, len(batch) + 1)},
    )

    pending_text = prompts.render(f"{ACTION_GOAL_PROMPT}.pending", actions=_json(actions))

    def render(through: int) -> StructuredModelRequest:
        rounds = _render_history(turns, through, prompts=prompts)
        messages = goal_compliance_messages(prompt.template,
            (*rounds[:-1], rounds[-1] + "\n\n" + pending_text), prompts=prompts)
        projection = sealed_context_projection_ref(purpose=GOAL_COMPLIANCE_OPERATION, messages=messages)
        return StructuredModelRequest(
            operation=GOAL_COMPLIANCE_OPERATION, version=prompt.version, messages=messages,
            output_type=output, output_transport="native_tool", max_tokens=16_384, temperature=0,
            context_projection_ref=projection, consumer_key=f"action:{prompt.version}:{projection}",
            metadata={"component": "interaction_verifier"},
        )

    request, through = _fit_history(turns, max(source.goal_compliance_history_compacted_through for source in sources),
                                   render, measure_capacity)
    return PreparedActionGoalRequest(request, through)


def bind_action_goal_assessment(batch: tuple[PendingPythonReview, ...],
                                assessment: ActionGoalAssessment) -> tuple[ActionGoalReview, ...]:
    reviews = []
    for slot, item in enumerate(batch, start=1):
        decision = getattr(assessment, f"a{slot}")
        reviews.append(ActionGoalReview(binding=item.binding, judgment=ActionGoalJudgment(
            action_id=item.binding.action_id, verdict=decision.verdict,
            feedback="" if decision.verdict == "no_conflict" else decision.feedback,
        )))
    return tuple(reviews)
