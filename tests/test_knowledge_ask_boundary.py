from __future__ import annotations

from personal_agent.application.knowledge import (
    FixtureKnowledgeAnswerVerifier,
    InMemoryKnowledgeStore,
    KnowledgeService,
)
from personal_agent.application.verifier import AnswerVerifier
from personal_agent.governance.policy import PolicyEngine
from personal_agent.governance.registry import ToolExecutor
from personal_agent.kernel.config import Settings
from personal_agent.orchestration.runtime_ask import AskService


class _UnavailableGraphStore:
    @staticmethod
    def configured() -> bool:
        return False


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


class _RecordingKnowledgeAnswerVerifier:
    name = "recording-knowledge-answer-verifier"
    version = "v1"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._delegate = FixtureKnowledgeAnswerVerifier()

    def verify(self, **kwargs):
        self.calls.append("knowledge_answer_semantic_verification")
        return self._delegate.verify(**kwargs)


class _AnswerLlm:
    @staticmethod
    def generate_answer(prompt: str, **kwargs) -> str:
        return (
            "Northstar 存在两个互相冲突的迁移日期："
            "2026-09-10 和 2026-10-15，需要进一步确认。"
        )


def _claim_sensitive_ask_service() -> tuple[AskService, _RecordingKnowledgeAnswerVerifier]:
    knowledge_store = InMemoryKnowledgeStore()
    recorder = _RecordingKnowledgeAnswerVerifier()
    knowledge = KnowledgeService(knowledge_store, answer_verifier=recorder)
    knowledge.ingest_text(
        (
            "Northstar 的迁移日期是 2026-09-10。"
            "Northstar 的迁移日期是 2026-10-15。"
        ),
        user_id="u1",
        owner_id="u1",
        source_type="document",
    )
    policy = PolicyEngine()
    service = AskService(
        settings=Settings(
            max_verify_retries=0,
            ask={"candidate_enricher": "none"},
        ),
        graph_store=_UnavailableGraphStore(),
        structural_retriever=object(),
        memory=_EmptyMemory(),
        tool_executor=ToolExecutor(policy_engine=policy),
        verifier=AnswerVerifier(),
        llm=_AnswerLlm(),
        knowledge_service=knowledge,
        policy_engine=policy,
    )
    return service, recorder


def test_claim_sensitive_ask_retrieves_knowledge_evidence_without_verifying_discarded_answer():
    service, recorder = _claim_sensitive_ask_service()

    ctx = service.build_run_context(
        "Northstar 的迁移日期是否冲突？",
        user_id="u1",
        session_id="baseline-knowledge-boundary",
    )
    service.run_retrieval_stage(ctx)

    knowledge_evidence = [
        item
        for item in ctx.evidence_pool
        if item.metadata.get("retrieved_by") == "personal_knowledge"
    ]
    assert knowledge_evidence
    assert all("answer_verification" not in item.metadata for item in knowledge_evidence)
    assert recorder.calls == []
    service.run_generation_stage(ctx)
    service.run_verification_stage(ctx)
    service.run_repair_stage(ctx)
    result = service.context_to_result(ctx)
    assert "2026-09-10" in result.answer
    assert "2026-10-15" in result.answer
    assert result.citations


def test_formal_knowledge_answer_still_owns_answer_verification():
    service, recorder = _claim_sensitive_ask_service()

    answer = service.knowledge_service.answer_with_evidence(
        "Northstar 的迁移日期是否冲突？",
        owner_id="u1",
    )

    assert answer.citations
    assert recorder.calls == ["knowledge_answer_semantic_verification"]
