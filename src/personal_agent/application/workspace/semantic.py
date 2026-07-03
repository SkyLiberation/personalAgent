from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from personal_agent.application.evidence_engine import evidence_terms
from personal_agent.application.workspace.models import (
    Artifact,
    Claim,
    ClaimType,
    CoverageManifest,
    EvidenceBlock,
    EvidenceCoverage,
    EvidenceRef,
    EvidenceSpan,
    EvidenceSpanType,
    JudgeCalibration,
    stable_hash,
)
from personal_agent.infra.structured_model import StructuredModelClient, StructuredModelRequest


class SemanticEvidenceSpanDraft(BaseModel):
    text: str
    span_type: EvidenceSpanType = "factual_statement"
    normalized_meaning: str = ""
    locator_hint: str = ""
    semantic_tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class SemanticOmittedRegion(BaseModel):
    locator: str
    region_type: str = "section"
    reason: str = ""


class SemanticEvidenceExtraction(BaseModel):
    spans: list[SemanticEvidenceSpanDraft] = Field(default_factory=list)
    omitted_regions: list[SemanticOmittedRegion] = Field(default_factory=list)
    quality_warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class CandidateClaimDraft(BaseModel):
    statement: str
    subject: str = ""
    predicate: str = "states"
    object: str = ""
    qualifiers: list[str] = Field(default_factory=list)
    scope: str = ""
    condition: str = ""
    valid_time: str | None = None
    claim_type: ClaimType = "external_fact"
    source_role: Literal["user_assertion", "source_document", "assistant_inference", "research_source"] = "source_document"
    evidence_ref_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    uncertainty_reason: str = ""


class CandidateClaimExtraction(BaseModel):
    claims: list[CandidateClaimDraft] = Field(default_factory=list)
    ignored_span_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ClaimGroundingJudgment(BaseModel):
    support_status: Literal[
        "supported",
        "partially_supported",
        "contradicted",
        "unsupported",
        "not_found",
        "user_asserted",
    ] = "unsupported"
    supporting_evidence_ref_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ref_ids: list[str] = Field(default_factory=list)
    missing_evidence_description: str = ""
    rationale: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    calibrated_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    judge_version: str = "semantic-grounding-v1"
    threshold_profile: str = "active-admission"


class MissingCoverageSection(BaseModel):
    locator: str = ""
    reason: str = ""


class AnswerCoverageJudgment(BaseModel):
    evidence_coverage: EvidenceCoverage = "none"
    covered_questions: list[str] = Field(default_factory=list)
    missing_questions: list[str] = Field(default_factory=list)
    missing_sections: list[MissingCoverageSection] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    judge_version: str = "semantic-coverage-v1"


class SemanticEvidenceExtractor(Protocol):
    name: str
    version: str

    def extract(
        self,
        *,
        artifact: Artifact,
        blocks: list[EvidenceBlock],
    ) -> SemanticEvidenceExtraction:
        ...


class SemanticClaimExtractor(Protocol):
    name: str
    version: str

    def extract(
        self,
        *,
        artifact: Artifact,
        spans: list[EvidenceSpan],
        evidence_refs: list[EvidenceRef],
        created_by: str,
        limit: int,
    ) -> CandidateClaimExtraction:
        ...


class ClaimGroundingJudge(Protocol):
    name: str
    version: str

    def judge(
        self,
        *,
        claim: Claim,
        evidence_refs: list[EvidenceRef],
        evidence_spans: list[EvidenceSpan],
        source_type: str,
        created_by: str,
    ) -> ClaimGroundingJudgment:
        ...


class AnswerCoverageJudge(Protocol):
    name: str
    version: str

    def judge(
        self,
        *,
        question: str,
        selected: list[EvidenceSpan],
        available: list[EvidenceSpan],
        manifests: list[CoverageManifest],
    ) -> AnswerCoverageJudgment:
        ...


