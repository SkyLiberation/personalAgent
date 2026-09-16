"""来源表示的准入 Contract；仅检验确定性读写，不替代 Agent 或 Product E2E。"""

from __future__ import annotations

from personal_agent.infra.artifact_ripgrep import RipgrepArtifactSearch
from personal_agent.application.conversation.artifact_search import SearchActionOutputArguments, search_artifact_text


import pytest

from personal_agent.application.artifacts import ArtifactService
from personal_agent.application.capture.models import UrlCaptureResult
from personal_agent.application.capture.web_source import (
    MAX_SOURCE_PAYLOAD_BYTES, WebReadOutput, source_body_text,
)
from personal_agent.application.conversation import ConversationService, ToolCallProposal
from personal_agent.application.conversation.observation_bounds import (
    MAX_OBSERVATION_PAYLOAD_CHARS,
    serialized_length,
)
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope


def _source(url: str, text: str) -> UrlCaptureResult:
    return UrlCaptureResult(url=url, text=text, provider="contract")


def _fit(service, principal, encoded, *, metadata=""):
    payload = WebReadOutput(source_url="https://example.org/source", provider="contract", source_text=encoded).model_dump(mode="json")
    fitted = service._fit_observation_payload(
        {"ok": True, "data": payload, "search_metadata": metadata},
        action_id="source", capability_id="web_read", run_ref="representation",
        owner=principal, execution_scope=ExecutionScope(principal=principal, execution_id="representation"),
    )
    assert serialized_length(fitted) <= MAX_OBSERVATION_PAYLOAD_CHARS
    return ResourceRef.model_validate(fitted["retrieval"]["resource_ref"])


def _window(service, principal, ref, *, start_line=1, start_column=1):
    result = service._read_artifact(ToolCallProposal(
        action_id=f"read-{start_line}", tool_name="read_artifact",
        arguments={"resource_ref": ref.model_dump(mode="json"),
                   "start_line": start_line, "start_column": start_column},
    ), principal=principal, owner=principal)
    assert result.interaction_input.status == "succeeded"
    payload = result.interaction_input.payload
    assert serialized_length(payload) <= MAX_OBSERVATION_PAYLOAD_CHARS
    assert "retrieval" not in payload, "完整来源片段不得被二次裁断"
    return payload


@pytest.mark.parametrize("body", (
    "页首" * 15_000 + "协议约束只适用于输入参数" + "页尾" * 30_000,
    ('中文\\路径\t"引文"\r\n\n' * 3_000),
    ("分隔\x85符\u2028仍\u2029属原文\x1c\x1d\x1e" * 3_000),
    ("重复正文\n" * 5_000),
), ids=("long-line", "escapes", "unicode-separators", "repeated-lines"))
def test_artifact_windows_reconstruct_every_source_byte(tmp_path, body):
    sources = (
        _source("https://example.org/source", body),
    )
    encoded = "\n".join(source_body_text(s, max_bytes=MAX_SOURCE_PAYLOAD_BYTES) for s in sources)
    principal = AuthenticatedPrincipal(tenant_id="contract", user_id="reader")
    artifacts = ArtifactService(Settings(data_dir=tmp_path))
    service = ConversationService(None, artifact_port=artifacts)
    ref = _fit(service, principal, encoded)
    stored = artifacts.read_text(ref, principal=principal, owner=principal)
    assert stored == encoded
    decoded = {}
    continuation = {"start_line": 1, "start_column": 1}
    while continuation is not None:
        window = _window(service, principal, ref, start_line=continuation["start_line"], start_column=continuation["start_column"])
        for line in window["lines"]:
            assert line["start_column"] == len(decoded.get(line["line"], "")) + 1
            decoded[line["line"]] = decoded.get(line["line"], "") + line["text"]
        following = window["next_read"]
        assert following is None or (following["start_line"], following["start_column"]) > (continuation["start_line"], continuation["start_column"])
        continuation = following
    assert list(decoded.values()) == body.splitlines()
    with pytest.raises(PermissionError):
        artifacts.read_text(ref, principal=AuthenticatedPrincipal(
            tenant_id="contract", user_id="another",
        ), owner=principal)


def test_dense_keyword_windows_have_no_missing_hits(tmp_path):
    encoded = source_body_text(_source("https://example.org/source", ('密集命中 "\\\n' * 16000)), max_bytes=MAX_SOURCE_PAYLOAD_BYTES)
    principal = AuthenticatedPrincipal(tenant_id="contract", user_id="reader")
    service = ConversationService(None, artifact_port=ArtifactService(Settings(data_dir=tmp_path)))
    ref = _fit(service, principal, encoded)
    seen = set()
    offset = 0
    while offset is not None:
        result = search_artifact_text(encoded,
            arguments=SearchActionOutputArguments(resource_ref=ref, keyword="密集命中", result_offset=offset), matcher=RipgrepArtifactSearch())
        seen.update(line.line for line in result.lines)
        following = result.next_offset
        assert following is None or following > offset
        offset = following
    assert seen == set(range(1, len(encoded.splitlines()) + 1))


def test_metadata_does_not_change_canonical_body():
    assert source_body_text(_source("https://example.org/" + "x" * 2_001, "正文"), max_bytes=MAX_SOURCE_PAYLOAD_BYTES) == "正文"


def test_read_state_parameters_survive_body_truncation(tmp_path):
    principal = AuthenticatedPrincipal(tenant_id="contract", user_id="reader")
    service = ConversationService(None, artifact_port=ArtifactService(Settings(data_dir=tmp_path)))
    keyword = "查询" * 300
    ref = _fit(service, principal, keyword + "正文" * 30_000)
    result = service._read_artifact(ToolCallProposal(
        action_id="long-line", tool_name="read_artifact",
        arguments={"resource_ref": ref.model_dump(mode="json"), "start_line": 1},
    ), principal=principal, owner=principal).interaction_input
    assert result.status == "succeeded"
    assert result.payload["next_read"]["start_column"] > 1
    assert result.payload["next_read"]["start_line"] == 1
    assert serialized_length(result.payload) <= MAX_OBSERVATION_PAYLOAD_CHARS


def test_oversized_read_parameters_fail_explicitly(tmp_path):
    principal = AuthenticatedPrincipal(tenant_id="contract", user_id="reader")
    service = ConversationService(None, artifact_port=ArtifactService(Settings(data_dir=tmp_path)))
    ref = _fit(service, principal, "正文" * 30_000)
    result = service._read_artifact(ToolCallProposal(
        action_id="long-query", tool_name="read_artifact",
        arguments={"resource_ref": ref.model_dump(mode="json"), "keyword": "查询" * 20_000},
    ), principal=principal, owner=principal).interaction_input
    assert result.status == "failed"
    assert result.payload["error_kind"] == "invalid_param"
    assert "lines" not in result.payload


def test_metadata_overflow_keeps_short_source_physically_addressable(tmp_path):
    encoded = source_body_text(_source("https://example.org/source", "独立事实\n" * 100), max_bytes=MAX_SOURCE_PAYLOAD_BYTES)
    assert len(encoded) < MAX_OBSERVATION_PAYLOAD_CHARS
    principal = AuthenticatedPrincipal(tenant_id="contract", user_id="reader")
    artifacts = ArtifactService(Settings(data_dir=tmp_path))
    service = ConversationService(None, artifact_port=artifacts)
    ref = _fit(service, principal, encoded, metadata="大搜索元数据" * 4_000)
    assert artifacts.read_text(ref, principal=principal, owner=principal) == encoded
    assert _window(service, principal, ref)["lines"]
