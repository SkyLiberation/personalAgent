from __future__ import annotations

from uuid import uuid4

import pytest

from personal_agent.application.knowledge import (
    Claim,
    ClaimRelationAdjudication,
    ClaimRelationCandidate,
    ConversationMessage,
    ClaimAdmissionPolicy,
    FixtureKnowledgeAnswerVerifier,
    InMemoryKnowledgeStore,
    KnowledgeStateMachine,
    KnowledgeService,
)
from personal_agent.infra.storage.postgres_knowledge_store import PostgresKnowledgeStore


class _AlwaysConflictJudge:
    name = "test-conflict-judge"

    def judge(
        self,
        candidate: ClaimRelationCandidate,
        new_claim: Claim,
        existing_claim: Claim,
    ) -> ClaimRelationAdjudication:
        return ClaimRelationAdjudication(
            relation_type="conflict",
            confidence=0.95,
            rationale="test semantic conflict",
            requires_decision=True,
        )


def test_ingest_text_creates_p0_chain_and_admits_supported_claims():
    store = InMemoryKnowledgeStore()
    service = KnowledgeService(store)

    result = service.ingest_text(
        "Redis 支持缓存。Redis 使用内存存储数据。",
        user_id="u1",
        owner_id="w1",
        source_type="document",
        source_ref="doc://redis",
    )

    assert result.artifact.artifact_id.startswith("art_")
    assert result.extraction_run.artifact_id == result.artifact.artifact_id
    assert result.evidence_blocks
    assert result.evidence_spans
    assert result.claims
    assert all(claim.evidence_span_ids for claim in result.claims)
    assert all(run.support_status == "supported" for run in result.grounding_runs)
    assert all(decision.admission_result == "allow_active" for decision in result.admission_decisions)
    assert all(claim.state == "active" for claim in result.claims)
    assert result.state_events
    assert result.knowledge_items
    assert result.knowledge_items[0].claim_ids
    active_items = store.list_knowledge_items("w1", state="active")
    deprecated_items = store.list_knowledge_items("w1", state="deprecated")
    assert {item.knowledge_item_id for item in active_items} == {
        item.knowledge_item_id for item in result.knowledge_items
    }
    assert len(deprecated_items) == 1
    assert deprecated_items[0].claim_ids == []


def test_assistant_inference_never_becomes_active_even_when_grounded():
    service = KnowledgeService(InMemoryKnowledgeStore())

    result = service.ingest_text(
        "用户可能喜欢低延迟缓存方案。",
        owner_id="w1",
        source_type="conversation",
        created_by="assistant",
    )

    assert result.claims
    assert all(claim.claim_type == "assistant_inference" for claim in result.claims)
    assert all(claim.state == "rejected" for claim in result.claims)
    assert all(decision.admission_result == "reject" for decision in result.admission_decisions)


def test_answer_with_evidence_returns_resolvable_citations_without_saving_answer_claims():
    store = InMemoryKnowledgeStore()
    service = KnowledgeService(
        store,
        answer_verifier=FixtureKnowledgeAnswerVerifier(),
    )
    service.ingest_text(
        "蓝绿发布会同时保留两套环境。发布时可以将一半流量切到绿色环境。",
        owner_id="w1",
        source_type="document",
    )

    answer = service.answer_with_evidence("蓝绿发布如何切流量？", owner_id="w1")

    assert answer.verification.verdict == "passed"
    assert answer.verification.conclusion_status == "supported"
    assert answer.citations
    assert answer.answer_claim_saved_count == 0
    assert answer.active_claim_count_delta == 0
    for citation in answer.citations:
        assert store.get_evidence_span(citation.evidence_span_id) is not None
        assert store.get_evidence_block(citation.evidence_block_id) is not None
        assert citation.artifact_id
        assert citation.claim_ids
    assert answer.selected_claim_ids


def test_no_evidence_question_returns_conservative_answer():
    service = KnowledgeService(InMemoryKnowledgeStore())

    answer = service.answer_with_evidence("完全不存在的主题是什么？", owner_id="w1")

    assert answer.verification.verdict == "insufficient_evidence"
    assert answer.verification.conclusion_status == "insufficient_evidence"
    assert answer.citations == []
    assert "证据不足" in answer.answer


def test_sensitive_claim_creates_decision_card_and_does_not_active_directly():
    store = InMemoryKnowledgeStore()
    service = KnowledgeService(store)

    result = service.ingest_text(
        "我的 api key 是 sk-secret-123。",
        owner_id="w1",
        source_type="conversation",
        created_by="user",
    )

    assert result.decisions
    assert result.decisions[0].decision_type == "claim_admission"
    assert result.decisions[0].status == "pending"
    assert all(claim.state != "active" for claim in result.claims)
    assert store.list_decisions("w1", status="pending")


def test_unsupported_claim_is_rejected_by_admission_policy():
    claim = Claim(
        statement="Redis 只能存储图片。",
        claim_type="external_fact",
        support_status="unsupported",
    )

    decision = ClaimAdmissionPolicy().evaluate(claim)

    assert decision.admission_result == "reject"
    assert decision.decision_policy == "block"


