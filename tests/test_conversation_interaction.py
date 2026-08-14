from __future__ import annotations

from hashlib import sha256
import json
from threading import Barrier

import pytest
from langchain_core.tools import StructuredTool

from personal_agent.agents import AgentGateway, InMemoryAgentRunStore
from personal_agent.application.conversation import (
    AgentDelegationProposal,
    AgentTurnDecision,
    AgentTurnDecisionWithPlan,
    ContinueTurnProposal,
    ConversationMessage,
    ConversationWorkingPlan,
    ConversationWorkingPlanStep,
    ConversationOperationNotFound,
    ConversationService,
    FileInteractionJournal,
    FinalMessage,
    InMemoryInteractionJournal,
    LoopBudgetPolicy,
    ReviewIntent,
    ReviewRequirement,
    ToolCallProposal,
    WorkingPlanProposal,
    WorkingPlanStepProposal,
)
from personal_agent.application.conversation.models import (
    ActionObservation,
    CommittedUsage,
    ConversationProjectSnapshot,
    DecisionFeedback,
    EffectiveCapabilities,
    ProjectReference,
    ReviewCriteria,
    PersonalKnowledgeCandidate,
    PersonalKnowledgeEvidenceSnapshot,
    InvestigationRequirementProgress,
    InvestigationSubgoalProgress,
    InteractionTrace,
)
from personal_agent.application.conversation.working_plan import (
    admit_action_plan_bindings,
    admit_final_plan_resolution,
    admit_working_plan,
)
from personal_agent.application.conversation.interaction_prompt import (
    build_interaction_system_prompt,
)
from personal_agent.application.knowledge_lifecycle.models import (
    KnowledgeDeleteCommand,
    KnowledgeDeleteOperationView,
)
from personal_agent.application.conversation.review_admission import (
    admit_review_intent,
    ungrounded_criteria_feedback,
)
from personal_agent.application.conversation.verification_admission import (
    observed_receipts,
)
from personal_agent.capabilities.contracts.model import (
    StructuredModelResponse,
    sealed_context_projection_ref,
)
from personal_agent.governance import ToolExecutor
from personal_agent.governance.policy import PolicyEngine
from personal_agent.application.knowledge import (
    InMemoryKnowledgeStore,
    KnowledgeService,
)
from personal_agent.kernel.contracts.agent import (
    AgentArtifact,
    AgentGatewayContext,
    AgentGovernance,
    AgentTask,
    ChildAgentArtifactIndex,
    ChildAgentRunDefinition,
    ChildAgentRunEvent,
    ChildAgentRunOutcome,
    ChildAgentRunProjection,
    ChildAgentRunRecord,
    SubagentProfile,
    new_agent_event_id,
    new_agent_run_id,
)
from personal_agent.kernel.llm_schemas import strictify_schema
from personal_agent.tools.interaction_verifier import (
    build_verify_interaction_draft_tool,
)
from personal_agent.kernel.contracts.scope import (
    ExecutionScope,
    AuthenticatedPrincipal,
)
from personal_agent.application.conversation.observation_bounds import (
    MAX_OBSERVATION_PAYLOAD_CHARS,
    serialized_length,
)
from personal_agent.application.conversation.context_materialization import (
    materialize_interaction_inputs,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.tools.base import governance_extras, tool_response, tool_success


class _Decisions:
    """Scripted decision turns, plus the runtime's own review-criteria derivation.

    ``review_intent`` answers the runtime-owned derivation call. Its default says
    "not a review request", which is what keeps every ordinary-path test free of
    verification setup it does not exercise.
    """

    def __init__(self, *items, review_intent: ReviewIntent | None = None) -> None:
        self.items = list(items)
        self.requests = []
        self.review_intent = review_intent or ReviewIntent(requires_review=False)
        self.decision_requests = []

    def generate(self, request):
        self.requests.append(request)
        if request.operation == "interaction_review_criteria":
            return self._response(self.review_intent)
        self.decision_requests.append(request)
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        if request.operation == "interaction_completion_answer":
            return self._response(item)
        return self._response(AgentTurnDecision(decision=item))

    @staticmethod
    def _response(value):
        return StructuredModelResponse(
            value=value,
            model="contract-model",
            latency_ms=1,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )


def test_agent_turn_decision_uses_supported_object_root_schema():
    schema = strictify_schema(AgentTurnDecision.model_json_schema())

    assert schema["type"] == "object"
    assert schema["required"] == ["decision"]
    assert "anyOf" in schema["properties"]["decision"]
    assert schema["properties"]["decision"]["anyOf"][0]["$ref"].endswith(
        "/ContinueTurnProposal"
    )

    plan_schema = strictify_schema(AgentTurnDecisionWithPlan.model_json_schema())
    assert plan_schema["properties"]["decision"]["anyOf"][0]["$ref"].endswith(
        "/FinalMessage"
    )

    def contains_one_of(node) -> bool:
        if isinstance(node, dict):
            return "oneOf" in node or any(
                contains_one_of(value) for value in node.values()
            )
        if isinstance(node, list):
            return any(contains_one_of(value) for value in node)
        return False

    assert contains_one_of(schema) is False


def test_working_plan_proposal_excludes_runtime_identity_and_revision():
    assert set(WorkingPlanProposal.model_fields) == {"goal", "steps"}
    assert set(WorkingPlanStepProposal.model_fields) == {
        "step_id",
        "description",
        "status",
    }
    assert set(FinalMessage.model_fields) == {
        "kind",
        "disposition",
        "message",
        "resolved_plan_step_ids",
    }


def test_continue_turn_can_handoff_an_all_completed_plan_to_completion_phase():
    completed = WorkingPlanProposal(
        goal="Finish the current goal",
        steps=(
            WorkingPlanStepProposal(
                step_id="inspect",
                description="Inspect the evidence",
                status="completed",
            ),
            WorkingPlanStepProposal(
                step_id="answer",
                description="Answer the user",
                status="completed",
            ),
        ),
    )

    proposal = ContinueTurnProposal(working_plan=completed)

    assert all(step.status == "completed" for step in proposal.working_plan.steps)


def test_interaction_prompt_matches_the_object_root_wire_contract():
    prompt = build_interaction_system_prompt(
        EffectiveCapabilities(),
        CommittedUsage(),
    )

    assert "revision" not in EffectiveCapabilities.model_fields
    assert '"revision":' not in prompt
    assert '{"decision": <FinalMessage | ContinueTurnProposal>}' in prompt
    assert (
        "Never place kind, type, actions, disposition, or message at the root" in prompt
    )
    assert '"disposition": "answer|clarification_required|limitation|failed"' in prompt
    assert '"kind": "continue_turn"' in prompt


def test_interaction_prompt_hides_runtime_plan_identity_and_revision():
    working_plan = ConversationWorkingPlan(
        plan_id="wplan-internal",
        revision=7,
        goal="Organize knowledge",
        steps=(
            ConversationWorkingPlanStep(
                step_id="inspect",
                description="Inspect recent knowledge",
                status="completed",
                completion_action_ids=("read-1",),
            ),
            ConversationWorkingPlanStep(
                step_id="answer",
                description="Answer from the evidence",
                status="pending",
            ),
        ),
    )

    prompt = build_interaction_system_prompt(
        EffectiveCapabilities(),
        CommittedUsage(),
        working_plan=working_plan,
    )

    assert "wplan-internal" not in prompt
    assert '"revision"' not in prompt
    assert "completion_action_ids" not in prompt
    assert "read-1" not in prompt
    assert '"goal":"Organize knowledge"' in prompt


def test_interaction_prompt_separates_default_review_from_explicit_auto_execution():
    prompt = build_interaction_system_prompt(
        EffectiveCapabilities(),
        CommittedUsage(),
    )

    assert "proactively propose working_plan" in prompt.lower()
    assert "verifiable work result" in prompt
    assert "A bare activity such as searching" in prompt
    assert "Result: ...; Complete when: ..." in prompt
    assert "结果：……；完成条件：……" in prompt
    assert "Keep the initial plan short-horizon" in prompt
    assert "several actions or Tool calls" in prompt
    assert "proactively create a formal plan" in prompt
    assert "wait_for_user true and no actions" in prompt
    assert "caller-selected auto interaction mode" in prompt
    assert "An agent-initiated plan does not require approval" not in prompt
    assert "must use wait_for_user true and contain no actions" in prompt

    auto_prompt = build_interaction_system_prompt(
        EffectiveCapabilities(),
        CommittedUsage(),
        interaction_mode="auto",
    )
    assert "caller selected auto interaction mode" in auto_prompt
    assert "must use wait_for_user true and contain no actions" not in auto_prompt
    assert "A bare request to continue refers to the current" in prompt
    assert "Without a current plan or another committed continuation contract" in prompt


def test_prompt_never_asks_the_model_to_run_or_reference_verification():
    """The invariant is the runtime's, so the prompt must not delegate it.

    Wording that tells the model to call a verifier is what the previous design
    relied on, and is exactly the probabilistic enforcement this change removes.
    Its absence is asserted so it cannot drift back in as a "helpful" hint.
    """
    prompt = build_interaction_system_prompt(
        EffectiveCapabilities(),
        CommittedUsage(),
        ReviewCriteria(criteria=("no unverifiable occurrence claims",)),
    )

    assert "no unverifiable occurrence claims" in prompt
    assert "verify_interaction_draft" not in prompt
    assert "verified_final_message" not in prompt
    assert "receipt" not in prompt.lower()


def test_prompt_requires_exact_preservation_of_cited_opaque_values():
    prompt = build_interaction_system_prompt(
        EffectiveCapabilities(),
        CommittedUsage(),
    )

    assert "Preserve opaque identifiers, dates, quantities, version strings" in prompt
    assert "must not erase them" in prompt


def _tool(name, function, *, side_effects=("none",), emits_verified_artifact=False):
    return StructuredTool.from_function(
        func=function,
        name=name,
        description=f"Contract tool {name}",
        response_format="content_and_artifact",
        extras=governance_extras(
            side_effects=side_effects,
            permission_scope=f"test:{name}",
            timeout_seconds=5,
            emits_verified_artifact=emits_verified_artifact,
        ),
    )


def _executor(*tools):
    executor = ToolExecutor(policy_engine=PolicyEngine())
    for item in tools:
        executor.register(item)
    return executor


def _continue(*actions):
    return ContinueTurnProposal(actions=actions)


def _plan(*steps, goal="Organize the saved knowledge"):
    return WorkingPlanProposal(
        goal=goal,
        steps=tuple(
            WorkingPlanStepProposal(step_id=step_id, description=description)
            for step_id, description in steps
        ),
    )


def _conversation_scope():
    return {
        "principal": AuthenticatedPrincipal(
            tenant_id="tenant-1",
            user_id="default",
        ),
    }


def _trace(service: ConversationService, interaction_run_ref: str):
    return service.trace(
        interaction_run_ref,
        principal=_conversation_scope()["principal"],
    )


def test_l01_observation_drives_next_react_decision_and_user_result():
    def read_fact(query: str):
        return tool_response(tool_success({"fact": f"observed:{query}"}))

    model = _Decisions(
        _continue(
            ToolCallProposal(
                action_id="read-1", tool_name="read_fact", arguments={"query": "Orion"}
            )
        ),
        FinalMessage(
            disposition="answer", message="Orion fact is grounded in the observation."
        ),
    )
    service = ConversationService(
        model, tool_port=_executor(_tool("read_fact", read_fact))
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-l01",
        interaction_run_ref="irun_l01",
        messages=[
            ConversationMessage(
                role="user", content="Read the Orion fact, then answer."
            )
        ],
    )
    trace = _trace(service, "irun_l01")

    assert result.disposition == "answer"
    assert trace is not None
    assert trace.inputs[0].kind == "tool_result"
    assert trace.inputs[0].payload["data"]["fact"] == "observed:Orion"
    next_turn_context = "\n".join(
        message["content"] for message in model.decision_requests[1].messages
    )
    assert "Typed execution inputs" in next_turn_context
    assert "Current Conversation working plan:" not in next_turn_context
    assert trace.final_message is not None


def test_user_requested_working_plan_is_committed_and_visible_without_project():
    model = _Decisions(
        ContinueTurnProposal(
            working_plan=_plan(
                ("inspect", "Inspect recent saved knowledge"),
                ("summarize", "Summarize the main themes"),
            ),
            wait_for_user=True,
            message="Review these remaining steps before I continue.",
        )
    )
    service = ConversationService(model)

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-working-plan",
        interaction_run_ref="irun_working_plan",
        messages=[
            ConversationMessage(
                role="user",
                content="Show me the remaining steps and wait for my revision.",
            )
        ],
    )
    trace = _trace(service, "irun_working_plan")

    assert result.disposition == "plan_ready"
    assert result.working_plan is not None
    assert result.working_plan.revision == 1
    assert result.project_reference is None
    assert trace is not None
    assert trace.working_plan == result.working_plan


