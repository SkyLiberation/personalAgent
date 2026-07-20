from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from personal_agent.capabilities.contracts.model import StructuredModelResponse
from personal_agent.kernel.models import ArtifactRef, EntryInput
from personal_agent.planning.task_analyzer import (
    ClarificationDraft,
    DefaultTaskAnalyzer,
    EvidenceRequirement,
    GoalDraft,
    GoalConstraintDraft,
    GoalRelationDraft,
    ResourceHint,
    SuccessCriterionDraft,
    TaskAnalysisProposalBody,
    TaskAnalysisGroundingClaim,
    TaskAnalysisProposal,
    describe_task_analysis,
)
from personal_agent.planning.task_analysis_admission import (
    TaskAnalysisAdmission,
    task_analysis_input_digest,
)


def _criterion(description: str) -> SuccessCriterionDraft:
    return SuccessCriterionDraft(description=description, origin="model_inferred")


class TestTaskAnalysisProposalBodyContract:
    def test_ready_requires_goals(self):
        with pytest.raises(ValidationError, match="requires at least one goal"):
            TaskAnalysisProposalBody(user_goal="回答问题", outcome="ready")

    def test_ready_rejects_clarification(self):
        with pytest.raises(ValidationError, match="cannot clarify"):
            TaskAnalysisProposalBody(
                user_goal="回答问题",
                outcome="ready",
                goals=[GoalDraft(
                    description="问题",
                    success_criteria=[_criterion("准确回答问题")],
                    result_contract="response",
                    evidence_requirement=EvidenceRequirement(citation_required=True),
                    resource_hints=[ResourceHint(
                        semantic_domain="knowledge",
                        resource_types=["note"],
                        operations=["search", "read"],
                    )],
                )],
                clarification=ClarificationDraft(
                    missing_information=["x"],
                    prompt="补充 x",
                ),
            )

    def test_clarify_requires_question_and_no_goals(self):
        with pytest.raises(ValidationError, match="requires clarification"):
            TaskAnalysisProposalBody(user_goal="理解目标", outcome="clarify")

    def test_relation_indexes_must_reference_goals(self):
        with pytest.raises(ValidationError, match="unknown 1-based goal index"):
            TaskAnalysisProposalBody(
                user_goal="非法关系",
                outcome="ready",
                goals=[GoalDraft(
                    description="唯一目标",
                    success_criteria=[_criterion("完成唯一目标")],
                )],
                relations=[GoalRelationDraft(
                    predecessor=1,
                    successor=2,
                    kind="consumes_output",
                    rationale="不存在第二个目标",
                )],
            )

    def test_schema_contains_task_understanding_not_execution_policy(self):
        properties = set(TaskAnalysisProposalBody.model_json_schema()["properties"])
        assert properties == {
            "user_goal", "outcome", "goals", "relations",
            "clarification", "rejection_reason", "grounding_claims",
        }
        assert properties.isdisjoint({
            "route_type", "coverage", "workflow", "tool", "capability",
        })


