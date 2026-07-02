from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from personal_agent.application.candidate_enrichers import CandidateEnricher
from personal_agent.application.entailment import (
    CONTRADICTED,
    ENTAILED,
    HeuristicEntailmentJudge,
)
from personal_agent.application.rerankers import EvidenceReranker
from personal_agent.kernel.evidence import (
    ContextPack,
    EvidenceItem,
    SourceDocument,
    _dedupe_evidence_items,
    apply_rrf_fusion,
    compress_evidence,
    evidence_text_spans,
    research_sources_to_source_documents,
    source_documents_to_evidence,
)
from personal_agent.kernel.models import Citation, KnowledgeNote
from personal_agent.kernel.query_understanding import RetrievalFilters


@dataclass(slots=True)
class EvidenceAssemblyPolicy:
    task_type: str = "ask"
    source_preference: list[str] = field(default_factory=list)
    evidence_requirement: str = "balanced"
    ranking_objective: str = "relevance_first"
    diversity_requirement: str = "moderate"
    freshness_requirement: str = "none"
    max_evidence_items: int = 12
    max_context_chars: int = 5000
    compression_mode: str = "sentence"
    citation_mode: str = "selected_context"
    verification_strictness: str = "medium"


@dataclass(slots=True)
class EvidenceTrace:
    input_evidence_count: int = 0
    after_dedupe_count: int = 0
    after_fusion_count: int = 0
    after_enrichment_count: int = 0
    after_compression_count: int = 0
    selected_count: int = 0
    dropped_count: int = 0
    citation_count: int = 0
    context_chars: int = 0
    events: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ClaimGroundingTrace:
    claim_count: int = 0
    supported_count: int = 0
    partially_supported_count: int = 0
    unsupported_count: int = 0
    contradicted_count: int = 0
    not_found_count: int = 0
    evidence_span_count: int = 0


@dataclass(slots=True)
class EvidenceAssemblyRequest:
    question: str
    evidence: list[EvidenceItem]
    matches: list[KnowledgeNote]
    citations: list[Citation]
    store: object
    filters: RetrievalFilters | None
    candidate_enricher: CandidateEnricher
    reranker: EvidenceReranker
    max_items: int
    char_budget: int
    mmr_lambda: float = 0.7
    compress_max_sentences: int = 0
    policy: EvidenceAssemblyPolicy | None = None


@dataclass(slots=True)
class EvidenceAssemblyResult:
    evidence: list[EvidenceItem]
    matches: list[KnowledgeNote]
    citations: list[Citation]
    context_pack: ContextPack
    selected_matches: list[KnowledgeNote]
    selected_citations: list[Citation]
    assembly_trace: EvidenceTrace = field(default_factory=EvidenceTrace)
    trace: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvidenceSpan:
    span_id: str
    evidence_id: str
    source_id: str
    source_type: str
    text: str
    score: float = 0.0
    page_number: int | None = None
    source_span: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceClaimCheck:
    claim: str
    status: str
    supporting_evidence_ids: list[str] = field(default_factory=list)
    evidence_spans: list[str] = field(default_factory=list)
    spans: list[EvidenceSpan] = field(default_factory=list)
    reason: str = ""
    overlap: int = 0
    coverage: float = 0.0
    source_type: str = ""
    grounding_trace: ClaimGroundingTrace | None = None


class SourceNormalizer:
    def sources_to_evidence(self, documents: list[SourceDocument]) -> list[EvidenceItem]:
        return source_documents_to_evidence(documents)

    def research_sources_to_evidence(self, sources: list[Any]) -> list[EvidenceItem]:
        return self.sources_to_evidence(research_sources_to_source_documents(sources))