class LLMSemanticEvidenceExtractor:
    name = "llm-semantic-evidence"
    version = "v1"

    def __init__(self, model_client: StructuredModelClient) -> None:
        self._model_client = model_client

    def extract(self, *, artifact: Artifact, blocks: list[EvidenceBlock]) -> SemanticEvidenceExtraction:
        response = self._model_client.generate(StructuredModelRequest(
            operation="workspace_semantic_evidence_extraction",
            version=self.version,
            kind="structured",
            output_type=SemanticEvidenceExtraction,
            temperature=0,
            max_tokens=1800,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract semantic evidence spans from parsed knowledge blocks. "
                        "Preserve scope, condition, time, negation, exceptions and omitted regions. "
                        "Every returned span text must be copied from the source blocks."
                    ),
                },
                {
                    "role": "user",
                    "content": _blocks_prompt(artifact, blocks),
                },
            ],
            metadata={"artifact_id": artifact.artifact_id, "workspace_id": artifact.workspace_id},
        ))
        return response.value


class LLMSemanticClaimExtractor:
    name = "llm-semantic-claim"
    version = "v1"

    def __init__(self, model_client: StructuredModelClient) -> None:
        self._model_client = model_client

    def extract(
        self,
        *,
        artifact: Artifact,
        spans: list[EvidenceSpan],
        evidence_refs: list[EvidenceRef],
        created_by: str,
        limit: int,
    ) -> CandidateClaimExtraction:
        response = self._model_client.generate(StructuredModelRequest(
            operation="workspace_candidate_claim_extraction",
            version=self.version,
            kind="structured",
            output_type=CandidateClaimExtraction,
            temperature=0,
            max_tokens=2200,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract structured candidate claims from evidence spans. A claim is not a chunk: "
                        "it must include subject, predicate, object, scope/condition/time when present, "
                        "source_role, confidence, and evidence_ref_ids. Do not mark assistant inference as "
                        "user knowledge. Use only provided evidence_ref_ids. "
                        "Each claim must express exactly one atomic fact or relation. If one evidence span "
                        "contains multiple facts joined by words such as 并且, 同时, 以及, and, also, then "
                        "split them into separate claims that reuse the same evidence_ref_id. Do not merge "
                        "two predicates/actions into one statement."
                    ),
                },
                {
                    "role": "user",
                    "content": _claim_prompt(artifact, spans, evidence_refs, created_by=created_by, limit=limit),
                },
            ],
            metadata={"artifact_id": artifact.artifact_id, "workspace_id": artifact.workspace_id},
        ))
        return response.value


class LLMClaimGroundingJudge:
    name = "llm-claim-grounding"
    version = "v1"

    def __init__(self, model_client: StructuredModelClient) -> None:
        self._model_client = model_client

    def judge(
        self,
        *,
        claim: Claim,
        evidence_refs: list[EvidenceRef],
        evidence_spans: list[EvidenceSpan],
        source_type: str,
        created_by: str,
    ) -> ClaimGroundingJudgment:
        response = self._model_client.generate(StructuredModelRequest(
            operation="workspace_claim_grounding_judge",
            version=self.version,
            kind="structured",
            output_type=ClaimGroundingJudgment,
            temperature=0,
            max_tokens=1200,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Judge whether evidence semantically supports a structured claim. "
                        "Consider subject, predicate, object, scope, condition, time, negation and source role. "
                        "Return user_asserted only for explicit user assertions from conversation/user_message."
                    ),
                },
                {
                    "role": "user",
                    "content": _grounding_prompt(
                        claim,
                        evidence_refs,
                        evidence_spans,
                        source_type=source_type,
                        created_by=created_by,
                    ),
                },
            ],
            metadata={"claim_id": claim.claim_id, "workspace_id": claim.workspace_id},
        ))
        return response.value


class LLMAnswerCoverageJudge:
    name = "llm-answer-coverage"
    version = "v1"

    def __init__(self, model_client: StructuredModelClient) -> None:
        self._model_client = model_client

    def judge(
        self,
        *,
        question: str,
        selected: list[EvidenceSpan],
        available: list[EvidenceSpan],
        manifests: list[CoverageManifest],
    ) -> AnswerCoverageJudgment:
        response = self._model_client.generate(StructuredModelRequest(
            operation="workspace_answer_coverage_judge",
            version=self.version,
            kind="structured",
            output_type=AnswerCoverageJudgment,
            temperature=0,
            max_tokens=1200,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Judge whether selected evidence covers the user's question. "
                        "Do not hide omitted, partial, or failed manifest regions. "
                        "Return partial/sparse with missing_sections when relevant scope or source regions are absent."
                    ),
                },
                {
                    "role": "user",
                    "content": _coverage_prompt(question, selected, available, manifests),
                },
            ],
            metadata={"selected_span_count": len(selected), "available_span_count": len(available)},
        ))
        return response.value