def test_default_mode_rejects_a_new_plan_that_skips_user_review():
    plan = _plan(
        ("inspect", "Inspect recent saved knowledge"),
        ("summarize", "Summarize the main themes"),
    )
    model = _Decisions(
        ContinueTurnProposal(working_plan=plan, wait_for_user=False),
        ContinueTurnProposal(working_plan=plan, wait_for_user=True),
    )
    service = ConversationService(model)

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-default-plan-review",
        interaction_run_ref="irun_default_plan_review",
        messages=[ConversationMessage(role="user", content="Analyze my saved knowledge.")],
    )
    trace = _trace(service, "irun_default_plan_review")

    assert result.disposition == "plan_ready"
    assert trace is not None
    assert any(
        item.reason_code == "working_plan_review_required"
        for item in trace.inputs
        if isinstance(item, DecisionFeedback)
    )
    assert len(model.decision_requests) == 2


def test_default_mode_rejects_a_formal_plan_added_after_execution_started():
    def read_fact(query: str):
        return tool_response(tool_success({"fact": f"observed:{query}"}))

    model = _Decisions(
        ContinueTurnProposal(actions=(
            ToolCallProposal(
                action_id="read-before-plan",
                tool_name="read_fact",
                arguments={"query": "Orion"},
            ),
        )),
        ContinueTurnProposal(
            working_plan=_plan(
                ("inspect", "Inspect the Orion fact"),
                ("answer", "Answer from the observed fact"),
            ),
            wait_for_user=True,
        ),
        FinalMessage(disposition="answer", message="Orion was observed."),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_fact", read_fact)),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-late-plan-review",
        interaction_run_ref="irun_late_plan_review",
        messages=[ConversationMessage(role="user", content="Read and explain Orion.")],
    )
    trace = _trace(service, "irun_late_plan_review")

    assert result.disposition == "answer"
    assert result.working_plan is None
    assert trace is not None
    assert trace.execution_order == ("read-before-plan",)
    assert any(
        item.reason_code == "working_plan_review_too_late"
        for item in trace.inputs
        if isinstance(item, DecisionFeedback)
    )


def test_waiting_plan_with_actions_is_repaired_before_any_action_executes():
    plan = _plan(
        ("inspect", "Inspect recent saved knowledge"),
        ("summarize", "Summarize the main themes"),
    )
    action = ToolCallProposal(
        action_id="read-during-review",
        tool_name="read_fact",
        arguments={"query": "Orion"},
        plan_step_id="inspect",
    )
    model = _Decisions(
        ContinueTurnProposal(
            working_plan=plan,
            actions=(action,),
            wait_for_user=True,
        ),
        ContinueTurnProposal(working_plan=plan, wait_for_user=True),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool(
            "read_fact",
            lambda query: tool_response(tool_success({"fact": query})),
        )),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-wait-actions-repair",
        interaction_run_ref="irun_wait_actions_repair",
        messages=[ConversationMessage(role="user", content="Analyze my knowledge.")],
    )
    trace = _trace(service, "irun_wait_actions_repair")

    assert result.disposition == "plan_ready"
    assert trace is not None
    assert trace.execution_order == ()
    assert any(
        item.reason_code == "waiting_plan_has_actions"
        for item in trace.inputs
        if isinstance(item, DecisionFeedback)
    )


def test_working_plan_update_preserves_completed_steps_from_current_plan():
    current = ConversationWorkingPlan(
        plan_id="wplan-1",
        revision=2,
        goal="Organize knowledge",
        steps=(
            ConversationWorkingPlanStep(
                step_id="inspect",
                description="Inspect recent saved knowledge",
                status="completed",
                completion_action_ids=("read-1",),
            ),
            ConversationWorkingPlanStep(
                step_id="summarize",
                description="Summarize the main themes",
                status="pending",
            ),
        ),
    )
    inputs = (
        ActionObservation(
            kind="tool_result",
            action_id="read-1",
            capability_id="read_recent",
            status="succeeded",
            payload={},
            plan_step_id="inspect",
        ),
    )
    rewritten = WorkingPlanProposal(
        goal=current.goal,
        steps=(
            WorkingPlanStepProposal(
                step_id="inspect",
                description="Inspect everything again",
                status="completed",
            ),
            WorkingPlanStepProposal(
                step_id="summarize",
                description="Summarize the main themes",
            ),
        ),
    )
    feedback, admitted = admit_working_plan(
        rewritten,
        current=current,
        inputs=inputs,
    )
    assert admitted is None
    assert feedback.reason_code == "completed_plan_step_immutable"


def test_plan_update_preserves_prior_completed_evidence_without_replaying_observation():
    current = ConversationWorkingPlan(
        plan_id="wplan-1",
        revision=2,
        goal="Organize knowledge and identify gaps",
        steps=(
            ConversationWorkingPlanStep(
                step_id="inspect",
                description="Inspect recent saved knowledge",
                status="completed",
                completion_action_ids=("context-personal-knowledge",),
            ),
            ConversationWorkingPlanStep(
                step_id="analyze",
                description="Identify knowledge gaps",
                status="pending",
            ),
        ),
    )
    update = WorkingPlanProposal(
        goal="Organize knowledge and identify conflicts",
        steps=(
            WorkingPlanStepProposal(
                step_id=current.steps[0].step_id,
                description=current.steps[0].description,
                status=current.steps[0].status,
            ),
            WorkingPlanStepProposal(
                step_id="analyze",
                description="Identify conflicting records",
            ),
        ),
    )

    feedback, admitted = admit_working_plan(
        update,
        current=current,
        inputs=(),
    )

    assert feedback is None
    assert admitted.steps[0] == current.steps[0]
    assert admitted.revision == 3


def test_plan_update_rejects_goal_text_from_a_replaced_pending_obligation():
    current = ConversationWorkingPlan(
        plan_id="wplan-1",
        revision=1,
        goal="Inspect recent knowledge, identify gaps, and recommend next steps",
        steps=(
            ConversationWorkingPlanStep(
                step_id="inspect",
                description="Inspect recent knowledge",
                status="pending",
            ),
            ConversationWorkingPlanStep(
                step_id="analyze",
                description="identify gaps",
                status="pending",
            ),
        ),
    )
    stale = WorkingPlanProposal(
        goal=current.goal,
        steps=(
            WorkingPlanStepProposal(
                step_id="inspect",
                description="Inspect recent knowledge",
            ),
            WorkingPlanStepProposal(
                step_id="analyze",
                description="identify conflicting records",
            ),
        ),
    )

    feedback, admitted = admit_working_plan(
        stale,
        current=current,
        inputs=(),
    )

    assert admitted is None
    assert feedback.reason_code == "working_plan_goal_stale"


def test_identical_working_plan_is_rejected_as_no_op():
    current = ConversationWorkingPlan(
        plan_id="wplan-1",
        revision=3,
        goal="Organize knowledge",
        steps=(
            ConversationWorkingPlanStep(
                step_id="inspect",
                description="Inspect recent saved knowledge",
                status="completed",
                completion_action_ids=("context-personal-knowledge",),
            ),
            ConversationWorkingPlanStep(
                step_id="summarize",
                description="Summarize the main themes",
                status="completed",
            ),
        ),
    )
    proposal = WorkingPlanProposal(
        goal=current.goal,
        steps=tuple(
            WorkingPlanStepProposal(
                step_id=step.step_id,
                description=step.description,
                status=step.status,
            )
            for step in current.steps
        ),
    )

    feedback, admitted = admit_working_plan(
        proposal,
        current=current,
        inputs=(
            ActionObservation(
                kind="context_evidence",
                action_id="context-personal-knowledge",
                capability_id="personal_knowledge_context",
                status="succeeded",
                payload={},
            ),
        ),
    )

    assert admitted is None
    assert feedback.reason_code == "working_plan_no_change"


def test_runtime_derives_completion_evidence_from_bound_observation():
    proposal = WorkingPlanProposal(
        goal="Organize knowledge",
        steps=(
            WorkingPlanStepProposal(
                step_id="inspect",
                description="Inspect recent saved knowledge",
                status="completed",
            ),
            WorkingPlanStepProposal(
                step_id="summarize",
                description="Summarize the main themes",
            ),
        ),
    )

    observation = ActionObservation(
        kind="tool_result",
        action_id="read-1",
        capability_id="read_recent",
        status="succeeded",
        payload={},
        plan_step_id="inspect",
    )

    feedback, admitted = admit_working_plan(
        proposal,
        current=None,
        inputs=(observation,),
    )

    assert feedback is None
    assert admitted.steps[0].completion_action_ids == ("read-1",)


def test_successful_context_evidence_can_support_semantic_plan_completion():
    proposal = WorkingPlanProposal(
        goal="Organize knowledge",
        steps=(
            WorkingPlanStepProposal(
                step_id="inspect",
                description="Inspect recent saved knowledge",
                status="completed",
            ),
            WorkingPlanStepProposal(
                step_id="summarize",
                description="Summarize the main themes",
            ),
        ),
    )
    context = ActionObservation(
        kind="context_evidence",
        action_id="context-personal-knowledge",
        capability_id="personal_knowledge_context",
        status="succeeded",
        payload={"citations": []},
    )

    feedback, admitted = admit_working_plan(
        proposal,
        current=None,
        inputs=(context,),
    )

    assert feedback is None
    assert admitted.steps[0].status == "completed"
    assert admitted.steps[0].completion_action_ids == ()


def test_actions_bind_to_pending_working_plan_steps():
    plan = ConversationWorkingPlan(
        plan_id="wplan-1",
        revision=1,
        goal="Organize knowledge",
        steps=(
            ConversationWorkingPlanStep(
                step_id="inspect",
                description="Inspect recent saved knowledge",
                status="pending",
            ),
            ConversationWorkingPlanStep(
                step_id="summarize",
                description="Summarize the main themes",
                status="pending",
            ),
        ),
    )
    unbound = ToolCallProposal(
        action_id="read-1",
        tool_name="read_recent",
        arguments={},
    )
    feedback = admit_action_plan_bindings(
        (unbound,),
        working_plan=plan,
    )
    assert feedback.reason_code == "plan_step_binding_required"

    bound = unbound.model_copy(update={"plan_step_id": "inspect"})
    assert (
        admit_action_plan_bindings(
            (bound,),
            working_plan=plan,
        )
        is None
    )


def test_bound_observation_does_not_block_a_follow_up_action_for_the_same_pending_result():
    plan = ConversationWorkingPlan(
        plan_id="wplan-1",
        revision=1,
        goal="Organize knowledge",
        steps=(
            ConversationWorkingPlanStep(
                step_id="inspect",
                description="Inspect recent saved knowledge",
                status="pending",
            ),
            ConversationWorkingPlanStep(
                step_id="summarize",
                description="Summarize the main themes",
                status="pending",
            ),
        ),
    )
    feedback = admit_action_plan_bindings(
        (
            ToolCallProposal(
                action_id="read-2",
                tool_name="read_recent",
                arguments={},
                plan_step_id="inspect",
            ),
        ),
        working_plan=plan,
    )

    assert feedback is None


def test_final_answer_resolves_only_the_remaining_delivery_step():
    plan = ConversationWorkingPlan(
        plan_id="wplan-1",
        revision=2,
        goal="Compare the observed sources",
        steps=(
            ConversationWorkingPlanStep(
                step_id="sources",
                description="Establish the official sources",
                status="completed",
                completion_action_ids=("search-1",),
            ),
            ConversationWorkingPlanStep(
                step_id="answer",
                description="Deliver the comparison and recommendation",
                status="pending",
            ),
        ),
    )

    feedback, resolved = admit_final_plan_resolution(
        ("answer",),
        working_plan=plan,
        inputs=(
            ActionObservation(
                kind="tool_result",
                action_id="search-1",
                capability_id="web_search",
                status="succeeded",
                payload={},
                plan_step_id="sources",
            ),
        ),
    )

    assert feedback is None
    assert resolved.revision == 3
    assert all(step.status == "completed" for step in resolved.steps)
    assert resolved.steps[0].completion_action_ids == ("search-1",)


def test_final_answer_resolves_execution_steps_and_runtime_binds_their_evidence():
    plan = ConversationWorkingPlan(
        plan_id="wplan-1",
        revision=1,
        goal="Inspect and answer",
        steps=(
            ConversationWorkingPlanStep(
                step_id="inspect",
                description="Establish the observed fact",
                status="pending",
            ),
            ConversationWorkingPlanStep(
                step_id="answer",
                description="Deliver the answer",
                status="pending",
            ),
        ),
    )

    feedback, resolved = admit_final_plan_resolution(
        ("inspect", "answer"),
        working_plan=plan,
        inputs=(
            ActionObservation(
                kind="tool_result",
                action_id="read-1",
                capability_id="read_recent",
                status="succeeded",
                payload={},
                plan_step_id="inspect",
            ),
        ),
    )

    assert feedback is None
    assert resolved.revision == 2
    assert all(step.status == "completed" for step in resolved.steps)
    assert resolved.steps[0].completion_action_ids == ("read-1",)
    assert resolved.steps[1].completion_action_ids == ()