class EvidenceAssembler:
    def assemble(self, request: EvidenceAssemblyRequest) -> EvidenceAssemblyResult:
        policy = request.policy or EvidenceAssemblyPolicy(
            task_type="ask",
            max_evidence_items=request.max_items,
            max_context_chars=request.char_budget,
        )
        trace = EvidenceTrace(input_evidence_count=len(request.evidence))
        evidence = _dedupe_evidence_items(request.evidence)
        trace.after_dedupe_count = len(evidence)
        evidence = apply_rrf_fusion(evidence)
        trace.after_fusion_count = len(evidence)
        fused = sum(1 for item in evidence if item.metadata.get("consensus_count", 1) > 1)
        if fused:
            trace.events.append(f"RRF 融合: 多路共识证据 consensus_items={fused}")

        enriched = request.candidate_enricher.enrich(
            request.question,
            evidence=evidence,
            matches=request.matches,
            citations=request.citations,
            store=request.store,
            filters=request.filters,
        )
        trace.after_enrichment_count = len(enriched.evidence)
        if enriched.added_note_ids:
            trace.events.append(
                f"CandidateEnricher({request.candidate_enricher.name}): "
                f"added={len(enriched.added_note_ids)}"
            )

        rerank_input = self.compress_for_context(
            request.question,
            enriched.evidence,
            max_sentences=request.compress_max_sentences if policy.compression_mode != "none" else 0,
            trace=trace,
        )
        context_pack = request.reranker.rerank(
            request.question,
            rerank_input,
            max_items=policy.max_evidence_items or request.max_items,
            char_budget=policy.max_context_chars or request.char_budget,
            mmr_lambda=request.mmr_lambda,
        )
        selected_graph_items = [
            item for item in context_pack.evidence
            if item.source_type == "graph_fact"
            or item.metadata.get("retrieved_by") in {"graphiti", "structural"}
        ]
        trace.selected_count = len(context_pack.selected)
        trace.dropped_count = len(context_pack.dropped)
        trace.context_chars = context_pack.used_chars
        trace.events.append(
            f"ContextPack({request.reranker.name}): "
            f"selected={len(context_pack.selected)} dropped={len(context_pack.dropped)} "
            f"graph_selected={len(selected_graph_items)} "
            f"chars={context_pack.used_chars}/{context_pack.char_budget}"
        )
        citations = CitationSelector().select_citations(enriched.citations, context_pack.evidence)
        trace.citation_count = len(citations)
        return EvidenceAssemblyResult(
            evidence=enriched.evidence,
            matches=enriched.matches,
            citations=enriched.citations,
            context_pack=context_pack,
            selected_matches=CitationSelector().select_matches(enriched.matches, context_pack.evidence),
            selected_citations=citations,
            assembly_trace=trace,
            trace=list(trace.events),
        )

    def compress_for_context(
        self,
        question: str,
        evidence: list[EvidenceItem],
        *,
        max_sentences: int,
        trace: EvidenceTrace | None = None,
    ) -> list[EvidenceItem]:
        if max_sentences <= 0:
            if trace is not None:
                trace.after_compression_count = len(evidence)
            return evidence
        compressed = compress_evidence(question, evidence, max_sentences=max_sentences)
        if trace is not None:
            trace.after_compression_count = len(compressed)
        trimmed = sum(1 for item in compressed if item.metadata.get("compressed_from_chars"))
        if trimmed and trace is not None:
            trace.events.append(f"ContextCompressor: 句级压缩 trimmed_snippets={trimmed}")
        return compressed


