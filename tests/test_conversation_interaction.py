from __future__ import annotations

from hashlib import sha256
from threading import Barrier

import pytest
from langchain_core.tools import StructuredTool

from personal_agent.agents import AgentGateway, InMemoryAgentRunStore
from personal_agent.application.conversation import (
    AgentDelegationProposal,
    AgentTurnDecision,
    ContinueTurnProposal,
    ConversationMessage,
    ConversationService,
    FileInteractionJournal,
    FinalMessage,
    LoopBudgetPolicy,
    ReviewIntent,
    ReviewRequirement,
    ToolCallProposal,
)
from personal_agent.application.conversation.models import (
    ActionObservation,
    CommittedUsage,
    DecisionFeedback,
    EffectiveCapabilities,
    ReviewCriteria,
)
from personal_agent.application.conversation.review_admission import (
    admit_review_intent,
    ungrounded_criteria_feedback,
)
from personal_agent.application.conversation.verification_admission import (
    observed_receipts,
)
from personal_agent.capabilities.contracts.model import StructuredModelResponse
from personal_agent.governance import ToolExecutor
from personal_agent.governance.policy import PolicyEngine
from personal_agent.application.workspace import InMemoryWorkspaceStore, WorkspaceService
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
    AuthenticatedPrincipal,
    SecurityScope,
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

    def contains_one_of(node) -> bool:
        if isinstance(node, dict):
            return "oneOf" in node or any(contains_one_of(value) for value in node.values())
        if isinstance(node, list):
            return any(contains_one_of(value) for value in node)
        return False

    assert contains_one_of(schema) is False


def test_interaction_prompt_matches_the_object_root_wire_contract():
    prompt = ConversationService(None)._system_prompt(
        EffectiveCapabilities(revision="test"),
        CommittedUsage(),
    )

    assert '{"decision": <FinalMessage | ContinueTurnProposal>}' in prompt
    assert "Never place kind, type, actions, disposition, or message at the root" in prompt
    assert '"disposition": "answer|clarification_required|limitation|failed"' in prompt
    assert '"kind": "continue_turn"' in prompt


def test_prompt_never_asks_the_model_to_run_or_reference_verification():
    """The invariant is the runtime's, so the prompt must not delegate it.

    Wording that tells the model to call a verifier is what the previous design
    relied on, and is exactly the probabilistic enforcement this change removes.
    Its absence is asserted so it cannot drift back in as a "helpful" hint.
    """
    prompt = ConversationService(None)._system_prompt(
        EffectiveCapabilities(revision="test"),
        CommittedUsage(),
        ReviewCriteria(criteria=("no unverifiable occurrence claims",)),
    )

    assert "no unverifiable occurrence claims" in prompt
    assert "verify_interaction_draft" not in prompt
    assert "verified_final_message" not in prompt
    assert "receipt" not in prompt.lower()


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


def _conversation_scope():
    return {
        "principal": AuthenticatedPrincipal(
            tenant_id="tenant-1",
            user_id="default",
        ),
        "security_scope": SecurityScope(
            tenant_id="tenant-1",
            workspace_id="workspace-1",
        ),
    }