def test_executed_action_observation_keeps_its_working_plan_step_binding():
    def read_fact(query: str):
        return tool_response(tool_success({"fact": f"observed:{query}"}))

    model = _Decisions(
        ContinueTurnProposal(
            working_plan=_plan(
                ("inspect", "Inspect the Orion fact"),
                ("answer", "Answer from the observed fact"),
            ),
            actions=(
                ToolCallProposal(
                    action_id="read-1",
                    tool_name="read_fact",
                    arguments={"query": "Orion"},
                    plan_step_id="inspect",
                ),
            ),
        ),
        ContinueTurnProposal(
            working_plan=WorkingPlanProposal(
                goal="Organize the saved knowledge",
                steps=(
                    WorkingPlanStepProposal(
                        step_id="inspect",
                        description="Inspect the Orion fact",
                        status="completed",
                    ),
                    WorkingPlanStepProposal(
                        step_id="answer",
                        description="Answer from the observed fact",
                    ),
                ),
            ),
            wait_for_user=True,
        ),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_fact", read_fact)),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-plan-binding",
        interaction_run_ref="irun_plan_binding",
        messages=[ConversationMessage(role="user", content="Show and execute the plan.")],
        interaction_mode="auto",
    )
    trace = _trace(service, "irun_plan_binding")

    assert result.disposition == "plan_ready"
    assert trace.inputs[0].plan_step_id == "inspect"
    assert result.working_plan.steps[0].status == "completed"


def test_unchanged_plan_does_not_block_actions_bound_to_the_current_plan():
    def read_fact(query: str):
        return tool_response(tool_success({"fact": f"observed:{query}"}))

    plan = _plan(
        ("inspect", "Inspect the Orion fact"),
        ("answer", "Answer from the observed fact"),
    )
    model = _Decisions(
        ContinueTurnProposal(working_plan=plan, wait_for_user=True),
        ContinueTurnProposal(
            working_plan=plan,
            actions=(
                ToolCallProposal(
                    action_id="read-1",
                    tool_name="read_fact",
                    arguments={"query": "Orion"},
                    plan_step_id="inspect",
                ),
            ),
        ),
        ContinueTurnProposal(
            working_plan=WorkingPlanProposal(
                goal=plan.goal,
                steps=tuple(
                    step.model_copy(update={"status": "completed"})
                    for step in plan.steps
                ),
            ),
        ),
        FinalMessage(
            disposition="answer",
            message="Observed Orion.",
        ),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_fact", read_fact)),
    )
    first_messages = [ConversationMessage(role="user", content="Show the plan first.")]
    first = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-no-op-plan-action",
        interaction_run_ref="irun_no_op_plan_first",
        messages=first_messages,
    )
    messages = [
        *first_messages,
        first.message,
        ConversationMessage(role="user", content="Continue."),
    ]

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-no-op-plan-action",
        interaction_run_ref="irun_no_op_plan_second",
        messages=messages,
    )
    trace = _trace(service, "irun_no_op_plan_second")

    assert result.disposition == "answer"
    assert trace.execution_order == ("read-1",)
    assert trace.working_plan.revision == 2


def test_unchanged_pending_plan_does_not_bypass_completion():
    def read_fact(query: str):
        return tool_response(tool_success({"fact": f"observed:{query}"}))

    plan = _plan(
        ("inspect", "Inspect the Orion fact"),
        ("answer", "Answer from the observed fact"),
    )
    progressed = WorkingPlanProposal(
        goal=plan.goal,
        steps=(
            WorkingPlanStepProposal(
                step_id="inspect",
                description="Inspect the Orion fact",
                status="completed",
            ),
            WorkingPlanStepProposal(
                step_id="answer",
                description="Answer from the observed fact",
            ),
        ),
    )
    model = _Decisions(
        ContinueTurnProposal(working_plan=plan, wait_for_user=True),
        ContinueTurnProposal(
            working_plan=plan,
            actions=(
                ToolCallProposal(
                    action_id="read-1",
                    tool_name="read_fact",
                    arguments={"query": "Orion"},
                    plan_step_id="inspect",
                ),
            ),
        ),
        ContinueTurnProposal(working_plan=progressed),
        ContinueTurnProposal(working_plan=progressed),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_fact", read_fact)),
        budget_policy=LoopBudgetPolicy(max_model_turns=3),
    )
    first_messages = [ConversationMessage(role="user", content="Show the plan first.")]
    first = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-stalled-plan",
        interaction_run_ref="irun_stalled_plan_first",
        messages=first_messages,
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-stalled-plan",
        interaction_run_ref="irun_stalled_plan_second",
        messages=[
            *first_messages,
            first.message,
            ConversationMessage(role="user", content="Continue."),
        ],
    )
    trace = _trace(service, "irun_stalled_plan_second")

    assert result.disposition == "limitation"
    assert trace.execution_order == ("read-1",)
    assert any(step.status == "pending" for step in result.working_plan.steps)
    assert sum(
        isinstance(item, DecisionFeedback)
        and item.reason_code == "working_plan_no_change"
        for item in trace.inputs
    ) == 1
    assert not any(
        request.operation == "interaction_completion_answer"
        for request in model.requests
    )


def test_plan_proposed_after_execution_switches_to_answer_only_recovery():
    def read_fact(query: str):
        return tool_response(tool_success({"fact": f"observed:{query}"}))

    model = _Decisions(
        ContinueTurnProposal(actions=(
            ToolCallProposal(
                action_id="read-1",
                tool_name="read_fact",
                arguments={"query": "Orion"},
            ),
        )),
        ContinueTurnProposal(
            working_plan=_plan(
                ("inspect", "Inspect the Orion fact"),
                ("answer", "Answer from the observed fact"),
            ),
            wait_for_user=True,
        ),
        FinalMessage(disposition="answer", message="Observed Orion."),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_fact", read_fact)),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-late-plan",
        interaction_run_ref="irun_late_plan",
        messages=[ConversationMessage(role="user", content="Inspect and answer.")],
    )
    trace = _trace(service, "irun_late_plan")

    assert result.disposition == "answer"
    assert result.working_plan is None
    assert trace.execution_order == ("read-1",)
    assert any(
        isinstance(item, DecisionFeedback)
        and item.reason_code == "working_plan_review_too_late"
        for item in trace.inputs
    )
    assert any(
        request.operation == "interaction_completion_answer"
        for request in model.requests
    )


def test_completed_plan_update_enters_runtime_owned_completion_call():
    def read_fact(query: str):
        return tool_response(tool_success({"fact": f"observed:{query}"}))

    plan = _plan(
        ("inspect", "Inspect the Orion fact"),
        ("answer", "Answer from the observed fact"),
    )
    completed = WorkingPlanProposal(
        goal=plan.goal,
        steps=(
            WorkingPlanStepProposal(
                step_id="inspect",
                description="Inspect the Orion fact",
                status="completed",
            ),
            WorkingPlanStepProposal(
                step_id="answer",
                description="Answer from the observed fact",
                status="completed",
            ),
        ),
    )
    model = _Decisions(
        ContinueTurnProposal(working_plan=plan, wait_for_user=True),
        ContinueTurnProposal(
            actions=(
                ToolCallProposal(
                    action_id="read-1",
                    tool_name="read_fact",
                    arguments={"query": "Orion"},
                    plan_step_id="inspect",
                ),
            ),
        ),
        ContinueTurnProposal(working_plan=completed),
        FinalMessage(disposition="answer", message="Observed Orion."),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_fact", read_fact)),
        budget_policy=LoopBudgetPolicy(max_model_turns=2),
    )
    first_messages = [ConversationMessage(role="user", content="Show the plan first.")]
    first = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-terminal-plan",
        interaction_run_ref="irun-terminal-plan-first",
        messages=first_messages,
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-terminal-plan",
        interaction_run_ref="irun-terminal-plan-second",
        messages=[
            *first_messages,
            first.message,
            ConversationMessage(role="user", content="Continue and finish."),
        ],
    )
    trace = _trace(service, "irun-terminal-plan-second")

    assert result.disposition == "answer"
    assert result.working_plan.revision == 2
    assert all(step.status == "completed" for step in result.working_plan.steps)
    assert trace.execution_order == ("read-1",)
    completion_request = next(
        request
        for request in model.requests
        if request.operation == "interaction_completion_answer"
    )
    completion_prompt = "\n".join(
        message["content"] for message in completion_request.messages
    )
    assert '"revision"' not in completion_prompt
    assert '"plan_id"' not in completion_prompt
    assert "completion_action_ids" not in completion_prompt


def test_answer_cannot_silently_complete_a_pending_working_plan():
    plan = _plan(
        ("inspect", "Inspect recent knowledge"),
        ("answer", "Answer from the evidence"),
    )
    model = _Decisions(
        ContinueTurnProposal(working_plan=plan, wait_for_user=True),
        FinalMessage(disposition="answer", message="Completed answer."),
    )
    service = ConversationService(
        model,
        budget_policy=LoopBudgetPolicy(max_model_turns=1),
    )
    first_messages = [ConversationMessage(role="user", content="Show the plan first.")]
    first = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-pending-final",
        interaction_run_ref="irun-pending-final-first",
        messages=first_messages,
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-pending-final",
        interaction_run_ref="irun-pending-final-second",
        messages=[
            *first_messages,
            first.message,
            ConversationMessage(role="user", content="Finish it."),
        ],
    )
    trace = _trace(service, "irun-pending-final-second")

    assert result.disposition == "limitation"
    assert result.working_plan.revision == 1
    assert any(step.status == "pending" for step in result.working_plan.steps)
    assert any(
        isinstance(item, DecisionFeedback)
        and item.reason_code == "working_plan_incomplete"
        for item in trace.inputs
    )


def test_denied_duplicate_action_is_not_recorded_as_execution_fact():
    calls = 0

    def read_fact(query: str):
        nonlocal calls
        calls += 1
        return tool_response(tool_success({"fact": query}))

    action = ToolCallProposal(
        action_id="read-1",
        tool_name="read_fact",
        arguments={"query": "Orion"},
    )
    model = _Decisions(
        ContinueTurnProposal(actions=(action,)),
        ContinueTurnProposal(actions=(action,)),
        FinalMessage(disposition="answer", message="Observed Orion."),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_fact", read_fact)),
    )

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-duplicate-action",
        interaction_run_ref="irun-duplicate-action",
        messages=[ConversationMessage(role="user", content="Read Orion, then answer.")],
    )
    trace = _trace(service, "irun-duplicate-action")

    assert calls == 1
    assert trace.execution_order == ("read-1",)
    assert any(
        isinstance(item, DecisionFeedback)
        and item.reason_code == "duplicate_action_id"
        for item in trace.inputs
    )


def test_file_journal_restores_working_plan_for_a_new_service(temp_dir):
    journal_root = temp_dir / "working-plan-journal"
    plan = _plan(
        ("summarize", "Summarize the visible evidence"),
        ("recommend", "Recommend the next action"),
    )
    first_messages = [ConversationMessage(role="user", content="Show the plan first.")]
    first_service = ConversationService(
        _Decisions(ContinueTurnProposal(working_plan=plan, wait_for_user=True)),
        journal=FileInteractionJournal(journal_root),
    )
    first = first_service.respond(
        **_conversation_scope(),
        conversation_id="conversation-file-plan",
        interaction_run_ref="irun-file-plan-first",
        messages=first_messages,
    )

    second_service = ConversationService(
        _Decisions(
            ContinueTurnProposal(
                working_plan=WorkingPlanProposal(
                    goal=plan.goal,
                    steps=tuple(
                        step.model_copy(update={"status": "completed"})
                        for step in plan.steps
                    ),
                ),
            ),
            FinalMessage(
                disposition="answer",
                message="Recovered and completed.",
            )
        ),
        journal=FileInteractionJournal(journal_root),
    )
    result = second_service.respond(
        **_conversation_scope(),
        conversation_id="conversation-file-plan",
        interaction_run_ref="irun-file-plan-second",
        messages=[
            *first_messages,
            first.message,
            ConversationMessage(role="user", content="Continue after restart."),
        ],
    )

    assert result.disposition == "answer"
    assert result.working_plan.plan_id == first.working_plan.plan_id
    assert result.working_plan.revision == 2


def test_new_user_turn_reuses_successful_observations_bound_to_current_plan():
    principal = AuthenticatedPrincipal(
        tenant_id="tenant-plan-context",
        user_id="user-plan-context",
    )
    plan = ConversationWorkingPlan(
        plan_id="wplan-context",
        revision=1,
        goal="Deliver both exact results",
        steps=(
            ConversationWorkingPlanStep(
                step_id="alpha",
                description="Deliver the exact ALPHA result",
                status="pending",
            ),
            ConversationWorkingPlanStep(
                step_id="beta",
                description="Deliver the exact BETA result",
                status="pending",
            ),
        ),
    )
    journal = InMemoryInteractionJournal()
    journal.put(InteractionTrace(
        interaction_run_ref="irun-plan-context-first",
        conversation_id="conversation-plan-context",
        principal=principal,
        messages=(ConversationMessage(role="user", content="Read both results."),),
        inputs=(
            ActionObservation(
                kind="tool_result",
                action_id="read-alpha",
                capability_id="archive.read",
                status="succeeded",
                payload={"value": "alpha-exact-value"},
                plan_step_id="alpha",
            ),
            ActionObservation(
                kind="tool_result",
                action_id="read-beta",
                capability_id="archive.read",
                status="succeeded",
                payload={"value": "beta-exact-value"},
                plan_step_id="beta",
            ),
        ),
        final_message=FinalMessage(
            disposition="limitation",
            message="Continue from committed results.",
        ),
        working_plan=plan,
    ))
    model = _Decisions(FinalMessage(
        disposition="answer",
        message="alpha-exact-value; beta-exact-value",
        resolved_plan_step_ids=("alpha", "beta"),
    ))
    service = ConversationService(model, journal=journal)

    result = service.respond(
        conversation_id="conversation-plan-context",
        interaction_run_ref="irun-plan-context-second",
        messages=[ConversationMessage(role="user", content="Continue.")],
        principal=principal,
    )

    visible_request = json.dumps(
        model.decision_requests[0].messages,
        ensure_ascii=False,
    )
    assert "alpha-exact-value" in visible_request
    assert "beta-exact-value" in visible_request
    assert result.disposition == "answer"
    assert all(step.status == "completed" for step in result.working_plan.steps)


