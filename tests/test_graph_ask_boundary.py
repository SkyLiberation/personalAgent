from __future__ import annotations

import pytest
from pydantic import ValidationError

from personal_agent.application.verifier import AnswerVerifier
from personal_agent.governance.policy import PolicyEngine
from personal_agent.governance.registry import ToolExecutor
from personal_agent.kernel.config import Settings
from personal_agent.kernel.graph_results import GraphRetrievalResult
from personal_agent.orchestration.runtime_ask import AskService


_UNSUPPORTED_PROVIDER_ANSWER = "Orion 已经完成生产发布，所有租户默认启用。"


class _UngroundedGraphProvider:
    @staticmethod
    def configured() -> bool:
        return True

    @staticmethod
    def retrieve(
        question: str,
        user_id: str,
        trace_id: str | None = None,
    ) -> GraphRetrievalResult:
        return GraphRetrievalResult(
            enabled=False,
            error=(
                "Graph provider returned a synthesized answer without "
                "source-grounded evidence."
            ),
        )


class _EmptyMemory:
    last_retrieval_debug: dict[str, object] = {}

    def bind_session(self, user_id: str, session_id: str) -> None:
        self.session = (user_id, session_id)

    @staticmethod
    def list_graph_sync_tasks(*, user_id: str, statuses: list[str]):
        return []

    @staticmethod
    def search_memory(user_id: str, query: str, *, limit: int, filters):
        return []

    @staticmethod
    def find_by_graph_episodes(user_id: str, episode_uuids: list[str], *, filters):
        return []


class _EvidenceEchoLlm:
    @staticmethod
    def generate_answer(prompt: str, **kwargs) -> str:
        if _UNSUPPORTED_PROVIDER_ANSWER in prompt:
            return _UNSUPPORTED_PROVIDER_ANSWER
        return "当前没有可追溯证据能够确认 Orion 的发布状态。"


def _ungrounded_graph_ask_service() -> AskService:
    policy = PolicyEngine()
    return AskService(
        settings=Settings(
            max_verify_retries=0,
            ask={
                "candidate_enricher": "none",
                "graph_provider": "graphiti",
            },
        ),
        graph_store=_UngroundedGraphProvider(),
        structural_retriever=object(),
        memory=_EmptyMemory(),
        tool_executor=ToolExecutor(policy_engine=policy),
        verifier=AnswerVerifier(),
        llm=_EvidenceEchoLlm(),
        policy_engine=policy,
    )


def test_graph_provider_answer_without_sources_is_not_ask_evidence():
    service = _ungrounded_graph_ask_service()

    result = service.execute_ask(
        "Orion 的发布状态是什么？",
        user_id="u1",
        session_id="graph-evidence-boundary",
    )

    assert _UNSUPPORTED_PROVIDER_ANSWER not in result.answer
    assert "找到足够依据" in result.answer
    assert result.citations == []
    assert all(
        ref.source_id != "graph_answer"
        for ref in result.evidence_refs
    )


def test_graph_retrieval_contract_rejects_candidate_answer():
    with pytest.raises(ValidationError, match="answer"):
        GraphRetrievalResult(
            enabled=True,
            answer=_UNSUPPORTED_PROVIDER_ANSWER,
        )


def test_invalid_graph_provider_fails_closed_during_configuration():
    for provider in ("typo-provider", "ms_graphrag"):
        with pytest.raises(ValidationError, match="graph_provider"):
            Settings(ask={"graph_provider": provider})
