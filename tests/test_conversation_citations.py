"""Citation transport and rejection/recovery contracts; no model-quality claims."""

import json

import pytest

from personal_agent.application.conversation.citations import (
    CitationBindingError,
    materialize_cited_draft,
    materialize_citation_context,
)
from personal_agent.application.conversation.models import (
    ActionObservation,
    FinalMessage,
)
from personal_agent.capabilities.contracts.verification import (
    CitedDraftUnit,
    ConversationEvidenceReference,
    ConversationAnswerSegment,
    OverreachFinding,
    OverreachReport,
    SemanticVerificationReport,
    VerificationCriterionResult,
)
from personal_agent.capabilities.contracts.model import StructuredModelResponse
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.tools.interaction_verifier import (
    build_verify_interaction_draft_tool,
)


def response(value):
    return StructuredModelResponse(value=value, model="contract", latency_ms=0)


def observation(action_id="read-1", status="succeeded"):
    return ActionObservation(
        kind="tool_result",
        action_id=action_id,
        capability_id="read_action_output",
        status=status,
        payload={
            "resource_ref": ResourceRef(
                resource_id="source-1",
                resource_type="conversation_action_output",
                owner=AuthenticatedPrincipal(tenant_id="test", user_id="writer"),
            ).model_dump(mode="json"),
            "total_lines": 3,
            "lines": [
                {"line": 1, "text": "支持 auto。"},
                {"line": 2, "text": "还支持 required。"},
            ],
        },
    )


def citation(quote, *lines, action_id="read-1"):
    return ConversationAnswerSegment(
        text=quote,
        references=tuple(
            ConversationEvidenceReference(evidence_id=f"e{line+1}" if action_id == "read-1" else "hidden")
            for line in lines
        ),
    )


def test_citations_preserve_every_submitted_fragment_and_unreferenced_draft():
    text = "说明\n支持 auto 和 required。\n尾注。"
    obs = observation()
    units = materialize_cited_draft(
        (citation("说明\n"), citation("支持 auto 和 required。", 1, 2), citation("\n尾注。")),
        (obs, observation("unrelated")),
    )
    assert "".join(u.draft for u in units) == text
    assert [e.text for e in units[1].execution_evidence] == [
        line["text"] for line in obs.payload["lines"]
    ]
    assert not units[0].execution_evidence and not units[2].execution_evidence
    assert "unrelated" not in "".join(u.model_dump_json() for u in units)


@pytest.mark.parametrize(
    "ref", [citation("正文", 3), citation("正文", 1, action_id="hidden")]
)
def test_citation_cannot_retrieve_unseen_lines_or_executions(ref):
    with pytest.raises(CitationBindingError):
        materialize_cited_draft((ref,), (observation(),))


def test_failed_execution_is_not_citable():
    with pytest.raises(CitationBindingError):
        materialize_cited_draft(
            (citation("正文", 1),), (observation(status="failed"),)
        )


@pytest.mark.parametrize("text", ["重复重复", "中文‘引号’与空格 😀\n", "第一句。\n第二句。"])
def test_body_is_stored_once_and_never_matched_against_a_second_copy(text):
    value = FinalMessage(disposition="answer", segments=(citation(text, 1), citation(text, 2)))
    units = materialize_cited_draft(value.segments, (observation(),))
    assert value.message == text + text == "".join(u.draft for u in units)
    assert [u.execution_evidence[0].text for u in units] == ["支持 auto。", "还支持 required。"]
    assert set(value.model_dump()) == {"kind", "disposition", "segments"}
    assert "message" not in FinalMessage.model_json_schema()["properties"]


def test_old_duplicate_body_write_contract_is_rejected():
    with pytest.raises(ValueError):
        FinalMessage.model_validate({"disposition":"answer", "message":"正文"})
    value = FinalMessage(disposition="answer", segments=(citation("正文"),))
    with pytest.raises((ValueError, AttributeError)):
        value.message = "另一个正文"


def test_no_citations_preserves_entire_draft_with_empty_evidence():
    assert materialize_cited_draft((citation("未引用事实。"),), (observation(),)) == (
        CitedDraftUnit(draft="未引用事实。"),
    )