def test_working_plan_observation_projection_excludes_other_scope_and_failures():
    principal = AuthenticatedPrincipal(
        tenant_id="tenant-plan-projection",
        user_id="user-plan-projection",
    )
    plan = ConversationWorkingPlan(
        plan_id="wplan-projection",
        revision=1,
        goal="Deliver two results",
        steps=(
            ConversationWorkingPlanStep(
                step_id="first",
                description="First result",
                status="pending",
            ),
            ConversationWorkingPlanStep(
                step_id="second",
                description="Second result",
                status="pending",
            ),
        ),
    )
    journal = InMemoryInteractionJournal()
    journal.put(InteractionTrace(
        interaction_run_ref="irun-plan-projection",
        conversation_id="conversation-plan-projection",
        principal=principal,
        messages=(ConversationMessage(role="user", content="Read results."),),
        inputs=(
            ActionObservation(
                kind="tool_result",
                action_id="accepted",
                capability_id="archive.read",
                status="succeeded",
                payload={"value": "accepted"},
                plan_step_id="first",
            ),
            ActionObservation(
                kind="tool_result",
                action_id="failed",
                capability_id="archive.read",
                status="failed",
                payload={"error": "failed"},
                plan_step_id="second",
            ),
            ActionObservation(
                kind="tool_result",
                action_id="unbound",
                capability_id="archive.read",
                status="succeeded",
                payload={"value": "unbound"},
            ),
        ),
        working_plan=plan,
    ))
    journal.put(InteractionTrace(
        interaction_run_ref="irun-plan-projection-other-scope",
        conversation_id="conversation-plan-projection",
        principal=AuthenticatedPrincipal(
            tenant_id="tenant-plan-projection",
            user_id="other-user",
        ),
        messages=(ConversationMessage(role="user", content="Read results."),),
        inputs=(ActionObservation(
            kind="tool_result",
            action_id="other-scope",
            capability_id="archive.read",
            status="succeeded",
            payload={"value": "other-scope"},
            plan_step_id="second",
        ),),
        working_plan=plan,
    ))

    projected = journal.working_plan_observations(
        "conversation-plan-projection",
        principal,
        plan,
    )

    assert tuple(item.action_id for item in projected) == ("accepted",)


def test_completed_working_plan_can_be_superseded_by_a_new_frontstage_goal():
    current = ConversationWorkingPlan(
        plan_id="wplan-completed",
        revision=3,
        goal="Finish the prior goal",
        steps=(
            ConversationWorkingPlanStep(
                step_id="inspect",
                description="Inspect prior evidence",
                status="completed",
            ),
            ConversationWorkingPlanStep(
                step_id="answer",
                description="Answer the prior goal",
                status="completed",
            ),
        ),
    )
    proposal = _plan(
        ("compare", "Compare the new alternatives"),
        ("recommend", "Recommend one alternative"),
        goal="Choose a new alternative",
    )

    feedback, admitted = admit_working_plan(
        proposal,
        current=current,
        inputs=(),
    )

    assert feedback is None
    assert admitted.plan_id != current.plan_id
    assert admitted.revision == 4
    assert admitted.goal == "Choose a new alternative"


def test_successful_tool_observation_does_not_auto_complete_a_plan_step():
    def read_fact(query: str):
        return tool_response(tool_success({"fact": query}))

    plan = _plan(
        ("inspect", "Inspect the Orion fact"),
        ("answer", "Answer from the observed fact"),
    )
    model = _Decisions(
        ContinueTurnProposal(working_plan=plan, wait_for_user=True),
        ContinueTurnProposal(
            actions=(
                ToolCallProposal(
                    action_id="read-1",
                    tool_name="read_fact",
                    arguments={"query": "Orion"},
                    plan_step_id="inspect",
                ),
            ),
        ),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_fact", read_fact)),
        budget_policy=LoopBudgetPolicy(max_model_turns=1),
    )
    first_messages = [ConversationMessage(role="user", content="Show the plan first.")]
    first = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-no-auto-complete",
        interaction_run_ref="irun-no-auto-complete-first",
        messages=first_messages,
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-no-auto-complete",
        interaction_run_ref="irun-no-auto-complete-second",
        messages=[
            *first_messages,
            first.message,
            ConversationMessage(role="user", content="Continue."),
        ],
    )

    assert result.disposition == "limitation"
    assert result.working_plan.steps[0].status == "pending"


def test_interaction_trace_read_and_resume_require_the_committed_principal(caplog):
    service = ConversationService(
        _Decisions(FinalMessage(disposition="answer", message="owner-only result"))
    )
    messages = [ConversationMessage(role="user", content="Return my private result.")]
    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-scope",
        interaction_run_ref="irun_scope",
        messages=messages,
    )
    other = AuthenticatedPrincipal(tenant_id="tenant-1", user_id="other")

    with pytest.raises(PermissionError, match="scope mismatch"):
        service.trace("irun_scope", principal=other)
    with pytest.raises(PermissionError, match="scope mismatch"):
        service.respond(
            principal=other,
            conversation_id="conversation-scope",
            interaction_run_ref="irun_scope",
            messages=messages,
        )

    assert "conversation_run_scope_mismatch" in caplog.text
    assert "owner-only result" not in caplog.text


def test_unscoped_legacy_interaction_snapshot_is_quarantined(temp_dir):
    journal_root = temp_dir / "unscoped-interaction"
    service = ConversationService(
        _Decisions(FinalMessage(disposition="answer", message="legacy result")),
        journal=FileInteractionJournal(journal_root),
    )
    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-legacy",
        interaction_run_ref="irun_legacy",
        messages=[
            ConversationMessage(role="user", content="Return the legacy result.")
        ],
    )
    snapshot_path = sorted((journal_root / "irun_legacy").glob("*.json"))[-1]
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload.pop("principal")
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    restarted = ConversationService(
        None,
        journal=FileInteractionJournal(journal_root),
    )
    with pytest.raises(ConversationOperationNotFound, match="no trustworthy owner"):
        _trace(restarted, "irun_legacy")


def test_context_materialization_keeps_reread_ref_without_repeating_lossy_excerpt():
    resource_ref = ResourceRef(
        resource_id="gen_0",
        resource_type="artifact",
        owner=AuthenticatedPrincipal(tenant_id="tenant-1", user_id="default"),
        revision=1,
    )
    observation = ActionObservation(
        kind="tool_result",
        action_id="read-big",
        capability_id="read_big",
        status="succeeded",
        payload={
            "ok": True,
            "content": "lossy excerpt" * 1_000,
            "retrieval": {
                "omitted_chars": 50_000,
                "original_chars": 70_000,
                "resource_ref": resource_ref.model_dump(mode="json"),
                "read_more": "Call read_action_output.",
            },
        },
    )

    materialized = materialize_interaction_inputs((observation,))

    assert observation.payload["content"].startswith("lossy excerpt")
    assert "content" not in materialized[0].payload
    assert materialized[0].payload["observation_excerpt_removed"] is True
    assert materialized[0].payload["retrieval"][
        "resource_ref"
    ] == resource_ref.model_dump(mode="json")


def test_recorded_context_segments_account_for_the_input_that_was_sent():
    """The four segments must add up to the request, not to a re-derivation.

    A composition measured by recomputing its own sources would be a second
    algorithm for the same input, free to drift from what the model actually saw.
    Summing per turn against the recorded request is what keeps it a measurement.
    """

    def read_fact(query: str):
        return tool_response(tool_success({"fact": f"observed:{query}"}))

    model = _Decisions(
        _continue(
            ToolCallProposal(
                action_id="read-1", tool_name="read_fact", arguments={"query": "Orion"}
            )
        ),
        FinalMessage(
            disposition="answer", message="Orion fact is grounded in the observation."
        ),
    )
    service = ConversationService(
        model, tool_port=_executor(_tool("read_fact", read_fact))
    )

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-composition",
        interaction_run_ref="irun_composition",
        messages=[
            ConversationMessage(
                role="user", content="Read the Orion fact, then answer."
            )
        ],
    )
    trace = _trace(service, "irun_composition")

    assert trace is not None
    assert len(trace.context_composition) == len(model.decision_requests) == 2
    for turn_index, (composition, request) in enumerate(
        zip(trace.context_composition, model.decision_requests, strict=True)
    ):
        sent_chars = sum(len(message["content"]) for message in request.messages)
        assert composition.turn_index == turn_index
        assert composition.total_chars == sent_chars
        assert composition.capability_projection_chars > 0
        assert composition.input_tokens == 10
    # The observation only exists after the first turn, so the typed-input
    # segment separates the two turns instead of being a constant offset.
    assert trace.context_composition[0].typed_inputs_chars == 0
    assert trace.context_composition[1].typed_inputs_chars > 0


def test_measuring_the_context_does_not_change_the_sealed_input():
    """Observation must stay outside assembly, or it becomes part of the input.

    The seal covers every visible message, so recomputing it from the recorded
    request proves the measured turn sent exactly the messages it sealed, and
    that no measurement field was smuggled in as a visible message.
    """
    model = _Decisions(FinalMessage(disposition="answer", message="Answered directly."))
    service = ConversationService(model)

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-seal",
        interaction_run_ref="irun_seal",
        messages=[ConversationMessage(role="user", content="Say hello.")],
    )

    request = model.decision_requests[0]
    assert request.context_projection_ref == sealed_context_projection_ref(
        purpose="agent_interaction_turn",
        messages=request.messages,
    )
    # Measuring yielded a record without yielding a message: the turn sent the
    # minimum visible set, so nothing was appended for the benefit of the trace.
    assert [message["role"] for message in request.messages] == ["system", "user"]
    trace = _trace(service, "irun_seal")
    assert trace is not None
    assert len(trace.context_composition) == 1


def test_oversized_tool_observation_is_bounded_and_offloaded_for_re_read():
    late_fact = "linux-xfs@vger.kernel.org"

    def read_big(path: str):
        filler = "\n".join(f"line {index}" for index in range(200_000))
        return tool_response(tool_success({"content": f"{filler}\n{late_fact}\n"}))

    offloaded_ref = ResourceRef(
        resource_id="gen_0",
        resource_type="artifact",
        owner=AuthenticatedPrincipal(tenant_id="tenant-1", user_id="default"),
        revision=1,
    )
    model = _Decisions(
        _continue(
            ToolCallProposal(
                action_id="read-big",
                tool_name="read_big",
                arguments={"path": "MAINTAINERS"},
            )
        ),
        # The model supplies only the ref and the keyword; no identity argument
        # exists for it to assert.
        _continue(
            ToolCallProposal(
                action_id="reread",
                tool_name="read_action_output",
                arguments={
                    "resource_ref": offloaded_ref.model_dump(mode="json"),
                    "keyword": "xfs",
                },
            )
        ),
        FinalMessage(disposition="answer", message=f"The address is {late_fact}."),
    )
    artifacts = _ArtifactTexts()
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_big", read_big)),
        artifact_port=artifacts,
    )

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-oversized",
        interaction_run_ref="irun-oversized",
        messages=[
            ConversationMessage(
                role="user", content="Tell me the XFS list address in that file."
            )
        ],
    )
    trace = _trace(service, "irun-oversized")

    observation = trace.inputs[0]
    assert observation.kind == "tool_result"
    assert serialized_length(observation.payload) <= MAX_OBSERVATION_PAYLOAD_CHARS
    retrieval = observation.payload["retrieval"]
    assert retrieval["omitted_chars"] > 0
    assert retrieval["original_chars"] > MAX_OBSERVATION_PAYLOAD_CHARS
    assert "unavailable_reason" not in retrieval
    assert len(artifacts.written) == 1
    assert artifacts.written[0]["producer_key"] == "irun-oversized:read-big:observation"
    # The omitted fact is recovered through the loop, with the identity the loop
    # resolved: the model supplies only the ref and the keyword.
    reread = trace.inputs[1]
    assert reread.capability_id == "read_action_output"
    assert reread.status == "succeeded"
    assert any(late_fact in line["text"] for line in reread.payload["lines"])
    assert reread.payload["keyword_match_count"] >= 1