class TestDefaultTaskAnalyzer:
    def test_model_analysis_normalizes_goal_ids_and_typed_relations(self):
        output = TaskAnalysisProposalBody(
            user_goal="记录事实并基于该事实回答",
            outcome="ready",
            goals=[
                GoalDraft(
                    description="记录 DNS 事实",
                    success_criteria=[_criterion("指定事实已写入")],
                    result_contract="external_state",
                    side_effect_intent="mutation",
                    resource_hints=[ResourceHint(
                        semantic_domain="knowledge",
                        resource_types=["text"],
                        operations=["ingest"],
                    )],
                ),
                GoalDraft(
                    description="解释 DNS 缓存",
                    success_criteria=[_criterion("解释 DNS 缓存机制")],
                    result_contract="response",
                    evidence_requirement=EvidenceRequirement(citation_required=True),
                    resource_hints=[ResourceHint(
                        semantic_domain="knowledge",
                        resource_types=["note"],
                        operations=["search", "read"],
                    )],
                ),
            ],
            relations=[GoalRelationDraft(
                predecessor=1,
                successor=2,
                kind="consumes_output",
                origin="model_inferred",
                rationale="回答明确要求基于刚记录的事实",
            )],
        )

        class FakeClient:
            request = None

            def generate(self, request):
                self.request = request
                return StructuredModelResponse(value=output, model="analyzer", latency_ms=1)

        client = FakeClient()
        result = DefaultTaskAnalyzer(client).analyze(EntryInput(text="复合请求"))
        assert result.accepted is not None
        analysis = result.accepted.analysis

        assert [goal.goal_id for goal in analysis.goals] == ["goal_1", "goal_2"]
        assert analysis.goals[0].result_contract == "external_state"
        assert analysis.goals[1].result_contract == "response"
        assert analysis.relations[0].predecessor_goal_id == "goal_1"
        assert analysis.relations[0].successor_goal_id == "goal_2"
        assert client.request.output_type is TaskAnalysisProposalBody
        assert client.request.operation == "task_analysis"

    def test_model_receives_artifact_metadata_without_structural_classification(self):
        output = TaskAnalysisProposalBody(
            user_goal="理解附件",
            outcome="ready",
            goals=[GoalDraft(
                description="概述附件",
                success_criteria=[_criterion("概述覆盖附件核心内容")],
                result_contract="artifact",
                evidence_requirement=EvidenceRequirement(citation_required=True),
                resource_hints=[ResourceHint(
                    semantic_domain="artifact",
                    resource_types=["document"],
                    operations=["read"],
                )],
            )],
        )

        class FakeClient:
            request = None

            def generate(self, request):
                self.request = request
                return StructuredModelResponse(value=output, model="analyzer", latency_ms=1)

        client = FakeClient()
        result = DefaultTaskAnalyzer(client).analyze(EntryInput(
            text="总结附件",
            artifacts=[_artifact()],
        ))
        assert result.accepted is not None
        analysis = result.accepted.analysis
        assert analysis.goals[0].result_contract == "artifact"
        assert "paper.pdf" in client.request.messages[-1]["content"]

    def test_empty_entry_requests_structural_clarification(self):
        result = DefaultTaskAnalyzer(None).analyze(EntryInput(text=""))
        assert result.accepted is not None
        analysis = result.accepted.analysis
        assert analysis.outcome == "clarify"
        assert analysis.error is None

    def test_missing_model_does_not_fall_back_to_keyword_routing(self):
        result = DefaultTaskAnalyzer(None).analyze(EntryInput(
            text="删除关于 DNS 的知识",
        ))
        assert result.accepted is not None
        analysis = result.accepted.analysis
        assert analysis.outcome == "clarify"
        assert analysis.error == "analyzer_unavailable"
        assert not analysis.goals

    def test_logs_analysis_strategy(self, caplog):
        caplog.set_level(logging.INFO)
        DefaultTaskAnalyzer(None).analyze(EntryInput(text="解释 DNS", user_id="alice"))
        assert "task_analysis.completed" in caplog.text
        assert '"strategy": "analyzer_unavailable"' in caplog.text

    def test_description_uses_goal_language(self):
        output = TaskAnalysisProposalBody(
            user_goal="解释服务降级",
            outcome="ready",
            goals=[GoalDraft(
                description="解释服务降级",
                success_criteria=[_criterion("解释服务降级的含义")],
                result_contract="response",
            )],
        )

        class FakeClient:
            def generate(self, _request):
                return StructuredModelResponse(value=output, model="analyzer", latency_ms=1)

        result = DefaultTaskAnalyzer(FakeClient()).analyze(EntryInput(text="什么是服务降级"))
        assert describe_task_analysis(result.accepted) == "已识别目标：解释服务降级"


