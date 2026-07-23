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
                    resource_types=["file", "artifact"],
                    operations=["read"],
                    locator="art-test",
                    origin="user_explicit",
                )],
            )],
            grounding_claims=(TaskAnalysisGroundingClaim(
                source_text="art-test",
                output_field_ref="goals.0.resource_hints.0.locator",
            ),),
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
        assert analysis.goals[0].resource_hints[0].locator == "art-test"
        assert "paper.pdf" in client.request.messages[-1]["content"]
        assert "semantic_domain=artifact" in client.request.messages[0]["content"]
        assert "附件不是 conversation" in client.request.messages[0]["content"]

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


def test_mutating_resource_hint_cannot_be_admitted_as_a_response_goal() -> None:
    entry = EntryInput(text="把 Orion 发布窗口记入知识库，然后告诉我发布时间")
    proposal = TaskAnalysisProposal(
        input_ref="entry:test",
        input_digest=task_analysis_input_digest(entry),
        body=TaskAnalysisProposalBody(
            user_goal=entry.text,
            outcome="ready",
            goals=[GoalDraft(
                description="记录并回答发布窗口",
                result_contract="response",
                success_criteria=[_criterion("给出发布时间")],
                resource_hints=[ResourceHint(
                    semantic_domain="knowledge",
                    resource_types=["text"],
                    operations=["ingest", "read"],
                )],
            )],
        ),
    )

    admission = TaskAnalysisAdmission().admit(entry, proposal)

    assert admission.verdict == "not_accepted"
    assert admission.reason_codes == ("task_analysis_mutation_contract_required",)
    assert admission.feedback is not None
    assert admission.feedback.revision_scope == "semantic_revision"


def test_read_only_resource_hint_cannot_be_admitted_as_a_mutation_goal() -> None:
    entry = EntryInput(text="读取架构文档并回答标题")
    proposal = TaskAnalysisProposal(
        input_ref="entry:test",
        input_digest=task_analysis_input_digest(entry),
        body=TaskAnalysisProposalBody(
            user_goal=entry.text,
            outcome="ready",
            goals=[GoalDraft(
                description="读取架构文档并回答标题",
                result_contract="external_state",
                success_criteria=[_criterion("给出文档标题")],
                side_effect_intent="mutation",
                resource_hints=[ResourceHint(
                    semantic_domain="artifact",
                    resource_types=["file"],
                    operations=["read"],
                )],
            )],
        ),
    )

    admission = TaskAnalysisAdmission().admit(entry, proposal)

    assert admission.verdict == "not_accepted"
    assert admission.reason_codes == ("task_analysis_mutation_operation_required",)
    assert admission.feedback is not None
    assert admission.feedback.revision_scope == "semantic_revision"


def test_delegation_artifact_cannot_be_admitted_as_external_state_mutation() -> None:
    entry = EntryInput(text="委派外部 Agent 研究 A2A 并返回报告")
    proposal = TaskAnalysisProposal(
        input_ref="entry:test",
        input_digest=task_analysis_input_digest(entry),
        body=TaskAnalysisProposalBody(
            user_goal=entry.text,
            outcome="ready",
            goals=[GoalDraft(
                description=entry.text,
                result_contract="external_state",
                success_criteria=[_criterion("返回研究报告")],
                side_effect_intent="mutation",
                resource_hints=[ResourceHint(
                    semantic_domain="external",
                    resource_types=["report"],
                    operations=["delegate"],
                )],
            )],
        ),
    )

    admission = TaskAnalysisAdmission().admit(entry, proposal)

    assert admission.verdict == "not_accepted"
    assert admission.reason_codes == ("task_analysis_mutation_operation_required",)


