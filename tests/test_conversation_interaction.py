from __future__ import annotations

from hashlib import sha256
from threading import Barrier

import pytest
from langchain_core.tools import StructuredTool

from personal_agent.agents import AgentGateway
from personal_agent.application.conversation import (
    AgentDelegationProposal,
    AgentTurnDecision,
    ContinueTurnProposal,
    ConversationMessage,
    ConversationService,
    FileInteractionJournal,
    FinalMessage,
    LoopBudgetPolicy,
    ToolCallProposal,
    WorkingPlanSnapshot,
)
from personal_agent.application.conversation.models import (
    CommittedUsage,
    EffectiveCapabilities,
)
from personal_agent.capabilities.contracts.model import StructuredModelResponse
from personal_agent.governance import ToolExecutor
from personal_agent.governance.policy import PolicyEngine
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
    new_agent_artifact_id,
    new_agent_event_id,
    new_agent_run_id,
)
from personal_agent.kernel.llm_schemas import strictify_schema
from personal_agent.tools.base import governance_extras, tool_response, tool_success


class _Decisions:
    def __init__(self, *items) -> None:
        self.items = list(items)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return StructuredModelResponse(
            value=AgentTurnDecision(decision=item),
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
        False,
    )

    assert '{"decision": <FinalMessage | ContinueTurnProposal>}' in prompt
    assert "Never place kind, type, working_plan, actions, disposition, or message at the root" in prompt
    assert '"disposition": "answer|clarification_required|limitation|failed"' in prompt
    assert '"kind": "continue_turn"' in prompt


def _tool(name, function, *, side_effects=("none",)):
    return StructuredTool.from_function(
        func=function,
        name=name,
        description=f"Contract tool {name}",
        response_format="content_and_artifact",
        extras=governance_extras(
            side_effects=side_effects,
            permission_scope=f"test:{name}",
            timeout_seconds=5,
        ),
    )


def _executor(*tools):
    executor = ToolExecutor(policy_engine=PolicyEngine())
    for item in tools:
        executor.register(item)
    return executor


def _continue(*actions, reason="initial"):
    return ContinueTurnProposal(
        working_plan=WorkingPlanSnapshot(
            summary="collect facts",
            remaining_work=("inspect observations",),
            revision_reason=reason,
        ),
        actions=actions,
    )


def test_l01_observation_revises_transient_plan_and_returns_user_result():
    def read_fact(query: str):
        return tool_response(tool_success({"fact": f"observed:{query}"}))

    model = _Decisions(
        _continue(ToolCallProposal(action_id="read-1", tool_name="read_fact", arguments={"query": "Orion"})),
        FinalMessage(disposition="answer", message="Orion fact is grounded in the observation."),
    )
    service = ConversationService(model, tool_port=_executor(_tool("read_fact", read_fact)))

    result = service.respond(
        conversation_id="conversation-l01",
        interaction_run_ref="irun_l01",
        messages=[ConversationMessage(role="user", content="Read the Orion fact, then answer.")],
    )
    trace = service.trace("irun_l01")

    assert result.disposition == "answer"
    assert trace is not None
    assert trace.inputs[0].kind == "tool_result"
    assert trace.inputs[0].payload["data"]["fact"] == "observed:Orion"
    next_turn_context = "\n".join(message["content"] for message in model.requests[1].messages)
    assert "Typed execution inputs" in next_turn_context
    assert "Current model-authored working plan" in next_turn_context
    assert '"summary":"collect facts"' in next_turn_context
    assert trace.final_message is not None


def test_initial_action_without_working_plan_is_rejected_before_execution():
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
        _continue(action),
        FinalMessage(disposition="answer", message="Observed Orion."),
    )
    service = ConversationService(model, tool_port=_executor(_tool("read_fact", read_fact)))

    service.respond(
        conversation_id="conversation-plan-admission",
        interaction_run_ref="irun-plan-admission",
        messages=[ConversationMessage(role="user", content="Read Orion, then answer.")],
    )
    trace = service.trace("irun-plan-admission")

    assert calls == 1
    assert trace is not None
    assert trace.working_plans
    assert any(
        item.kind == "decision_feedback" and item.reason_code == "working_plan_required"
        for item in trace.inputs
    )


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
            conversation_id="conversation-l03",
            interaction_run_ref="irun_l03",
            messages=messages,
        )

    resumed_model = _Decisions(
        FinalMessage(disposition="answer", message="Premature final without rebuilt context."),
        ContinueTurnProposal(
            working_plan=WorkingPlanSnapshot(
                summary="rebuild from committed observation",
                remaining_work=("answer from committed fact",),
                revision_reason="context_rebuild",
            ),
            actions=(),
        ),
        FinalMessage(disposition="answer", message="Recovered from the committed fact."),
    )
    resumed = ConversationService(
        resumed_model,
        tool_port=_executor(_tool("read_once", read_once)),
        journal=FileInteractionJournal(temp_dir / "interaction-l03"),
    )
    result = resumed.respond(
        conversation_id="conversation-l03",
        interaction_run_ref="irun_l03",
        messages=messages,
    )

    assert result.disposition == "answer"
    assert calls == 1
    assert "revision_reason=context_rebuild" in resumed_model.requests[0].messages[0]["content"]
    trace = resumed.trace("irun_l03")
    assert trace.working_plans[0].revision_reason == "context_rebuild"
    assert any(
        item.kind == "decision_feedback"
        and item.reason_code == "context_rebuild_plan_required"
        for item in trace.inputs
    )


