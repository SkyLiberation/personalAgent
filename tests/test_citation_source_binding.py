"""引用来源由可见执行记录确定，禁止按正文、顺序或跨版本补造。"""
import json

import pytest

from personal_agent.application.capture.web_source import WebReadOutput
from personal_agent.application.conversation.citations import materialize_citation_context, materialize_cited_draft
from personal_agent.application.conversation.models import ActionObservation
from personal_agent.capabilities.contracts.verification import ConversationAnswerSegment, ConversationEvidenceReference
from personal_agent.kernel.contracts.resource import ResourceRef
from tests.test_conversation_citations import ScriptedSupportModel
from personal_agent.tools.interaction_verifier import build_verify_interaction_draft_tool


def source_pair(name, *, revision=1, user="reader", url=None):
    ref = ResourceRef(resource_id=name, resource_type="artifact", revision=revision,
                      owner={"tenant_id":"test", "user_id":user})
    origin = ActionObservation(kind="tool_result", action_id=f"fetch-{name}-{revision}-{user}",
        capability_id="web_read", status="succeeded", payload={
            "data":WebReadOutput(source_url=url or f"https://example.org/{name}/{revision}/{user}", provider="builtin", source_text="相同正文").model_dump(mode="json"),
            "retrieval":{"resource_ref":ref.model_dump(mode="json"), "total_lines":100}})
    read = ActionObservation(kind="tool_result", action_id=f"read-{name}-{revision}-{user}",
        capability_id="read_action_output", status="succeeded", payload={
            "resource_ref":ref.model_dump(mode="json"), "total_lines":100,
            "lines":[{"line":14,"text":"相同正文", "start_column":3, "line_length":10}]})
    return origin, read


def cite_reads(inputs):
    context = materialize_citation_context(inputs)
    refs = tuple(ConversationEvidenceReference(evidence_id=line["evidence_id"])
        for item in context if item.observation.capability_id=="read_action_output"
        for line in item.observation.payload["lines"])
    return materialize_cited_draft((ConversationAnswerSegment(text="说明来源", references=refs),), inputs)[0]


@pytest.mark.parametrize("second", [source_pair("b"), source_pair("a",revision=2), source_pair("a",user="other")])
def test_identical_text_preserves_exact_resource_version_and_owner(second):
    first = source_pair("a")
    # 调换来源出现顺序，禁止按最近 URL 或相同正文猜测绑定。
    unit = cite_reads((second[0], first[0], first[1], second[1]))
    assert [e.text for e in unit.execution_evidence]==["相同正文", "相同正文"]
    for evidence, (origin, read) in zip(unit.execution_evidence, (first,second), strict=True):
        assert evidence.source.resource_ref.model_dump(mode="json")==read.payload["resource_ref"]
        assert evidence.source.source_url==origin.payload["data"]["source_url"]
        assert (evidence.source.line,evidence.source.start_column)==(14,3)


@pytest.mark.parametrize("missing", ["absent", "failed", "other_version", "other_owner"])
def test_unknown_origin_is_not_inferred_from_unrelated_metadata(missing):
    origin, read = source_pair("a")
    if missing=="failed":
        origin=origin.model_copy(update={"status":"failed"})
    elif missing=="other_version":
        origin=source_pair("a",revision=2)[0]
    elif missing=="other_owner":
        origin=source_pair("a",user="other")[0]
    inputs = (read,) if missing=="absent" else (origin,read)
    source = cite_reads(inputs).execution_evidence[0].source
    assert source.source_url is None
    assert source.resource_ref.model_dump(mode="json")==read.payload["resource_ref"]


def test_conflicting_metadata_for_one_resource_fails_closed():
    origin, read = source_pair("a")
    conflicting = source_pair("a",url="https://example.org/wrong")[0].model_copy(update={"action_id":"conflict"})
    with pytest.raises(ValueError,match="inconsistent metadata"):
        cite_reads((origin,conflicting,read))


def test_source_binding_reaches_both_semantic_consumers_without_changing_body():
    a,b = source_pair("a"),source_pair("b")
    unit=cite_reads((*a,*b))
    model=ScriptedSupportModel()
    result=build_verify_interaction_draft_tool(model).invoke({"type":"tool_call","id":"check",
        "name":"verify_interaction_draft", "args":{"draft":unit.draft,"success_criteria":["说明来源"],
        "cited_units":[unit.model_dump(mode="json")]}})
    assert result.artifact.data["verified_draft"]==unit.draft
    for request in model.requests:
        evidence=json.loads(request.messages[-1]["content"])["execution_evidence"]
        assert [e["source"]["source_url"] for e in evidence]==[a[0].payload["data"]["source_url"],b[0].payload["data"]["source_url"]]
