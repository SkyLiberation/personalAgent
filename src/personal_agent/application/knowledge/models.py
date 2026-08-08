from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from personal_agent.kernel.models import local_now


ClaimType = Literal[
    "external_fact",
    "user_fact",
    "user_preference",
    "user_plan",
    "analysis_judgment",
    "assistant_inference",
    "uncertain_claim",
]
SupportStatus = Literal[
    "supported",
    "partially_supported",
    "unsupported",
    "contradicted",
    "user_asserted",
    "not_found",
]
KnowledgeState = Literal[
    "candidate",
    "grounded",
    "verified",
    "active",
    "rejected",
    "uncertain",
    "conflicted",
    "superseded",
    "deprecated",
    "deleted",
]
AdmissionResult = Literal["allow_active", "keep_candidate", "require_decision", "reject"]
DecisionEffect = Literal["auto_execute", "ask_confirmation", "block"]
RelationType = Literal[
    "duplicate",
    "supplement",
    "supersede",
    "conflict",
    "potential_conflict",
    "derived_from",
    "cited_by",
]
EvidenceSourceKind = Literal[
    "evidence_span",
    "claim",
    "artifact_block",
    "web_snapshot",
    "thread_message",
    "research_source",
]
ProjectionType = Literal[
    "project_evidence_indexes",
    "project_claim_indexes",
    "project_ui_card",
    "project_graph",
    "project_review",
]
ProjectionStatus = Literal["pending", "completed", "failed", "retrying"]
KnowledgeItemPrimaryState = Literal["indexing", "evidence_ready", "ready", "partial_failed"]
KnowledgeItemFlag = Literal[
    "claims_pending",
    "index_projection_pending",
    "graph_projection_pending",
    "review_projection_pending",
    "semantic_extraction_failed",
    "semantic_claim_failed",
]
EvidenceCoverage = Literal["complete", "partial", "sparse", "none"]
RegionStatus = Literal["parsed", "omitted", "partial", "failed", "extracted"]
EvidenceRefHealthStatus = Literal["valid", "broken", "stale", "redacted", "permission_denied"]
EvidenceBlockType = Literal["section", "paragraph", "table", "list", "image_caption", "code", "transcript_turn"]
EvidenceSpanType = Literal["factual_statement", "definition", "procedure", "constraint", "example", "table_cell", "quote"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Artifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: new_id("art"))
    owner_id: str = "default"
    user_id: str = "default"
    source_type: str = "text"
    source_ref: str | None = None
    content_hash: str
    extraction_version: str = "p0-v1"
    raw_location: str = ""
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    derived_evidence_block_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=local_now)


class ExtractionRun(BaseModel):
    extraction_run_id: str = Field(default_factory=lambda: new_id("xrun"))
    artifact_id: str
    owner_id: str = "default"
    extractor: str = "semantic-lifecycle"
    extractor_version: str = "p0-v1"
    parser_version: str = "deterministic-block-parser-v1"
    semantic_extractor_version: str = ""
    model_name: str = ""
    prompt_version: str = ""
    input_hash: str = ""
    status: Literal["completed", "partial", "failed"] = "completed"
    evidence_block_ids: list[str] = Field(default_factory=list)
    evidence_span_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    coverage_manifest: dict[str, Any] = Field(default_factory=dict)
    omitted_regions: list[dict[str, Any]] = Field(default_factory=list)
    parsed_region_count: int = 0
    semantic_region_count: int = 0
    coverage_status: EvidenceCoverage = "complete"
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=local_now)


class CoverageRegion(BaseModel):
    locator: str
    region_type: str = "paragraph"
    parse_status: RegionStatus = "parsed"
    semantic_status: RegionStatus = "extracted"
    reason: str = ""


class CoverageManifest(BaseModel):
    artifact_id: str
    extraction_run_id: str
    expected_regions: list[CoverageRegion] = Field(default_factory=list)
    parsed_region_count: int = 0
    semantic_region_count: int = 0
    omitted_region_count: int = 0
    coverage_status: EvidenceCoverage = "complete"


class EvidenceBlock(BaseModel):
    evidence_block_id: str = Field(default_factory=lambda: new_id("eblk"))
    artifact_id: str
    owner_id: str = "default"
    locator: str = ""
    block_type: EvidenceBlockType = "paragraph"
    title_path: list[str] = Field(default_factory=list)
    page_number: int | None = None
    char_range: tuple[int, int] | None = None
    full_context: str
    source_type: str = "text"
    extraction_run_id: str
    confidence: float = 1.0
    modality: str = "text"
    created_at: datetime = Field(default_factory=local_now)


