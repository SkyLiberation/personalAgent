"""Prepare and resolve goal proposals through the existing immutable draft tools."""
from copy import deepcopy

from personal_agent.application.artifacts.models import CreateArtifact
from personal_agent.capabilities.contracts.model import ModelActionDefinition
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.prompt_registry import PromptCatalog

from .artifact_sources import trace_goal_draft_refs
from .context_materialization import READ_ARTIFACT_CAPABILITY, SEARCH_ACTION_OUTPUT_CAPABILITY
from .goal_models import AnalysisGoal, CurrentAnalysisGoal, GoalMaintenanceInvocation, GoalOperationRecord
from .models import DecisionFeedback, InteractionTrace, ToolCallProposal
from .ports import InteractionArtifactPort
from .tool_requests import PATCH_ARTIFACT_ACTION


def goal_draft_refs(trace: InteractionTrace, current: CurrentAnalysisGoal | None) -> tuple[ResourceRef, ...]:
    """Derive descendants from accepted reads and draft receipts, never filenames."""
    if current is None:
        return ()
    return trace_goal_draft_refs(trace, base=current.reference)


def prepare_goal_draft(record: GoalOperationRecord, trace: InteractionTrace,
                       artifacts: InteractionArtifactPort | None, *,
                       prompts: PromptCatalog) -> GoalOperationRecord | DecisionFeedback:
    if artifacts is None or trace.principal is None:
        message = prompts.get("conversation.goal.draft_unavailable").template
    else:
        try:
            receipt = artifacts.write_draft(
                execution_scope=ExecutionScope(principal=trace.principal, execution_id=trace.interaction_run_ref,
                                               thread_id=trace.conversation_id, task_id=record.call_id),
                tool_call_id=record.call_id,
                request=CreateArtifact(operation="create", filename="goal-candidate.md",
                                       content_type="text/markdown", content=record.goal.objective),
                allowed_resource_refs=(),
            )
        except (ValueError, OSError) as error:
            detail = (error.strerror or type(error).__name__) if isinstance(error, OSError) else str(error)
            message = prompts.render("conversation.goal.draft_write_failed", detail=detail)
        else:
            return record.model_copy(update={"draft_ref": receipt.resource_ref})
    return DecisionFeedback(action_id=record.call_id, action_name="read_current_goal",
        reason_code="goal_draft_unavailable", message=message,
        required_repair=prompts.get("conversation.goal.repair_no_draft").template)


def resolve_goal_submission(invocation: GoalMaintenanceInvocation, trace: InteractionTrace,
                            current: CurrentAnalysisGoal | None,
                            artifacts: InteractionArtifactPort | None,
                            *, prompts: PromptCatalog) -> tuple[AnalysisGoal, ResourceRef | None]:
    args = invocation.arguments
    if args is None:
        if current is None:
            raise ValueError(prompts.render("conversation.goal.retain_missing"))
        return current.goal, None
    if isinstance(args, AnalysisGoal):
        if current is not None:
            raise ValueError(prompts.render("conversation.goal.draft_reference_required"))
        return args, None
    matches = [ref for ref in goal_draft_refs(trace, current) if ref.resource_id == args.resource_id]
    if len(matches) != 1 or artifacts is None or trace.principal is None:
        raise ValueError(prompts.render("conversation.goal.draft_reference_invalid"))
    ref = matches[0]
    snapshot = artifacts.read_snapshot(ref, principal=trace.principal, owner=trace.principal)
    scope = snapshot.record.execution_scope
    if (snapshot.record.purpose != "draft" or scope is None
            or scope.execution_id != trace.interaction_run_ref or scope.thread_id != trace.conversation_id
            or snapshot.record.content_type != "text/markdown"):
        raise ValueError(prompts.render("conversation.goal.draft_reference_invalid"))
    return AnalysisGoal(objective=snapshot.content), ref


def goal_draft_action_allowed(action: ToolCallProposal, refs: tuple[ResourceRef, ...]) -> bool:
    allowed = {ref.resource_id for ref in refs}
    if action.tool_name in {READ_ARTIFACT_CAPABILITY, SEARCH_ACTION_OUTPUT_CAPABILITY}:
        return action.arguments.get("resource_id") in allowed
    if action.tool_name == "write_artifact":
        request = action.arguments.get("request")
        return (isinstance(request, dict) and request.get("operation") == "patch"
                and request.get("base_resource_id") in allowed)
    return False


def goal_draft_action_definitions(definitions: tuple[ModelActionDefinition, ...],
                                 refs: tuple[ResourceRef, ...]) -> tuple[ModelActionDefinition, ...]:
    """Narrow the existing tools to the same exact draft set used by admission."""
    ids = [ref.resource_id for ref in refs]
    if not ids:
        return ()
    result = []
    for definition in definitions:
        schema = deepcopy(definition.input_schema)
        if definition.target_name in {READ_ARTIFACT_CAPABILITY, SEARCH_ACTION_OUTPUT_CAPABILITY}:
            schema["properties"]["resource_id"]["enum"] = ids
        elif definition.name == PATCH_ARTIFACT_ACTION:
            schema["properties"]["base_resource_id"]["enum"] = ids
        else:
            continue
        result.append(definition.model_copy(update={"input_schema": schema}))
    return tuple(result)