class ClaimGrounder:
    def __init__(self, *, entailment_judge: object | None = None) -> None:
        self._judge = entailment_judge or HeuristicEntailmentJudge()

    def verify_claims(self, text: str, evidence: list[EvidenceItem], *, limit: int = 8) -> list[EvidenceClaimCheck]:
        spans = self._evidence_spans(evidence)
        checks: list[EvidenceClaimCheck] = []
        for claim in extract_claims(text, limit=limit):
            claim_terms = evidence_terms(claim)
            if not claim_terms:
                continue
            best_overlap = 0
            best_coverage = 0.0
            best_spans: list[EvidenceSpan] = []
            best_text = ""
            best_source_type = ""
            for span in spans:
                overlap = len(claim_terms & evidence_terms(span.text))
                coverage = overlap / max(len(claim_terms), 1)
                if overlap > best_overlap or (
                    overlap == best_overlap and coverage > best_coverage
                ):
                    best_overlap = overlap
                    best_coverage = coverage
                    best_spans = [span]
                    best_text = span.text
                    best_source_type = span.source_type
                elif overlap == best_overlap and overlap > 0 and span.evidence_id not in {
                    item.evidence_id for item in best_spans
                }:
                    best_spans.append(span)

            verdict = self._judge.judge(
                claim,
                best_text,
                overlap=best_overlap,
                claim_term_count=len(claim_terms),
                coverage=best_coverage,
                source_type=best_source_type,
            )
            status = self._status_from_verdict(
                verdict.verdict,
                overlap=best_overlap,
                coverage=best_coverage,
            )
            selected_spans = best_spans[:3] if status not in {"unsupported", "not_found"} else []
            checks.append(EvidenceClaimCheck(
                claim=claim,
                status=status,
                supporting_evidence_ids=[span.evidence_id for span in selected_spans],
                evidence_spans=[span.text for span in selected_spans],
                spans=selected_spans,
                reason=f"{verdict.verdict}: {verdict.reason}",
                overlap=best_overlap,
                coverage=best_coverage,
                source_type=best_source_type,
            ))
        grounding_trace = self._trace(checks, len(spans))
        for check in checks:
            check.grounding_trace = grounding_trace
        return checks

    def _status_from_verdict(self, verdict: str, *, overlap: int, coverage: float) -> str:
        if verdict == CONTRADICTED:
            return "contradicted"
        if verdict == ENTAILED:
            return "supported"
        if overlap >= 2 and coverage >= 0.25:
            return "partially_supported"
        if overlap > 0:
            return "unsupported"
        return "not_found"

    def _trace(self, checks: list[EvidenceClaimCheck], span_count: int) -> ClaimGroundingTrace:
        return ClaimGroundingTrace(
            claim_count=len(checks),
            supported_count=sum(1 for item in checks if item.status == "supported"),
            partially_supported_count=sum(1 for item in checks if item.status == "partially_supported"),
            unsupported_count=sum(1 for item in checks if item.status == "unsupported"),
            contradicted_count=sum(1 for item in checks if item.status == "contradicted"),
            not_found_count=sum(1 for item in checks if item.status == "not_found"),
            evidence_span_count=span_count,
        )

    def _evidence_spans(self, evidence: list[EvidenceItem]) -> list[EvidenceSpan]:
        spans: list[EvidenceSpan] = []
        for item in evidence:
            evidence_id = item.source_id or item.evidence_id
            for index, text in enumerate(evidence_text_spans(item)):
                spans.append(EvidenceSpan(
                    span_id=f"{evidence_id}:{index}",
                    evidence_id=evidence_id,
                    source_id=item.source_id,
                    source_type=item.source_type,
                    text=text,
                    score=float(item.score),
                    page_number=item.page_number,
                    source_span=item.source_span,
                    metadata={
                        "evidence_uuid": item.evidence_id,
                        "source_ref": item.source_ref,
                        "source_fingerprint": item.source_fingerprint,
                    },
                ))
        return spans


class CitationSelector:
    def select_matches(
        self,
        matches: list[KnowledgeNote],
        evidence: list[EvidenceItem],
    ) -> list[KnowledgeNote]:
        return select_matches(matches, evidence)

    def select_citations(
        self,
        citations: list[Citation],
        evidence: list[EvidenceItem],
    ) -> list[Citation]:
        return select_citations(citations, evidence)