class EvidenceSpan(BaseModel):
    evidence_span_id: str = Field(default_factory=lambda: new_id("espn"))
    evidence_block_id: str
    owner_id: str = "default"
    start_offset: int = 0
    end_offset: int = 0
    span_type: EvidenceSpanType = "factual_statement"
    text_span: str
    normalized_meaning: str = ""
    locator: str = ""
    semantic_tags: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    quote_hash: str
    claim_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=local_now)


class EvidenceRef(BaseModel):
    source_kind: EvidenceSourceKind = "evidence_span"
    source_id: str
    artifact_id: str = ""
    evidence_block_id: str = ""
    evidence_span_id: str = ""
    locator: str = ""
    quote_hash: str = ""
    health_status: EvidenceRefHealthStatus = "valid"
    extracted_at: datetime = Field(default_factory=local_now)
    extraction_run_id: str = ""


class EvidenceRefHealth(BaseModel):
    evidence_ref_id: str = ""
    status: EvidenceRefHealthStatus = "valid"
    reason: str = ""
    checked_at: datetime = Field(default_factory=local_now)


class JudgeCalibration(BaseModel):
    confidence: float = 0.0
    calibrated_confidence: float = 0.0
    judge_version: str = "deterministic-semantic-v1"
    threshold_profile: str = "default"
    rationale: str = ""


class ClaimQualityGate(BaseModel):
    schema_valid: bool = True
    has_valid_evidence_ref: bool = False
    evidence_ref_health: EvidenceRefHealthStatus = "valid"
    grounding_confidence: float = 0.0
    support_status: SupportStatus = "unsupported"
    lifecycle_state: KnowledgeState = "candidate"
    source_role: str = ""
    critical_missing_scope: bool = False
    critical_missing_valid_time: bool = False
    judge_version: str = "deterministic-semantic-v1"
    passed: bool = False
    blocked_reasons: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    claim_id: str = Field(default_factory=lambda: new_id("clm"))
    owner_id: str = "default"
    user_id: str = "default"
    claim_type: ClaimType = "external_fact"
    statement: str
    canonical_statement: str = ""
    subject: str = ""
    predicate: str = ""
    object: str = ""
    qualifiers: list[str] = Field(default_factory=list)
    scope: str = ""
    condition: str = ""
    valid_time: str | None = None
    source_role: Literal["user_assertion", "source_document", "assistant_inference", "research_source"] = "source_document"
    source_attribution: str = ""
    confidence: float = 0.0
    support_status: SupportStatus = "unsupported"
    state: KnowledgeState = "candidate"
    sensitivity_level: Literal["low", "medium", "high"] = "low"
    memory_policy: Literal["auto_save_allowed", "requires_user_confirmation", "never_store"] = "auto_save_allowed"
    retention_policy: Literal["permanent", "expires_after", "session_only"] = "permanent"
    created_from: str = ""
    created_by: Literal["user", "assistant", "system"] = "system"
    evidence_span_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    uncertainty_reason: str = ""
    quality_gate: ClaimQualityGate = Field(default_factory=ClaimQualityGate)
    canonical_key: str = ""
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)


class GroundingRun(BaseModel):
    grounding_run_id: str = Field(default_factory=lambda: new_id("grun"))
    owner_id: str = "default"
    claim_id: str
    evidence_span_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_span_ids: list[str] = Field(default_factory=list)
    support_status: SupportStatus = "unsupported"
    verifier: str = "semantic-grounding-judge"
    verifier_version: str = "v1"
    rationale: str = ""
    confidence: float = 0.0
    calibration: JudgeCalibration = Field(default_factory=JudgeCalibration)
    created_at: datetime = Field(default_factory=local_now)


class ClaimSupportEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("cse"))
    owner_id: str = "default"
    claim_id: str
    from_support_status: SupportStatus | None = None
    to_support_status: SupportStatus
    grounding_run_id: str
    reason: str = ""
    actor: Literal["user", "assistant", "system"] = "system"
    created_at: datetime = Field(default_factory=local_now)


class ClaimAdmissionDecision(BaseModel):
    admission_id: str = Field(default_factory=lambda: new_id("adm"))
    owner_id: str = "default"
    claim_id: str
    admission_result: AdmissionResult
    reason: str = ""
    required_evidence: list[str] = Field(default_factory=list)
    decision_policy: DecisionEffect = "auto_execute"
    memory_policy: Literal["auto_save_allowed", "requires_user_confirmation", "never_store"] = "auto_save_allowed"
    retention_policy: Literal["permanent", "expires_after", "session_only"] = "permanent"
    created_at: datetime = Field(default_factory=local_now)


class KnowledgeStateEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("kst"))
    owner_id: str = "default"
    target_type: Literal["claim", "knowledge_item"] = "claim"
    target_id: str
    from_state: KnowledgeState | None = None
    to_state: KnowledgeState
    reason: str = ""
    actor: Literal["user", "assistant", "system"] = "system"
    evidence_span_ids: list[str] = Field(default_factory=list)
    grounding_run_id: str | None = None
    decision_id: str | None = None
    policy_result: str = ""
    created_at: datetime = Field(default_factory=local_now)


class KnowledgeRelation(BaseModel):
    relation_id: str = Field(default_factory=lambda: new_id("krel"))
    owner_id: str = "default"
    source_type: Literal["claim", "knowledge_item", "artifact", "research_event"] = "claim"
    source_id: str
    target_type: Literal["claim", "knowledge_item", "artifact", "research_event"] = "claim"
    target_id: str
    relation_type: RelationType
    confidence: float = 0.0
    evidence_span_ids: list[str] = Field(default_factory=list)
    decision_id: str | None = None
    reason: str = ""
    created_at: datetime = Field(default_factory=local_now)


class KnowledgeItem(BaseModel):
    knowledge_item_id: str = Field(default_factory=lambda: new_id("kitm"))
    owner_id: str = "default"
    user_id: str = "default"
    title: str
    summary: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    evidence_span_ids: list[str] = Field(default_factory=list)
    primary_state: KnowledgeItemPrimaryState = "evidence_ready"
    flags: list[KnowledgeItemFlag] = Field(default_factory=list)
    state: Literal["active", "conflicted", "deprecated", "deleted"] = "active"
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)


class ProjectionJob(BaseModel):
    projection_job_id: str = Field(default_factory=lambda: new_id("pjob"))
    owner_id: str = "default"
    projection_type: ProjectionType
    source_object_type: Literal["artifact", "evidence", "claim", "knowledge_item"] = "artifact"
    source_object_id: str
    status: ProjectionStatus = "pending"
    retry_count: int = 0
    last_error: str = ""
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)


class DecisionCard(BaseModel):
    decision_id: str = Field(default_factory=lambda: new_id("dec"))
    owner_id: str = "default"
    decision_type: Literal[
        "claim_admission",
        "claim_correction",
        "delete_or_restore",
        "conflict_resolution",
        "research_save",
    ]
    proposed_action: str
    impact_claim_ids: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "medium"
    policy_reason: str = ""
    status: Literal["pending", "accepted", "rejected", "auto_executed", "blocked"] = "pending"
    user_response: str = ""
    created_at: datetime = Field(default_factory=local_now)
    resolved_at: datetime | None = None


class AnswerCitation(BaseModel):
    evidence_span_id: str
    evidence_block_id: str
    artifact_id: str
    quote: str
    locator: str = ""
    evidence_ref: EvidenceRef | None = None
    claim_ids: list[str] = Field(default_factory=list)


class KnowledgeEvidenceSelection(BaseModel):
    """Read-only evidence and knowledge-state facts selected for one question."""

    question: str
    selected_spans: list[EvidenceSpan] = Field(default_factory=list)
    citations: list[AnswerCitation] = Field(default_factory=list)
    selected_claims: list[Claim] = Field(default_factory=list)
    conflicted_claim_ids: list[str] = Field(default_factory=list)
    potential_conflicted_claim_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class AnswerVerificationConflict(BaseModel):
    evidence_span_ids: list[str] = Field(min_length=2)
    description: str = Field(min_length=1)


class AnswerVerificationAssessment(BaseModel):
    verdict: Literal["passed", "needs_revision", "insufficient_evidence"]
    conclusion_status: Literal["supported", "conflicted", "insufficient_evidence"]
    evidence_coverage: EvidenceCoverage = "none"
    conflicts: list[AnswerVerificationConflict] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_sections: list[dict[str, str]] = Field(default_factory=list)
    feedback: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    verifier_name: str
    verifier_version: str


class EvidenceGroundedAnswer(BaseModel):
    question: str
    answer: str
    citations: list[AnswerCitation] = Field(default_factory=list)
    verification: AnswerVerificationAssessment
    answer_claim_count: int = 0
    answer_claim_saved_count: int = 0
    active_claim_count_delta: int = 0
    selected_claim_ids: list[str] = Field(default_factory=list)
    conflicted_claim_ids: list[str] = Field(default_factory=list)
    claim_summaries: list[str] = Field(default_factory=list)
    diagnostic_fields: dict[str, Any] = Field(default_factory=dict)