def test_explicit_independent_read_instruction_is_visible_to_model():
    model = _Decisions(FinalMessage(disposition="answer", message="done"))
    service = ConversationService(model, tool_port=_executor())

    service.respond(
        conversation_id="conversation-explicit-reads",
        messages=[ConversationMessage(role="user", content="Call two named read tools together.")],
    )

    system_prompt = model.requests[0].messages[0]["content"]
    assert "multiple named available read-only capabilities" in system_prompt
    assert model.requests[0].temperature == 0


def test_interaction_delegation_budget_cannot_exceed_synchronous_policy_limit():
    with pytest.raises(ValueError, match="less than or equal to 180"):
        AgentDelegationProposal(
            agent_id="specialist",
            bounded_sub_goal="Research a bounded question.",
            time_budget_seconds=181,
        )


def test_l04_parent_synthesizes_async_specialist_artifact_without_child_completion_shortcut():
    gateway = AgentGateway(policy_engine=PolicyEngine())
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
    service = ConversationService(model, agent_port=gateway)

    result = service.respond(
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
    gateway = AgentGateway(policy_engine=PolicyEngine())
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
    service = ConversationService(model, agent_port=gateway)

    result = service.respond(
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
    assert "produce the parent synthesis" in model.requests[1].messages[0]["content"]


def test_cancelled_child_artifact_remains_visible_and_rejects_duplicate_delegation():
    class _CancelledSpecialist(_AsyncSpecialist):
        def submit(self, task: AgentTask, context: AgentGatewayContext) -> ChildAgentRunRecord:
            self.submit_calls += 1
            return self._run(task, context, status="cancelled")

    gateway = AgentGateway(policy_engine=PolicyEngine())
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
    service = ConversationService(model, agent_port=gateway)

    result = service.respond(
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
        conversation_id="conversation-l05",
        interaction_run_ref="irun_l05",
        messages=[ConversationMessage(role="user", content="Keep working past the configured budget.")],
    )

    assert result.disposition == "limitation"
    assert "未生成替代答案" in result.message.content
    assert service.trace("irun_l05").inputs[0].status == "succeeded"


def test_l06_verifier_feedback_revises_answer_without_rewriting_execution_fact():
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
        conversation_id="conversation-l06",
        interaction_run_ref="irun_l06",
        messages=[ConversationMessage(role="user", content="Verify and revise the draft.")],
    )
    trace = service.trace("irun_l06")

    assert calls == 1
    assert result.message.content.startswith("Revised answer")
    assert trace.inputs[0].payload["data"]["status"] == "failed"
    assert trace.execution_order == ("verify",)
    assert "do not repeat a rejected claim verbatim" in model.requests[1].messages[0]["content"]


def test_answer_is_bound_to_latest_passed_verification_receipt():
    calls: list[str] = []
    revised = "Only observed facts are reported."

    def verify_interaction_draft(
        draft: str,
        success_criteria: tuple[str, ...],
        evidence_refs: tuple[str, ...] = (),
    ):
        calls.append(draft)
        verdict = "needs_revision" if len(calls) == 1 else "passed"
        return tool_response(tool_success({
            "verdict": verdict,
            "criterion_results": [{
                "criterion": success_criteria[0],
                "status": "not_satisfied" if verdict == "needs_revision" else "satisfied",
                "feedback": "revise" if verdict == "needs_revision" else "",
            }],
            "revision_feedback": "revise" if verdict == "needs_revision" else "",
            "verified_draft": draft.strip(),
            "draft_digest": sha256(draft.strip().encode("utf-8")).hexdigest(),
            "criteria_digest": "0" * 64,
        }))

    first = ToolCallProposal(
        action_id="verify-bad",
        tool_name="verify_interaction_draft",
        arguments={"draft": "unsupported", "success_criteria": ["grounded"]},
    )
    second = ToolCallProposal(
        action_id="verify-revised",
        tool_name="verify_interaction_draft",
        arguments={"draft": revised, "success_criteria": ["grounded"]},
    )
    redundant = ToolCallProposal(
        action_id="verify-redundant",
        tool_name="verify_interaction_draft",
        arguments={"draft": "unsupported", "success_criteria": ["grounded"]},
    )
    model = _Decisions(
        _continue(first),
        FinalMessage(disposition="answer", message="premature"),
        ContinueTurnProposal(actions=(second,)),
        ContinueTurnProposal(actions=(redundant,)),
        FinalMessage(disposition="answer", message="different text"),
        FinalMessage(disposition="answer", message=revised),
    )
    service = ConversationService(
        model,
        tool_port=_executor(_tool("verify_interaction_draft", verify_interaction_draft)),
    )

    result = service.respond(
        conversation_id="conversation-verification-binding",
        interaction_run_ref="irun-verification-binding",
        messages=[ConversationMessage(role="user", content="Verify the exact final draft.")],
    )
    trace = service.trace("irun-verification-binding")

    assert calls == ["unsupported", revised]
    assert result.message.content == revised
    assert trace is not None
    assert [
        item.reason_code for item in trace.inputs if item.kind == "decision_feedback"
    ] == [
        "verification_required",
        "verified_draft_ready",
        "verified_draft_mismatch",
    ]


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

    def submit(self, task: AgentTask, context: AgentGatewayContext) -> ChildAgentRunRecord:
        self.submit_calls += 1
        return self._run(task, context, status="running")

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
            artifact_id=new_agent_artifact_id(),
            agent_run_id=run_id,
            kind="report",
            content="bounded specialist evidence",
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
