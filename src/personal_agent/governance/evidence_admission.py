"""Admit observations for a bounded purpose without asserting they are true."""

from __future__ import annotations

from datetime import UTC, datetime

from personal_agent.governance.contracts.evidence import EvidenceAdmissionDecision, EvidenceRef
from personal_agent.runtime.contracts.control import ObservationRef


class EvidenceAdmission:
    def admit(
        self,
        observation: ObservationRef,
        *,
        purpose: str,
        criterion_scope: tuple[str, ...],
    ) -> EvidenceAdmissionDecision:
        reasons: list[str] = []
        if not criterion_scope:
            reasons.append("criterion_scope_missing")
        if not observation.provenance.content_hash:
            reasons.append("content_hash_missing")
        if "instruction" in observation.taint:
            reasons.append("untrusted_instruction_taint")
        if reasons:
            return EvidenceAdmissionDecision(
                observation_ref=observation.observation_id,
                verdict="rejected",
                reason_codes=tuple(reasons),
            )
        evidence = EvidenceRef(
            observation_ref=observation.observation_id,
            admitted_purpose=purpose,
            criterion_scope=criterion_scope,
            trust=observation.trust,
            content_hash=observation.provenance.content_hash,
            admitted_at=datetime.now(UTC),
        )
        return EvidenceAdmissionDecision(
            observation_ref=observation.observation_id,
            verdict="accepted",
            evidence=evidence,
            reason_codes=("admitted_for_bounded_use",),
        )


__all__ = ["EvidenceAdmission"]