def test_refetching_a_tool_with_unread_offloaded_output_is_rejected_without_spending_budget():
    late_fact = "linux-xfs@vger.kernel.org"

    def read_big(path: str):
        filler = "\n".join(f"line {index}" for index in range(200_000))
        return tool_response(tool_success({"content": f"{filler}\n{late_fact}\n"}))

    offloaded_ref = ResourceRef(
        resource_id="gen_0",
        resource_type="artifact",
        owner=AuthenticatedPrincipal(tenant_id="tenant-1", user_id="default"),
        revision=1,
    )
    model = _Decisions(
        _continue(
            ToolCallProposal(
                action_id="read-big",
                tool_name="read_big",
                arguments={"path": "MAINTAINERS"},
            )
        ),
        _continue(
            ToolCallProposal(
                action_id="read-big-again",
                tool_name="read_big",
                arguments={"path": "MAINTAINERS"},
            )
        ),
        _continue(
            ToolCallProposal(
                action_id="reread",
                tool_name="read_action_output",
                arguments={
                    "resource_ref": offloaded_ref.model_dump(mode="json"),
                    "keyword": "xfs",
                },
            )
        ),
        FinalMessage(disposition="answer", message=f"The address is {late_fact}."),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_big", read_big)),
        artifact_port=_ArtifactTexts(),
    )

    view = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-refetch",
        interaction_run_ref="irun-refetch",
        messages=[ConversationMessage(role="user", content="Read the XFS address.")],
    )
    trace = _trace(service, "irun-refetch")

    assert view.disposition == "answer"
    feedback = [item for item in trace.inputs if isinstance(item, DecisionFeedback)]
    assert [item.reason_code for item in feedback] == ["offloaded_output_refetch"]
    assert "gen_0" in feedback[0].required_repair
    assert trace.usage.tool_calls == 2


def test_offload_failure_is_reported_in_the_observation_not_swallowed():
    def read_big(path: str):
        return tool_response(tool_success({"content": "q" * 500_000}))

    model = _Decisions(
        _continue(
            ToolCallProposal(
                action_id="read-big", tool_name="read_big", arguments={"path": "f"}
            )
        ),
        FinalMessage(disposition="answer", message="Bounded without the remainder."),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_big", read_big)),
        artifact_port=_ArtifactTexts(write_error=RuntimeError("store offline")),
    )

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-offload-fail",
        interaction_run_ref="irun-offload-fail",
        messages=[
            ConversationMessage(role="user", content="Read that file and answer.")
        ],
    )
    trace = _trace(service, "irun-offload-fail")

    retrieval = trace.inputs[0].payload["retrieval"]
    assert "resource_ref" not in retrieval
    assert "RuntimeError" in retrieval["unavailable_reason"]
    assert serialized_length(trace.inputs[0].payload) <= MAX_OBSERVATION_PAYLOAD_CHARS


def test_re_reading_another_principals_offloaded_output_is_denied():
    """A ref from another principal's run must not become a read of their output.

    The re-read is served with the identity the loop resolved, so a stolen or
    guessed ref fails the artifact's own principal check instead of leaking.
    """

    artifacts = _ArtifactTexts()
    scope = AuthenticatedPrincipal(tenant_id="tenant-1", user_id="someone-else")
    foreign_ref = artifacts.write_generated(
        owner=scope,
        execution_scope=ExecutionScope(
            principal=scope,
            execution_id="irun-foreign",
        ),
        producer_key="irun-foreign:act:observation",
        producer_ref="read_big",
        kind="action_output",
        content="another principal's private output",
        content_digest="d",
        source_artifact_refs=(),
        evidence_refs=(),
    )
    model = _Decisions(
        _continue(
            ToolCallProposal(
                action_id="steal",
                tool_name="read_action_output",
                arguments={
                    "resource_ref": foreign_ref.model_dump(mode="json"),
                    "keyword": "private",
                },
            )
        ),
        FinalMessage(
            disposition="limitation", message="That output is not available to me."
        ),
    )
    service = ConversationService(model, tool_port=_executor(), artifact_port=artifacts)

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-foreign",
        interaction_run_ref="irun-foreign-read",
        messages=[
            ConversationMessage(role="user", content="Show me that earlier output.")
        ],
    )
    trace = _trace(service, "irun-foreign-read")

    observation = trace.inputs[0]
    assert observation.status == "failed"
    assert observation.payload["ok"] is False
    assert "PermissionError" in observation.payload["error"]
    assert "private" not in json.dumps(observation.payload, ensure_ascii=False)


def test_asking_the_user_about_an_output_this_run_offloaded_is_rejected():
    """The user cannot answer a question about a file only this run has read.

    Observed live: a turn read an oversized file, then asked the user which branch
    of it to look at, while holding the read remainder. The exit is rejected; what
    the remainder says stays the model's call.
    """

    late_fact = "linux-xfs@vger.kernel.org"

    def read_big(path: str):
        filler = "\n".join(f"line {index}" for index in range(200_000))
        return tool_response(tool_success({"content": f"{filler}\n{late_fact}\n"}))

    offloaded_ref = ResourceRef(
        resource_id="gen_0",
        resource_type="artifact",
        owner=AuthenticatedPrincipal(tenant_id="tenant-1", user_id="default"),
        revision=1,
    )
    model = _Decisions(
        _continue(
            ToolCallProposal(
                action_id="read-big",
                tool_name="read_big",
                arguments={"path": "MAINTAINERS"},
            )
        ),
        FinalMessage(
            disposition="clarification_required",
            message="Which branch of MAINTAINERS did you mean?",
        ),
        _continue(
            ToolCallProposal(
                action_id="reread",
                tool_name="read_action_output",
                arguments={
                    "resource_ref": offloaded_ref.model_dump(mode="json"),
                    "keyword": "xfs",
                },
            )
        ),
        FinalMessage(disposition="answer", message=f"The address is {late_fact}."),
    )
    artifacts = _ArtifactTexts()
    service = ConversationService(
        model, tool_port=_executor(_tool("read_big", read_big)), artifact_port=artifacts
    )

    view = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-unread",
        interaction_run_ref="irun-unread",
        messages=[
            ConversationMessage(
                role="user", content="Tell me the XFS list address in that file."
            )
        ],
    )
    trace = _trace(service, "irun-unread")

    assert view.disposition == "answer"
    assert late_fact in view.message.content
    feedback = [item for item in trace.inputs if isinstance(item, DecisionFeedback)]
    assert [item.reason_code for item in feedback] == ["offloaded_output_unread"]
    assert feedback[0].repairable_fields == ("disposition", "message")
    assert "gen_0" in feedback[0].required_repair
    reread = trace.inputs[-1]
    assert reread.payload["resource_id"] == "gen_0"


def test_answer_about_an_unread_offloaded_output_is_rejected_until_reread():
    def read_big(path: str):
        filler = "\n".join(f"line {index}" for index in range(200_000))
        return tool_response(tool_success({"content": filler}))

    offloaded_ref = ResourceRef(
        resource_id="gen_0",
        resource_type="artifact",
        owner=AuthenticatedPrincipal(tenant_id="tenant-1", user_id="default"),
        revision=1,
    )
    model = _Decisions(
        _continue(
            ToolCallProposal(
                action_id="read-big",
                tool_name="read_big",
                arguments={"path": "f"},
            )
        ),
        FinalMessage(disposition="answer", message="The answer is line 100000."),
        _continue(
            ToolCallProposal(
                action_id="reread",
                tool_name="read_action_output",
                arguments={
                    "resource_ref": offloaded_ref.model_dump(mode="json"),
                    "start_line": 100000,
                },
            )
        ),
        FinalMessage(disposition="answer", message="The answer is line 100000."),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_big", read_big)),
        artifact_port=_ArtifactTexts(),
    )

    view = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-unread-answer",
        interaction_run_ref="irun-unread-answer",
        messages=[ConversationMessage(role="user", content="Read line 100000.")],
    )
    trace = _trace(service, "irun-unread-answer")

    assert view.disposition == "answer"
    feedback = [item for item in trace.inputs if isinstance(item, DecisionFeedback)]
    assert [item.reason_code for item in feedback] == ["offloaded_output_unread"]
    assert trace.inputs[-1].capability_id == "read_action_output"


def test_a_limitation_stands_once_the_offloaded_remainder_has_been_read():
    """Reading it is the requirement, not concluding anything about it.

    The remainder here genuinely lacks what was asked for, so the same rule that
    rejected the unread exit must let this one through.
    """

    def read_big(path: str):
        return tool_response(
            tool_success({"content": "\n".join(f"line {i}" for i in range(200_000))})
        )

    offloaded_ref = ResourceRef(
        resource_id="gen_0",
        resource_type="artifact",
        owner=AuthenticatedPrincipal(tenant_id="tenant-1", user_id="default"),
        revision=1,
    )
    model = _Decisions(
        _continue(
            ToolCallProposal(
                action_id="read-big", tool_name="read_big", arguments={"path": "f"}
            )
        ),
        _continue(
            ToolCallProposal(
                action_id="reread",
                tool_name="read_action_output",
                arguments={
                    "resource_ref": offloaded_ref.model_dump(mode="json"),
                    "keyword": "xfs",
                },
            )
        ),
        FinalMessage(disposition="limitation", message="That file has no XFS entry."),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("read_big", read_big)),
        artifact_port=_ArtifactTexts(),
    )

    view = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-read-limit",
        interaction_run_ref="irun-read-limit",
        messages=[
            ConversationMessage(
                role="user", content="Is there an XFS entry in that file?"
            )
        ],
    )
    trace = _trace(service, "irun-read-limit")

    assert view.disposition == "limitation"
    assert not [item for item in trace.inputs if isinstance(item, DecisionFeedback)]
    assert trace.inputs[1].payload["keyword_match_count"] == 0


def test_initial_action_executes_without_a_synthetic_working_plan_contract():
    calls = 0

    def read_fact(query: str):
        nonlocal calls
        calls += 1
        return tool_response(tool_success({"fact": query}))

    action = ToolCallProposal(
        action_id="read-1",
        tool_name="read_fact",
        arguments={"query": "Orion"},
    )
    model = _Decisions(
        ContinueTurnProposal(actions=(action,)),
        FinalMessage(disposition="answer", message="Observed Orion."),
    )
    service = ConversationService(
        model, tool_port=_executor(_tool("read_fact", read_fact))
    )

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-plan-admission",
        interaction_run_ref="irun-plan-admission",
        messages=[ConversationMessage(role="user", content="Read Orion, then answer.")],
    )
    trace = _trace(service, "irun-plan-admission")

    assert calls == 1
    assert trace is not None
    assert [item.kind for item in trace.inputs] == ["tool_result"]


def test_l02_only_mechanically_safe_actions_run_concurrently():
    barrier = Barrier(2)

    def read_left(value: str):
        barrier.wait(timeout=2)
        return tool_response(tool_success({"value": value}))

    def read_right(value: str):
        barrier.wait(timeout=2)
        return tool_response(tool_success({"value": value}))

    model = _Decisions(
        _continue(
            ToolCallProposal(
                action_id="left", tool_name="read_left", arguments={"value": "L"}
            ),
            ToolCallProposal(
                action_id="right", tool_name="read_right", arguments={"value": "R"}
            ),
        ),
        FinalMessage(disposition="answer", message="Both independent reads completed."),
    )
    service = ConversationService(
        model,
        tool_port=_executor(
            _tool("read_left", read_left),
            _tool("read_right", read_right),
        ),
    )

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-l02",
        interaction_run_ref="irun_l02",
        messages=[
            ConversationMessage(role="user", content="Read both independent sources.")
        ],
    )
    trace = _trace(service, "irun_l02")

    assert trace is not None
    assert trace.concurrent_batches == (("left", "right"),)
    assert trace.execution_order == ("left", "right")


def test_l03_restart_rebuilds_plan_from_durable_facts_without_reexecuting_tool(
    temp_dir,
):
    calls = 0

    def read_once(value: str):
        nonlocal calls
        calls += 1
        return tool_response(tool_success({"value": value}))

    messages = [
        ConversationMessage(role="user", content="Read once and recover after a crash.")
    ]
    first = ConversationService(
        _Decisions(
            _continue(
                ToolCallProposal(
                    action_id="once", tool_name="read_once", arguments={"value": "fact"}
                )
            ),
            RuntimeError("simulated process termination"),
        ),
        tool_port=_executor(_tool("read_once", read_once)),
        journal=FileInteractionJournal(temp_dir / "interaction-l03"),
    )
    with pytest.raises(RuntimeError, match="process termination"):
        first.respond(
            **_conversation_scope(),
            conversation_id="conversation-l03",
            interaction_run_ref="irun_l03",
            messages=messages,
        )

    resumed_model = _Decisions(
        FinalMessage(
            disposition="answer", message="Recovered from the committed fact."
        ),
    )
    resumed = ConversationService(
        resumed_model,
        tool_port=_executor(_tool("read_once", read_once)),
        journal=FileInteractionJournal(temp_dir / "interaction-l03"),
    )
    result = resumed.respond(
        **_conversation_scope(),
        conversation_id="conversation-l03",
        interaction_run_ref="irun_l03",
        messages=messages,
    )

    assert result.disposition == "answer"
    assert calls == 1
    resumed_context = "\n".join(
        message["content"] for message in resumed_model.decision_requests[0].messages
    )
    assert "Typed execution inputs" in resumed_context
    trace = _trace(resumed, "irun_l03")
    assert [item.kind for item in trace.inputs] == ["tool_result"]