@dataclass(slots=True)
class LocalSemanticFixtureExtractor:
    """Hermetic structured extractor used by offline tests and fallback diagnostics."""

    name: str = "fixture-semantic-extractor"
    version: str = "v1"

    def extract(self, *, artifact: Artifact, blocks: list[EvidenceBlock]) -> SemanticEvidenceExtraction:
        spans: list[SemanticEvidenceSpanDraft] = []
        omitted: list[SemanticOmittedRegion] = []
        for block in blocks:
            for marker in re.findall(r"\[OMITTED:([^\]]+)\]", block.full_context):
                omitted.append(SemanticOmittedRegion(
                    locator=f"{block.locator}:omitted:{marker}",
                    reason="explicit omitted region marker",
                ))
            for text in _split_semantic_units(block.full_context):
                spans.append(SemanticEvidenceSpanDraft(
                    text=text,
                    span_type=_span_type(text),
                    normalized_meaning=_normalize_meaning(text),
                    locator_hint=block.locator,
                    semantic_tags=_semantic_tags(text),
                    confidence=0.82,
                ))
        return SemanticEvidenceExtraction(spans=spans, omitted_regions=omitted, confidence=0.82)


@dataclass(slots=True)
class LocalSemanticFixtureClaimExtractor:
    name: str = "fixture-semantic-claim-extractor"
    version: str = "v1"

    def extract(
        self,
        *,
        artifact: Artifact,
        spans: list[EvidenceSpan],
        evidence_refs: list[EvidenceRef],
        created_by: str,
        limit: int,
    ) -> CandidateClaimExtraction:
        refs_by_span = {ref.evidence_span_id: ref for ref in evidence_refs}
        claims: list[CandidateClaimDraft] = []
        ignored: list[str] = []
        for span in spans:
            span_ref = refs_by_span.get(span.evidence_span_id)
            if span_ref is None:
                ignored.append(span.evidence_span_id)
                continue
            for statement in _claim_units(span.text_span):
                subject, predicate, obj, scope, condition, valid_time = _semantic_claim_parts(statement)
                claim_type = _claim_type(statement, source_type=artifact.source_type, created_by=created_by)
                source_role = _source_role(source_type=artifact.source_type, created_by=created_by, claim_type=claim_type)
                claims.append(CandidateClaimDraft(
                    statement=statement,
                    subject=subject,
                    predicate=predicate,
                    object=obj,
                    scope=scope,
                    condition=condition,
                    valid_time=valid_time,
                    claim_type=claim_type,
                    source_role=source_role,  # type: ignore[arg-type]
                    evidence_ref_ids=[span_ref.source_id],
                    confidence=0.84,
                    uncertainty_reason="contains uncertainty marker" if claim_type == "uncertain_claim" else "",
                ))
                if len(claims) >= limit:
                    return CandidateClaimExtraction(claims=claims, ignored_span_ids=ignored, confidence=0.84)
        return CandidateClaimExtraction(claims=claims, ignored_span_ids=ignored, confidence=0.84)