def test_state_machine_blocks_illegal_active_transition():
    claim = Claim(
        statement="Redis 只能存储图片。",
        claim_type="external_fact",
        support_status="unsupported",
    )

    with pytest.raises(ValueError, match="unsupported -> active"):
        KnowledgeStateMachine().assert_allowed(claim, "active")


def test_solidify_conversation_only_persists_user_claims():
    service = KnowledgeService(InMemoryKnowledgeStore())

    result = service.solidify_conversation(
        [
            ConversationMessage(role="user", content="我的部署窗口是每周三上午十点。"),
            ConversationMessage(role="assistant", content="我推断你可能喜欢夜间发布。"),
        ],
        user_id="u1",
        owner_id="w1",
    )

    assert result.user_claim_count >= 1
    assert result.assistant_candidate_count >= 1
    assert result.rejected_assistant_claim_count == result.assistant_candidate_count
    assert all(claim.created_by == "user" for claim in result.ingest_result.claims)
    assert all(claim.state == "active" for claim in result.ingest_result.claims)
    evidence_span_ids = {
        span.evidence_span_id for span in result.ingest_result.evidence_spans
    }
    assert evidence_span_ids
    assert all(
        evidence_span_ids.intersection(item.evidence_span_ids)
        for item in result.ingest_result.knowledge_items
    )


def test_correct_claim_supersedes_old_claim_and_creates_relation():
    store = InMemoryKnowledgeStore()
    service = KnowledgeService(store)
    ingest = service.ingest_text(
        "Atlas 的部署窗口是周三上午十点。",
        owner_id="w1",
        source_type="document",
    )
    old_claim = ingest.claims[0]

    result = service.correct_claim(
        old_claim.claim_id,
        "Atlas 的部署窗口是周四上午十点。",
        user_id="u1",
    )

    assert result.old_claim.state == "superseded"
    assert result.new_claim.state == "active"
    assert result.relation.relation_type == "supersede"
    assert result.relation.source_id == result.new_claim.claim_id
    assert result.relation.target_id == old_claim.claim_id
    assert store.get_claim(old_claim.claim_id).state == "superseded"


def test_correction_state_transition_is_readable_with_actor_and_from_state():
    """A superseded claim must be able to answer who changed it, when, and from what.

    Without a read path the written KnowledgeStateEvent is unobservable, so
    "history is auditable" would be a claim with no production consumer.
    """
    store = InMemoryKnowledgeStore()
    service = KnowledgeService(store)
    ingest = service.ingest_text(
        "Atlas 的部署窗口是周三上午十点。",
        owner_id="w1",
        source_type="document",
    )
    old_claim = ingest.claims[0]
    previous_state = old_claim.state

    service.correct_claim(
        old_claim.claim_id,
        "Atlas 的部署窗口是周四上午十点。",
        user_id="u1",
        actor="user",
    )

    history = store.list_knowledge_state_events("w1", target_id=old_claim.claim_id)
    supersede = [event for event in history if event.to_state == "superseded"]
    assert len(supersede) == 1
    assert supersede[0].from_state == previous_state
    assert supersede[0].actor == "user"
    assert supersede[0].reason == "user correction"
    assert supersede[0].target_id == old_claim.claim_id


def test_potential_conflict_creates_relation_decision_and_gap_without_state_change():
    store = InMemoryKnowledgeStore()
    service = KnowledgeService(
        store,
        answer_verifier=FixtureKnowledgeAnswerVerifier(),
    )
    first = service.ingest_text(
        "Orion 功能默认开启。",
        owner_id="w1",
        source_type="document",
    )
    second = service.ingest_text(
        "Orion 功能默认关闭。",
        owner_id="w1",
        source_type="document",
    )

    relations = store.list_knowledge_relations("w1", relation_type="potential_conflict")

    assert relations
    assert first.claims[0].claim_id in {relations[0].source_id, relations[0].target_id}
    assert second.claims[0].claim_id in {relations[0].source_id, relations[0].target_id}
    assert store.get_claim(first.claims[0].claim_id).state == "active"
    assert store.get_claim(second.claims[0].claim_id).state == "active"
    assert store.list_decisions("w1", status="pending")
    assert store.list_knowledge_gaps("w1", state="open")
    answer = service.answer_with_evidence("Orion 功能默认是否开启？", owner_id="w1")
    assert not answer.conflicted_claim_ids
    assert answer.diagnostic_fields["potential_conflicted_claim_ids"]
    assert "潜在冲突" in answer.answer


