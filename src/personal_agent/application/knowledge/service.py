from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

from personal_agent.application.evidence_engine import evidence_terms, extract_claims
from personal_agent.application.knowledge.models import (
    AnswerCitation,
    ArtifactDeleteImpactResult,
    Artifact,
    Claim,
    ClaimAdmissionDecision,
    ClaimSupportEvent,
    ClaimCorrectionResult,
    ClaimQualityGate,
    ConversationMessage,
    ConversationSolidifyResult,
    CoverageManifest,
    CoverageRegion,
    DecisionCard,
    EvidenceRef,
    EvidenceBlock,
    EvidenceSpan,
    ExtractionRun,
    GraphProjection,
    GraphProjectionResult,
    GroundingRun,
    IngestKnowledgeResult,
    KnowledgeGap,
    KnowledgeItem,
    KnowledgeStateEvent,
    KnowledgeRelation,
    ProjectionJob,
    ResearchEvent,
    ResearchIngestResult,
    ReviewItem,
    ReviewPlanResult,
    SemanticReplayDiffResult,
    KnowledgeEvidenceSelection,
    stable_hash,
)
from personal_agent.application.knowledge.policy import ClaimAdmissionPolicy, KnowledgeStateMachine
from personal_agent.application.knowledge.relation_judge import (
    ClaimRelationAdjudication,
    ClaimRelationCandidate,
    ClaimRelationJudge,
)
from personal_agent.application.knowledge.semantic import (
    ClaimGroundingJudge,
    LocalSemanticFixtureClaimExtractor,
    LocalSemanticFixtureExtractor,
    LocalSemanticFixtureGroundingJudge,
    SemanticClaimExtractor,
    SemanticEvidenceExtraction,
    SemanticEvidenceExtractor,
    calibration_from_grounding,
)
from personal_agent.application.knowledge.store import KnowledgeStore
from personal_agent.application.knowledge.text_rules import (
    block_type as _block_type,
    canonical as _canonical,
    confidence_for_support as _confidence_for_support,
    extract_entities as _extract_entities,
    knowledge_item_title as _knowledge_item_title,
    normalize_meaning as _normalize_meaning,
    normalize_text as _normalize_text,
    relation_between_claims as _relation_between_claims,
    relation_write_allowed as _relation_write_allowed,
    requires_scope as _requires_scope,
    semantic_claim_parts as _semantic_claim_parts,
    semantic_tags as _semantic_tags,
    sensitivity_level as _sensitivity_level,
    span_type as _span_type,
    split_blocks as _split_blocks,
    split_spans as _split_spans,
)