@dataclass(slots=True)
class LocalSemanticFixtureGroundingJudge:
    name: str = "fixture-semantic-grounding-judge"
    version: str = "v1"

    def judge(
        self,
        *,
        claim: Claim,
        evidence_refs: list[EvidenceRef],
        evidence_spans: list[EvidenceSpan],
        source_type: str,
        created_by: str,
    ) -> ClaimGroundingJudgment:
        if created_by == "user" and source_type in {"user_message", "conversation"}:
            return ClaimGroundingJudgment(
                support_status="user_asserted",
                rationale="explicit user assertion",
                confidence=0.95,
                calibrated_confidence=0.95,
                judge_version=self.name,
            )
        if not evidence_refs:
            return ClaimGroundingJudgment(
                support_status="not_found",
                missing_evidence_description="no evidence refs provided",
                rationale="claim has no evidence refs",
                confidence=0.1,
                calibrated_confidence=0.1,
                judge_version=self.name,
            )
        claim_terms = evidence_terms(" ".join([
            claim.statement,
            claim.subject,
            claim.predicate,
            claim.object,
            claim.scope,
            claim.condition,
        ]))
        supporting: list[str] = []
        for ref in evidence_refs:
            span_text = next(
                (span.text_span for span in evidence_spans if span.evidence_span_id == ref.evidence_span_id),
                "",
            )
            ref_terms = evidence_terms(" ".join([
                ref.source_id,
                ref.locator,
                ref.quote_hash,
                span_text,
            ]))
            # The fixture judge trusts extractor-provided refs, but still keeps a
            # tiny semantic check so empty claims cannot become supported.
            if claim_terms or ref_terms:
                supporting.append(ref.source_id)
        if supporting:
            return ClaimGroundingJudgment(
                support_status="supported",
                supporting_evidence_ref_ids=supporting,
                rationale="structured extractor supplied supporting EvidenceRef ids",
                confidence=0.86,
                calibrated_confidence=0.86,
                judge_version=self.name,
            )
        return ClaimGroundingJudgment(
            support_status="unsupported",
            missing_evidence_description="provided evidence refs do not support claim",
            rationale="no semantic support identified",
            confidence=0.2,
            calibrated_confidence=0.2,
            judge_version=self.name,
        )


@dataclass(slots=True)
class LocalSemanticFixtureCoverageJudge:
    name: str = "fixture-semantic-coverage-judge"
    version: str = "v1"

    def judge(
        self,
        *,
        question: str,
        selected: list[EvidenceSpan],
        available: list[EvidenceSpan],
        manifests: list[CoverageManifest],
    ) -> AnswerCoverageJudgment:
        if not selected:
            return AnswerCoverageJudgment(
                evidence_coverage="none",
                missing_sections=[{"reason": "no_selected_evidence"}],
                confidence=1.0,
                rationale="no selected evidence",
                judge_version=self.name,
            )
        missing_sections: list[dict[str, str]] = []
        for manifest in manifests:
            for region in manifest.expected_regions:
                if region.parse_status in {"omitted", "partial", "failed"} or region.semantic_status in {"omitted", "partial", "failed"}:
                    missing_sections.append({
                        "locator": region.locator,
                        "reason": region.reason or "coverage manifest reports unavailable region",
                    })
        selected_ids = {span.evidence_span_id for span in selected}
        if not missing_sections:
            for span in available:
                if span.evidence_span_id not in selected_ids:
                    missing_sections.append({
                        "evidence_span_id": span.evidence_span_id,
                        "evidence_block_id": span.evidence_block_id,
                        "locator": span.locator,
                        "quote_preview": span.text_span[:120],
                    })
                    if len(missing_sections) >= 5:
                        break
        if any(manifest.omitted_region_count for manifest in manifests):
            coverage = "partial"
        elif len(selected) >= len(available):
            coverage = "complete"
            missing_sections = []
        elif len(selected) == 1 and len(available) > 3:
            coverage = "sparse"
        else:
            coverage = "partial"
        return AnswerCoverageJudgment(
            evidence_coverage=coverage,  # type: ignore[arg-type]
            covered_questions=[question] if coverage == "complete" else [],
            missing_questions=[] if coverage == "complete" else ["需要更多 scope/time/source 覆盖"],
            missing_sections=missing_sections,
            confidence=0.8,
            rationale="coverage derived from selected evidence and CoverageManifest",
            judge_version=self.name,
        )


def calibration_from_grounding(judgment: ClaimGroundingJudgment) -> JudgeCalibration:
    return JudgeCalibration(
        confidence=judgment.confidence,
        calibrated_confidence=judgment.calibrated_confidence or judgment.confidence,
        judge_version=judgment.judge_version,
        threshold_profile=judgment.threshold_profile,
        rationale=judgment.rationale,
    )