def test_resource_locator_cannot_also_be_a_constraint_identity() -> None:
    path = r"D:\docs\architecture.md"
    entry = EntryInput(text=f"读取文件 {path}")
    proposal = TaskAnalysisProposal(
        input_ref="entry:test",
        input_digest=task_analysis_input_digest(entry),
        body=TaskAnalysisProposalBody(
            user_goal=entry.text,
            outcome="ready",
            goals=[GoalDraft(
                description="读取架构文档",
                result_contract="response",
                success_criteria=[_criterion("返回文档内容")],
                constraints=[GoalConstraintDraft(
                    description=path,
                    origin="user_explicit",
                )],
                resource_hints=[ResourceHint(
                    semantic_domain="artifact",
                    resource_types=["file"],
                    operations=["read"],
                    locator=path,
                    origin="user_explicit",
                )],
            )],
            grounding_claims=(
                TaskAnalysisGroundingClaim(
                    source_text=path,
                    output_field_ref="goals.0.constraints.0.description",
                ),
                TaskAnalysisGroundingClaim(
                    source_text=path,
                    output_field_ref="goals.0.resource_hints.0.locator",
                ),
            ),
        ),
    )

    admission = TaskAnalysisAdmission().admit(entry, proposal)

    assert admission.verdict == "not_accepted"
    assert admission.reason_codes == ("task_analysis_duplicate_resource_identity",)
    assert admission.feedback is not None
    assert admission.feedback.rejected_field_refs == ("goals.0.constraints.0",)
    assert admission.feedback.revision_scope == "semantic_revision"


def test_delete_with_explicit_canonical_id_requires_grounded_resource_locator() -> None:
    note_id = "d6113b10-29d9-4d77-bfae-31e49106dfd6"
    entry = EntryInput(text=f"删除知识库中 ID 为 {note_id} 的笔记。")
    missing_locator = TaskAnalysisProposal(
        input_ref="entry:test",
        input_digest=task_analysis_input_digest(entry),
        body=TaskAnalysisProposalBody(
            user_goal=entry.text,
            outcome="ready",
            goals=[GoalDraft(
                description="删除指定笔记",
                result_contract="external_state",
                success_criteria=[_criterion("指定笔记已删除")],
                side_effect_intent="mutation",
                resource_hints=[ResourceHint(
                    semantic_domain="knowledge",
                    resource_types=["note"],
                    operations=["delete"],
                )],
            )],
        ),
    )

    denied = TaskAnalysisAdmission().admit(entry, missing_locator)

    assert denied.verdict == "not_accepted"
    assert denied.reason_codes == ("task_analysis_explicit_identity_required",)
    assert denied.feedback is not None
    assert denied.feedback.revision_scope == "semantic_revision"

    accepted = TaskAnalysisProposal(
        input_ref="entry:test",
        input_digest=task_analysis_input_digest(entry),
        body=TaskAnalysisProposalBody(
            user_goal=entry.text,
            outcome="ready",
            goals=[GoalDraft(
                description="删除指定笔记",
                result_contract="external_state",
                success_criteria=[_criterion("指定笔记已删除")],
                side_effect_intent="mutation",
                resource_hints=[ResourceHint(
                    semantic_domain="knowledge",
                    resource_types=["note"],
                    operations=["delete"],
                    locator=note_id,
                    origin="user_explicit",
                )],
            )],
            grounding_claims=(TaskAnalysisGroundingClaim(
                source_text=note_id,
                output_field_ref="goals.0.resource_hints.0.locator",
            ),),
        ),
    )

    admitted = TaskAnalysisAdmission().admit(entry, accepted)

    assert admitted.verdict == "accepted"


