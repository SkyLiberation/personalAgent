from __future__ import annotations

from dataclasses import dataclass

from personal_agent.application.workspace.models import (
    Claim,
    ClaimAdmissionDecision,
    DecisionEffect,
    KnowledgeState,
    SupportStatus,
)


@dataclass(slots=True)
class DecisionPolicy:
    """General action confirmation policy for P0 knowledge side effects."""

    def decide(self, *, risk_level: str, sensitivity_level: str = "low") -> DecisionEffect:
        if risk_level == "blocked":
            return "block"
        if risk_level == "high" or sensitivity_level == "high":
            return "ask_confirmation"
        return "auto_execute"


class ClaimAdmissionPolicy:
    """Only entry point for turning a candidate claim into active knowledge."""

    def __init__(self, decision_policy: DecisionPolicy | None = None) -> None:
        self._decision_policy = decision_policy or DecisionPolicy()

    def evaluate(self, claim: Claim) -> ClaimAdmissionDecision:
        support = claim.support_status
        claim_type = claim.claim_type
        if support in {"unsupported", "not_found"}:
            return self._decision(
                claim,
                "reject",
                reason="unsupported claims cannot enter long-term knowledge",
                decision_policy="block",
                required_evidence=["supported EvidenceSpan"],
            )
        if support == "contradicted":
            return self._decision(
                claim,
                "reject",
                reason="contradicted claims must be rejected or routed to conflict handling",
                decision_policy="block",
            )
        if claim_type == "assistant_inference":
            return self._decision(
                claim,
                "reject",
                reason="assistant inference cannot become user knowledge without explicit confirmation",
                decision_policy="block",
            )
        if claim.memory_policy == "never_store":
            return self._decision(
                claim,
                "reject",
                reason="memory policy forbids storage",
                decision_policy="block",
            )
        if claim.sensitivity_level == "high":
            return self._decision(
                claim,
                "require_decision",
                reason="high-sensitivity claim requires explicit user confirmation",
                decision_policy=self._decision_policy.decide(
                    risk_level="high",
                    sensitivity_level=claim.sensitivity_level,
                ),
            )
        if claim_type in {"analysis_judgment", "uncertain_claim"}:
            return self._decision(
                claim,
                "keep_candidate",
                reason=f"{claim_type} should remain candidate until reviewed",
                decision_policy="auto_execute",
            )
        if claim_type == "user_plan":
            return self._decision(
                claim,
                "keep_candidate",
                reason="user plans belong to task/reminder flow unless explicitly stored",
                decision_policy="auto_execute",
                retention_policy="session_only",
            )
        if support in {"supported", "user_asserted"}:
            return self._decision(
                claim,
                "allow_active",
                reason="claim has sufficient evidence or explicit user assertion",
                decision_policy="auto_execute",
            )
        return self._decision(
            claim,
            "keep_candidate",
            reason="partially supported claims need more evidence before active",
            decision_policy="auto_execute",
        )

    def _decision(
        self,
        claim: Claim,
        admission_result: str,
        *,
        reason: str,
        decision_policy: DecisionEffect,
        required_evidence: list[str] | None = None,
        retention_policy: str | None = None,
    ) -> ClaimAdmissionDecision:
        return ClaimAdmissionDecision(
            workspace_id=claim.workspace_id,
            claim_id=claim.claim_id,
            admission_result=admission_result,  # type: ignore[arg-type]
            reason=reason,
            required_evidence=required_evidence or [],
            decision_policy=decision_policy,
            memory_policy=claim.memory_policy,
            retention_policy=retention_policy or claim.retention_policy,
        )


class KnowledgeStateMachine:
    _forbidden: set[tuple[SupportStatus | str, KnowledgeState]] = {
        ("unsupported", "active"),
        ("not_found", "active"),
        ("contradicted", "active"),
        ("assistant_inference", "active"),
        ("user_denied", "active"),
        ("graph_fact", "active"),
        ("sensitive_without_decision", "active"),
    }

    def next_state(self, claim: Claim, decision: ClaimAdmissionDecision) -> KnowledgeState:
        if decision.admission_result == "reject":
            return "rejected"
        if decision.admission_result == "require_decision":
            return "verified" if claim.support_status in {"supported", "user_asserted"} else "grounded"
        if decision.admission_result == "keep_candidate":
            return "grounded" if claim.support_status in {"supported", "partially_supported", "user_asserted"} else "candidate"
        if decision.admission_result == "allow_active":
            self.assert_allowed(
                claim,
                "active",
                has_decision=decision.decision_policy != "ask_confirmation",
            )
            return "active"
        return "candidate"

    def assert_allowed(
        self,
        claim: Claim,
        to_state: KnowledgeState,
        *,
        has_decision: bool = False,
        denied_by_user: bool = False,
        from_graph_fact: bool = False,
    ) -> None:
        markers: list[SupportStatus | str] = [claim.support_status]
        markers.append(claim.claim_type)
        if denied_by_user:
            markers.append("user_denied")
        if from_graph_fact:
            markers.append("graph_fact")
        if claim.sensitivity_level == "high" and not has_decision:
            markers.append("sensitive_without_decision")
        for marker in markers:
            if (marker, to_state) in self._forbidden:
                raise ValueError(f"Illegal KnowledgeState transition: {marker} -> {to_state}")