def test_l01_observation_drives_next_react_decision_and_user_result():
    def read_fact(query: str):
        return tool_response(tool_success({"fact": f"observed:{query}"}))

    model = _Decisions(
        _continue(ToolCallProposal(action_id="read-1", tool_name="read_fact", arguments={"query": "Orion"})),
        FinalMessage(disposition="answer", message="Orion fact is grounded in the observation."),
    )
    service = ConversationService(model, tool_port=_executor(_tool("read_fact", read_fact)))

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-l01",
        interaction_run_ref="irun_l01",
        messages=[ConversationMessage(role="user", content="Read the Orion fact, then answer.")],
    )
    trace = service.trace("irun_l01")

    assert result.disposition == "answer"
    assert trace is not None
    assert trace.inputs[0].kind == "tool_result"
    assert trace.inputs[0].payload["data"]["fact"] == "observed:Orion"
    next_turn_context = "\n".join(
        message["content"] for message in model.decision_requests[1].messages
    )
    assert "Typed execution inputs" in next_turn_context
    assert "working plan" not in next_turn_context.lower()
    assert trace.final_message is not None


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
    service = ConversationService(model, tool_port=_executor(_tool("read_fact", read_fact)))

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-plan-admission",
        interaction_run_ref="irun-plan-admission",
        messages=[ConversationMessage(role="user", content="Read Orion, then answer.")],
    )
    trace = service.trace("irun-plan-admission")

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
            ToolCallProposal(action_id="left", tool_name="read_left", arguments={"value": "L"}),
            ToolCallProposal(action_id="right", tool_name="read_right", arguments={"value": "R"}),
        ),
        FinalMessage(disposition="answer", message="Both independent reads completed."),
    )
    service = ConversationService(model, tool_port=_executor(
        _tool("read_left", read_left),
        _tool("read_right", read_right),
    ))

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-l02",
        interaction_run_ref="irun_l02",
        messages=[ConversationMessage(role="user", content="Read both independent sources.")],
    )
    trace = service.trace("irun_l02")

    assert trace is not None
    assert trace.concurrent_batches == (("left", "right"),)
    assert trace.execution_order == ("left", "right")