def test_independent_user_results_instruction_does_not_require_named_capabilities():
    model = _Decisions(FinalMessage(disposition="answer", message="done"))
    service = ConversationService(model, tool_port=_executor())

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-explicit-reads",
        messages=[
            ConversationMessage(
                role="user",
                content="Summarize my recent notes and identify any knowledge gaps.",
            )
        ],
    )

    system_prompt = model.decision_requests[0].messages[0]["content"]
    assert "goal requires multiple independent read-only results" in system_prompt
    assert "user does not need to know or name internal capabilities" in system_prompt
    assert model.decision_requests[0].temperature == 0
    assert model.decision_requests[0].max_tokens == 1_600


def test_interaction_delegation_budget_cannot_exceed_synchronous_policy_limit():
    with pytest.raises(ValueError, match="less than or equal to 180"):
        AgentDelegationProposal(
            agent_id="specialist",
            bounded_sub_goal="Research a bounded question.",
            time_budget_seconds=181,
        )


def test_l04_parent_synthesizes_async_specialist_artifact_without_child_completion_shortcut():
    gateway = AgentGateway(policy_engine=PolicyEngine(), store=InMemoryAgentRunStore())
    specialist = _AsyncSpecialist()
    gateway.register(specialist)
    model = _Decisions(
        _continue(
            AgentDelegationProposal(
                action_id="specialist-1",
                agent_id="specialist",
                bounded_sub_goal="Research only the bounded Orion question.",
                expected_artifact_types=("report",),
            )
        ),
        FinalMessage(
            disposition="answer", message="Parent synthesis of the specialist report."
        ),
    )
    service = ConversationService(
        model,
        agent_port=gateway,
        artifact_port=_ArtifactTexts(),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-l04",
        interaction_run_ref="irun_l04",
        messages=[
            ConversationMessage(
                role="user", content="Delegate the bounded research and synthesize it."
            )
        ],
    )
    trace = _trace(service, "irun_l04")

    assert result.message.content.startswith("Parent synthesis")
    assert trace.inputs[0].kind == "agent_artifact"
    assert trace.inputs[0].payload["status"] == "completed"
    artifact_projection = trace.inputs[0].payload["artifacts"][0]
    assert artifact_projection["content_excerpt"] == "bounded specialist evidence"
    assert artifact_projection["content_length"] == len("bounded specialist evidence")
    assert "content" not in artifact_projection
    assert trace.final_message.message == result.message.content
    assert specialist.submit_calls == 1
    assert specialist.poll_calls == 2


def test_successful_agent_artifact_rejects_ungrounded_repeat_delegation():
    gateway = AgentGateway(policy_engine=PolicyEngine(), store=InMemoryAgentRunStore())
    specialist = _AsyncSpecialist()
    gateway.register(specialist)
    model = _Decisions(
        _continue(
            AgentDelegationProposal(
                action_id="specialist-1",
                agent_id="specialist",
                bounded_sub_goal="Research the bounded question once.",
                expected_artifact_types=("report",),
            )
        ),
        ContinueTurnProposal(
            actions=(
                AgentDelegationProposal(
                    action_id="specialist-2",
                    agent_id="specialist",
                    bounded_sub_goal="Research the same requested result again.",
                    expected_artifact_types=("report",),
                ),
            )
        ),
        FinalMessage(
            disposition="answer", message="Parent synthesis from the first artifact."
        ),
    )
    service = ConversationService(
        model,
        agent_port=gateway,
        artifact_port=_ArtifactTexts(),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-repeat-delegation",
        interaction_run_ref="irun-repeat-delegation",
        messages=[
            ConversationMessage(role="user", content="Delegate once, then synthesize.")
        ],
    )
    trace = _trace(service, "irun-repeat-delegation")

    assert result.disposition == "answer"
    assert specialist.submit_calls == 1
    assert any(
        item.kind == "decision_feedback"
        and item.reason_code == "agent_artifact_already_returned"
        for item in trace.inputs
    )
    assert (
        "produce the parent synthesis"
        in model.decision_requests[1].messages[0]["content"]
    )


def test_cancelled_child_artifact_remains_visible_and_rejects_duplicate_delegation():
    class _CancelledSpecialist(_AsyncSpecialist):
        def submit(
            self,
            task: AgentTask,
            context: AgentGatewayContext,
            *,
            submission_key: str,
        ) -> ChildAgentRunRecord:
            self.submit_calls += 1
            return self._run(task, context, status="cancelled")

        def lookup_submission(
            self,
            submission_key: str,
            task: AgentTask,
            context: AgentGatewayContext,
        ) -> ChildAgentRunRecord | None:
            return None

    gateway = AgentGateway(policy_engine=PolicyEngine(), store=InMemoryAgentRunStore())
    specialist = _CancelledSpecialist()
    gateway.register(specialist)
    first = AgentDelegationProposal(
        action_id="specialist-cancelled-1",
        agent_id="specialist",
        bounded_sub_goal="Return the bounded evidence available before cancellation.",
        expected_artifact_types=("report",),
    )
    repeated = first.model_copy(update={"action_id": "specialist-cancelled-2"})
    model = _Decisions(
        _continue(first),
        ContinueTurnProposal(actions=(repeated,)),
        FinalMessage(
            disposition="answer", message="Parent assessed the returned artifact."
        ),
    )
    service = ConversationService(
        model,
        agent_port=gateway,
        artifact_port=_ArtifactTexts(),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-cancelled-artifact",
        interaction_run_ref="irun-cancelled-artifact",
        messages=[
            ConversationMessage(
                role="user", content="Assess returned evidence without retrying."
            )
        ],
    )
    trace = _trace(service, "irun-cancelled-artifact")

    artifact = next(item for item in trace.inputs if item.kind == "agent_artifact")
    assert result.disposition == "answer"
    assert artifact.status == "cancelled"
    assert artifact.payload["artifact_refs"]
    assert specialist.submit_calls == 1
    assert any(
        item.kind == "decision_feedback"
        and item.reason_code == "agent_artifact_already_returned"
        for item in trace.inputs
    )


def test_l05_budget_exhaustion_fails_closed_after_committed_result():
    def inspect(value: str):
        return tool_response(tool_success({"value": value}))

    service = ConversationService(
        _Decisions(
            _continue(
                ToolCallProposal(
                    action_id="inspect",
                    tool_name="inspect",
                    arguments={"value": "fact"},
                )
            )
        ),
        tool_port=_executor(_tool("inspect", inspect)),
        budget_policy=LoopBudgetPolicy(max_model_turns=1),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-l05",
        interaction_run_ref="irun_l05",
        messages=[
            ConversationMessage(
                role="user", content="Keep working past the configured budget."
            )
        ],
    )

    assert result.disposition == "limitation"
    assert "未生成替代答案" in result.message.content
    assert _trace(service, "irun_l05").inputs[0].status == "succeeded"


def test_a_single_batch_cannot_spend_more_tool_calls_than_remain():
    calls: list[str] = []

    def inspect(value: str):
        calls.append(value)
        return tool_response(tool_success({"value": value}))

    service = ConversationService(
        _Decisions(
            ContinueTurnProposal(
                actions=tuple(
                    ToolCallProposal(
                        action_id=f"inspect-{value}",
                        tool_name="inspect",
                        arguments={"value": value},
                    )
                    for value in ("A", "B", "C")
                )
            ),
            FinalMessage(disposition="limitation", message="Only A and B were read."),
        ),
        tool_port=_executor(_tool("inspect", inspect)),
        budget_policy=LoopBudgetPolicy(max_tool_calls=2),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-batch-budget",
        interaction_run_ref="irun_batch_budget",
        messages=[ConversationMessage(role="user", content="Read A, B, and C.")],
    )
    trace = _trace(service, "irun_batch_budget")

    assert len(calls) == 2
    assert set(calls) == {"A", "B"}
    assert trace.usage.tool_calls == 2
    assert trace.execution_order == ("inspect-A", "inspect-B")
    assert any(
        item.kind == "decision_feedback"
        and item.action_id == "inspect-C"
        and item.reason_code == "budget_exhausted"
        for item in trace.inputs
    )
    assert result.disposition == "limitation"


def test_l06_observation_drives_revision_without_rewriting_execution_fact():
    calls = 0

    def verify(draft: str):
        nonlocal calls
        calls += 1
        return tool_response(
            tool_success(
                {
                    "verification_ref": "verify-1",
                    "status": "failed",
                    "feedback": "cite the observed limitation",
                    "draft": draft,
                }
            )
        )

    model = _Decisions(
        _continue(
            ToolCallProposal(
                action_id="verify",
                tool_name="verify",
                arguments={"draft": "unsupported"},
            )
        ),
        FinalMessage(
            disposition="answer", message="Revised answer that states the limitation."
        ),
    )
    service = ConversationService(model, tool_port=_executor(_tool("verify", verify)))
    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-l06",
        interaction_run_ref="irun_l06",
        messages=[
            ConversationMessage(role="user", content="Check the draft, then answer.")
        ],
    )
    trace = _trace(service, "irun_l06")

    assert calls == 1
    assert result.message.content.startswith("Revised answer")
    assert trace.inputs[0].payload["data"]["status"] == "failed"
    assert trace.execution_order == ("verify",)


def _receipt_payload(draft, *, verdict, criterion="grounded", criteria_digest="0" * 64):
    normalized = draft.strip()
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    return {
        "verdict": verdict,
        "criterion_results": [
            {
                "criterion": criterion,
                "status": "satisfied" if verdict == "passed" else "not_satisfied",
                "feedback": "" if verdict == "passed" else "revise",
            }
        ],
        "revision_feedback": "" if verdict == "passed" else "revise",
        "receipt_id": f"svr_{digest[:20]}",
        "verified_draft": normalized,
        "draft_digest": digest,
        "success_criteria": [criterion],
        "criteria_digest": criteria_digest,
    }


def _receipt_id(draft):
    return f"svr_{sha256(draft.strip().encode('utf-8')).hexdigest()[:20]}"


def _receipt_observation(draft, *, verdict, action_id="verify", **kwargs):
    return ActionObservation(
        kind="tool_result",
        action_id=action_id,
        capability_id="verify_interaction_draft",
        status="succeeded",
        payload={
            "ok": True,
            "data": _receipt_payload(draft, verdict=verdict, **kwargs),
        },
    )


_RECEIPT_CAPABILITIES = frozenset({"verify_interaction_draft"})


_REVIEW_REQUEST = (
    "请审查这段要发给用户的答复：“系统已经完成所有写入。”"
    "要求是：没有可核验的执行证据时，不能声称写入已经发生。"
)


def _review_intent(*criteria_and_spans):
    return ReviewIntent(
        requires_review=True,
        requirements=tuple(
            ReviewRequirement(criterion=criterion, source_span=span)
            for criterion, span in criteria_and_spans
        ),
    )


def _verifier_tool(recorder, *, verdicts):
    """A verifier whose verdicts are scripted, recording every call it receives."""

    def verify_interaction_draft(
        draft: str,
        success_criteria: tuple[str, ...],
        evidence_refs: tuple[str, ...] = (),
    ):
        recorder.append((draft, tuple(success_criteria)))
        return tool_response(
            tool_success(
                _receipt_payload(
                    draft,
                    verdict=verdicts[min(len(recorder) - 1, len(verdicts) - 1)],
                    criterion=success_criteria[0],
                )
            )
        )

    return _tool(
        "verify_interaction_draft",
        verify_interaction_draft,
        emits_verified_artifact=True,
    )


def test_review_criteria_must_be_traceable_to_the_user_verbatim():
    """A criterion the user did not write is dropped, not repaired.

    This is the mechanical replacement for asking the model, in a prompt, to copy
    the user's requirement faithfully: an invented standard cannot enter the turn,
    so the verifier's verdict always means something the user actually asked for.
    """
    messages = [ConversationMessage(role="user", content=_REVIEW_REQUEST)]

    admitted = admit_review_intent(
        _review_intent(
            ("must not claim writes occurred", "不能声称写入已经发生"),
            ("text should be enthusiastic", "make it sound great"),
        ),
        messages=messages,
    )

    assert admitted.criteria == ("must not claim writes occurred",)
    assert admitted.ungrounded_spans == ("make it sound great",)
    assert admitted.requires_review is True


def test_a_review_request_with_no_grounded_criterion_is_not_silently_downgraded():
    messages = [ConversationMessage(role="user", content=_REVIEW_REQUEST)]

    admitted = admit_review_intent(
        _review_intent(("text should be enthusiastic", "make it sound great")),
        messages=messages,
    )

    assert admitted.criteria == ()
    assert admitted.requires_review is False
    assert admitted.ungrounded_spans == ("make it sound great",)
    assert (
        ungrounded_criteria_feedback(admitted).reason_code
        == "review_criteria_not_grounded"
    )


