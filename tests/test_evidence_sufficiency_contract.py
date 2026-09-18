"""Contract and Runtime Conformance only; scripted model results are not E2E."""

import json

import pytest
from pydantic import ValidationError

from personal_agent.application.conversation.models import (
    CommittedUsage,
    FinalMessage,
    ReviewCriteria,
)
from personal_agent.application.conversation.service import ConversationService
from personal_agent.capabilities.contracts.model import StructuredModelResponse
from personal_agent.capabilities.contracts.verification import (
    ConversationAnswerSegment,
    ConversationEvidenceReference,
    DocumentAbsenceReport,
    EvidenceSufficiencyAssessment,
    OverreachFinding,
    OverreachReport,
    SemanticVerificationReport,
    VerificationCriterionResult,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.tools.interaction_verifier import build_verify_interaction_draft_tool


REASON = "本稿已说明当前证据不能确认的事项，现有引用足以支持其余有限结论。"
DRAFT = "本次证据不足以确认保修期限。"


class VerificationModel:
    """Vary semantic results at the model Port; exercise actual gate code."""

    def __init__(self, *, supported=True, satisfied=True):
        self.requests = []
        self.supported = supported
        self.satisfied = satisfied

    def generate(self, request):
        self.requests.append(request)
        content = json.loads(request.messages[-1]["content"])
        if request.operation == "interaction_document_absence_classification":
            result = DocumentAbsenceReport(absence_by_source=(True,))
        elif request.operation == "interaction_cited_support":
            result = OverreachReport(findings=() if self.supported else (
                OverreachFinding(
                    draft_quote=content["draft"], evidence_ids=("e1",),
                    exceeded_scope="引用没有支持这条保证。",
                ),
            ))
        else:
            assert request.operation == "interaction_semantic_verification"
            result = SemanticVerificationReport(
                criterion_results=tuple(
                    VerificationCriterionResult(
                        criterion=c,
                        status="satisfied" if self.satisfied else "insufficient_evidence",
                        feedback="目标满足" if self.satisfied else "缺少用户要求的比较内容。",
                    ) for c in content["success_criteria"]
                ),
                revision_feedback="" if self.satisfied else "请补齐用户要求的比较内容。",
            )
        return StructuredModelResponse(value=result, model="contract", latency_ms=0)


def arguments(*, sufficient):
    return {
        "draft": DRAFT, "success_criteria": ["说明当前资料能否确认保修期限。"],
        "cited_units": [{"draft": DRAFT, "execution_evidence": [
            {"id": "e1", "text": "当前摘录仅介绍电源安装方法。"},
        ]}],
        "source_reading_state": [{
            "resource_ref": {
                "resource_id": "manual", "resource_type": "artifact",
                "owner": {"tenant_id": "test", "user_id": "reader"}, "revision": 1,
            },
            "source_url": "https://example.org/manual", "returned_unique_segments": 1,
            "total_segments": 100, "fully_read": False,
        }],
        "evidence_sufficiency": {"reason": REASON} if sufficient else None,
    }


def invoke(tool, *, sufficient):
    return tool.invoke({
        "type": "tool_call", "name": "verify_interaction_draft", "id": "review",
        "args": arguments(sufficient=sufficient),
    }).artifact.data


def test_same_draft_can_continue_past_coverage_without_changing_facts():
    model = VerificationModel()
    tool = build_verify_interaction_draft_tool(model)
    rejected = invoke(tool, sufficient=False)
    assert rejected["kind"] == "source_coverage_rejection"
    assert len(model.requests) == 1

    accepted = invoke(tool, sufficient=True)
    assert accepted["verdict"] == "passed"
    assert accepted["verified_draft"] == rejected["rejected_draft"] == DRAFT
    # Assessment is a control decision, never evidence fed to any semantic judge.
    assert model.requests[0].messages == model.requests[1].messages
    assert all(REASON not in str(request.messages) for request in model.requests)
    assert [r.operation for r in model.requests[1:]] == [
        "interaction_document_absence_classification", "interaction_cited_support",
        "interaction_semantic_verification",
    ]
    assert json.loads(model.requests[-1].messages[-1]["content"])[
        "source_reading_state"
    ] == arguments(sufficient=True)["source_reading_state"]
    # A later submission without its own decision cannot inherit the old one.
    assert invoke(tool, sufficient=False)["kind"] == "source_coverage_rejection"


@pytest.mark.parametrize("supported,satisfied,expected", [
    (False, True, "cited_support_rejection"),
    (True, False, "failed"),
])
def test_sufficiency_neither_overrides_source_support_nor_user_goal(supported, satisfied, expected):
    result = invoke(build_verify_interaction_draft_tool(
        VerificationModel(supported=supported, satisfied=satisfied)
    ), sufficient=True)
    assert result.get("kind", result.get("verdict")) == expected


@pytest.mark.parametrize("reason", ["", " \n ", "长" * 2001])
def test_sufficiency_requires_a_bounded_nonempty_reason(reason):
    with pytest.raises(ValidationError):
        EvidenceSufficiencyAssessment(reason=reason)


def test_sufficiency_belongs_to_one_answer_submission():
    answer = FinalMessage(
        disposition="answer", segments=(ConversationAnswerSegment(text=DRAFT),),
        evidence_sufficiency=EvidenceSufficiencyAssessment(reason=REASON),
    )
    assert FinalMessage.model_validate_json(answer.model_dump_json()) == answer
    assert answer.message == DRAFT
    with pytest.raises(ValidationError):
        FinalMessage(**{**answer.model_dump(), "disposition": "limitation"})
    assert FinalMessage(disposition="answer", segments=answer.segments).evidence_sufficiency is None


class RecordingVerificationPort:
    def __init__(self): self.arguments = []

    def invoke_workflow(self, name, arguments, **kwargs):
        assert name == "verify_interaction_draft"
        self.arguments.append(arguments)
        return {"ok": False, "error": "测试语义拒绝", "error_kind": "unrecoverable"}


def test_formal_service_projects_only_this_finals_decision_and_keeps_citation_admission():
    port = RecordingVerificationPort()
    service = ConversationService(VerificationModel(), tool_port=port)
    principal = AuthenticatedPrincipal(tenant_id="test", user_id="reader")
    kwargs = dict(
        review_criteria=ReviewCriteria(criteria=("说明证据边界",)),
        verification_inputs=(), conversation_id="conversation", run_ref="run",
        principal=principal, owner=principal, source_platform="test",
        usage=CommittedUsage(), attempt=0,
    )
    decision = FinalMessage(
        disposition="answer", segments=(ConversationAnswerSegment(text=DRAFT),),
        evidence_sufficiency=EvidenceSufficiencyAssessment(reason=REASON),
    )
    service._verify_before_send(decision, **kwargs)
    assert port.arguments[-1]["evidence_sufficiency"] == {"reason": REASON}
    assert port.arguments[-1]["draft"] == DRAFT
    service._verify_before_send(
        FinalMessage(disposition="answer", segments=decision.segments), **kwargs,
    )
    assert port.arguments[-1]["evidence_sufficiency"] is None
    invalid = decision.model_copy(update={"segments": (
        ConversationAnswerSegment(text=DRAFT, references=(
            ConversationEvidenceReference(evidence_id="not-visible"),
        )),
    )})
    verified, result, _ = service._verify_before_send(invalid, **kwargs)
    assert verified is None and len(port.arguments) == 2
    assert result.interaction_input.reason_code == "citation_source_unavailable"