def test_user_explicit_task_semantics_require_identity_grounding() -> None:
    text = "只记录 Orion 发布窗口是周五 20:00"
    entry = EntryInput(text=text)
    body = TaskAnalysisProposalBody(
        user_goal=text,
        outcome="ready",
        goals=[GoalDraft(
            description="记录发布窗口",
            result_contract="external_state",
            success_criteria=[_criterion("事实已写入")],
            constraints=[GoalConstraintDraft(
                description="Orion 发布窗口是周五 20:00",
                origin="user_explicit",
            )],
            side_effect_intent="mutation",
            resource_hints=[ResourceHint(
                semantic_domain="knowledge",
                resource_types=["text"],
                operations=["ingest"],
            )],
        )],
    )
    proposal = TaskAnalysisProposal(
        input_ref="entry:test",
        input_digest=task_analysis_input_digest(entry),
        body=body,
    )

    admission = TaskAnalysisAdmission().admit(entry, proposal)

    assert admission.verdict == "not_accepted"
    assert admission.reason_codes == ("task_analysis_grounding_required",)
    assert admission.feedback is not None
    assert admission.feedback.revision_scope == "grounding_only"


def test_grounding_only_task_revision_cannot_change_semantics() -> None:
    text = "Orion 发布窗口是周五 20:00"
    entry = EntryInput(text=text)
    first_body = TaskAnalysisProposalBody(
        user_goal=text,
        outcome="ready",
        goals=[GoalDraft(
            description="记录发布窗口",
            result_contract="external_state",
            success_criteria=[_criterion("事实已写入")],
            constraints=[GoalConstraintDraft(description=text, origin="user_explicit")],
            side_effect_intent="mutation",
            resource_hints=[ResourceHint(
                semantic_domain="knowledge",
                resource_types=["text"],
                operations=["ingest"],
            )],
        )],
    )
    first = TaskAnalysisProposal(
        input_ref="entry:test",
        input_digest=task_analysis_input_digest(entry),
        body=first_body,
    )
    denial = TaskAnalysisAdmission().admit(entry, first)
    assert denial.feedback is not None
    changed_body = first_body.model_copy(update={
        "user_goal": "记录另一个事实",
        "grounding_claims": (TaskAnalysisGroundingClaim(
            source_text=text,
            output_field_ref="goals.0.constraints.0.description",
        ),),
    })
    revised = TaskAnalysisProposal(
        input_ref="entry:test",
        input_digest=task_analysis_input_digest(entry),
        body=changed_body,
        supersedes_proposal_ref=first.proposal_id,
        revision_feedback_ref=denial.feedback.feedback_id,
        revision_attempt=1,
    )

    admission = TaskAnalysisAdmission().admit(
        entry,
        revised,
        prior_proposal=first,
        revision_feedback=denial.feedback,
    )

    assert admission.verdict == "not_accepted"
    assert "task_analysis_revision_scope_exceeded" in admission.reason_codes


def test_task_analyzer_revises_denied_grounding_and_preserves_attempt_audit() -> None:
    text = "Orion 发布窗口是周五 20:00"
    constraint = GoalConstraintDraft(description=text, origin="user_explicit")
    goal = GoalDraft(
        description="记录发布窗口",
        result_contract="external_state",
        success_criteria=[_criterion("事实已写入")],
        constraints=[constraint],
        side_effect_intent="mutation",
        resource_hints=[ResourceHint(
            semantic_domain="knowledge",
            resource_types=["text"],
            operations=["ingest"],
        )],
    )
    bodies = [
        TaskAnalysisProposalBody(user_goal=text, outcome="ready", goals=[goal]),
        TaskAnalysisProposalBody(
            user_goal=text,
            outcome="ready",
            goals=[goal],
            grounding_claims=(TaskAnalysisGroundingClaim(
                source_text=text,
                output_field_ref="goals.0.constraints.0.description",
            ),),
        ),
    ]

    class RevisingClient:
        def generate(self, _request):
            return StructuredModelResponse(
                value=bodies.pop(0),
                model="analyzer",
                latency_ms=1,
            )

    result = DefaultTaskAnalyzer(RevisingClient()).analyze(EntryInput(text=text))

    assert result.accepted is not None
    assert len(result.attempts) == 2
    assert result.attempts[0].admission.verdict == "not_accepted"
    assert result.attempts[1].admission.verdict == "accepted"
    assert result.attempts[1].proposal.supersedes_proposal_ref == (
        result.attempts[0].proposal.proposal_id
    )


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="art-test",
        filename="paper.pdf",
        content_type="application/pdf",
        source_type="pdf",
        file_path="/tmp/paper.pdf",
        size_bytes=123,
    )