class ScriptedSupportModel:
    """Only the support verdict varies; verifies deterministic gate consumption."""

    def __init__(self):
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        data = json.loads(request.messages[1]["content"])
        if request.operation == "interaction_cited_support":
            findings = (
                ()
                if len(data["execution_evidence"]) == 2
                else (
                    OverreachFinding(
                        draft_quote=data["draft"],
                        evidence_ids=(),
                        exceeded_scope="本次提交缺少第二项的依据。",
                    ),
                )
            )
            return response(OverreachReport(findings=findings))
        assert request.operation == "interaction_semantic_verification"
        return response(
            SemanticVerificationReport(
                criterion_results=tuple(
                    VerificationCriterionResult(criterion=c, status="satisfied")
                    for c in data["success_criteria"]
                )
            )
        )


def test_support_rejection_cannot_be_overridden_and_same_draft_can_be_supplemented():
    model = ScriptedSupportModel()
    tool = build_verify_interaction_draft_tool(model)
    draft = "支持 auto 和 required。"

    def invoke(lines):
        units = materialize_cited_draft(
            (citation(draft, *lines),), (observation(),)
        )
        message = tool.invoke(
            {
                "type": "tool_call",
                "name": "verify_interaction_draft",
                "id": "verify",
                "args": {
                    "draft": draft,
                    "success_criteria": ["解释支持的模式"],
                    "cited_units": [u.model_dump(mode="json") for u in units],
                },
            }
        )
        return message.artifact.data

    rejected = invoke((1,))
    assert rejected["kind"] == "cited_support_rejection"
    assert [q.operation for q in model.requests] == ["interaction_cited_support"]
    accepted = invoke((1, 2))
    assert accepted["verdict"] == "passed" and accepted["verified_draft"] == draft
    assert [q.operation for q in model.requests] == [
        "interaction_cited_support",
        "interaction_cited_support",
        "interaction_semantic_verification",
    ]
    assert json.loads(model.requests[1].messages[1]["content"])[
        "execution_evidence"
    ] == [
        {"id": "e001", "text": "支持 auto。"},
        {"id": "e002", "text": "还支持 required。"},
    ]
    ordinary = json.loads(model.requests[-1].messages[1]["content"])
    assert ordinary["execution_evidence"] == ["支持 auto。", "还支持 required。"]


def test_final_message_retains_writer_citations_in_serialized_contract():
    value = FinalMessage(
        disposition="answer",
        segments=(citation("正文", 1, 2),),
    )
    assert FinalMessage.model_validate_json(value.model_dump_json()) == value


def test_partial_unit_submission_cannot_skip_uncited_claims():
    tool = build_verify_interaction_draft_tool(ScriptedSupportModel())
    with pytest.raises(ValueError, match="entire exact draft"):
        tool.invoke(
            {
                "draft": "第一句。第二句。",
                "success_criteria": ["说明事实"],
                "cited_units": [
                    CitedDraftUnit(draft="第一句。").model_dump(mode="json")
                ],
            }
        )