def test_uploaded_artifact_requires_its_grounded_canonical_id() -> None:
    artifact = _artifact()
    entry = EntryInput(text="总结附件", artifacts=[artifact])

    def proposal(locator: str) -> TaskAnalysisProposal:
        return TaskAnalysisProposal(
            input_ref="entry:test",
            input_digest=task_analysis_input_digest(entry),
            body=TaskAnalysisProposalBody(
                user_goal=entry.text,
                outcome="ready",
                goals=[GoalDraft(
                    description="总结附件",
                    result_contract="response",
                    success_criteria=[_criterion("回答覆盖附件内容")],
                    resource_hints=[ResourceHint(
                        semantic_domain="artifact",
                        resource_types=["file", "artifact"],
                        operations=["read"],
                        locator=locator,
                        origin="user_explicit",
                    )],
                )],
                grounding_claims=(TaskAnalysisGroundingClaim(
                    source_text=locator,
                    output_field_ref="goals.0.resource_hints.0.locator",
                ),),
            ),
        )

    filename_denial = TaskAnalysisAdmission().admit(
        entry, proposal(artifact.filename),
    )
    accepted = TaskAnalysisAdmission().admit(
        entry, proposal(artifact.artifact_id),
    )

    assert filename_denial.verdict == "not_accepted"
    assert "task_analysis_grounding_source_unknown" in filename_denial.reason_codes
    assert "task_analysis_artifact_identity_required" in filename_denial.reason_codes
    assert accepted.verdict == "accepted"


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
    body = TaskAnalysisProposalBody(user_goal=text, outcome="ready", goals=[goal])
    requests = []

    class RevisingClient:
        def generate(self, request):
            requests.append(request)
            if request.operation == "task_analysis_grounding_revision":
                value = request.output_type.model_validate({
                    "repairs": [{
                        "output_field_ref": "goals.0.constraints.0.description",
                        "include_identity_claim": True,
                    }],
                })
            else:
                value = body
            return StructuredModelResponse(
                value=value,
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
    revision_prompt = requests[1].messages[-1]["content"]
    assert requests[1].operation == "task_analysis_grounding_revision"
    assert requests[1].output_type.__name__ == "_TaskAnalysisGroundingRevision"
    assert '"rejected_field_refs"' in revision_prompt
    assert '"immutable_proposal_body"' in revision_prompt
    revision_system = requests[1].messages[0]["content"]
    assert "exactly one repair for every rejected_field_ref" in revision_system
    assert "include_identity_claim=true" in revision_system


def test_task_analyzer_repairs_provider_grounding_without_rewriting_semantics() -> None:
    text = "请通过 provider gpt_researcher 委派外部 Agent 研究 A2A"
    provider_ref = "goals.0.resource_hints.0.user_required_provider"
    initial = TaskAnalysisProposalBody(
        user_goal=text,
        outcome="ready",
        goals=[GoalDraft(
            description="委派外部 Agent 研究 A2A",
            result_contract="artifact",
            success_criteria=[_criterion("返回研究报告")],
            side_effect_intent="none",
            resource_hints=[ResourceHint(
                semantic_domain="external",
                resource_types=["report"],
                operations=["delegate"],
                user_required_provider="gpt_researcher",
                origin="user_explicit",
            )],
        )],
        grounding_claims=(TaskAnalysisGroundingClaim(
            source_text="provider gpt_researcher",
            output_field_ref=provider_ref,
        ),),
    )
    requests = []

    class RevisingClient:
        def generate(self, request):
            requests.append(request)
            if request.operation == "task_analysis_grounding_revision":
                value = request.output_type.model_validate({
                    "repairs": [{
                        "output_field_ref": provider_ref,
                        "include_identity_claim": True,
                    }],
                })
            else:
                value = initial
            return StructuredModelResponse(value=value, model="analyzer", latency_ms=1)

    result = DefaultTaskAnalyzer(RevisingClient()).analyze(EntryInput(text=text))

    assert result.accepted is not None
    assert len(result.attempts) == 2
    accepted_body = result.attempts[1].proposal.body
    assert accepted_body.model_dump(exclude={"grounding_claims"}) == initial.model_dump(
        exclude={"grounding_claims"}
    )
    assert accepted_body.grounding_claims == (TaskAnalysisGroundingClaim(
        source_text="gpt_researcher",
        output_field_ref=provider_ref,
    ),)


def test_task_analyzer_semantic_revision_explains_read_only_mutation_repair() -> None:
    text = "读取架构文档并回答标题"
    resource = ResourceHint(
        semantic_domain="artifact",
        resource_types=["file"],
        operations=["read"],
    )
    bodies = [TaskAnalysisProposalBody(
        user_goal=text,
        outcome="ready",
        goals=[GoalDraft(
            description=text,
            result_contract="external_state",
            success_criteria=[_criterion("给出标题")],
            side_effect_intent="mutation",
            resource_hints=[resource],
        )],
    )]
    requests = []

    class RevisingClient:
        def generate(self, request):
            requests.append(request)
            if request.operation == "task_analysis_mutation_classification_revision":
                return StructuredModelResponse(
                    value=request.output_type.model_validate({
                        "repairs": [{
                            "goal_index": 0,
                            "result_contract": "response",
                            "side_effect_intent": "none",
                        }],
                    }),
                    model="analyzer",
                    latency_ms=1,
                )
            return StructuredModelResponse(
                value=bodies.pop(0),
                model="analyzer",
                latency_ms=1,
            )

    result = DefaultTaskAnalyzer(RevisingClient()).analyze(EntryInput(text=text))

    assert result.accepted is not None
    assert len(result.attempts) == 2
    assert result.accepted.analysis.goals[0].result_contract == "response"
    assert requests[1].operation == "task_analysis_mutation_classification_revision"
    revision_system = requests[1].messages[0]["content"]
    assert "Revise only the result classification" in revision_system
    assert "cannot revise descriptions" in revision_system


def test_read_only_mutation_revision_cannot_drop_explicit_resource_scope() -> None:
    path = "D:/docs/architecture.md"
    entry = EntryInput(text=f"通过 provider filesystem_release 读取文件 {path}")
    resource = ResourceHint(
        semantic_domain="artifact",
        resource_types=["file"],
        operations=["read"],
        locator=path,
        user_required_provider="filesystem_release",
        origin="user_explicit",
    )
    first = TaskAnalysisProposal(
        input_ref="entry:test",
        input_digest=task_analysis_input_digest(entry),
        body=TaskAnalysisProposalBody(
            user_goal=entry.text,
            outcome="ready",
            goals=[GoalDraft(
                description="读取架构文档",
                result_contract="external_state",
                success_criteria=[_criterion("给出标题")],
                side_effect_intent="mutation",
                resource_hints=[resource],
            )],
            grounding_claims=(
                TaskAnalysisGroundingClaim(
                    source_text=path,
                    output_field_ref="goals.0.resource_hints.0.locator",
                ),
                TaskAnalysisGroundingClaim(
                    source_text="filesystem_release",
                    output_field_ref=(
                        "goals.0.resource_hints.0.user_required_provider"
                    ),
                ),
            ),
        ),
    )
    denial = TaskAnalysisAdmission().admit(entry, first)
    assert denial.feedback is not None
    revised = TaskAnalysisProposal(
        input_ref="entry:test",
        input_digest=task_analysis_input_digest(entry),
        body=TaskAnalysisProposalBody(
            user_goal=entry.text,
            outcome="ready",
            goals=[GoalDraft(
                description="读取架构文档",
                result_contract="response",
                success_criteria=[_criterion("给出标题")],
                side_effect_intent="none",
                resource_hints=[],
            )],
        ),
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


def test_task_analyzer_applies_typed_delegation_classification_patch_only() -> None:
    text = "通过 provider gpt_researcher 委派外部 Agent 研究 A2A"
    resource = ResourceHint(
        semantic_domain="external",
        resource_types=["report"],
        operations=["delegate"],
        user_required_provider="gpt_researcher",
        origin="user_explicit",
    )
    initial = TaskAnalysisProposalBody(
        user_goal=text,
        outcome="ready",
        goals=[GoalDraft(
            description="委派外部 Agent 研究 A2A",
            result_contract="external_state",
            success_criteria=[_criterion("返回研究报告")],
            side_effect_intent="mutation",
            resource_hints=[resource],
        )],
        grounding_claims=(TaskAnalysisGroundingClaim(
            source_text="gpt_researcher",
            output_field_ref="goals.0.resource_hints.0.user_required_provider",
        ),),
    )
    requests = []

    class RevisingClient:
        def generate(self, request):
            requests.append(request)
            if request.operation == "task_analysis_mutation_classification_revision":
                value = request.output_type.model_validate({
                    "repairs": [{
                        "goal_index": 0,
                        "result_contract": "artifact",
                        "side_effect_intent": "none",
                    }],
                })
            else:
                value = initial
            return StructuredModelResponse(
                value=value,
                model="analyzer",
                latency_ms=1,
            )

    result = DefaultTaskAnalyzer(RevisingClient()).analyze(EntryInput(text=text))

    assert result.accepted is not None
    repaired = result.accepted.analysis.goals[0]
    assert repaired.result_contract == "artifact"
    assert repaired.side_effect_intent == "none"
    assert repaired.description == initial.goals[0].description
    assert repaired.resource_hints == [resource]
    assert repaired.resource_hints[0].user_required_provider == "gpt_researcher"
    assert len(requests) == 2


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="art-test",
        filename="paper.pdf",
        content_type="application/pdf",
        source_type="pdf",
        file_path="/tmp/paper.pdf",
        size_bytes=123,
    )