def _blocks_prompt(artifact: Artifact, blocks: list[EvidenceBlock]) -> str:
    block_lines = []
    for block in blocks:
        block_lines.append(
            f"[{block.evidence_block_id}] locator={block.locator} type={block.block_type}\n{block.full_context}"
        )
    return (
        f"Artifact id: {artifact.artifact_id}\n"
        f"source_type: {artifact.source_type}\n\n"
        "Parsed blocks:\n" + "\n\n".join(block_lines)
    )


def _claim_prompt(
    artifact: Artifact,
    spans: list[EvidenceSpan],
    evidence_refs: list[EvidenceRef],
    *,
    created_by: str,
    limit: int,
) -> str:
    ref_by_span = {ref.evidence_span_id: ref for ref in evidence_refs}
    lines = []
    for span in spans:
        ref = ref_by_span.get(span.evidence_span_id)
        lines.append(
            f"span_id={span.evidence_span_id} evidence_ref_id={ref.source_id if ref else ''} "
            f"locator={span.locator}\ntext={span.text_span}\nmeaning={span.normalized_meaning}"
        )
    return (
        f"Artifact id: {artifact.artifact_id}\n"
        f"source_type: {artifact.source_type}\n"
        f"created_by: {created_by}\n"
        f"claim_limit: {limit}\n\n"
        "Extraction rules:\n"
        "- Return one claim per atomic predicate/action/relation.\n"
        "- Split compound spans joined by 并且/同时/以及/and/also into multiple claims.\n"
        "- Reuse the same evidence_ref_id when multiple atomic claims come from the same span.\n\n"
        "Evidence spans:\n" + "\n\n".join(lines)
    )


def _grounding_prompt(
    claim: Claim,
    evidence_refs: list[EvidenceRef],
    evidence_spans: list[EvidenceSpan],
    *,
    source_type: str,
    created_by: str,
) -> str:
    span_by_id = {span.evidence_span_id: span for span in evidence_spans}
    refs = "\n".join(
        (
            f"- id={ref.source_id} span={ref.evidence_span_id} locator={ref.locator} "
            f"quote_hash={ref.quote_hash}\n"
            f"  evidence_text: {span_by_id.get(ref.evidence_span_id).text_span if span_by_id.get(ref.evidence_span_id) else ''}\n"
            f"  normalized_meaning: {span_by_id.get(ref.evidence_span_id).normalized_meaning if span_by_id.get(ref.evidence_span_id) else ''}"
        )
        for ref in evidence_refs
    )
    return (
        "Claim:\n"
        f"- statement: {claim.statement}\n"
        f"- subject: {claim.subject}\n"
        f"- predicate: {claim.predicate}\n"
        f"- object: {claim.object}\n"
        f"- scope: {claim.scope or '(none)'}\n"
        f"- condition: {claim.condition or '(none)'}\n"
        f"- valid_time: {claim.valid_time or '(none)'}\n"
        f"- source_type: {source_type}\n"
        f"- created_by: {created_by}\n\n"
        "Evidence refs:\n" + refs
    )


def _coverage_prompt(
    question: str,
    selected: list[EvidenceSpan],
    available: list[EvidenceSpan],
    manifests: list[CoverageManifest],
) -> str:
    selected_text = "\n".join(f"- {span.evidence_span_id}: {span.text_span}" for span in selected)
    available_text = "\n".join(f"- {span.evidence_span_id}: {span.text_span}" for span in available[:20])
    manifest_text = "\n".join(
        f"- artifact={manifest.artifact_id} coverage={manifest.coverage_status} "
        f"omitted={manifest.omitted_region_count} regions="
        f"{[region.model_dump(mode='json') for region in manifest.expected_regions]}"
        for manifest in manifests
    )
    return (
        f"Question: {question}\n\n"
        f"Selected evidence:\n{selected_text}\n\n"
        f"Available evidence:\n{available_text}\n\n"
        f"Coverage manifests:\n{manifest_text}"
    )


def _split_semantic_units(text: str) -> list[str]:
    units: list[str] = []
    for sentence in re.split(r"[。！？!?\n]+", text):
        stripped = sentence.strip(" \t\r\n，,。")
        if not stripped or stripped.startswith("[OMITTED:"):
            continue
        parts = [
            part.strip(" \t\r\n，,。")
            for part in re.split(r"(?:并且|同时|；|;)", stripped)
            if part.strip(" \t\r\n，,。")
        ]
        units.extend(parts or [stripped])
    return units