def test_semantic_conflict_judge_marks_both_claims_conflicted():
    store = InMemoryKnowledgeStore()
    service = KnowledgeService(
        store,
        relation_judge=_AlwaysConflictJudge(),
        answer_verifier=FixtureKnowledgeAnswerVerifier(),
    )
    first = service.ingest_text(
        "Orion 功能默认开启。",
        owner_id="w1",
        source_type="document",
    )
    second = service.ingest_text(
        "Orion 功能默认关闭。",
        owner_id="w1",
        source_type="document",
    )

    relations = store.list_knowledge_relations("w1", relation_type="conflict")

    assert relations
    assert first.claims[0].claim_id in {relations[0].source_id, relations[0].target_id}
    assert second.claims[0].claim_id in {relations[0].source_id, relations[0].target_id}
    assert store.get_claim(first.claims[0].claim_id).state == "conflicted"
    assert store.get_claim(second.claims[0].claim_id).state == "conflicted"
    answer = service.answer_with_evidence("Orion 功能默认是否开启？", owner_id="w1")
    assert answer.conflicted_claim_ids


def test_research_event_enters_lifecycle_and_records_feedback():
    store = InMemoryKnowledgeStore()
    service = KnowledgeService(store)
    service.ingest_text(
        "Kappa API rate limit 是每分钟 60 次。",
        owner_id="w1",
        source_type="document",
    )

    result = service.ingest_research_event(
        topic="Kappa API",
        title="Kappa API rate limit update",
        summary="Kappa API rate limit 是每分钟 120 次。",
        owner_id="w1",
        source_ref="https://example.com/kappa",
    )
    feedback = service.submit_research_feedback(
        result.event.research_event_id,
        negative_feedback_reason="already_known",
    )

    assert result.event.status == "saved"
    assert result.ingest_result.claims
    assert result.event.artifact_id == result.ingest_result.artifact.artifact_id
    assert store.list_knowledge_relations("w1")
    assert feedback.negative_feedback_reason == "already_known"
    assert feedback.interest_score <= 0.25


def test_review_plan_uses_claim_state_and_creates_conflict_gap():
    store = InMemoryKnowledgeStore()
    service = KnowledgeService(store)
    service.ingest_text("Orion 功能默认开启。", owner_id="w1", source_type="document")
    service.ingest_text("Orion 功能默认关闭。", owner_id="w1", source_type="document")

    result = service.plan_review_and_gaps(owner_id="w1")

    assert result.knowledge_gaps
    assert any(gap.gap_type == "conflict" for gap in result.knowledge_gaps)
    assert store.list_knowledge_gaps("w1", state="open")


def test_review_plan_creates_due_items_for_active_claims():
    store = InMemoryKnowledgeStore()
    service = KnowledgeService(store)
    service.ingest_text("Redis 支持缓存。", owner_id="w1", source_type="document")

    result = service.plan_review_and_gaps(owner_id="w1")

    assert result.review_items
    assert result.review_items[0].state == "due"
    assert result.review_items[0].claim_id
    assert store.list_review_items("w1", state="due")


def test_graph_projection_backlinks_to_claim_and_evidence():
    store = InMemoryKnowledgeStore()
    service = KnowledgeService(store)
    ingest = service.ingest_text(
        "Redis 支持缓存。",
        owner_id="w1",
        source_type="document",
    )

    result = service.project_knowledge_graph(owner_id="w1")

    assert result.projections
    assert result.backlink_ok is True
    projection = result.projections[0]
    assert projection.source_claim_id == ingest.claims[0].claim_id
    assert projection.backlink_claim_ids == [ingest.claims[0].claim_id]
    assert projection.backlink_evidence_span_ids
    assert projection.relation_facts == [ingest.claims[0].statement]


@pytest.mark.usefixtures("clean_postgres_business_tables")
def test_postgres_knowledge_store_roundtrips_p0_chain(postgres_url: str):
    owner_id = f"w-{uuid4().hex}"
    store = PostgresKnowledgeStore(postgres_url)
    service = KnowledgeService(store)

    result = service.ingest_text(
        "Postgres 支持 JSONB。JSONB 可以存储结构化 payload。",
        owner_id=owner_id,
        source_type="document",
    )
    answer = service.answer_with_evidence("Postgres 支持什么结构化字段？", owner_id=owner_id)

    assert store.get_artifact(result.artifact.artifact_id) is not None
    assert store.list_claims(owner_id, state="active")
    assert answer.citations
    assert store.get_evidence_block(answer.citations[0].evidence_block_id) is not None


@pytest.mark.usefixtures("clean_postgres_business_tables")
def test_postgres_knowledge_store_reads_back_correction_state_events(postgres_url: str):
    owner_id = f"w-{uuid4().hex}"
    store = PostgresKnowledgeStore(postgres_url)
    service = KnowledgeService(store)

    ingest = service.ingest_text(
        "Orion 的维护窗口是周三。",
        owner_id=owner_id,
        source_type="document",
    )
    old_claim = ingest.claims[0]

    service.correct_claim(
        old_claim.claim_id,
        "Orion 的维护窗口是周四。",
        user_id="u1",
        actor="user",
    )

    history = store.list_knowledge_state_events(owner_id, target_id=old_claim.claim_id)
    assert [event.to_state for event in history if event.to_state == "superseded"] == ["superseded"]
    assert all(event.target_id == old_claim.claim_id for event in history)
    other = store.list_knowledge_state_events(f"w-{uuid4().hex}")
    assert other == []