@pytest.mark.parametrize("repair_protocol", [False, True])
def test_conversation_loop_can_supplement_citations_without_rewriting_the_draft(repair_protocol):
    from tests.test_conversation_interaction import (
        _Decisions,
        _executor,
        _tool,
        _review_intent,
        _conversation_scope,
        _trace,
    )
    from personal_agent.application.conversation import (
        ConversationService,
        ConversationMessage,
        ContinueTurnProposal,
        ToolCallProposal,
    )
    from personal_agent.tools.base import tool_response, tool_success

    draft = "支持 auto 和 required。"
    criterion = "解释记录中支持的模式"

    def read_fact(name: str):
        return tool_response(tool_success({"text": name}))

    def final(action_ids):
        return FinalMessage(
            disposition="answer",
            segments=(
                ConversationAnswerSegment(
                    text=draft,
                    references=tuple(
                        ConversationEvidenceReference(evidence_id={"read-auto":"e1", "read-required":"e2"}.get(a, "hidden")) for a in action_ids
                    ),
                ),
            ),
        )

    protocol_errors = []
    if repair_protocol:
        malformed = final(("not-visible",))
        protocol_errors = [malformed]
    writer = _Decisions(
        ContinueTurnProposal(
            actions=(
                ToolCallProposal(
                    action_id="read-auto",
                    tool_name="read_fact",
                    arguments={"name": "支持 auto。"},
                ),
                ToolCallProposal(
                    action_id="read-required",
                    tool_name="read_fact",
                    arguments={"name": "支持 required。"},
                ),
            ),
            finalization_requested=True,
        ),
        *protocol_errors,
        final(("read-auto",)),
        final(("read-auto", "read-required")),
        review_intent=_review_intent((criterion, criterion)),
    )
    verifier = ScriptedSupportModel()
    service = ConversationService(
        writer,
        tool_port=_executor(
            _tool("read_fact", read_fact),
            build_verify_interaction_draft_tool(verifier),
        ),
    )
    result = service.respond(
        **_conversation_scope(),
        conversation_id="citation-repair",
        interaction_run_ref="citation-repair-run",
        interaction_mode="auto",
        messages=[ConversationMessage(role="user", content=criterion)],
    )
    assert result.disposition == "answer" and result.message.content == draft
    assert [q.operation for q in verifier.requests] == [
        "interaction_cited_support",
        "interaction_cited_support",
        "interaction_semantic_verification",
    ]
    assert any(
        "本次提交缺少第二项的依据" in str(q.messages) for q in writer.decision_requests
    )
    trace = _trace(service, "citation-repair-run")
    if repair_protocol:
        from personal_agent.application.conversation.models import DecisionFeedback
        feedback = [x for x in trace.inputs if isinstance(x, DecisionFeedback)]
        assert [x.reason_code for x in feedback] == [
            "citation_source_unavailable",
        ]
        assert malformed.model_dump_json() in feedback[0].message
        encoded_draft = json.dumps(malformed.model_dump_json(), ensure_ascii=False)[1:-1]
        assert any(encoded_draft in str(m.get("content", ""))
                   for q in writer.decision_requests for m in q.messages)
        # Different corrected causes must not trip the existing same-cause guard.
        assert service._repeated_action_feedback(tuple(feedback)) is None
        same_cause = feedback[0].model_copy(update={"decision_turn": 99})
        assert service._repeated_action_feedback((feedback[0], same_cause)) is same_cause
    assert len(trace.final_message.segments[0].references) == 2
    assert [
        x.capability_id for x in trace.inputs if isinstance(x, ActionObservation)
    ].count("read_fact") == 2


def test_published_identifiers_resolve_to_exact_locations_without_duplicate_source_text():
    obs = observation()
    context, = materialize_citation_context((obs,))
    assert context.evidence_id == "e1"
    assert [line["evidence_id"] for line in context.observation.payload["lines"]] == ["e2", "e3"]
    assert "evidence_id" not in obs.payload["lines"][0]
    assert context.model_dump_json().count("支持 auto") == 1
    segment = ConversationAnswerSegment(text="两种模式", references=tuple(
        ConversationEvidenceReference(evidence_id=line["evidence_id"]) for line in context.observation.payload["lines"]
    ))
    units=materialize_cited_draft((segment,), (obs,))
    assert [e.text for e in units[0].execution_evidence] == ["支持 auto。", "还支持 required。"]


def test_source_and_read_window_have_distinct_noncomposable_identifiers():
    source=observation().model_copy(update={"action_id":"fetch", "capability_id":"web_read", "payload":{"text":"来源正文"}})
    context=materialize_citation_context((source, observation()))
    assert context[0].evidence_id == "e1"
    assert context[1].evidence_id == "e2"
    assert [line["evidence_id"] for line in context[1].observation.payload["lines"]] == ["e3", "e4"]
    with pytest.raises(CitationBindingError):
        materialize_cited_draft((ConversationAnswerSegment(text="声明", references=(ConversationEvidenceReference(evidence_id="o1:l1"),)),), (source,observation()))