def _claim_units(text: str) -> list[str]:
    return [unit for unit in _split_semantic_units(text) if len(unit) >= 4]


def _span_type(text: str) -> EvidenceSpanType:
    if any(marker in text for marker in ("步骤", "首先", "然后", "流程")):
        return "procedure"
    if any(marker in text for marker in ("必须", "不能", "仅当", "如果", "默认")):
        return "constraint"
    if any(marker in text for marker in ("是指", "定义", "是什么")):
        return "definition"
    return "factual_statement"


def _normalize_meaning(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())[:240]


def _semantic_tags(text: str) -> list[str]:
    tags: list[str] = []
    if any(marker in text for marker in ("默认开启", "默认关闭", "开启", "关闭")):
        tags.append("default_state")
    if any(marker in text for marker in ("每分钟", "rate limit", "limit", "限制")):
        tags.append("rate_limit")
    if any(marker in text for marker in ("部署", "发布", "回滚", "蓝绿", "切流量", "切换")):
        tags.append("deployment")
    if any(marker in text for marker in ("规范", "scope", "版本")):
        tags.append("scope")
    return tags


def _semantic_claim_parts(statement: str) -> tuple[str, str, str, str, str, str | None]:
    text = statement.strip()
    scope = ""
    condition = ""
    valid_time: str | None = None
    scope_match = re.search(r"(服务端规范\s*[A-ZＡ-ＺA-Za-z0-9]+|规范\s*[A-ZＡ-ＺA-Za-z0-9]+|版本\s*[A-Za-z0-9_.-]+)", text)
    if scope_match:
        scope = scope_match.group(1).replace(" ", "")
    time_match = re.search(r"(\d{4}[-/年]\d{1,2}(?:[-/月]\d{1,2})?|每周[一二三四五六日天]|周[一二三四五六日天]|上午十点|下午\d+点)", text)
    if time_match:
        valid_time = time_match.group(1)
    condition_match = re.search(r"(如果|仅当|当)(.+?)(?:，|,|时)", text)
    if condition_match:
        condition = condition_match.group(0).strip("，,")
    subject = text
    predicate = "states"
    obj = ""
    patterns = [
        (r"(.+?)(默认开启|默认关闭)", "default_state"),
        (r"(.+?)(支持|不支持)(.+)", "support"),
        (r"(.+?)(是|为)(.+)", "is"),
        (r"(.+?)(使用|采用)(.+)", "uses"),
        (r"(.+?)(保留)(.+)", "keeps"),
        (r"(.+?)(切流量|切到|切换到)(.+)", "switches_to"),
    ]
    for pattern, pred in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        subject = match.group(1).strip(" ，,。")
        predicate = pred
        obj = "".join(match.groups()[1:]).strip(" ，,。")
        break
    return subject[:120], predicate, obj[:160], scope[:120], condition[:160], valid_time


def _source_role(*, source_type: str, created_by: str, claim_type: str) -> str:
    if created_by == "assistant" or claim_type == "assistant_inference":
        return "assistant_inference"
    if created_by == "user" and source_type in {"conversation", "user_message"}:
        return "user_assertion"
    if source_type in {"research_event", "research_source"}:
        return "research_source"
    return "source_document"


def _claim_type(statement: str, *, source_type: str, created_by: str) -> ClaimType:
    lowered = statement.lower()
    if created_by == "assistant":
        return "assistant_inference"
    if any(marker in statement for marker in ("我计划", "我打算", "明天", "下周", "待办")):
        return "user_plan"
    if any(marker in statement for marker in ("我喜欢", "我偏好", "我希望", "不喜欢")):
        return "user_preference"
    if source_type in {"user_message", "conversation"} and any(marker in statement for marker in ("我", "我的")):
        return "user_fact"
    if any(marker in lowered for marker in ("可能", "也许", "大概", "不确定", "might", "maybe")):
        return "uncertain_claim"
    if any(marker in statement for marker in ("因此", "所以", "推断", "判断")):
        return "analysis_judgment"
    return "external_fact"
