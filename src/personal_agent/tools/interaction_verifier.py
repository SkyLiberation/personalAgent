from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal
from uuid import uuid4

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.tools.base import governance_extras, tool_response, tool_success


class VerificationCriterionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion: str
    status: Literal["satisfied", "not_satisfied", "insufficient_evidence"]
    feedback: str = ""


class SemanticVerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str = Field(default_factory=lambda: f"svr_{uuid4().hex[:16]}")
    verdict: Literal["passed", "needs_revision", "insufficient_evidence"]
    criterion_results: tuple[VerificationCriterionResult, ...] = Field(min_length=1)
    revision_feedback: str = ""


class SemanticVerificationReceipt(SemanticVerificationReport):
    verified_draft: str = Field(min_length=1, max_length=20_000)
    draft_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    criteria_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class VerifyInteractionDraftArgs(BaseModel):
    draft: str = Field(min_length=1, max_length=20_000)
    success_criteria: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()


def build_verify_interaction_draft_tool(model_client: StructuredModelClient) -> BaseTool:
    @tool(
        "verify_interaction_draft",
        description=(
            "Use when the user asks to review, validate, or revise a draft against explicit success criteria. "
            "Evaluate only against caller-supplied criteria and visible evidence refs. Returns a typed "
            "SemanticVerificationReceipt; it cannot execute effects or mark completion."
        ),
        args_schema=VerifyInteractionDraftArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="low",
            side_effects=("none",),
            permission_scope="interaction:verify",
            timeout_seconds=60,
            max_retries=0,
            rate_limit_per_minute=20,
        ),
    )
    def verify_interaction_draft(
        draft: str,
        success_criteria: tuple[str, ...],
        evidence_refs: tuple[str, ...] = (),
    ):
        messages = [{
            "role": "system",
            "content": (
                "Evaluate the draft only against the supplied criteria and evidence refs. "
                "Do not invent criteria, execution facts, evidence, or completion. Return needs_revision "
                "when the draft itself contradicts a criterion or makes a claim that the criterion prohibits, "
                "even when evidence_refs is empty. In that case mark the criterion not_satisfied and provide "
                "concrete revision feedback. Distinguish a positive or presupposed assertion that an event "
                "occurred from a draft that makes no such assertion. When a criterion only prohibits claiming "
                "that an unobserved event occurred, a draft that omits the event, declines to confirm it, or "
                "states that it was not observed does not itself assert occurrence and must not be rejected for "
                "that reason. Return insufficient_evidence only when the draft and supplied "
                "evidence genuinely cannot determine whether the criterion is satisfied."
            ),
        }, {
            "role": "user",
            "content": (
                f"Draft:\n{draft}\n\nCriteria:\n" + "\n".join(success_criteria)
                + "\n\nEvidence refs:\n" + "\n".join(evidence_refs)
            ),
        }]
        response = model_client.generate(StructuredModelRequest(
            operation="interaction_semantic_verification",
            version="v2",
            messages=messages,
            output_type=SemanticVerificationReport,
            context_projection_ref=sealed_context_projection_ref(
                purpose="interaction_semantic_verification", messages=messages,
            ),
            max_tokens=1_200,
            temperature=0,
            metadata={"component": "interaction_verifier"},
        ))
        report = response.value
        criteria_payload = json.dumps(
            success_criteria,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        receipt = SemanticVerificationReceipt(
            **report.model_dump(mode="python"),
            verified_draft=draft.strip(),
            draft_digest=sha256(draft.strip().encode("utf-8")).hexdigest(),
            criteria_digest=sha256(criteria_payload.encode("utf-8")).hexdigest(),
        )
        return tool_response(tool_success(receipt.model_dump(mode="json")))

    return verify_interaction_draft


__all__ = [
    "SemanticVerificationReceipt", "SemanticVerificationReport",
    "VerificationCriterionResult",
    "VerifyInteractionDraftArgs", "build_verify_interaction_draft_tool",
]
