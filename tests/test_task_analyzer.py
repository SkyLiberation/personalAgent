from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from personal_agent.infra.structured_model import StructuredModelResponse
from personal_agent.kernel.models import ArtifactRef, EntryInput
from personal_agent.planning.task_analyzer import (
    ClarificationDraft,
    DefaultTaskAnalyzer,
    EvidenceRequirement,
    GoalDraft,
    GoalRelationDraft,
    ResourceHint,
    TaskAnalysisOutput,
    describe_task_analysis,
)


class TestTaskAnalysisOutputContract:
    def test_ready_requires_goals(self):
        with pytest.raises(ValidationError, match="requires at least one goal"):
            TaskAnalysisOutput(user_goal="回答问题", outcome="ready")

    def test_ready_rejects_clarification(self):
        with pytest.raises(ValidationError, match="cannot clarify"):
            TaskAnalysisOutput(
                user_goal="回答问题",
                outcome="ready",
                goals=[GoalDraft(
                    description="问题",
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
            TaskAnalysisOutput(user_goal="理解目标", outcome="clarify")

    def test_relation_indexes_must_reference_goals(self):
        with pytest.raises(ValidationError, match="unknown 1-based goal index"):
            TaskAnalysisOutput(
                user_goal="非法关系",
                outcome="ready",
                goals=[GoalDraft(description="唯一目标")],
                relations=[GoalRelationDraft(
                    predecessor=1,
                    successor=2,
                    kind="consumes_output",
                    rationale="不存在第二个目标",
                )],
            )

    def test_schema_contains_task_understanding_not_execution_policy(self):
        properties = set(TaskAnalysisOutput.model_json_schema()["properties"])
        assert properties == {
            "user_goal", "outcome", "goals", "relations",
            "clarification", "rejection_reason", "direct_answer",
        }
        assert properties.isdisjoint({
            "route_type", "coverage", "workflow", "tool", "capability",
        })


class TestDefaultTaskAnalyzer:
    def test_model_analysis_normalizes_goal_ids_and_typed_relations(self):
        output = TaskAnalysisOutput(
            user_goal="记录事实并基于该事实回答",
            outcome="ready",
            goals=[
                GoalDraft(
                    description="记录 DNS 事实",
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
                origin="user_explicit",
                rationale="回答明确要求基于刚记录的事实",
            )],
        )

        class FakeClient:
            request = None

            def generate(self, request):
                self.request = request
                return StructuredModelResponse(value=output, model="analyzer", latency_ms=1)

        client = FakeClient()
        analysis = DefaultTaskAnalyzer(client).analyze(EntryInput(text="复合请求"))

        assert [goal.goal_id for goal in analysis.goals] == ["goal_1", "goal_2"]
        assert analysis.goals[0].result_contract == "external_state"
        assert analysis.goals[1].result_contract == "response"
        assert analysis.relations[0].predecessor_goal_id == "goal_1"
        assert analysis.relations[0].successor_goal_id == "goal_2"
        assert client.request.output_type is TaskAnalysisOutput
        assert client.request.operation == "task_analysis"

    def test_model_receives_artifact_metadata_without_structural_classification(self):
        output = TaskAnalysisOutput(
            user_goal="理解附件",
            outcome="ready",
            goals=[GoalDraft(
                description="概述附件",
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
        analysis = DefaultTaskAnalyzer(client).analyze(EntryInput(
            text="总结附件",
            artifacts=[_artifact()],
        ))
        assert analysis.goals[0].result_contract == "artifact"
        assert "paper.pdf" in client.request.messages[-1]["content"]

    def test_empty_entry_requests_structural_clarification(self):
        analysis = DefaultTaskAnalyzer(None).analyze(EntryInput(text=""))
        assert analysis.outcome == "clarify"
        assert analysis.error is None

    def test_missing_model_does_not_fall_back_to_keyword_routing(self):
        analysis = DefaultTaskAnalyzer(None).analyze(EntryInput(
            text="删除关于 DNS 的知识",
        ))
        assert analysis.outcome == "clarify"
        assert analysis.error == "analyzer_unavailable"
        assert not analysis.goals

    def test_logs_analysis_strategy(self, caplog):
        caplog.set_level(logging.INFO)
        DefaultTaskAnalyzer(None).analyze(EntryInput(text="解释 DNS", user_id="alice"))
        assert "task_analysis.completed" in caplog.text
        assert '"strategy": "analyzer_unavailable"' in caplog.text

    def test_description_uses_goal_language(self):
        output = TaskAnalysisOutput(
            user_goal="解释服务降级",
            outcome="ready",
            goals=[GoalDraft(
                description="解释服务降级",
                result_contract="response",
            )],
        )

        class FakeClient:
            def generate(self, _request):
                return StructuredModelResponse(value=output, model="analyzer", latency_ms=1)

        analysis = DefaultTaskAnalyzer(FakeClient()).analyze(EntryInput(text="什么是服务降级"))
        assert describe_task_analysis(analysis) == "已识别目标：解释服务降级"


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="art-test",
        filename="paper.pdf",
        content_type="application/pdf",
        source_type="pdf",
        file_path="/tmp/paper.pdf",
        size_bytes=123,
    )
