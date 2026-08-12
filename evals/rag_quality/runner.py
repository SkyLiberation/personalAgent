"""Deterministic projections used by the hermetic RAG component scorer.

This module does not represent a product answer path. Product answer quality is
measured from the Conversation E2E archive; these helpers only score frozen
answer/evidence fixtures for low-level verifier regression.
"""

from __future__ import annotations

from .dataset import RunOutput


def _evidence_text(item) -> str:
    parts = [
        str(getattr(item, "title", "") or ""),
        str(getattr(item, "fact", "") or ""),
        str(getattr(item, "snippet", "") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def _evidence_id(item) -> str:
    return str(getattr(item, "source_id", "") or getattr(item, "evidence_id", "") or "")


def _retrieval_source(item) -> str:
    metadata = getattr(item, "metadata", {}) or {}
    return str(metadata.get("retrieved_by") or getattr(item, "source_type", "") or "")


def run_output_from_fixture(*, answer: str, evidence: list, verification=None) -> RunOutput:
    """Project one frozen answer/evidence fixture into the component schema."""
    checks = list(getattr(verification, "claim_checks", []) or []) if verification else []
    counter = sum(
        1 for item in evidence
        if (getattr(item, "metadata", {}) or {}).get("retrieved_by") == "contrastive"
    )
    return RunOutput(
        ranked_evidence_ids=[_evidence_id(e) for e in evidence],
        selected_evidence_ids=[_evidence_id(e) for e in evidence],
        selected_evidence_texts=[_evidence_text(e) for e in evidence],
        answer=answer,
        claim_verdicts=[c.status for c in checks],
        counter_evidence_found=counter,
        retrieval_sources=[_retrieval_source(e) for e in evidence],
    )