def test_l03_restart_rebuilds_plan_from_durable_facts_without_reexecuting_tool(temp_dir):
    calls = 0

    def read_once(value: str):
        nonlocal calls
        calls += 1
        return tool_response(tool_success({"value": value}))

    messages = [ConversationMessage(role="user", content="Read once and recover after a crash.")]
    first = ConversationService(
        _Decisions(
            _continue(ToolCallProposal(action_id="once", tool_name="read_once", arguments={"value": "fact"})),
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
        FinalMessage(disposition="answer", message="Recovered from the committed fact."),
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
    trace = resumed.trace("irun_l03")
    assert [item.kind for item in trace.inputs] == ["tool_result"]


def test_independent_user_results_instruction_does_not_require_named_capabilities():
    model = _Decisions(FinalMessage(disposition="answer", message="done"))
    service = ConversationService(model, tool_port=_executor())

    service.respond(
        **_conversation_scope(),
        conversation_id="conversation-explicit-reads",
        messages=[ConversationMessage(
            role="user",
            content="Summarize my recent notes and identify any knowledge gaps.",
        )],
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
    gateway = AgentGateway(
        policy_engine=PolicyEngine(), store=InMemoryAgentRunStore()
    )
    specialist = _AsyncSpecialist()
    gateway.register(specialist)
    model = _Decisions(
        _continue(AgentDelegationProposal(
            action_id="specialist-1",
            agent_id="specialist",
            bounded_sub_goal="Research only the bounded Orion question.",
            expected_artifact_types=("report",),
        )),
        FinalMessage(disposition="answer", message="Parent synthesis of the specialist report."),
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
        messages=[ConversationMessage(role="user", content="Delegate the bounded research and synthesize it.")],
    )
    trace = service.trace("irun_l04")

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
    gateway = AgentGateway(
        policy_engine=PolicyEngine(), store=InMemoryAgentRunStore()
    )
    specialist = _AsyncSpecialist()
    gateway.register(specialist)
    model = _Decisions(
        _continue(AgentDelegationProposal(
            action_id="specialist-1",
            agent_id="specialist",
            bounded_sub_goal="Research the bounded question once.",
            expected_artifact_types=("report",),
        )),
        ContinueTurnProposal(actions=(AgentDelegationProposal(
            action_id="specialist-2",
            agent_id="specialist",
            bounded_sub_goal="Research the same requested result again.",
            expected_artifact_types=("report",),
        ),)),
        FinalMessage(disposition="answer", message="Parent synthesis from the first artifact."),
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
        messages=[ConversationMessage(role="user", content="Delegate once, then synthesize.")],
    )
    trace = service.trace("irun-repeat-delegation")

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

    gateway = AgentGateway(
        policy_engine=PolicyEngine(), store=InMemoryAgentRunStore()
    )
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
        FinalMessage(disposition="answer", message="Parent assessed the returned artifact."),
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
        messages=[ConversationMessage(role="user", content="Assess returned evidence without retrying." )],
    )
    trace = service.trace("irun-cancelled-artifact")

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
        _Decisions(_continue(ToolCallProposal(action_id="inspect", tool_name="inspect", arguments={"value": "fact"}))),
        tool_port=_executor(_tool("inspect", inspect)),
        budget_policy=LoopBudgetPolicy(max_model_turns=1),
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-l05",
        interaction_run_ref="irun_l05",
        messages=[ConversationMessage(role="user", content="Keep working past the configured budget.")],
    )

    assert result.disposition == "limitation"
    assert "未生成替代答案" in result.message.content
    assert service.trace("irun_l05").inputs[0].status == "succeeded"


def test_l06_observation_drives_revision_without_rewriting_execution_fact():
    calls = 0

    def verify(draft: str):
        nonlocal calls
        calls += 1
        return tool_response(tool_success({
            "verification_ref": "verify-1",
            "status": "failed",
            "feedback": "cite the observed limitation",
            "draft": draft,
        }))

    model = _Decisions(
        _continue(ToolCallProposal(action_id="verify", tool_name="verify", arguments={"draft": "unsupported"})),
        FinalMessage(disposition="answer", message="Revised answer that states the limitation."),
    )
    service = ConversationService(model, tool_port=_executor(_tool("verify", verify)))
    result = service.respond(
        **_conversation_scope(),
        conversation_id="conversation-l06",
        interaction_run_ref="irun_l06",
        messages=[ConversationMessage(role="user", content="Check the draft, then answer.")],
    )
    trace = service.trace("irun_l06")

    assert calls == 1
    assert result.message.content.startswith("Revised answer")
    assert trace.inputs[0].payload["data"]["status"] == "failed"
    assert trace.execution_order == ("verify",)


def _receipt_payload(draft, *, verdict, criterion="grounded", criteria_digest="0" * 64):
    normalized = draft.strip()
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    return {
        "verdict": verdict,
        "criterion_results": [{
            "criterion": criterion,
            "status": "satisfied" if verdict == "passed" else "not_satisfied",
            "feedback": "" if verdict == "passed" else "revise",
        }],
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
        payload={"ok": True, "data": _receipt_payload(draft, verdict=verdict, **kwargs)},
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
        return tool_response(tool_success(_receipt_payload(
            draft,
            verdict=verdicts[min(len(recorder) - 1, len(verdicts) - 1)],
            criterion=success_criteria[0],
        )))

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
    model = _Decisions(FinalMessage(disposition="answer", message="Orion is a constellation."))
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
    trace = service.trace("irun-no-review")

    assert result.message.content == "Orion is a constellation."
    assert recorder == []
    assert trace.execution_order == ()
    assert trace.review_criteria == ReviewCriteria()


def test_the_real_verifier_is_not_a_capability_the_model_can_see():
    """The model cannot skip a step it does not know exists.

    Exposure is what makes "verification will happen" structural: the capability
    list is the model's only route to a tool, and the production verifier is
    absent from it while remaining callable by the runtime.
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
        ).status == "accepted"
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
    trace = service.trace("irun-runtime-verified")

    assert [draft for draft, _ in recorder] == ["系统已经完成所有写入。", safe]
    assert result.disposition == "answer"
    assert result.message.content == safe
    assert trace.final_message.message == safe
    assert trace.execution_order == ("runtime-verify-0", "runtime-verify-1")
    assert [item.capability_id for item in trace.inputs] == [
        "verify_interaction_draft", "verify_interaction_draft",
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
    trace = service.trace("irun-review-disposition")

    assert [draft for draft, _ in recorder] == [safe]
    assert result.disposition == "answer"
    assert result.message.content == safe
    assert [
        item.reason_code for item in trace.inputs
        if isinstance(item, DecisionFeedback)
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
    trace = service.trace("irun-frozen-criteria")

    criteria_per_call = {criteria for _, criteria in recorder}
    assert criteria_per_call == {("must not claim writes occurred",)}
    assert trace.review_criteria.criteria == ("must not claim writes occurred",)
    assert (
        sum(request.operation == "interaction_review_criteria" for request in model.requests)
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
    trace = service.trace("irun-verifier-missing")

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
    assert service.trace("irun-derivation-failed").review_criteria == ReviewCriteria()


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
        inputs, capability_names=frozenset({"verify_interaction_draft"}),
    )

    assert [receipt.verdict for receipt in receipts] == ["needs_revision", "passed"]
    assert receipts[-1].verified_draft == "final draft"


def test_governed_knowledge_save_recovers_confirms_and_replays_without_duplicate(
    temp_dir,
):
    store = InMemoryWorkspaceStore()
    writer = WorkspaceService(store)
    journal_root = temp_dir / "conversation-knowledge-save"
    messages = [ConversationMessage(
        role="user",
        content="Save this conclusion after confirmation: SLO budgets need weekly review.",
    )]
    first = ConversationService(
        _Decisions(_continue(ToolCallProposal(
            action_id="save-1",
            tool_name="prepare_conversation_knowledge_save",
            arguments={"selections": [{
                "source_message_index": 0,
                "text_span": "SLO budgets need weekly review.",
            }]},
        ))),
        knowledge_writer=writer,
        journal=FileInteractionJournal(journal_root),
    )

    prepared = first.respond(
        **_conversation_scope(),
        conversation_id="workspace-1",
        interaction_run_ref="irun_knowledge_save",
        messages=messages,
    )

    assert prepared.disposition == "confirmation_required"
    assert prepared.pending_confirmation is not None
    assert prepared.pending_confirmation.status == "awaiting_confirmation"
    assert store.list_claims("workspace-1") == []
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
    recovered = resumed.trace("irun_knowledge_save")
    assert recovered is not None
    assert recovered.knowledge_save_operation is not None
    assert recovered.knowledge_save_operation.command == command

    executed = resumed.decide_knowledge_save(
        **_conversation_scope(),
        interaction_run_ref="irun_knowledge_save",
        decision="confirm",
        command_digest=command.command_digest,
        confirmation_ref="unit-user-confirmation",
    )
    claim_count = len(store.list_claims("workspace-1"))
    replayed = resumed.decide_knowledge_save(
        **_conversation_scope(),
        interaction_run_ref="irun_knowledge_save",
        decision="confirm",
        command_digest=command.command_digest,
        confirmation_ref="unit-user-confirmation",
    )

    assert executed.status == "executed"
    assert executed.receipt is not None
    assert replayed.receipt == executed.receipt
    assert len(store.list_claims("workspace-1")) == claim_count
    after_restart = ConversationService(
        None,
        knowledge_writer=writer,
        journal=FileInteractionJournal(journal_root),
    ).trace("irun_knowledge_save")
    assert after_restart is not None
    assert after_restart.knowledge_save_operation == executed


def test_governed_knowledge_save_rejects_without_writing(temp_dir):
    store = InMemoryWorkspaceStore()
    writer = WorkspaceService(store)
    service = ConversationService(
        _Decisions(_continue(ToolCallProposal(
            action_id="save-reject",
            tool_name="prepare_conversation_knowledge_save",
            arguments={"selections": [{
                "source_message_index": 0,
                "text_span": "SLO budgets need weekly review.",
            }]},
        ))),
        knowledge_writer=writer,
        journal=FileInteractionJournal(temp_dir / "conversation-knowledge-save-reject"),
    )
    prepared = service.respond(
        **_conversation_scope(),
        conversation_id="workspace-1",
        interaction_run_ref="irun_knowledge_save_reject",
        messages=[ConversationMessage(
            role="user",
            content=(
                "Conclusion: SLO budgets need weekly review. "
                "Save this only if I confirm."
            ),
        )],
    )
    command = prepared.pending_confirmation.command

    rejected = service.decide_knowledge_save(
        **_conversation_scope(),
        interaction_run_ref="irun_knowledge_save_reject",
        decision="reject",
        command_digest=command.command_digest,
        confirmation_ref="",
    )

    assert rejected.status == "rejected"
    assert rejected.receipt is None
    assert store.list_claims("workspace-1") == []


def test_governed_knowledge_save_rejects_fabricated_selection():
    store = InMemoryWorkspaceStore()
    writer = WorkspaceService(store)
    service = ConversationService(
        _Decisions(
            _continue(ToolCallProposal(
                action_id="save-fabricated",
                tool_name="prepare_conversation_knowledge_save",
                arguments={"selections": [{
                    "source_message_index": 0,
                    "text_span": "A conclusion the user never wrote.",
                }]},
            )),
            FinalMessage(
                disposition="failed",
                message="The requested knowledge span could not be selected.",
            ),
        ),
        knowledge_writer=writer,
    )

    result = service.respond(
        **_conversation_scope(),
        conversation_id="workspace-1",
        interaction_run_ref="irun_knowledge_save_fabricated",
        messages=[ConversationMessage(
            role="user",
            content="Save my SLO conclusion after confirmation.",
        )],
    )
    trace = service.trace("irun_knowledge_save_fabricated")

    assert result.disposition == "failed"
    assert trace is not None
    assert trace.knowledge_save_operation is None
    assert [
        item.reason_code for item in trace.inputs if item.kind == "decision_feedback"
    ] == ["invalid_knowledge_save_source"]
    assert store.list_claims("workspace-1") == []


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

    def invoke(self, task: AgentTask, context: AgentGatewayContext) -> ChildAgentRunOutcome:
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

    def poll(self, run: ChildAgentRunRecord, context: AgentGatewayContext) -> ChildAgentRunRecord:
        self.poll_calls += 1
        status = "completed" if self.poll_calls >= 2 else "running"
        return self._run(
            run.definition.task,
            context,
            status=status,
            agent_run_id=run.definition.agent_run_id,
        )

    def cancel(self, run: ChildAgentRunRecord, context: AgentGatewayContext) -> ChildAgentRunRecord:
        return self._run(run.definition.task, context, status="cancelled", agent_run_id=run.definition.agent_run_id)

    def stream(self, run: ChildAgentRunRecord, context: AgentGatewayContext):
        yield ChildAgentRunEvent(
            event_id=new_agent_event_id(),
            agent_run_id=run.definition.agent_run_id,
            type="stream_delta",
            payload={"delta": "research"},
        )

    def _run(self, task, context, *, status, agent_run_id=None):
        run_id = agent_run_id or new_agent_run_id()
        artifacts = () if status == "running" else (AgentArtifact(
            agent_run_id=run_id,
            kind="report",
            artifact_ref=ResourceRef(
                resource_id=f"artifact-{run_id}",
                resource_type="artifact",
                owner_scope=context.execution_scope.security_scope,
            ),
        ),)
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
            artifact_index=ChildAgentArtifactIndex(agent_run_id=run_id, artifacts=artifacts),
        )


class _ArtifactTexts:
    def read_text(self, resource_ref, *, principal, security_scope):
        if resource_ref.owner_scope != security_scope:
            raise PermissionError("cross-scope test artifact")
        return "bounded specialist evidence"