class IngestKnowledgeResult(BaseModel):
    artifact: Artifact
    extraction_run: ExtractionRun
    evidence_blocks: list[EvidenceBlock]
    evidence_spans: list[EvidenceSpan]
    claims: list[Claim]
    grounding_runs: list[GroundingRun]
    support_events: list[ClaimSupportEvent]
    admission_decisions: list[ClaimAdmissionDecision]
    state_events: list[KnowledgeStateEvent]
    relations: list[KnowledgeRelation] = Field(default_factory=list)
    knowledge_items: list[KnowledgeItem] = Field(default_factory=list)
    projection_jobs: list[ProjectionJob] = Field(default_factory=list)
    decisions: list[DecisionCard] = Field(default_factory=list)
    partial_failure_count: int = 0


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ConversationSolidifyResult(BaseModel):
    ingest_result: IngestKnowledgeResult
    user_claim_count: int = 0
    assistant_candidate_count: int = 0
    rejected_assistant_claim_count: int = 0


class ClaimCorrectionResult(BaseModel):
    old_claim: Claim
    new_claim: Claim
    relation: KnowledgeRelation
    state_events: list[KnowledgeStateEvent]


class ResearchEvent(BaseModel):
    research_event_id: str = Field(default_factory=lambda: new_id("rev"))
    owner_id: str = "default"
    user_id: str = "default"
    topic: str = ""
    title: str = ""
    summary: str = ""
    source_ref: str | None = None
    artifact_id: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    status: Literal["candidate", "saved", "irrelevant", "reported"] = "candidate"
    negative_feedback_reason: Literal[
        "not_interested",
        "source_noise",
        "already_known",
        "too_frequent",
        "low_quality",
        "",
    ] = ""
    interest_score: float = 1.0
    created_at: datetime = Field(default_factory=local_now)
    updated_at: datetime = Field(default_factory=local_now)


class ResearchIngestResult(BaseModel):
    event: ResearchEvent
    ingest_result: IngestKnowledgeResult
    impact_relation_count: int = 0


class ReviewItem(BaseModel):
    review_item_id: str = Field(default_factory=lambda: new_id("rvi"))
    owner_id: str = "default"
    claim_id: str
    prompt: str
    priority: float = 0.0
    reason: str = ""
    state: Literal["due", "answered", "skipped"] = "due"
    due_at: datetime = Field(default_factory=lambda: local_now() + timedelta(days=1))
    created_at: datetime = Field(default_factory=local_now)


class KnowledgeGap(BaseModel):
    gap_id: str = Field(default_factory=lambda: new_id("kgap"))
    owner_id: str = "default"
    gap_type: Literal["conflict", "uncertain", "missing_evidence", "low_coverage"]
    claim_ids: list[str] = Field(default_factory=list)
    question: str
    reason: str = ""
    severity: Literal["low", "medium", "high"] = "medium"
    state: Literal["open", "resolved", "dismissed"] = "open"
    created_at: datetime = Field(default_factory=local_now)


class ReviewPlanResult(BaseModel):
    review_items: list[ReviewItem] = Field(default_factory=list)
    knowledge_gaps: list[KnowledgeGap] = Field(default_factory=list)


class GraphProjection(BaseModel):
    graph_projection_id: str = Field(default_factory=lambda: new_id("gprj"))
    owner_id: str = "default"
    source_claim_id: str
    evidence_span_ids: list[str] = Field(default_factory=list)
    entity_names: list[str] = Field(default_factory=list)
    relation_facts: list[str] = Field(default_factory=list)
    backlink_claim_ids: list[str] = Field(default_factory=list)
    backlink_evidence_span_ids: list[str] = Field(default_factory=list)
    quality_signal: Literal["ok", "weak", "no_backlink"] = "ok"
    created_at: datetime = Field(default_factory=local_now)


class GraphProjectionResult(BaseModel):
    projections: list[GraphProjection] = Field(default_factory=list)
    backlink_ok: bool = True


class ArtifactDeleteImpactResult(BaseModel):
    artifact_id: str
    affected_claim_ids: list[str] = Field(default_factory=list)
    affected_evidence_span_ids: list[str] = Field(default_factory=list)
    state_events: list[KnowledgeStateEvent] = Field(default_factory=list)
    invalidated_projection_count: int = 0


class SemanticReplayDiffResult(BaseModel):
    artifact_id: str
    old_claim_ids: list[str] = Field(default_factory=list)
    new_claim_ids: list[str] = Field(default_factory=list)
    added_claims: list[str] = Field(default_factory=list)
    removed_claims: list[str] = Field(default_factory=list)
    changed_scope_claims: list[str] = Field(default_factory=list)
    changed_support_claims: list[str] = Field(default_factory=list)
    regression_stage: str = ""
    low_confidence: bool = False
