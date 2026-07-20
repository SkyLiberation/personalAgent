from __future__ import annotations

from types import SimpleNamespace

from personal_agent.planning.task_analyzer import (
    Goal,
    GoalConstraintDraft,
    ResourceHint,
    SuccessCriterionDraft,
    TaskAnalysis,
)
from personal_agent.planning.task_compiler import GoalGraphCompiler
from personal_agent.runtime.contracts.task import materialize_goals
from personal_agent.runtime.contracts.control import (
    AuthorizationProjection,
    DerivationInvariantResults,
    DerivationRecord,
    ResolvedExecutionCommand,
)
from personal_agent.verification.runtime import ExecutionFactVerifier, GoalVerifier


def _command(digest: str = "execution-command-digest") -> ResolvedExecutionCommand:
    return ResolvedExecutionCommand(
        command_id="command-1",
        accepted_intent_ref="intent-1",
        route="procedure",
        authorization_projection=AuthorizationProjection(
            operation="knowledge.ingest",
            user_visible_payload="Gamma-Live-E2E-7319 的发布窗口是周五 20:00",
            requested_result_contract="external_state",
            side_effect_envelope="mutation",
        ),
        authorization_digest="authorization-digest",
        execution_command_digest=digest,
        derivation_record=DerivationRecord(
            derivation_kind="command_resolution",
            source_contract_refs=("intent-1",),
            rule_id="mandatory-knowledge-route",
            rule_version="v1",
            policy_snapshot_ref="policy:v1",
            source_digests=("intent-digest",),
            output_ref="command-1",
            output_digest=digest,
            invariant_results=DerivationInvariantResults(
                route_uniqueness="passed",
                authorization_projection_preserved="passed",
            ),
            uniqueness_kind="single_policy_allowed_route",
        ),
    )


def test_mutation_receipt_fact_cannot_be_downgraded_by_semantic_verifier() -> None:
    class InconclusiveSemanticClient:
        def generate(self, request):
            return SimpleNamespace(value=request.output_type(judgments=[{
                "criterion_id": "goal_1:result:1",
                "status": "inconclusive",
                "reason_code": "insufficient_evidence",
            }]))

    release_fact = "Gamma-Live-E2E-7319 的发布窗口是周五 20:00"
    constraint = "只将用户给出的句子作为待写入内容，不添加推断信息。"
    compilation = GoalGraphCompiler().compile(TaskAnalysis(
        user_goal=f"把“{release_fact}”记入知识库",
        goals=[Goal(
            goal_id="goal_1",
            description=f"将“{release_fact}”记入知识库。",
            result_contract="external_state",
            success_criteria=[SuccessCriterionDraft(
                description="该句已作为知识条目被写入。",
                origin="model_inferred",
            )],
            constraints=[GoalConstraintDraft(
                description=constraint,
                origin="model_inferred",
            )],
            side_effect_intent="mutation",
            resource_hints=[ResourceHint(
                semantic_domain="knowledge",
                resource_types=["text"],
                operations=["ingest"],
            )],
        )],
    ), f"把“{release_fact}”记入知识库")
    goal = materialize_goals(compilation.task_contract, compilation.runtime)[0]
    command = _command()
    tool_results = ({
        "ok": True,
        "note_id": "note-1",
        "_execution_command_digest": command.execution_command_digest,
    },)
    execution_fact = ExecutionFactVerifier().verify(command, tool_results)

    report = GoalVerifier(InconclusiveSemanticClient()).verify(
        compilation.task_contract,
        goal,
        answer="写入操作已完成。",
        citation_count=0,
        tool_results=tool_results,
        execution_fact_report=execution_fact,
        model_context={"projection_id": "verify-context"},
    )

    assert execution_fact.status == "passed"
    assert execution_fact.receipt_refs == ("note-1",)
    # The receipt fact stays passed, but it does not prove the separate
    # semantic criterion; therefore the goal as a whole remains inconclusive.
    assert report.status == "inconclusive"
    assert {
        item.criterion_id: item.reason_code for item in report.checked_criteria
    } == {
        "goal_1:result:1": "insufficient_evidence",
        "goal_1:receipt": "execution_fact_and_receipt_passed",
    }


def test_mutation_receipt_with_wrong_command_digest_fails_closed() -> None:
    command = _command()

    report = ExecutionFactVerifier().verify(command, ({
        "ok": True,
        "note_id": "note-1",
        "_execution_command_digest": "different-command-digest",
    },))

    assert report.status == "failed"
    assert report.receipt_refs == ()
    assert report.reason_codes == ("execution_command_digest_mismatch",)
