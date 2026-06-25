from __future__ import annotations

from personal_agent.orchestration.ask import AskRunContext, AskRunContextStore, PostgresAskRunContextStore
from personal_agent.application.verifier import ClaimVerification, VerificationResult
from personal_agent.kernel.evidence import EvidenceItem, build_context_pack
from personal_agent.kernel.models import Citation
from personal_agent.kernel.query_understanding import QueryUnderstanding, RetrievalPlan


def _sample_context(sample_note) -> AskRunContext:
    evidence = EvidenceItem(
        source_type="chunk",
        source_id=sample_note.id,
        title=sample_note.body.title,
        snippet=sample_note.body.summary,
        score=0.8,
        metadata={"retrieved_by": "local"},
    )
    citation = Citation(
        note_id=sample_note.id,
        title=sample_note.body.title,
        snippet=sample_note.body.summary,
    )
    ctx = AskRunContext(
        question="Python 单元测试是什么？",
        user_id="u1",
        session_id="s1",
        working_context="当前任务目标：回答用户问题",
        structured_context="用户：之前问过 Python",
        has_dialogue_context=True,
        trace_id="trace-1",
    )
    ctx.understanding = QueryUnderstanding(query_rewrite="Python 单元测试")
    ctx.retrieval_plan = RetrievalPlan(query="Python 单元测试", sources=["local"])
    ctx.effective_query = "Python 单元测试"
    ctx.evidence_pool = [evidence]
    ctx.combined_matches = [sample_note]
    ctx.combined_citations = [citation]
    ctx.context_pack = build_context_pack(ctx.question, [evidence])
    ctx.selected_matches = [sample_note]
    ctx.selected_citations = [citation]
    ctx.answer = "Python 单元测试用于验证函数行为。"
    ctx.verification = VerificationResult(
        evidence_score=0.8,
        citation_valid=True,
        warnings=["ok"],
        claim_checks=[
            ClaimVerification(
                claim="Python 单元测试用于验证函数行为",
                status="supported",
                supporting_evidence_ids=[evidence.evidence_id],
            )
        ],
    )
    ctx.add_trace("ContextPack selected=1")
    return ctx


def test_ask_context_artifact_roundtrip(sample_note):
    ctx = _sample_context(sample_note)

    restored = AskRunContext.from_artifact_payload(ctx.to_artifact_payload())

    assert restored.question == ctx.question
    assert restored.understanding.query_rewrite == "Python 单元测试"
    assert restored.retrieval_plan.sources == ["local"]
    assert restored.context_pack.evidence[0].source_id == sample_note.id
    assert restored.selected_matches[0].id == sample_note.id
    assert restored.selected_citations[0].note_id == sample_note.id
    assert restored.verification.evidence_score == 0.8
    assert restored.verification.claim_checks[0].status == "supported"
    assert restored.trace_steps == ["ContextPack selected=1"]


def test_in_memory_store_uses_artifact_payload_boundary(sample_note):
    store = AskRunContextStore()
    ctx = _sample_context(sample_note)
    store.put("run-1", ctx)

    ctx.answer = "mutated after put"
    restored = store.get("run-1")

    assert restored is not ctx
    assert restored.answer == "Python 单元测试用于验证函数行为。"


def test_postgres_store_persists_ask_context(postgres_url, clean_postgres_business_tables, sample_note):
    store = PostgresAskRunContextStore(postgres_url)
    ctx = _sample_context(sample_note)

    store.put("run-artifact-1", ctx)
    restored = PostgresAskRunContextStore(postgres_url).get("run-artifact-1")

    assert restored is not None
    assert restored.question == ctx.question
    assert restored.context_pack.evidence[0].source_id == sample_note.id
    assert restored.answer == ctx.answer

    restored.answer = "updated answer"
    store.put("run-artifact-1", restored)
    updated = PostgresAskRunContextStore(postgres_url).get("run-artifact-1")
    assert updated.answer == "updated answer"