@dataclass(slots=True)
class KnowledgeService:
    store: KnowledgeStore
    admission_policy: ClaimAdmissionPolicy | None = None
    state_machine: KnowledgeStateMachine | None = None
    relation_judge: ClaimRelationJudge | None = None
    semantic_evidence_extractor: SemanticEvidenceExtractor | None = None
    semantic_claim_extractor: SemanticClaimExtractor | None = None
    claim_grounding_judge: ClaimGroundingJudge | None = None

    def __post_init__(self) -> None:
        self.admission_policy = self.admission_policy or ClaimAdmissionPolicy()
        self.state_machine = self.state_machine or KnowledgeStateMachine()
        self.semantic_evidence_extractor = self.semantic_evidence_extractor or LocalSemanticFixtureExtractor()
        self.semantic_claim_extractor = self.semantic_claim_extractor or LocalSemanticFixtureClaimExtractor()
        self.claim_grounding_judge = self.claim_grounding_judge or LocalSemanticFixtureGroundingJudge()

    def ingest_text(
        self,
        text: str,
        *,
        user_id: str = "default",
        owner_id: str = "default",
        source_type: str = "text",
        source_ref: str | None = None,
        raw_location: str = "",
        artifact_id: str | None = None,
        artifact_metadata: dict[str, object] | None = None,
        created_by: str = "user",
        extract_claim_limit: int = 12,
    ) -> IngestKnowledgeResult:
        # Convenience composition: the target architecture exposes evidence-first
        # ingest and claim lifecycle as separate methods below.
        ingest = self.ingest_knowledge(
            text,
            user_id=user_id,
            owner_id=owner_id,
            source_type=source_type,
            source_ref=source_ref,
            raw_location=raw_location,
            artifact_id=artifact_id,
            artifact_metadata=artifact_metadata,
        )
        return self.enhance_claim_lifecycle(
            ingest,
            created_by=created_by,
            extract_claim_limit=extract_claim_limit,
        )

    def ingest_knowledge(
        self,
        text: str,
        *,
        user_id: str = "default",
        owner_id: str = "default",
        source_type: str = "text",
        source_ref: str | None = None,
        raw_location: str = "",
        artifact_id: str | None = None,
        artifact_metadata: dict[str, object] | None = None,
    ) -> IngestKnowledgeResult:
        """Evidence-first ingest: Artifact/Evidence is the success boundary."""
        normalized = _normalize_text(text)
        if not normalized:
            raise ValueError("text is required")
        artifact = Artifact(
            **({"artifact_id": artifact_id} if artifact_id else {}),
            owner_id=owner_id,
            user_id=user_id,
            source_type=source_type,
            source_ref=source_ref,
            content_hash=stable_hash(normalized),
            raw_location=raw_location or source_ref or "",
            text=normalized,
            metadata=artifact_metadata or {},
        )
        extraction_run = ExtractionRun(
            artifact_id=artifact.artifact_id,
            owner_id=owner_id,
            input_hash=artifact.content_hash,
            semantic_extractor_version=self.semantic_evidence_extractor.version if self.semantic_evidence_extractor else "",
            prompt_version=self.semantic_evidence_extractor.version if self.semantic_evidence_extractor else "",
            model_name=self.semantic_evidence_extractor.name if self.semantic_evidence_extractor else "",
        )
        blocks = self._build_evidence_blocks(artifact, extraction_run.extraction_run_id)
        semantic_failed = False
        semantic_result: SemanticEvidenceExtraction | None = None
        try:
            semantic_result = self.semantic_evidence_extractor.extract(  # type: ignore[union-attr]
                artifact=artifact,
                blocks=blocks,
            )
            spans = self._build_semantic_evidence_spans(
                semantic_result,
                blocks,
                owner_id=owner_id,
            )
        except Exception as exc:  # pragma: no cover - exercised through fallback tests.
            semantic_failed = True
            semantic_result = LocalSemanticFixtureExtractor().extract(artifact=artifact, blocks=blocks)
            spans = self._build_semantic_evidence_spans(
                semantic_result,
                blocks,
                owner_id=owner_id,
            )
            extraction_run.status = "partial"
            extraction_run.errors.append(f"semantic_evidence_extraction_failed:{type(exc).__name__}:{exc}")
        manifest = self._coverage_manifest(artifact, extraction_run, blocks, spans)
        if semantic_result is not None:
            for omitted in semantic_result.omitted_regions:
                manifest.expected_regions.append(CoverageRegion(
                    locator=omitted.locator,
                    region_type=omitted.region_type,
                    parse_status="parsed",
                    semantic_status="omitted",
                    reason=omitted.reason,
                ))
            manifest.omitted_region_count = sum(
                1 for region in manifest.expected_regions
                if region.parse_status in {"omitted", "partial", "failed"}
                or region.semantic_status in {"omitted", "partial", "failed"}
            )
            manifest.coverage_status = "partial" if manifest.omitted_region_count else manifest.coverage_status
        extraction_run.coverage_manifest = manifest.model_dump(mode="json")
        extraction_run.parsed_region_count = manifest.parsed_region_count
        extraction_run.semantic_region_count = manifest.semantic_region_count
        extraction_run.coverage_status = manifest.coverage_status
        extraction_run.omitted_regions = [
            region.model_dump(mode="json")
            for region in manifest.expected_regions
            if region.parse_status in {"omitted", "partial", "failed"}
            or region.semantic_status in {"omitted", "partial", "failed"}
        ]
        for block in blocks:
            artifact.derived_evidence_block_ids.append(block.evidence_block_id)
            extraction_run.evidence_block_ids.append(block.evidence_block_id)
        extraction_run.evidence_span_ids = [span.evidence_span_id for span in spans]
        knowledge_items = [self._minimal_knowledge_item(artifact, spans, primary_state="evidence_ready")]
        if semantic_failed:
            knowledge_items = [
                item.model_copy(update={
                    "primary_state": "partial_failed",
                    "flags": sorted({*item.flags, "semantic_extraction_failed"}),
                })
                for item in knowledge_items
            ]
        self.store.save_artifact(artifact)
        self.store.save_extraction_run(extraction_run)
        self.store.save_evidence_blocks(blocks)
        self.store.save_evidence_spans(spans)
        self.store.save_knowledge_items(knowledge_items)
        projection_jobs = self._enqueue_projection_jobs(
            owner_id=owner_id,
            source_object_type="artifact",
            source_object_id=artifact.artifact_id,
            include_claims=False,
        )
        return IngestKnowledgeResult(
            artifact=artifact,
            extraction_run=extraction_run,
            evidence_blocks=blocks,
            evidence_spans=spans,
            claims=[],
            grounding_runs=[],
            support_events=[],
            admission_decisions=[],
            state_events=[],
            knowledge_items=knowledge_items,
            projection_jobs=projection_jobs,
        )

    def enhance_claim_lifecycle(
        self,
        ingest: IngestKnowledgeResult,
        *,
        created_by: str = "user",
        extract_claim_limit: int = 12,
    ) -> IngestKnowledgeResult:
        """Run recoverable Claim/Grounding/Admission enhancement for an ingest."""
        artifact = ingest.artifact
        owner_id = artifact.owner_id
        evidence_refs_by_span = {
            span.evidence_span_id: self._evidence_ref_for_span_id(
                span.evidence_span_id,
                extraction_run_id=ingest.extraction_run.extraction_run_id,
            )
            for span in ingest.evidence_spans
        }
        evidence_refs = [ref for ref in evidence_refs_by_span.values() if ref is not None]
        claim_extraction_failed = False
        try:
            claim_extraction = self.semantic_claim_extractor.extract(  # type: ignore[union-attr]
                artifact=artifact,
                spans=ingest.evidence_spans,
                evidence_refs=evidence_refs,
                created_by=created_by,
                limit=extract_claim_limit,
            )
            claims = self._claims_from_semantic_extraction(
                claim_extraction,
                artifact=artifact,
                evidence_spans=ingest.evidence_spans,
                user_id=artifact.user_id,
                owner_id=owner_id,
                created_from=artifact.artifact_id,
                created_by=created_by,
                source_type=artifact.source_type,
                evidence_refs_by_span=evidence_refs_by_span,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback.
            claim_extraction_failed = True
            ingest.extraction_run.status = "partial"
            ingest.extraction_run.errors.append(f"semantic_claim_extraction_failed:{type(exc).__name__}:{exc}")
            claim_extraction = LocalSemanticFixtureClaimExtractor().extract(
                artifact=artifact,
                spans=ingest.evidence_spans,
                evidence_refs=evidence_refs,
                created_by=created_by,
                limit=extract_claim_limit,
            )
            claims = self._claims_from_semantic_extraction(
                claim_extraction,
                artifact=artifact,
                evidence_spans=ingest.evidence_spans,
                user_id=artifact.user_id,
                owner_id=owner_id,
                created_from=artifact.artifact_id,
                created_by=created_by,
                source_type=artifact.source_type,
                evidence_refs_by_span=evidence_refs_by_span,
            )
        grounding_runs: list[GroundingRun] = []
        support_events: list[ClaimSupportEvent] = []
        admission_decisions: list[ClaimAdmissionDecision] = []
        state_events: list[KnowledgeStateEvent] = []
        decisions: list[DecisionCard] = []
        existing_claims = self.store.list_claims(owner_id, limit=500)
        for claim in claims:
            grounding = self._ground_claim_with_judge(
                claim,
                evidence_spans=ingest.evidence_spans,
                source_type=artifact.source_type,
                created_by=created_by,
            )
            grounding_runs.append(grounding)
            claim.support_status = grounding.support_status
            claim.evidence_span_ids = list(grounding.evidence_span_ids)
            if claim.evidence_span_ids:
                claim.evidence_refs = [
                    ref for span_id in claim.evidence_span_ids
                    if (ref := self._evidence_ref_for_span_id(
                        span_id,
                        extraction_run_id=ingest.extraction_run.extraction_run_id,
                    )) is not None
                ]
            claim.confidence = _confidence_for_support(grounding.support_status)
            claim.quality_gate = self._claim_quality_gate(claim, grounding=grounding)
            support_events.append(ClaimSupportEvent(
                owner_id=owner_id,
                claim_id=claim.claim_id,
                from_support_status=None,
                to_support_status=grounding.support_status,
                grounding_run_id=grounding.grounding_run_id,
                reason=grounding.rationale,
            ))
            admission = self.admission_policy.evaluate(claim)
            admission_decisions.append(admission)
            decision_card = self._decision_card_for_admission(claim, admission)
            if decision_card is not None:
                decisions.append(decision_card)
            from_state = claim.state
            claim.state = self.state_machine.next_state(claim, admission)
            claim.quality_gate = self._claim_quality_gate(claim, grounding=grounding)
            state_events.append(KnowledgeStateEvent(
                owner_id=owner_id,
                target_id=claim.claim_id,
                from_state=from_state,
                to_state=claim.state,
                reason=admission.reason,
                evidence_span_ids=list(claim.evidence_span_ids),
                grounding_run_id=grounding.grounding_run_id,
                decision_id=admission.admission_id,
                policy_result=admission.admission_result,
            ))
        relations, relation_state_events, relation_updated_claims, relation_decisions, relation_gaps = (
            self._relate_new_claims(claims, existing_claims, owner_id=owner_id)
        )
        state_events.extend(relation_state_events)
        if relation_updated_claims:
            self.store.save_claims(relation_updated_claims)
        decisions.extend(relation_decisions)
        claim_ids_by_span: dict[str, list[str]] = {}
        for claim in claims:
            for evidence_span_id in claim.evidence_span_ids:
                claim_ids_by_span.setdefault(evidence_span_id, []).append(claim.claim_id)
        spans = [
            span.model_copy(update={"claim_ids": claim_ids_by_span.get(span.evidence_span_id, [])})
            for span in ingest.evidence_spans
        ]
        ingest.extraction_run.claim_ids = [claim.claim_id for claim in claims]
        knowledge_items = self._build_knowledge_items(claims)
        if not knowledge_items:
            flags = ["claims_pending"]
            if claim_extraction_failed:
                flags.append("semantic_claim_failed")
            knowledge_items = [
                item.model_copy(update={"flags": sorted({*item.flags, *flags})})
                for item in ingest.knowledge_items
            ]
        else:
            # The evidence-first item is a provisional projection. Once
            # claim-backed projections exist it must leave the active view;
            # keeping both would expose one canonical artifact as two notes.
            self.store.save_knowledge_items(
                item.model_copy(update={
                    "state": "deprecated",
                    "flags": sorted({*item.flags, "claims_pending"}),
                })
                for item in ingest.knowledge_items
            )
        self.store.save_evidence_spans(spans)
        self.store.save_extraction_run(ingest.extraction_run)
        self.store.save_claims(claims)
        self.store.save_grounding_runs(grounding_runs)
        self.store.save_claim_support_events(support_events)
        self.store.save_claim_admission_decisions(admission_decisions)
        self.store.save_knowledge_state_events(state_events)
        self.store.save_knowledge_relations(relations)
        self.store.save_knowledge_items(knowledge_items)
        self.store.save_knowledge_gaps(relation_gaps)
        self.store.save_decisions(decisions)
        projection_jobs = self._enqueue_projection_jobs(
            owner_id=owner_id,
            source_object_type="claim",
            source_object_id=artifact.artifact_id,
            include_claims=bool(claims),
        )
        return ingest.model_copy(update={
            "evidence_spans": spans,
            "claims": claims,
            "grounding_runs": grounding_runs,
            "support_events": support_events,
            "admission_decisions": admission_decisions,
            "state_events": state_events,
            "relations": relations,
            "knowledge_items": knowledge_items,
            "projection_jobs": [*ingest.projection_jobs, *projection_jobs],
            "decisions": decisions,
            "partial_failure_count": 0,
        })

    def select_evidence(
        self,
        question: str,
        *,
        owner_id: str = "default",
        limit: int = 5,
    ) -> KnowledgeEvidenceSelection:
        normalized = _normalize_text(question)
        if not normalized:
            raise ValueError("question is required")
        selected_claims = self._select_answerable_claims(
            normalized,
            owner_id=owner_id,
            limit=limit,
        )
        if not selected_claims:
            return KnowledgeEvidenceSelection(
                question=question,
                reason="no_answerable_claim",
            )
        selected = self._evidence_for_claims(
            selected_claims,
            owner_id=owner_id,
            limit=limit,
        )
        if not selected:
            return KnowledgeEvidenceSelection(
                question=question,
                reason="no_answerable_claim_evidence",
            )
        citations: list[AnswerCitation] = []
        conflicting_ids = self._conflicting_claim_ids(owner_id, selected_claims)
        potential_conflicting_ids = self._potential_conflicting_claim_ids(owner_id, selected_claims)
        for span in selected:
            block = self.store.get_evidence_block(span.evidence_block_id)
            artifact_id = block.artifact_id if block is not None else ""
            evidence_ref = EvidenceRef(
                source_kind="evidence_span",
                source_id=span.evidence_span_id,
                artifact_id=artifact_id,
                evidence_block_id=span.evidence_block_id,
                evidence_span_id=span.evidence_span_id,
                locator=block.locator if block is not None else "",
                quote_hash=span.quote_hash,
                extraction_run_id=block.extraction_run_id if block is not None else "",
            )
            citations.append(AnswerCitation(
                evidence_span_id=span.evidence_span_id,
                evidence_block_id=span.evidence_block_id,
                artifact_id=artifact_id,
                quote=span.text_span,
                locator=block.locator if block is not None else "",
                evidence_ref=evidence_ref,
                claim_ids=[
                    claim.claim_id
                    for claim in selected_claims
                    if span.evidence_span_id in claim.evidence_span_ids
                ],
            ))
        return KnowledgeEvidenceSelection(
            question=question,
            selected_spans=selected,
            citations=citations,
            selected_claims=selected_claims,
            conflicted_claim_ids=conflicting_ids,
            potential_conflicted_claim_ids=potential_conflicting_ids,
        )

    def solidify_conversation(
        self,
        messages: list[ConversationMessage | dict[str, str]],
        *,
        user_id: str = "default",
        owner_id: str = "default",
    ) -> ConversationSolidifyResult:
        normalized_messages = [
            item if isinstance(item, ConversationMessage) else ConversationMessage.model_validate(item)
            for item in messages
        ]
        user_text = "\n".join(item.content for item in normalized_messages if item.role == "user")
        assistant_text = "\n".join(item.content for item in normalized_messages if item.role == "assistant")
        assistant_claim_count = len(extract_claims(assistant_text, limit=20)) if assistant_text.strip() else 0
        ingest = self.ingest_text(
            user_text,
            user_id=user_id,
            owner_id=owner_id,
            source_type="conversation",
            created_by="user",
        )
        return ConversationSolidifyResult(
            ingest_result=ingest,
            user_claim_count=len(ingest.claims),
            assistant_candidate_count=assistant_claim_count,
            rejected_assistant_claim_count=assistant_claim_count,
        )

    def correct_claim(
        self,
        claim_id: str,
        corrected_statement: str,
        *,
        owner_id: str,
        user_id: str = "default",
        actor: str = "user",
    ) -> ClaimCorrectionResult:
        old_claim = self.store.get_claim(claim_id)
        if old_claim is None:
            raise KeyError(f"Claim not found: {claim_id}")
        if old_claim.owner_id != owner_id:
            raise PermissionError("Claim is outside the authenticated owner scope")
        if old_claim.state in {"superseded", "deprecated", "deleted"}:
            raise ValueError(f"Claim in terminal state cannot be corrected: {old_claim.state}")
        statement = _normalize_text(corrected_statement)
        if not statement:
            raise ValueError("corrected_statement is required")
        correction_artifact = Artifact(
            owner_id=old_claim.owner_id,
            user_id=user_id,
            source_type="user_correction",
            source_ref=f"claim:{old_claim.claim_id}",
            content_hash=stable_hash(statement),
            raw_location=f"claim:{old_claim.claim_id}",
            text=statement,
        )
        correction_run = ExtractionRun(
            artifact_id=correction_artifact.artifact_id,
            owner_id=old_claim.owner_id,
            extractor="user-correction",
            extractor_version="v1",
            input_hash=correction_artifact.content_hash,
        )
        correction_blocks = self._build_evidence_blocks(
            correction_artifact,
            correction_run.extraction_run_id,
        )
        correction_spans = self._build_evidence_spans(
            correction_blocks,
            owner_id=old_claim.owner_id,
        )
        if not correction_spans:
            raise ValueError("corrected_statement did not produce evidence")
        correction_artifact.derived_evidence_block_ids = [
            block.evidence_block_id for block in correction_blocks
        ]
        correction_run.evidence_block_ids = [
            block.evidence_block_id for block in correction_blocks
        ]
        correction_run.evidence_span_ids = [
            span.evidence_span_id for span in correction_spans
        ]
        correction_run.parsed_region_count = len(correction_blocks)
        correction_run.semantic_region_count = len(correction_spans)
        correction_run.coverage_manifest = self._coverage_manifest(
            correction_artifact,
            correction_run,
            correction_blocks,
            correction_spans,
        ).model_dump(mode="json")
        subject, predicate, obj, scope, condition, valid_time = _semantic_claim_parts(statement)
        new_claim = Claim(
            owner_id=old_claim.owner_id,
            user_id=user_id,
            claim_type="user_fact",
            statement=statement,
            canonical_statement=_canonical(statement),
            subject=subject,
            predicate=predicate,
            object=obj,
            scope=scope,
            condition=condition,
            valid_time=valid_time,
            source_attribution="user_correction",
            source_role="user_assertion",
            confidence=0.95,
            support_status="user_asserted",
            state="active",
            created_from=old_claim.claim_id,
            created_by="user",
            evidence_span_ids=[span.evidence_span_id for span in correction_spans],
            evidence_refs=[
                self._evidence_ref_for_span(
                    span,
                    next(
                        block for block in correction_blocks
                        if block.evidence_block_id == span.evidence_block_id
                    ),
                    extraction_run_id=correction_run.extraction_run_id,
                )
                for span in correction_spans
            ],
            canonical_key=stable_hash(f"user_fact:{_canonical(statement)}")[:20],
        )
        correction_spans = [
            span.model_copy(update={"claim_ids": [new_claim.claim_id]})
            for span in correction_spans
        ]
        correction_run.claim_ids = [new_claim.claim_id]
        new_claim.quality_gate = self._claim_quality_gate(new_claim)
        previous_state = old_claim.state
        old_claim.state = "superseded"
        relation = KnowledgeRelation(
            owner_id=old_claim.owner_id,
            source_id=new_claim.claim_id,
            target_id=old_claim.claim_id,
            relation_type="supersede",
            confidence=1.0,
            evidence_span_ids=list(new_claim.evidence_span_ids),
            reason="user correction supersedes previous claim",
        )
        events = [
            KnowledgeStateEvent(
                owner_id=old_claim.owner_id,
                target_id=old_claim.claim_id,
                from_state=previous_state,
                to_state="superseded",
                reason="user correction",
                actor=actor,  # type: ignore[arg-type]
                evidence_span_ids=list(old_claim.evidence_span_ids),
                policy_result="user_confirmed_correction",
            ),
            KnowledgeStateEvent(
                owner_id=old_claim.owner_id,
                target_id=new_claim.claim_id,
                from_state="candidate",
                to_state="active",
                reason="user correction",
                actor=actor,  # type: ignore[arg-type]
                evidence_span_ids=list(new_claim.evidence_span_ids),
                policy_result="user_asserted",
            ),
        ]
        correction_decision = DecisionCard(
            owner_id=old_claim.owner_id,
            decision_type="claim_correction",
            proposed_action="supersede old claim with corrected user assertion",
            impact_claim_ids=[old_claim.claim_id, new_claim.claim_id],
            risk_level="high",
            policy_reason="claim correction changes long-term knowledge",
            status="accepted",
            user_response="confirmed",
            resolved_at=events[-1].created_at,
        )
        self.store.save_artifact(correction_artifact)
        self.store.save_extraction_run(correction_run)
        self.store.save_evidence_blocks(correction_blocks)
        self.store.save_evidence_spans(correction_spans)
        self.store.save_claims([old_claim, new_claim])
        self.store.save_knowledge_relations([relation])
        self.store.save_knowledge_state_events(events)
        self.store.save_decisions([correction_decision])
        return ClaimCorrectionResult(
            old_claim=old_claim,
            new_claim=new_claim,
            relation=relation,
            state_events=events,
        )

    def ingest_research_event(
        self,
        *,
        topic: str,
        title: str,
        summary: str,
        user_id: str = "default",
        owner_id: str = "default",
        source_ref: str | None = None,
    ) -> ResearchIngestResult:
        text = _normalize_text(f"{title}\n{summary}")
        ingest = self.ingest_text(
            text,
            user_id=user_id,
            owner_id=owner_id,
            source_type="research_event",
            source_ref=source_ref,
            created_by="system",
        )
        event = ResearchEvent(
            owner_id=owner_id,
            user_id=user_id,
            topic=topic,
            title=title,
            summary=summary,
            source_ref=source_ref,
            artifact_id=ingest.artifact.artifact_id,
            claim_ids=[claim.claim_id for claim in ingest.claims],
            relation_ids=[relation.relation_id for relation in ingest.relations],
            status="saved" if ingest.claims else "candidate",
        )
        derived_relations = [
            KnowledgeRelation(
                owner_id=owner_id,
                source_type="research_event",
                source_id=event.research_event_id,
                target_type="claim",
                target_id=claim.claim_id,
                relation_type="derived_from",
                confidence=1.0,
                evidence_span_ids=list(claim.evidence_span_ids),
                reason="research event produced candidate claim",
            )
            for claim in ingest.claims
        ]
        event.relation_ids.extend(relation.relation_id for relation in derived_relations)
        self.store.save_research_events([event])
        self.store.save_knowledge_relations(derived_relations)
        return ResearchIngestResult(
            event=event,
            ingest_result=ingest,
            impact_relation_count=len(ingest.relations),
        )

    def submit_research_feedback(
        self,
        research_event_id: str,
        *,
        negative_feedback_reason: str,
    ) -> ResearchEvent:
        event = self.store.get_research_event(research_event_id)
        if event is None:
            raise ValueError(f"Research event not found: {research_event_id}")
        event.negative_feedback_reason = negative_feedback_reason  # type: ignore[assignment]
        if negative_feedback_reason == "not_interested":
            event.status = "irrelevant"
            event.interest_score = 0.0
        elif negative_feedback_reason == "already_known":
            event.interest_score = min(event.interest_score, 0.25)
        elif negative_feedback_reason:
            event.interest_score = min(event.interest_score, 0.5)
        self.store.save_research_events([event])
        return event

    def plan_review_and_gaps(
        self,
        *,
        owner_id: str = "default",
        limit: int = 10,
    ) -> ReviewPlanResult:
        claims = self.store.list_claims(owner_id, limit=500)
        review_items: list[ReviewItem] = []
        gaps: list[KnowledgeGap] = []
        for claim in claims:
            if claim.state == "active" and self._claim_projection_eligible(claim, "review"):
                priority = round(claim.confidence + min(len(claim.evidence_span_ids), 3) * 0.05, 4)
                review_items.append(ReviewItem(
                    owner_id=owner_id,
                    claim_id=claim.claim_id,
                    prompt=f"复习：{claim.statement}",
                    priority=priority,
                    reason="active claim with evidence",
                    due_at=claim.created_at + timedelta(days=1),
                ))
                if not claim.evidence_span_ids and claim.support_status != "user_asserted":
                    gaps.append(KnowledgeGap(
                        owner_id=owner_id,
                        gap_type="missing_evidence",
                        claim_ids=[claim.claim_id],
                        question=f"这条知识缺少证据：{claim.statement}",
                        reason="active claim has no EvidenceSpan",
                        severity="high",
                    ))
            elif claim.state == "active" and not self._claim_projection_eligible(claim, "review"):
                gaps.append(KnowledgeGap(
                    owner_id=owner_id,
                    gap_type="missing_evidence",
                    claim_ids=[claim.claim_id],
                    question=f"这条知识未通过复习投影质量门：{claim.statement}",
                    reason="claim failed review projection eligibility",
                    severity="medium",
                ))
            elif claim.state == "conflicted":
                gaps.append(KnowledgeGap(
                    owner_id=owner_id,
                    gap_type="conflict",
                    claim_ids=[claim.claim_id],
                    question=f"需要澄清冲突知识：{claim.statement}",
                    reason="claim is conflicted",
                    severity="high",
                ))
            elif claim.state in {"uncertain", "grounded", "verified"} or claim.support_status in {"partially_supported", "not_found"}:
                gaps.append(KnowledgeGap(
                    owner_id=owner_id,
                    gap_type="uncertain",
                    claim_ids=[claim.claim_id],
                    question=f"需要补充证据或确认：{claim.statement}",
                    reason=f"state={claim.state} support={claim.support_status}",
                    severity="medium",
                ))
        seen_potential_conflicts: set[tuple[str, str]] = set()
        for relation in self.store.list_knowledge_relations(
            owner_id,
            relation_type="potential_conflict",
            limit=500,
        ):
            pair = tuple(sorted((relation.source_id, relation.target_id)))
            if pair in seen_potential_conflicts:
                continue
            seen_potential_conflicts.add(pair)
            source = self.store.get_claim(relation.source_id)
            target = self.store.get_claim(relation.target_id)
            if source is None or target is None:
                continue
            gaps.append(KnowledgeGap(
                owner_id=owner_id,
                gap_type="conflict",
                claim_ids=[source.claim_id, target.claim_id],
                question=f"需要语义确认潜在冲突：{source.statement} / {target.statement}",
                reason=relation.reason,
                severity="medium",
            ))
        review_items.sort(key=lambda item: item.priority, reverse=True)
        review_items = review_items[:max(1, limit)]
        self.store.save_review_items(review_items)
        self.store.save_knowledge_gaps(gaps)
        return ReviewPlanResult(review_items=review_items, knowledge_gaps=gaps)

    def project_knowledge_graph(
        self,
        *,
        owner_id: str = "default",
        limit: int = 100,
    ) -> GraphProjectionResult:
        claims = [
            claim for claim in self.store.list_claims(owner_id, limit=limit)
            if self._claim_projection_eligible(claim, "graph")
        ]
        projections: list[GraphProjection] = []
        for claim in claims:
            entities = sorted({claim.subject, claim.object, *_extract_entities(claim.statement)} - {""})
            quality = "ok" if claim.evidence_span_ids else "no_backlink"
            projections.append(GraphProjection(
                owner_id=owner_id,
                source_claim_id=claim.claim_id,
                evidence_span_ids=list(claim.evidence_span_ids),
                entity_names=entities,
                relation_facts=[claim.statement],
                backlink_claim_ids=[claim.claim_id],
                backlink_evidence_span_ids=list(claim.evidence_span_ids),
                quality_signal=quality,
            ))
        self.store.save_graph_projections(projections)
        return GraphProjectionResult(
            projections=projections,
            backlink_ok=all(
                projection.backlink_claim_ids and projection.backlink_evidence_span_ids
                for projection in projections
            ),
        )

    def delete_artifact_cascade(
        self,
        artifact_id: str,
        *,
        actor: str = "user",
    ) -> ArtifactDeleteImpactResult:
        artifact = self.store.get_artifact(artifact_id)
        if artifact is None:
            raise ValueError(f"Artifact not found: {artifact_id}")
        spans = []
        for span in self.store.list_evidence_spans(artifact.owner_id, limit=1000):
            block = self.store.get_evidence_block(span.evidence_block_id)
            if block is not None and block.artifact_id == artifact_id:
                spans.append(span)
        affected_span_ids = {span.evidence_span_id for span in spans}
        affected_claims: list[Claim] = []
        events: list[KnowledgeStateEvent] = []
        for claim in self.store.list_claims(artifact.owner_id, limit=1000):
            if not (set(claim.evidence_span_ids) & affected_span_ids):
                continue
            previous = claim.state
            claim.state = "deleted"
            claim.support_status = "not_found"
            claim.evidence_refs = [
                ref.model_copy(update={"health_status": "stale"})
                for ref in claim.evidence_refs
            ]
            claim.quality_gate = self._claim_quality_gate(claim)
            affected_claims.append(claim)
            events.append(KnowledgeStateEvent(
                owner_id=artifact.owner_id,
                target_id=claim.claim_id,
                from_state=previous,
                to_state="deleted",
                reason="source artifact deleted; dependent evidence refs invalidated",
                actor=actor,  # type: ignore[arg-type]
                evidence_span_ids=list(claim.evidence_span_ids),
                policy_result="artifact_delete_cascade",
            ))
        if affected_claims:
            self.store.save_claims(affected_claims)
        if events:
            self.store.save_knowledge_state_events(events)
        invalidated = sum(
            1 for projection in self.store.list_graph_projections(artifact.owner_id, limit=1000)
            if projection.source_claim_id in {claim.claim_id for claim in affected_claims}
        )
        return ArtifactDeleteImpactResult(
            artifact_id=artifact_id,
            affected_claim_ids=[claim.claim_id for claim in affected_claims],
            affected_evidence_span_ids=sorted(affected_span_ids),
            state_events=events,
            invalidated_projection_count=invalidated,
        )

    def replay_semantic_extraction_diff(
        self,
        artifact_id: str,
        *,
        prompt_version: str = "replay",
    ) -> SemanticReplayDiffResult:
        artifact = self.store.get_artifact(artifact_id)
        if artifact is None:
            raise ValueError(f"Artifact not found: {artifact_id}")
        old_claims = [
            claim for claim in self.store.list_claims(artifact.owner_id, limit=1000)
            if claim.created_from == artifact_id
        ]
        replay_run = ExtractionRun(
            artifact_id=artifact.artifact_id,
            owner_id=artifact.owner_id,
            input_hash=artifact.content_hash,
            semantic_extractor_version=self.semantic_evidence_extractor.version if self.semantic_evidence_extractor else "",
            prompt_version=prompt_version,
            model_name=self.semantic_evidence_extractor.name if self.semantic_evidence_extractor else "",
        )
        blocks = self._build_evidence_blocks(artifact, replay_run.extraction_run_id)
        try:
            semantic_result = self.semantic_evidence_extractor.extract(  # type: ignore[union-attr]
                artifact=artifact,
                blocks=blocks,
            )
            spans = self._build_semantic_evidence_spans(
                semantic_result,
                blocks,
                owner_id=artifact.owner_id,
            )
        except Exception:
            semantic_result = LocalSemanticFixtureExtractor().extract(artifact=artifact, blocks=blocks)
            spans = self._build_semantic_evidence_spans(
                semantic_result,
                blocks,
                owner_id=artifact.owner_id,
            )
        refs_by_span = {
            span.evidence_span_id: EvidenceRef(
                source_kind="evidence_span",
                source_id=span.evidence_span_id,
                artifact_id=artifact.artifact_id,
                evidence_block_id=span.evidence_block_id,
                evidence_span_id=span.evidence_span_id,
                locator=span.locator,
                quote_hash=span.quote_hash,
                health_status="valid",
                extraction_run_id=replay_run.extraction_run_id,
            )
            for span in spans
        }
        try:
            claim_extraction = self.semantic_claim_extractor.extract(  # type: ignore[union-attr]
                artifact=artifact,
                spans=spans,
                evidence_refs=list(refs_by_span.values()),
                created_by="system",
                limit=50,
            )
        except Exception:
            claim_extraction = LocalSemanticFixtureClaimExtractor().extract(
                artifact=artifact,
                spans=spans,
                evidence_refs=list(refs_by_span.values()),
                created_by="system",
                limit=50,
            )
        new_claims = self._claims_from_semantic_extraction(
            claim_extraction,
            artifact=artifact,
            user_id=artifact.user_id,
            owner_id=artifact.owner_id,
            created_from=artifact.artifact_id,
            created_by="system",
            source_type=artifact.source_type,
            evidence_refs_by_span=refs_by_span,
        )
        old_by_key = {claim.canonical_key: claim for claim in old_claims}
        new_by_key = {claim.canonical_key: claim for claim in new_claims}
        added = [claim.statement for key, claim in new_by_key.items() if key not in old_by_key]
        removed = [claim.statement for key, claim in old_by_key.items() if key not in new_by_key]
        changed_scope = [
            new_by_key[key].statement for key in old_by_key.keys() & new_by_key.keys()
            if old_by_key[key].scope != new_by_key[key].scope
        ]
        changed_support = [
            new_by_key[key].statement for key in old_by_key.keys() & new_by_key.keys()
            if old_by_key[key].support_status != new_by_key[key].support_status
        ]
        return SemanticReplayDiffResult(
            artifact_id=artifact_id,
            old_claim_ids=[claim.claim_id for claim in old_claims],
            new_claim_ids=[claim.claim_id for claim in new_claims],
            added_claims=added,
            removed_claims=removed,
            changed_scope_claims=changed_scope,
            changed_support_claims=changed_support,
            regression_stage="claim_extraction" if added or removed or changed_scope else "",
            low_confidence=any(claim.confidence < 0.8 for claim in new_claims),
        )

    def _decision_card_for_admission(
        self,
        claim: Claim,
        admission: ClaimAdmissionDecision,
    ) -> DecisionCard | None:
        if admission.decision_policy == "auto_execute" and admission.admission_result != "require_decision":
            return None
        status = "pending"
        if admission.decision_policy == "block":
            status = "blocked"
        elif admission.decision_policy == "auto_execute":
            status = "auto_executed"
        return DecisionCard(
            owner_id=claim.owner_id,
            decision_type="claim_admission",
            proposed_action=f"{admission.admission_result}: {claim.statement}",
            impact_claim_ids=[claim.claim_id],
            risk_level="high" if claim.sensitivity_level == "high" else "medium",
            policy_reason=admission.reason,
            status=status,  # type: ignore[arg-type]
        )

    def _minimal_knowledge_item(
        self,
        artifact: Artifact,
        spans: list[EvidenceSpan],
        *,
        primary_state: str,
    ) -> KnowledgeItem:
        title = artifact.metadata.get("title") if isinstance(artifact.metadata, dict) else ""
        if not title:
            title = artifact.source_ref or artifact.text.splitlines()[0][:48] or "Untitled knowledge item"
        return KnowledgeItem(
            owner_id=artifact.owner_id,
            user_id=artifact.user_id,
            title=str(title)[:80],
            summary=artifact.text[:500],
            claim_ids=[],
            evidence_span_ids=[span.evidence_span_id for span in spans],
            primary_state=primary_state,  # type: ignore[arg-type]
            flags=["claims_pending"],
            state="active",
        )

    def _coverage_manifest(
        self,
        artifact: Artifact,
        extraction_run: ExtractionRun,
        blocks: list[EvidenceBlock],
        spans: list[EvidenceSpan],
    ) -> CoverageManifest:
        span_block_ids = {span.evidence_block_id for span in spans}
        regions: list[CoverageRegion] = []
        for block in blocks:
            semantic_status = "extracted" if block.evidence_block_id in span_block_ids else "failed"
            regions.append(CoverageRegion(
                locator=block.locator,
                region_type=block.block_type,
                parse_status="parsed",
                semantic_status=semantic_status,  # type: ignore[arg-type]
                reason="" if semantic_status == "extracted" else "no semantic span extracted",
            ))
            for marker in re.findall(r"\[OMITTED:([^\]]+)\]", block.full_context):
                regions.append(CoverageRegion(
                    locator=f"omitted:{marker}",
                    region_type="section",
                    parse_status="omitted",
                    semantic_status="omitted",
                    reason="fixture omitted region marker",
                ))
        omitted_count = sum(
            1 for region in regions
            if region.parse_status in {"omitted", "partial", "failed"}
            or region.semantic_status in {"omitted", "partial", "failed"}
        )
        if not blocks:
            coverage: str = "none"
        elif omitted_count:
            coverage = "partial" if spans else "sparse"
        else:
            coverage = "complete"
        return CoverageManifest(
            artifact_id=artifact.artifact_id,
            extraction_run_id=extraction_run.extraction_run_id,
            expected_regions=regions,
            parsed_region_count=len(blocks),
            semantic_region_count=len(spans),
            omitted_region_count=omitted_count,
            coverage_status=coverage,  # type: ignore[arg-type]
        )

    def _evidence_ref_for_span_id(
        self,
        evidence_span_id: str,
        *,
        extraction_run_id: str = "",
    ) -> EvidenceRef | None:
        span = self.store.get_evidence_span(evidence_span_id)
        if span is None:
            return None
        block = self.store.get_evidence_block(span.evidence_block_id)
        if block is None:
            return None
        return self._evidence_ref_for_span(
            span,
            block,
            extraction_run_id=extraction_run_id,
        )

    @staticmethod
    def _evidence_ref_for_span(
        span: EvidenceSpan,
        block: EvidenceBlock,
        *,
        extraction_run_id: str = "",
    ) -> EvidenceRef:
        return EvidenceRef(
            source_kind="evidence_span",
            source_id=span.evidence_span_id,
            artifact_id=block.artifact_id,
            evidence_block_id=span.evidence_block_id,
            evidence_span_id=span.evidence_span_id,
            locator=span.locator or block.locator,
            quote_hash=span.quote_hash,
            health_status="valid",
            extraction_run_id=extraction_run_id,
        )

    def _claim_quality_gate(self, claim: Claim, *, grounding: GroundingRun | None = None) -> ClaimQualityGate:
        support = grounding.support_status if grounding is not None else claim.support_status
        confidence = grounding.confidence if grounding is not None and grounding.confidence else _confidence_for_support(support)
        has_valid_ref = any(ref.health_status == "valid" for ref in claim.evidence_refs)
        user_asserted = support == "user_asserted"
        blocked: list[str] = []
        if not claim.statement.strip():
            blocked.append("empty_statement")
        if not has_valid_ref and not user_asserted:
            blocked.append("missing_valid_evidence_ref")
        if support in {"unsupported", "not_found", "contradicted"}:
            blocked.append(f"support_status:{support}")
        if claim.source_role == "assistant_inference":
            blocked.append("assistant_inference")
        critical_missing_scope = _requires_scope(claim.statement) and not claim.scope
        if critical_missing_scope:
            blocked.append("critical_missing_scope")
        return ClaimQualityGate(
            schema_valid=bool(claim.statement.strip()),
            has_valid_evidence_ref=has_valid_ref,
            evidence_ref_health="valid" if has_valid_ref or user_asserted else "broken",
            grounding_confidence=confidence,
            support_status=support,  # type: ignore[arg-type]
            lifecycle_state=claim.state,
            source_role=claim.source_role,
            critical_missing_scope=critical_missing_scope,
            critical_missing_valid_time=False,
            judge_version=grounding.verifier if grounding is not None else "semantic-quality-gate-v1",
            passed=not blocked,
            blocked_reasons=blocked,
        )

    def _claim_projection_eligible(self, claim: Claim, projection: str) -> bool:
        if not claim.quality_gate.passed:
            return False
        if projection == "ask":
            return (
                claim.state in {"active", "conflicted"}
                and claim.support_status in {"supported", "user_asserted"}
            )
        if projection == "review":
            return (
                claim.state == "active"
                and claim.support_status in {"supported", "user_asserted"}
                and claim.source_role != "assistant_inference"
            )
        if projection == "graph":
            return claim.state == "active" and bool(claim.subject and claim.predicate)
        return claim.quality_gate.passed

    def _enqueue_projection_jobs(
        self,
        *,
        owner_id: str,
        source_object_type: str,
        source_object_id: str,
        include_claims: bool,
    ) -> list[ProjectionJob]:
        projection_types = ["project_evidence_indexes", "project_ui_card"]
        if include_claims:
            projection_types.extend(["project_claim_indexes", "project_review", "project_graph"])
        jobs = [
            ProjectionJob(
                owner_id=owner_id,
                projection_type=projection_type,  # type: ignore[arg-type]
                source_object_type=source_object_type,  # type: ignore[arg-type]
                source_object_id=source_object_id,
                status="pending",
            )
            for projection_type in projection_types
        ]
        self.store.save_projection_jobs(jobs)
        return jobs

    def _coverage_manifests_for_spans(self, spans: list[EvidenceSpan]) -> list[CoverageManifest]:
        seen_run_ids: set[str] = set()
        manifests: list[CoverageManifest] = []
        for span in spans:
            block = self.store.get_evidence_block(span.evidence_block_id)
            if block is None or not block.extraction_run_id or block.extraction_run_id in seen_run_ids:
                continue
            seen_run_ids.add(block.extraction_run_id)
            extraction_run = self.store.get_extraction_run(block.extraction_run_id)
            if extraction_run is None or not extraction_run.coverage_manifest:
                continue
            manifests.append(CoverageManifest.model_validate(extraction_run.coverage_manifest))
        return manifests

    def _build_knowledge_items(self, claims: list[Claim]) -> list[KnowledgeItem]:
        items: list[KnowledgeItem] = []
        for claim in claims:
            if claim.state not in {"active", "conflicted", "verified", "grounded"}:
                continue
            items.append(KnowledgeItem(
                owner_id=claim.owner_id,
                user_id=claim.user_id,
                title=_knowledge_item_title(claim.statement),
                summary=claim.statement,
                claim_ids=[claim.claim_id],
                evidence_span_ids=list(claim.evidence_span_ids),
                primary_state="ready" if claim.state == "active" else "partial_failed",
                flags=[] if claim.state == "active" else ["claims_pending"],
                state="conflicted" if claim.state == "conflicted" else "active",
            ))
        return items

    def _build_evidence_blocks(self, artifact: Artifact, extraction_run_id: str) -> list[EvidenceBlock]:
        blocks: list[EvidenceBlock] = []
        cursor = 0
        for index, paragraph in enumerate(_split_blocks(artifact.text), 1):
            start = artifact.text.find(paragraph, cursor)
            if start < 0:
                start = cursor
            end = start + len(paragraph)
            cursor = end
            blocks.append(EvidenceBlock(
                artifact_id=artifact.artifact_id,
                owner_id=artifact.owner_id,
                locator=f"paragraph:{index}",
                block_type=_block_type(paragraph),
                char_range=(start, end),
                full_context=paragraph,
                source_type=artifact.source_type,
                extraction_run_id=extraction_run_id,
                modality="text",
            ))
        return blocks

    def _build_evidence_spans(self, blocks: list[EvidenceBlock], *, owner_id: str) -> list[EvidenceSpan]:
        spans: list[EvidenceSpan] = []
        for block in blocks:
            for start, end, sentence in _split_spans(block.full_context):
                spans.append(EvidenceSpan(
                    evidence_block_id=block.evidence_block_id,
                    owner_id=owner_id,
                    start_offset=start,
                    end_offset=end,
                    span_type=_span_type(sentence),
                    text_span=sentence,
                    normalized_meaning=_normalize_meaning(sentence),
                    locator=f"{block.locator}:chars:{start}-{end}",
                    semantic_tags=_semantic_tags(sentence),
                    quote_hash=stable_hash(sentence)[:16],
                ))
        return spans

    def _build_semantic_evidence_spans(
        self,
        extraction: SemanticEvidenceExtraction,
        blocks: list[EvidenceBlock],
        *,
        owner_id: str,
    ) -> list[EvidenceSpan]:
        spans: list[EvidenceSpan] = []
        blocks_by_locator = {block.locator: block for block in blocks}
        for draft in extraction.spans:
            text = _normalize_text(draft.text)
            if not text:
                continue
            block = blocks_by_locator.get(draft.locator_hint)
            if block is None:
                block = next((candidate for candidate in blocks if text in candidate.full_context), None)
            if block is None:
                continue
            start = block.full_context.find(text)
            if start < 0:
                continue
            end = start + len(text)
            spans.append(EvidenceSpan(
                evidence_block_id=block.evidence_block_id,
                owner_id=owner_id,
                start_offset=start,
                end_offset=end,
                span_type=draft.span_type,
                text_span=text,
                normalized_meaning=draft.normalized_meaning or text,
                locator=f"{block.locator}:chars:{start}-{end}",
                semantic_tags=list(draft.semantic_tags),
                confidence=draft.confidence,
                quote_hash=stable_hash(text)[:16],
            ))
        if spans:
            return spans
        return self._build_evidence_spans(blocks, owner_id=owner_id)

    def _claims_from_semantic_extraction(
        self,
        extraction,
        *,
        artifact: Artifact,
        evidence_spans: list[EvidenceSpan],
        user_id: str,
        owner_id: str,
        created_from: str,
        created_by: str,
        source_type: str,
        evidence_refs_by_span: dict[str, EvidenceRef | None],
    ) -> list[Claim]:
        refs_by_id = {
            ref.source_id: ref for ref in evidence_refs_by_span.values()
            if ref is not None
        }
        span_text_by_ref_id = {
            ref.source_id: span.text_span
            for span in evidence_spans
            if (ref := evidence_refs_by_span.get(span.evidence_span_id)) is not None
        }
        draft_count_by_ref_id = Counter(
            ref_id
            for draft in extraction.claims
            for ref_id in draft.evidence_ref_ids
        )
        claims: list[Claim] = []
        seen: set[str] = set()
        for draft in extraction.claims:
            statement = _normalize_text(draft.statement)
            if (
                created_by == "user"
                and source_type == "conversation"
                and len(draft.evidence_ref_ids) == 1
                and draft_count_by_ref_id[draft.evidence_ref_ids[0]] == 1
            ):
                statement = _normalize_text(
                    span_text_by_ref_id.get(draft.evidence_ref_ids[0], statement)
                )
            if not statement:
                continue
            canonical_statement = _canonical(statement)
            canonical_key = stable_hash(f"{draft.claim_type}:{canonical_statement}")[:20]
            if canonical_key in seen:
                continue
            seen.add(canonical_key)
            sensitivity = _sensitivity_level(statement)
            memory_policy = "requires_user_confirmation" if sensitivity == "high" else "auto_save_allowed"
            evidence_refs = [
                refs_by_id[ref_id]
                for ref_id in draft.evidence_ref_ids
                if ref_id in refs_by_id
            ]
            claim = Claim(
                owner_id=owner_id,
                user_id=user_id,
                claim_type=draft.claim_type,
                statement=statement,
                canonical_statement=canonical_statement,
                subject=draft.subject,
                predicate=draft.predicate,
                object=draft.object,
                qualifiers=list(draft.qualifiers),
                scope=draft.scope,
                condition=draft.condition,
                valid_time=draft.valid_time,
                source_attribution=source_type,
                source_role=draft.source_role,
                sensitivity_level=sensitivity,
                memory_policy=memory_policy,
                created_from=created_from,
                created_by=created_by,  # type: ignore[arg-type]
                evidence_span_ids=[ref.evidence_span_id for ref in evidence_refs],
                evidence_refs=evidence_refs,
                uncertainty_reason=draft.uncertainty_reason,
                confidence=draft.confidence,
                canonical_key=canonical_key,
            )
            claims.append(claim)
        return claims

    def _ground_claim_with_judge(
        self,
        claim: Claim,
        *,
        evidence_spans: list[EvidenceSpan],
        source_type: str,
        created_by: str,
    ) -> GroundingRun:
        judge = self.claim_grounding_judge
        try:
            judgment = judge.judge(  # type: ignore[union-attr]
                claim=claim,
                evidence_refs=claim.evidence_refs,
                evidence_spans=evidence_spans,
                source_type=source_type,
                created_by=created_by,
            )
        except Exception:
            judge = LocalSemanticFixtureGroundingJudge()
            judgment = judge.judge(
                claim=claim,
                evidence_refs=claim.evidence_refs,
                evidence_spans=evidence_spans,
                source_type=source_type,
                created_by=created_by,
            )
        refs_by_id = {ref.source_id: ref for ref in claim.evidence_refs}
        supporting_ref_ids = [
            ref_id for ref_id in judgment.supporting_evidence_ref_ids
            if ref_id in refs_by_id
        ]
        if (
            judgment.support_status in {"supported", "user_asserted"}
            and not supporting_ref_ids
        ):
            supporting_ref_ids = [ref.source_id for ref in claim.evidence_refs if ref.health_status == "valid"]
        contradicting_ref_ids = [
            ref_id for ref_id in judgment.contradicting_evidence_ref_ids
            if ref_id in refs_by_id
        ]
        return GroundingRun(
            owner_id=claim.owner_id,
            claim_id=claim.claim_id,
            evidence_span_ids=[refs_by_id[ref_id].evidence_span_id for ref_id in supporting_ref_ids],
            contradicting_evidence_span_ids=[refs_by_id[ref_id].evidence_span_id for ref_id in contradicting_ref_ids],
            support_status=judgment.support_status,
            verifier=judge.name if judge else "semantic-grounding-judge",
            verifier_version=judge.version if judge else "v1",
            rationale=judgment.rationale or judgment.missing_evidence_description,
            confidence=judgment.confidence,
            calibration=calibration_from_grounding(judgment),
        )

    def _select_answerable_claims(self, question: str, *, owner_id: str, limit: int) -> list[Claim]:
        q_terms = evidence_terms(question)
        if not q_terms:
            return []
        scored: list[tuple[int, Claim]] = []
        for claim in self.store.list_claims(owner_id, limit=500):
            if not self._claim_projection_eligible(claim, "ask"):
                continue
            claim_terms = evidence_terms(" ".join([
                claim.statement,
                claim.subject,
                claim.predicate,
                claim.object,
                claim.scope,
                claim.condition,
            ]))
            overlap = len(q_terms & claim_terms)
            if overlap:
                scored.append((overlap, claim))
        scored.sort(
            key=lambda item: (item[0], item[1].confidence, item[1].created_at),
            reverse=True,
        )
        return [claim for _, claim in scored[:max(1, limit)]]

    def _evidence_for_claims(
        self,
        claims: list[Claim],
        *,
        owner_id: str,
        limit: int,
    ) -> list[EvidenceSpan]:
        selected_by_id: dict[str, EvidenceSpan] = {}
        for claim in claims:
            refs_by_span_id = {
                ref.evidence_span_id: ref
                for ref in claim.evidence_refs
                if ref.health_status == "valid"
            }
            for evidence_span_id in claim.evidence_span_ids:
                if evidence_span_id in selected_by_id:
                    continue
                ref = refs_by_span_id.get(evidence_span_id)
                if ref is None or ref.source_id != evidence_span_id:
                    continue
                span = self.store.get_evidence_span(evidence_span_id)
                if span is None or span.owner_id != owner_id:
                    continue
                block = self.store.get_evidence_block(span.evidence_block_id)
                if (
                    block is None
                    or block.owner_id != owner_id
                    or ref.evidence_block_id != block.evidence_block_id
                    or ref.artifact_id != block.artifact_id
                ):
                    continue
                artifact = self.store.get_artifact(block.artifact_id)
                if artifact is None or artifact.owner_id != owner_id:
                    continue
                selected_by_id[span.evidence_span_id] = span
                if len(selected_by_id) >= limit:
                    return list(selected_by_id.values())
        return list(selected_by_id.values())

    def _conflicting_claim_ids(self, owner_id: str, claims: list[Claim]) -> list[str]:
        return self._related_claim_ids(owner_id, claims, relation_type="conflict", include_claim_state=True)

    def _potential_conflicting_claim_ids(self, owner_id: str, claims: list[Claim]) -> list[str]:
        return self._related_claim_ids(owner_id, claims, relation_type="potential_conflict")

    def _related_claim_ids(
        self,
        owner_id: str,
        claims: list[Claim],
        *,
        relation_type: str,
        include_claim_state: bool = False,
    ) -> list[str]:
        ids: set[str] = set()
        for claim in claims:
            if include_claim_state and claim.state == "conflicted":
                ids.add(claim.claim_id)
            for relation in self.store.list_knowledge_relations(
                owner_id,
                source_id=claim.claim_id,
                relation_type=relation_type,
                limit=50,
            ):
                ids.add(relation.source_id)
                ids.add(relation.target_id)
            for relation in self.store.list_knowledge_relations(
                owner_id,
                target_id=claim.claim_id,
                relation_type=relation_type,
                limit=50,
            ):
                ids.add(relation.source_id)
                ids.add(relation.target_id)
        return sorted(ids)

    def _relate_new_claims(
        self,
        new_claims: list[Claim],
        existing_claims: list[Claim],
        *,
        owner_id: str,
    ) -> tuple[list[KnowledgeRelation], list[KnowledgeStateEvent], list[Claim], list[DecisionCard], list[KnowledgeGap]]:
        relations: list[KnowledgeRelation] = []
        state_events: list[KnowledgeStateEvent] = []
        updated_existing: dict[str, Claim] = {}
        decisions: list[DecisionCard] = []
        gaps: list[KnowledgeGap] = []
        for new_claim in new_claims:
            if new_claim.state not in {"active", "grounded", "verified"}:
                continue
            for existing in existing_claims:
                if existing.claim_id == new_claim.claim_id or existing.state in {"deleted", "rejected", "superseded"}:
                    continue
                relation_type, confidence, reason = _relation_between_claims(new_claim, existing)
                if relation_type is None:
                    continue
                relation_type, confidence, reason = self._adjudicate_relation(
                    new_claim,
                    existing,
                    candidate=ClaimRelationCandidate(
                        relation_type=relation_type,
                        confidence=confidence,
                        reason=reason,
                    ),
                )
                if relation_type is None:
                    continue
                decision: DecisionCard | None = None
                if relation_type in {"conflict", "potential_conflict"}:
                    decision = self._decision_card_for_relation(
                        new_claim,
                        existing,
                        relation_type=relation_type,
                        reason=reason,
                    )
                    decisions.append(decision)
                    gaps.append(KnowledgeGap(
                        owner_id=owner_id,
                        gap_type="conflict",
                        claim_ids=[new_claim.claim_id, existing.claim_id],
                        question=f"需要确认这两条知识是否冲突：{new_claim.statement} / {existing.statement}",
                        reason=reason,
                        severity="high" if relation_type == "conflict" else "medium",
                    ))
                relation = KnowledgeRelation(
                    owner_id=owner_id,
                    source_id=new_claim.claim_id,
                    target_id=existing.claim_id,
                    relation_type=relation_type,
                    confidence=confidence,
                    evidence_span_ids=list(new_claim.evidence_span_ids),
                    decision_id=decision.decision_id if decision is not None else None,
                    reason=reason,
                )
                relations.append(relation)
                if relation_type == "conflict":
                    if new_claim.state == "active":
                        from_state = new_claim.state
                        new_claim.state = "conflicted"
                        state_events.append(KnowledgeStateEvent(
                            owner_id=owner_id,
                            target_id=new_claim.claim_id,
                            from_state=from_state,
                            to_state="conflicted",
                            reason="new claim conflicts with existing claim",
                            evidence_span_ids=list(new_claim.evidence_span_ids),
                            policy_result="conflict_detected",
                        ))
                    if existing.state == "active":
                        previous = existing.state
                        existing.state = "conflicted"
                        updated_existing[existing.claim_id] = existing
                        state_events.append(KnowledgeStateEvent(
                            owner_id=owner_id,
                            target_id=existing.claim_id,
                            from_state=previous,
                            to_state="conflicted",
                            reason="existing claim conflicts with new claim",
                            evidence_span_ids=list(existing.evidence_span_ids),
                            policy_result="conflict_detected",
                        ))
        return relations, state_events, list(updated_existing.values()), decisions, gaps

    def _adjudicate_relation(
        self,
        new_claim: Claim,
        existing: Claim,
        *,
        candidate: ClaimRelationCandidate,
    ) -> tuple[str | None, float, str]:
        if candidate.relation_type != "potential_conflict":
            return candidate.relation_type, candidate.confidence, candidate.reason
        if self.relation_judge is None:
            return (
                "potential_conflict",
                min(candidate.confidence, 0.79),
                f"{candidate.reason}; semantic adjudication required",
            )
        try:
            adjudication = self.relation_judge.judge(candidate, new_claim, existing)
        except Exception as exc:
            adjudication = ClaimRelationAdjudication(
                relation_type="uncertain",
                confidence=0.0,
                rationale=f"relation judge failed: {exc}",
                requires_decision=True,
            )
        relation_type = adjudication.relation_type
        if relation_type == "unrelated":
            return None, 0.0, adjudication.rationale or "semantic judge found no relation"
        if relation_type == "uncertain" or adjudication.confidence < 0.8:
            return (
                "potential_conflict",
                max(candidate.confidence, adjudication.confidence),
                adjudication.rationale or "semantic judge was uncertain",
            )
        if relation_type in {"conflict", "supersede", "duplicate"} and not _relation_write_allowed(
            new_claim,
            existing,
            confidence=adjudication.confidence,
        ):
            return (
                "potential_conflict",
                max(candidate.confidence, min(adjudication.confidence, 0.79)),
                f"{adjudication.rationale}; relation write gate requires aligned scope and valid evidence",
            )
        return relation_type, adjudication.confidence, adjudication.rationale

    def _decision_card_for_relation(
        self,
        new_claim: Claim,
        existing: Claim,
        *,
        relation_type: str,
        reason: str,
    ) -> DecisionCard:
        action = "确认冲突并选择保留哪条知识" if relation_type == "conflict" else "确认两条知识是否真的冲突"
        return DecisionCard(
            owner_id=new_claim.owner_id,
            decision_type="conflict_resolution",
            proposed_action=f"{action}: {new_claim.statement} / {existing.statement}",
            impact_claim_ids=[new_claim.claim_id, existing.claim_id],
            risk_level="high" if relation_type == "conflict" else "medium",
            policy_reason=reason,
            status="pending",
        )