def test_criteria_are_never_taken_from_an_assistant_message():
    """Only user text can set the standard.

    Otherwise a turn could state a lenient criterion in its own prose and have it
    admitted on the next turn -- self-authored criteria via the conversation.
    """
    admitted = admit_review_intent(
        _review_intent(("any claim is fine", "any claim is fine")),
        messages=[
            ConversationMessage(role="user", content="审查这段话。"),
            ConversationMessage(role="assistant", content="any claim is fine"),
        ],
    )

    assert admitted.criteria == ()
    assert admitted.requires_review is False


def test_an_ordinary_request_is_answered_without_any_verification():
    """Non-review requests must not pay for verification, or trigger it at all."""
    recorder: list[tuple[str, tuple[str, ...]]] = []
    model = _Decisions(
        FinalMessage(disposition="answer", message="Orion is a constellation.")
    )
    service = ConversationService(
        model,
        tool_port=_executor(_verifier_tool(recorder, verdicts=("passed",))),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-no-review",
        interaction_run_ref="irun-no-review",
        messages=[ConversationMessage(role="user", content="What is Orion?")],
    )
    trace = _trace(service, "irun-no-review")

    assert result.message.content == "Orion is a constellation."
    assert recorder == []
    assert trace.execution_order == ()
    assert trace.review_criteria == ReviewCriteria()


def test_the_real_verifier_is_not_a_capability_the_model_can_see():
    """The runtime-owned verifier stays out of the model-visible projection.

    This is a visibility assertion, not an authorization proof: the runtime can
    still resolve the internal tool for its mandatory verification step. The
    ordinary-user prompt-injection boundary is covered separately by GOV-001.
    """
    verifier = build_verify_interaction_draft_tool(_Decisions())
    executor = _executor(verifier)
    service = ConversationService(None, tool_port=executor)

    visible = [tool.name for tool in service._effective_capabilities().tools]

    assert "verify_interaction_draft" not in visible
    assert executor.get("verify_interaction_draft") is verifier
    assert (
        executor.validate_interaction_call(
            "verify_interaction_draft",
            {"draft": "d", "success_criteria": ["c"]},
        ).status
        == "accepted"
    )


def test_a_review_answer_is_verified_before_it_can_be_sent():
    """The runtime verifies the answer itself, against the frozen criteria.

    The model proposes ordinary prose and never references a receipt: the sent
    bytes come from the receipt the runtime already holds, so "verified" and
    "sent" cannot diverge.
    """
    recorder: list[tuple[str, tuple[str, ...]]] = []
    safe = "无法确认写入是否发生。"
    model = _Decisions(
        FinalMessage(disposition="answer", message="系统已经完成所有写入。"),
        FinalMessage(disposition="answer", message=safe),
        review_intent=_review_intent(
            ("must not claim writes occurred", "不能声称写入已经发生"),
        ),
    )
    service = ConversationService(
        model,
        tool_port=_executor(
            _verifier_tool(recorder, verdicts=("needs_revision", "passed")),
        ),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-runtime-verified",
        interaction_run_ref="irun-runtime-verified",
        messages=[ConversationMessage(role="user", content=_REVIEW_REQUEST)],
    )
    trace = _trace(service, "irun-runtime-verified")

    assert [draft for draft, _ in recorder] == ["系统已经完成所有写入。", safe]
    assert result.disposition == "answer"
    assert result.message.content == safe
    assert trace.final_message.message == safe
    assert trace.execution_order == ("runtime-verify-0", "runtime-verify-1")
    assert [item.capability_id for item in trace.inputs] == [
        "verify_interaction_draft",
        "verify_interaction_draft",
    ]


def test_a_review_request_cannot_be_ended_without_a_verified_answer():
    """A non-answer disposition is not a way past verification.

    Only ``answer`` is verified, so ending a review request as a clarification
    would deliver unverified text. Observed against the live model: asked to
    remove an unevidenced claim, it asked the user for the evidence instead. The
    runtime rejects the disposition and the retried answer is verified normally.
    """
    recorder: list[tuple[str, tuple[str, ...]]] = []
    safe = "无法确认写入是否发生。"
    model = _Decisions(
        FinalMessage(
            disposition="clarification_required",
            message="请提供可核验的执行证据。",
        ),
        FinalMessage(disposition="answer", message=safe),
        review_intent=_review_intent(
            ("must not claim writes occurred", "不能声称写入已经发生"),
        ),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_verifier_tool(recorder, verdicts=("passed",))),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-review-disposition",
        interaction_run_ref="irun-review-disposition",
        messages=[ConversationMessage(role="user", content=_REVIEW_REQUEST)],
    )
    trace = _trace(service, "irun-review-disposition")

    assert [draft for draft, _ in recorder] == [safe]
    assert result.disposition == "answer"
    assert result.message.content == safe
    assert [
        item.reason_code for item in trace.inputs if isinstance(item, DecisionFeedback)
    ] == ["review_requires_sendable_answer"]


def test_the_frozen_criteria_are_reused_for_every_verification_in_the_turn():
    """One derivation, one standard.

    Re-deriving per attempt would restore the drift this change removes: a later
    turn could be judged against a weaker criterion than the first.
    """
    recorder: list[tuple[str, tuple[str, ...]]] = []
    model = _Decisions(
        FinalMessage(disposition="answer", message="系统已经完成所有写入。"),
        FinalMessage(disposition="answer", message="无法确认写入是否发生。"),
        review_intent=_review_intent(
            ("must not claim writes occurred", "不能声称写入已经发生"),
        ),
    )
    service = ConversationService(
        model,
        tool_port=_executor(
            _verifier_tool(recorder, verdicts=("needs_revision", "passed")),
        ),
    )

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-frozen-criteria",
        interaction_run_ref="irun-frozen-criteria",
        messages=[ConversationMessage(role="user", content=_REVIEW_REQUEST)],
    )
    trace = _trace(service, "irun-frozen-criteria")

    criteria_per_call = {criteria for _, criteria in recorder}
    assert criteria_per_call == {("must not claim writes occurred",)}
    assert trace.review_criteria.criteria == ("must not claim writes occurred",)
    assert (
        sum(
            request.operation == "interaction_review_criteria"
            for request in model.requests
        )
        == 1
    )


def test_a_review_request_fails_closed_when_verification_is_unavailable():
    """No verifier means no claim of review, rather than an unverified answer."""
    model = _Decisions(
        FinalMessage(disposition="answer", message="无法确认写入是否发生。"),
        review_intent=_review_intent(
            ("must not claim writes occurred", "不能声称写入已经发生"),
        ),
    )
    service = ConversationService(model, tool_port=_executor())

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-verifier-missing",
        interaction_run_ref="irun-verifier-missing",
        messages=[ConversationMessage(role="user", content=_REVIEW_REQUEST)],
    )
    trace = _trace(service, "irun-verifier-missing")

    assert result.disposition == "answer"
    assert trace.review_criteria == ReviewCriteria()
    assert [
        item.reason_code for item in trace.inputs if item.kind == "decision_feedback"
    ] == ["verification_capability_unavailable"]


def test_a_failed_criteria_derivation_answers_without_claiming_review():
    """A broken derivation must not become a runtime-invented standard."""

    class _FailingDerivation(_Decisions):
        def generate(self, request):
            if request.operation == "interaction_review_criteria":
                raise RuntimeError("derivation provider unavailable")
            return super().generate(request)

    model = _FailingDerivation(
        FinalMessage(disposition="answer", message="无法确认写入是否发生。"),
    )
    recorder: list[tuple[str, tuple[str, ...]]] = []
    service = ConversationService(
        model,
        tool_port=_executor(_verifier_tool(recorder, verdicts=("passed",))),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-derivation-failed",
        interaction_run_ref="irun-derivation-failed",
        messages=[ConversationMessage(role="user", content=_REVIEW_REQUEST)],
    )

    assert result.disposition == "answer"
    assert recorder == []
    assert _trace(service, "irun-derivation-failed").review_criteria == ReviewCriteria()


def test_receipts_are_read_from_observations_by_contract_not_by_position():
    inputs = [
        _receipt_observation("first draft", verdict="needs_revision", action_id="v1"),
        ActionObservation(
            kind="tool_result",
            action_id="v2",
            capability_id="verify_interaction_draft",
            status="succeeded",
            payload={"ok": True, "data": {"not": "a receipt"}},
        ),
        _receipt_observation("final draft", verdict="passed", action_id="v3"),
    ]

    receipts = observed_receipts(
        inputs,
        capability_names=frozenset({"verify_interaction_draft"}),
    )

    assert [receipt.verdict for receipt in receipts] == ["needs_revision", "passed"]
    assert receipts[-1].verified_draft == "final draft"


def test_governed_knowledge_save_recovers_confirms_and_replays_without_duplicate(
    temp_dir,
):
    store = InMemoryKnowledgeStore()
    writer = KnowledgeService(store)
    journal_root = temp_dir / "conversation-knowledge-save"
    messages = [
        ConversationMessage(
            role="user",
            content="Save this conclusion after confirmation: SLO budgets need weekly review.",
        )
    ]
    first = ConversationService(
        _Decisions(
            _continue(
                ToolCallProposal(
                    action_id="save-1",
                    tool_name="prepare_conversation_knowledge_save",
                    arguments={
                        "selections": [
                            {
                                "source_message_index": 0,
                                "text_span": "SLO budgets need weekly review.",
                            }
                        ]
                    },
                )
            )
        ),
        knowledge_writer=writer,
        journal=FileInteractionJournal(journal_root),
    )

    prepared = first.respond(
        **_conversation_scope(),
        conversation_id="conversation-1",
        interaction_run_ref="irun_knowledge_save",
        messages=messages,
    )

    assert prepared.disposition == "confirmation_required"
    assert prepared.pending_confirmation is not None
    assert prepared.pending_confirmation.status == "awaiting_confirmation"
    assert store.list_claims("tenant-1:default") == []
    command = prepared.pending_confirmation.command
    assert command.source_message_indexes == (0,)
    assert command.messages == (
        ConversationMessage(
            role="user",
            content="SLO budgets need weekly review.",
        ),
    )

    resumed = ConversationService(
        None,
        knowledge_writer=writer,
        journal=FileInteractionJournal(journal_root),
    )
    recovered = _trace(resumed, "irun_knowledge_save")
    assert recovered is not None
    assert recovered.knowledge_save_operation is not None
    assert recovered.knowledge_save_operation.command == command

    executed = resumed.decide_knowledge_save(
        **_conversation_scope(),
        interaction_run_ref="irun_knowledge_save",
        decision="confirm",
        confirmation_ref="unit-user-confirmation",
    )
    claim_count = len(store.list_claims("tenant-1:default"))
    replayed = resumed.decide_knowledge_save(
        **_conversation_scope(),
        interaction_run_ref="irun_knowledge_save",
        decision="confirm",
        confirmation_ref="unit-user-confirmation",
    )

    assert executed.status == "executed"
    assert executed.receipt is not None
    assert replayed.receipt == executed.receipt
    assert len(store.list_claims("tenant-1:default")) == claim_count
    after_restart = _trace(
        ConversationService(
            None,
            knowledge_writer=writer,
            journal=FileInteractionJournal(journal_root),
        ),
        "irun_knowledge_save",
    )
    assert after_restart is not None
    assert after_restart.knowledge_save_operation == executed


def test_governed_knowledge_save_rejects_without_writing(temp_dir):
    store = InMemoryKnowledgeStore()
    writer = KnowledgeService(store)
    service = ConversationService(
        _Decisions(
            _continue(
                ToolCallProposal(
                    action_id="save-reject",
                    tool_name="prepare_conversation_knowledge_save",
                    arguments={
                        "selections": [
                            {
                                "source_message_index": 0,
                                "text_span": "SLO budgets need weekly review.",
                            }
                        ]
                    },
                )
            )
        ),
        knowledge_writer=writer,
        journal=FileInteractionJournal(temp_dir / "conversation-knowledge-save-reject"),
    )
    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-1",
        interaction_run_ref="irun_knowledge_save_reject",
        messages=[
            ConversationMessage(
                role="user",
                content=(
                    "Conclusion: SLO budgets need weekly review. "
                    "Save this only if I confirm."
                ),
            )
        ],
    )
    rejected = service.decide_knowledge_save(
        **_conversation_scope(),
        interaction_run_ref="irun_knowledge_save_reject",
        decision="reject",
        confirmation_ref="",
    )

    assert rejected.status == "rejected"
    assert rejected.receipt is None
    assert store.list_claims("tenant-1:default") == []


def test_governed_knowledge_save_rejects_fabricated_selection():
    store = InMemoryKnowledgeStore()
    writer = KnowledgeService(store)
    service = ConversationService(
        _Decisions(
            _continue(
                ToolCallProposal(
                    action_id="save-fabricated",
                    tool_name="prepare_conversation_knowledge_save",
                    arguments={
                        "selections": [
                            {
                                "source_message_index": 0,
                                "text_span": "A conclusion the user never wrote.",
                            }
                        ]
                    },
                )
            ),
            FinalMessage(
                disposition="failed",
                message="The requested knowledge span could not be selected.",
            ),
        ),
        knowledge_writer=writer,
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-1",
        interaction_run_ref="irun_knowledge_save_fabricated",
        messages=[
            ConversationMessage(
                role="user",
                content="Save my SLO conclusion after confirmation.",
            )
        ],
    )
    trace = _trace(service, "irun_knowledge_save_fabricated")

    assert result.disposition == "failed"
    assert trace is not None
    assert trace.knowledge_save_operation is None
    assert [
        item.reason_code for item in trace.inputs if item.kind == "decision_feedback"
    ] == ["invalid_knowledge_save_source"]
    assert store.list_claims("tenant-1:default") == []