class EvidenceEngine:
    """Shared source/evidence assembly and claim-grounding service.

    Workflow-specific services own control flow. This engine owns the common
    evidence mechanics: source normalization, pool assembly, prompt context
    selection and claim grounding.
    """

    def __init__(self, *, entailment_judge: object | None = None) -> None:
        self._normalizer = SourceNormalizer()
        self._assembler = EvidenceAssembler()
        self._grounder = ClaimGrounder(entailment_judge=entailment_judge)

    def sources_to_evidence(self, documents: list[SourceDocument]) -> list[EvidenceItem]:
        return self._normalizer.sources_to_evidence(documents)

    def research_sources_to_evidence(self, sources: list[Any]) -> list[EvidenceItem]:
        return self._normalizer.research_sources_to_evidence(sources)

    def assemble_context(self, request: EvidenceAssemblyRequest) -> EvidenceAssemblyResult:
        return self._assembler.assemble(request)

    def compress_for_context(
        self,
        question: str,
        evidence: list[EvidenceItem],
        *,
        max_sentences: int,
        trace: list[str] | None = None,
    ) -> list[EvidenceItem]:
        events = EvidenceTrace(events=trace) if trace is not None else None
        compressed = self._assembler.compress_for_context(
            question,
            evidence,
            max_sentences=max_sentences,
            trace=events,
        )
        if trace is not None and events is not None:
            trace[:] = events.events
        return compressed

    def verify_claims(self, text: str, evidence: list[EvidenceItem], *, limit: int = 8) -> list[EvidenceClaimCheck]:
        return self._grounder.verify_claims(text, evidence, limit=limit)


def extract_claims(text: str, *, limit: int = 8) -> list[str]:
    cleaned = re.sub(r"\[[Ee]?\d+\]", "", text)
    parts = re.split(r"[。！？!?；;\n]+", cleaned)
    claims: list[str] = []
    skip_markers = ("校验提示", "注意", "证据不足", "不确定", "无法回答")
    for part in parts:
        claim = part.strip(" -:：\t\r")
        if len(claim) < 8:
            continue
        if any(marker in claim for marker in skip_markers):
            continue
        if claim not in claims:
            claims.append(claim)
        if len(claims) >= limit:
            break
    return claims


def evidence_terms(text: str) -> set[str]:
    terms: set[str] = set()
    lowered = text.lower()
    for token in re.findall(r"[a-z0-9_+-]{2,}", lowered):
        terms.add(token)
    for run in re.findall(r"[\u3400-\u9fff]{2,}", text):
        terms.add(run)
        for size in (2, 3):
            for index in range(0, max(0, len(run) - size + 1)):
                terms.add(run[index:index + size])
    return terms


def order_matches_by_evidence(
    matches: list[KnowledgeNote],
    evidence: list[EvidenceItem],
) -> list[KnowledgeNote]:
    by_id = {note.id: note for note in matches}
    ordered: list[KnowledgeNote] = []
    seen: set[str] = set()
    for item in evidence:
        note = by_id.get(item.source_id)
        if note is None or note.id in seen:
            continue
        ordered.append(note)
        seen.add(note.id)
    ordered.extend(note for note in matches if note.id not in seen)
    return ordered


def select_matches(
    matches: list[KnowledgeNote],
    evidence: list[EvidenceItem],
) -> list[KnowledgeNote]:
    selected_ids = {
        item.source_id
        for item in evidence
        if item.source_id and item.source_type in {"note", "chunk"}
    }
    return [
        note for note in order_matches_by_evidence(matches, evidence)
        if note.id in selected_ids
    ]


def select_citations(
    citations: list[Citation],
    evidence: list[EvidenceItem],
) -> list[Citation]:
    selected_note_ids = {
        item.source_id
        for item in evidence
        if item.source_id and item.source_type in {"note", "chunk"}
    }
    selected_web_urls = {
        item.url or item.source_ref or item.source_id
        for item in evidence
        if item.source_type == "web" and (item.url or item.source_ref or item.source_id)
    }
    selected: list[Citation] = []
    seen: set[tuple[str, str, str | None]] = set()
    for citation in citations:
        keep = (
            citation.source_type == "web"
            and citation.url is not None
            and citation.url in selected_web_urls
        ) or (
            citation.source_type != "web"
            and citation.note_id in selected_note_ids
        )
        if not keep:
            continue
        key = (citation.note_id, citation.url or "", citation.relation_fact)
        if key in seen:
            continue
        seen.add(key)
        selected.append(citation)
    return selected
