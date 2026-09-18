"""查询执行事实、可引用来源和修订上下文的确定性边界。"""
import pytest
import json

from personal_agent.application.conversation.artifact_search import SearchActionOutputArguments, search_artifact_text
from personal_agent.infra.artifact_ripgrep import RipgrepArtifactSearch
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.kernel.config import Settings
from personal_agent.tools.web_search import build_web_search_tool
from tests.test_web_research_tools_contract import _Search
from personal_agent.application.conversation.models import ActionObservation
from personal_agent.application.conversation.citations import materialize_citation_context, materialize_cited_draft
from personal_agent.application.conversation.context_materialization import materialize_interaction_inputs
from personal_agent.application.conversation import ConversationService
from personal_agent.application.artifacts import ArtifactService
from personal_agent.capabilities.contracts.verification import ConversationAnswerSegment, ConversationEvidenceReference
from personal_agent.kernel.contracts.scope import ExecutionScope


def resource(revision=1, user="reader"):
    return ResourceRef(resource_id="source", resource_type="conversation_action_output",
                       owner=AuthenticatedPrincipal(tenant_id="contract", user_id=user), revision=revision)


def test_web_search_returns_exact_executed_query_and_limit():
    tool = build_web_search_tool(Settings(), _Search())
    message = tool.invoke({"type": "tool_call", "name": "web_search", "id": "query",
                           "args": {"query": "权限要求", "limit": 3}})
    assert message.artifact.data["query"] == "权限要求"
    assert message.artifact.data["limit"] == 3


@pytest.mark.parametrize("keyword,regex,offset,ref", [
    ("permission", False, 0, resource()),
    ("consent", False, 0, resource()),
    ("per.*", True, 0, resource(2)),
    ("permission", False, 1, resource(user="another")),
])
def test_local_search_returns_actual_query_including_empty_and_paginated_results(keyword, regex, offset, ref):
    args = SearchActionOutputArguments(resource_ref=ref, keyword=keyword, regex=regex, result_offset=offset)
    result = search_artifact_text("permission\npermission\n正文", arguments=args, matcher=RipgrepArtifactSearch())
    encoded = result.model_dump(mode="json")
    assert {key: encoded[key] for key in SearchActionOutputArguments.model_fields} == args.model_dump(mode="json")
    if keyword == "consent":
        assert not result.lines and result.matched_record_count == 0


def search_observation(keyword="查询不能当作证据"):
    result = search_artifact_text("该来源要求用户同意。", arguments=SearchActionOutputArguments(
        resource_ref=resource(), keyword=keyword), matcher=RipgrepArtifactSearch())
    return ActionObservation(kind="tool_result", action_id="search", capability_id="search_action_output",
                             status="succeeded", payload={"ok": True, **result.model_dump(mode="json")})


@pytest.mark.parametrize("web", [False, True])
def test_query_changes_decision_data_but_never_changes_cited_evidence(web):
    first = search_observation()
    if web:
        first = first.model_copy(update={"capability_id": "web_search", "payload": {
            "ok": True, "data": {"query": "查询不能当作证据", "limit": 3, "results": []}}})
    changed = json.loads(first.model_dump_json())
    if web:
        changed["payload"]["data"].update(query="另一未命中问题", limit=5)
    else:
        changed["payload"].update(keyword="另一未命中问题", regex=True, result_offset=0)
    second = ActionObservation.model_validate(changed)
    contexts = [materialize_citation_context((item,))[0] for item in (first, second)]
    assert contexts[0].executed_query != contexts[1].executed_query
    assert contexts[0].observation == contexts[1].observation
    segment = ConversationAnswerSegment(text="说明搜索范围", references=(ConversationEvidenceReference(evidence_id="e1"),))
    units = [materialize_cited_draft((segment,), (item,)) for item in (first, second)]
    assert units[0] == units[1]
    assert "查询不能当作证据" not in units[0][0].execution_evidence[0].text


def test_large_search_preserves_exact_query_but_offloaded_source_excludes_it(tmp_path):
    owner = resource().owner
    artifacts = ArtifactService(Settings(data_dir=tmp_path))
    service = ConversationService(None, artifact_port=artifacts)
    payload = {"ok": True, "data": {"query": "不可引用的查询" * 40, "limit": 10,
        "results": [{"title": "来源" * 700, "url": f"https://example.org/{i}", "snippet": "正文" * 700} for i in range(10)]}}
    fitted = service._fit_observation_payload(payload, action_id="large", capability_id="web_search", run_ref="large",
        owner=owner, execution_scope=ExecutionScope(principal=owner, execution_id="large"))
    from personal_agent.application.conversation.observation_bounds import serialized_length, MAX_OBSERVATION_PAYLOAD_CHARS
    assert serialized_length(fitted) <= MAX_OBSERVATION_PAYLOAD_CHARS
    obs = ActionObservation(kind="tool_result", action_id="large", capability_id="web_search", status="succeeded", payload=fitted)
    context = materialize_citation_context(materialize_interaction_inputs((obs,)))
    query = context[0].executed_query.model_dump(mode="json")
    assert query == {"query": payload["data"]["query"], "limit": 10}
    body = artifacts.read_text(ResourceRef.model_validate(fitted["retrieval"]["resource_ref"]), principal=owner, owner=owner)
    assert "不可引用的查询" not in body
    assert json.loads(body)["results"][9]["snippet"] == payload["data"]["results"][9]["snippet"]