class _KnowledgeKnowledgeReader:
    def select_personal_evidence(self, *, question, owner_id, user_id, limit):
        assert owner_id == "tenant-1:default"
        assert user_id == "default"
        return PersonalKnowledgeEvidenceSnapshot(
            question=question,
            citations=(),
            claim_summaries=(),
            conflicted_claim_ids=(),
            potential_conflicted_claim_ids=(),
        )

    def list_personal_knowledge(self, *, owner_id, user_id, limit):
        assert owner_id == "tenant-1:default"
        assert user_id == "default"
        assert limit <= 50
        return (
            PersonalKnowledgeCandidate(
                knowledge_item_id="kitm_target",
                title="Incorrect launch window",
                summary="The launch window is Monday at 09:00.",
                state="active",
            ),
        )


class _KnowledgeDeleteLifecycle:
    def __init__(self):
        self.operations = {}

    def prepare_delete(
        self,
        *,
        owner_id,
        user_id,
        target_note_id,
        reason,
        idempotency_key,
    ):
        operation = KnowledgeDeleteOperationView(
            command=KnowledgeDeleteCommand(
                command_id="kdel_target",
                idempotency_key=idempotency_key,
                owner_id=owner_id,
                user_id=user_id,
                target_note_id=target_note_id,
                reason=reason,
                command_digest="a" * 64,
            ),
            status="awaiting_confirmation",
        )
        self.operations[operation.command.command_id] = operation
        return operation

    def get_delete(self, command_id, *, user_id):
        operation = self.operations.get(command_id)
        return operation if operation and operation.command.user_id == user_id else None


class _ProjectStarter:
    def __init__(self):
        self.calls = 0
        self.reads = 0
        self.steers = 0

    def start(self, *, principal, owner, request, idempotency_key):
        self.calls += 1
        assert principal.user_id == "default"
        assert owner == principal
        assert idempotency_key
        return ProjectReference(
            project_id="iprj_target",
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            state="planning",
            title=request.title,
            goal=request.goal,
        )

    def get(self, *, principal, reference):
        self.reads += 1
        assert reference.project_id == "iprj_target"
        return self._snapshot(plan_version=1)

    def steer(self, *, principal, reference, request, idempotency_key):
        self.steers += 1
        assert reference.project_id == "iprj_target"
        assert request.statement == "Add deployment compatibility."
        assert idempotency_key
        return self._snapshot(plan_version=2)

    @staticmethod
    def _snapshot(*, plan_version):
        return ConversationProjectSnapshot(
            project_id="iprj_target",
            state="active",
            title="Protocol changes",
            goal="Investigate protocol changes and deliver a sourced report.",
            plan_version=plan_version,
            requirements=(
                InvestigationRequirementProgress(
                    requirement_id="req-1",
                    statement="Use official sources.",
                    acceptance_contract="Every material claim has an official source.",
                    status="active",
                ),
            ),
            subgoals=(
                InvestigationSubgoalProgress(
                    logical_subgoal_id="sg-1",
                    objective="Collect official changes.",
                    status="pending",
                ),
            ),
            waiting_reasons=(),
        )


def test_goal_entry_observes_canonical_item_then_prepares_existing_delete_command():
    lifecycle = _KnowledgeDeleteLifecycle()
    service = ConversationService(
        _Decisions(
            _continue(
                ToolCallProposal(
                    action_id="list-knowledge",
                    tool_name="list_personal_knowledge",
                    arguments={"limit": 20},
                )
            ),
            _continue(
                ToolCallProposal(
                    action_id="prepare-delete",
                    tool_name="prepare_knowledge_delete",
                    arguments={
                        "target_knowledge_item_id": "kitm_target",
                        "reason": "The user identified this entry as incorrect.",
                    },
                )
            ),
        ),
        knowledge_reader=_KnowledgeKnowledgeReader(),
        knowledge_lifecycle=lifecycle,
    )

    prepared = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-1",
        interaction_run_ref="irun_delete_from_goal",
        messages=[
            ConversationMessage(
                role="user",
                content="Delete the incorrect launch-window knowledge, but confirm first.",
            )
        ],
    )
    trace = _trace(service, "irun_delete_from_goal")

    assert prepared.disposition == "confirmation_required"
    assert prepared.pending_confirmation.kind == "knowledge_delete"
    assert (
        prepared.pending_confirmation.operation.command.target_note_id == "kitm_target"
    )
    assert trace.knowledge_delete_command_ref == "kdel_target"
    assert trace.project_reference is None
    assert [item.capability_id for item in trace.inputs] == ["list_personal_knowledge"]


def test_goal_entry_starts_one_existing_project_and_replay_returns_same_reference():
    project_port = _ProjectStarter()
    service = ConversationService(
        _Decisions(
            _continue(
                ToolCallProposal(
                    action_id="start-project",
                    tool_name="start_durable_investigation",
                    arguments={
                        "title": "Protocol changes",
                        "goal": "Investigate protocol changes and deliver a sourced report.",
                        "requirements": [
                            {
                                "statement": "Use official sources.",
                                "acceptance_contract": "Every material claim has an official source.",
                            }
                        ],
                    },
                )
            )
        ),
        project_port=project_port,
    )
    kwargs = {
        **_conversation_scope(),
        "conversation_id": "conversation-1",
        "interaction_run_ref": "irun_project_from_goal",
        "messages": [
            ConversationMessage(
                role="user",
                content="Investigate this in the background so I can pause or steer it later.",
            )
        ],
    }

    started = service.respond(**kwargs)
    replayed = service.respond(**kwargs)
    trace = _trace(service, "irun_project_from_goal")

    assert started.disposition == "background_started"
    assert replayed.project_reference == started.project_reference
    assert project_port.calls == 1
    assert trace.project_reference == started.project_reference
    assert trace.knowledge_delete_command_ref is None


def test_later_turn_reads_and_steers_only_the_project_linked_to_its_conversation():
    project_port = _ProjectStarter()
    service = ConversationService(
        _Decisions(
            _continue(
                ToolCallProposal(
                    action_id="start-project",
                    tool_name="start_durable_investigation",
                    arguments={
                        "title": "Protocol changes",
                        "goal": "Investigate protocol changes and deliver a sourced report.",
                        "requirements": [{
                            "statement": "Use official sources.",
                            "acceptance_contract": "Every material claim has an official source.",
                        }],
                    },
                )
            ),
            _continue(ToolCallProposal(
                action_id="steer-project",
                tool_name="steer_investigation_project",
                arguments={
                    "statement": "Add deployment compatibility.",
                    "added_requirements": [{
                        "statement": "Cover deployment compatibility.",
                        "acceptance_contract": "The report contains a compatibility section.",
                    }],
                },
            )),
            FinalMessage(
                disposition="answer",
                message="Plan version 2 is active.",
            ),
        ),
        project_port=project_port,
    )
    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-linked-project",
        interaction_run_ref="irun_project_start",
        messages=[ConversationMessage(
            role="user",
            content="Investigate this in the background so I can steer it later.",
        )],
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-linked-project",
        interaction_run_ref="irun_project_steer",
        messages=[ConversationMessage(
            role="user",
            content="Show progress, then add deployment compatibility to unfinished work.",
        )],
    )
    trace = _trace(service, "irun_project_steer")

    assert result.disposition == "answer"
    assert result.project_reference.project_id == "iprj_target"
    assert project_port.calls == 1
    assert project_port.reads == 1
    assert project_port.steers == 1
    assert trace.project_reference.project_id == "iprj_target"
    assert [item.capability_id for item in trace.inputs] == [
        "investigation_project_context",
        "steer_investigation_project",
    ]


def test_explanation_only_request_does_not_create_a_project_or_delete_command():
    project_port = _ProjectStarter()
    lifecycle = _KnowledgeDeleteLifecycle()
    service = ConversationService(
        _Decisions(
            FinalMessage(
                disposition="answer",
                message="Here is how the deletion policy works; no operation was prepared.",
            )
        ),
        knowledge_reader=_KnowledgeKnowledgeReader(),
        knowledge_lifecycle=lifecycle,
        project_port=project_port,
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-1",
        interaction_run_ref="irun_explain_only",
        messages=[
            ConversationMessage(
                role="user",
                content="Only explain how deletion works. Do not execute or start anything.",
            )
        ],
    )
    trace = _trace(service, "irun_explain_only")

    assert result.disposition == "answer"
    assert project_port.calls == 0
    assert lifecycle.operations == {}
    assert trace.knowledge_delete_command_ref is None
    assert trace.project_reference is None


class _AsyncSpecialist:
    profile = SubagentProfile(
        agent_id="specialist",
        provider="specialist",
        protocol="local",
        task_types=("research",),
        allowed_operations=("delegate",),
        governance=AgentGovernance(permission_scope="a2a:specialist:invoke"),
    )

    def __init__(self) -> None:
        self.submit_calls = 0
        self.poll_calls = 0

    def invoke(
        self, task: AgentTask, context: AgentGatewayContext
    ) -> ChildAgentRunOutcome:
        raise AssertionError("interaction delegation must use submit/poll")

    def submit(
        self,
        task: AgentTask,
        context: AgentGatewayContext,
        *,
        submission_key: str,
    ) -> ChildAgentRunRecord:
        self.submit_calls += 1
        return self._run(task, context, status="running")

    def lookup_submission(
        self,
        submission_key: str,
        task: AgentTask,
        context: AgentGatewayContext,
    ) -> ChildAgentRunRecord | None:
        return None

    def poll(
        self, run: ChildAgentRunRecord, context: AgentGatewayContext
    ) -> ChildAgentRunRecord:
        self.poll_calls += 1
        status = "completed" if self.poll_calls >= 2 else "running"
        return self._run(
            run.definition.task,
            context,
            status=status,
            agent_run_id=run.definition.agent_run_id,
        )

    def cancel(
        self, run: ChildAgentRunRecord, context: AgentGatewayContext
    ) -> ChildAgentRunRecord:
        return self._run(
            run.definition.task,
            context,
            status="cancelled",
            agent_run_id=run.definition.agent_run_id,
        )

    def stream(self, run: ChildAgentRunRecord, context: AgentGatewayContext):
        yield ChildAgentRunEvent(
            event_id=new_agent_event_id(),
            agent_run_id=run.definition.agent_run_id,
            type="stream_delta",
            payload={"delta": "research"},
        )

    def _run(self, task, context, *, status, agent_run_id=None):
        run_id = agent_run_id or new_agent_run_id()
        artifacts = (
            ()
            if status == "running"
            else (
                AgentArtifact(
                    agent_run_id=run_id,
                    kind="report",
                    artifact_ref=ResourceRef(
                        resource_id=f"artifact-{run_id}",
                        resource_type="artifact",
                        owner=context.execution_scope.principal,
                    ),
                ),
            )
        )
        return ChildAgentRunRecord(
            definition=ChildAgentRunDefinition(
                agent_run_id=run_id,
                agent_id=self.profile.agent_id,
                task=task,
                context=context,
            ),
            projection=ChildAgentRunProjection(
                agent_run_id=run_id,
                status=status,
                external_task_id="external-specialist-1",
            ),
            artifact_index=ChildAgentArtifactIndex(
                agent_run_id=run_id, artifacts=artifacts
            ),
        )


class _ArtifactTexts:
    def __init__(self, *, write_error: Exception | None = None) -> None:
        self.written: list[dict[str, object]] = []
        self._write_error = write_error

    def read_text(self, resource_ref, *, principal, owner):
        if resource_ref.owner != owner:
            raise PermissionError("cross-scope test artifact")
        for record in self.written:
            if record["resource_ref"].resource_id != resource_ref.resource_id:
                continue
            # ArtifactService.resolve rejects a principal that did not create the
            # artifact. The fake must reject it too, or it grants a read that
            # production denies.
            if record["created_by_principal_id"] != principal.principal_id:
                raise PermissionError("artifact principal is not authorized")
            return record["content"]
        return "bounded specialist evidence"

    def write_generated(
        self,
        *,
        owner,
        execution_scope,
        producer_key,
        producer_ref,
        kind,
        content,
        content_digest,
        source_artifact_refs,
        evidence_refs,
        limitations=(),
    ):
        if self._write_error is not None:
            raise self._write_error
        for record in self.written:
            if record["producer_key"] == producer_key:
                return record["resource_ref"]
        resource_ref = ResourceRef(
            resource_id=f"gen_{len(self.written)}",
            resource_type="artifact",
            owner=owner,
            revision=1,
        )
        self.written.append(
            {
                "producer_key": producer_key,
                "producer_ref": producer_ref,
                "kind": kind,
                "content": content,
                "resource_ref": resource_ref,
                "created_by_principal_id": execution_scope.principal.principal_id,
            }
        )
        return resource_ref
