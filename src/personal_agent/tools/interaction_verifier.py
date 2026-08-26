from __future__ import annotations

from hashlib import sha256
import json

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.capabilities.contracts.verification import (
    SemanticVerificationReceipt,
    SemanticVerificationReport,
)
from personal_agent.tools.base import governance_extras, tool_response, tool_success


_VERIFICATION_INSTRUCTION = (
    "Evaluate the draft only against the supplied criteria and evidence refs. "
    "Evidence refs are an allowed evidence inventory, not additional criteria: the draft need not "
    "cite or discuss every ref, and refs must not be used to infer hidden plan items, broaden scope, "
    "or add requirements. Use a ref only to check a claim or source that the draft actually makes. "
    "When a criterion requires an official or specifically named source and the evidence inventory "
    "contains a matching ref, compare the draft's cited identity and URL with that ref. A different "
    "project or URL, a placeholder, or wording such as 'needs confirmation' or 'or the official "
    "source' does not satisfy the criterion merely because the draft labels it official. "
    "Return exactly one criterion_result for every supplied criterion, copy each criterion string "
    "exactly, and return no result for any other criterion. Never omit a criterion, even when the "
    "overall verdict is needs_revision or insufficient_evidence. "
    "Do not invent criteria, execution facts, evidence, or completion. Mark a criterion not_satisfied "
    "when the draft itself contradicts a criterion or makes a claim that the criterion prohibits, "
    "even when evidence_refs is empty. In that case mark the criterion not_satisfied and provide "
    "concrete revision feedback. Distinguish a positive or presupposed assertion that an event "
    "occurred from a draft that makes no such assertion. When a criterion only prohibits claiming "
    "that an unobserved event occurred, a draft that omits the event, declines to confirm it, or "
    "states that it was not observed does not itself assert occurrence and must not be rejected for "
    "that reason. Use insufficient_evidence only when the draft and supplied evidence genuinely "
    "cannot determine whether the criterion is satisfied. When a criterion applies to every, each, "
    "or per-item entry, enumerate every relevant entry and evaluate it independently; a URL, source, "
    "or validation condition attached to one entry cannot satisfy another entry. Treat a URL as "
    "invalid when it contains whitespace, lacks a scheme or host, or is split into separate tokens; "
    "do not silently repair an invalid URL while judging the submitted draft."
)


class VerifyInteractionDraftArgs(BaseModel):
    draft: str = Field(min_length=1, max_length=20_000)
    success_criteria: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()


def build_verify_interaction_draft_tool(model_client: StructuredModelClient) -> BaseTool:
    @tool(
        "verify_interaction_draft",
        description=(
            "Runtime-invoked semantic verification of an interaction draft against runtime-derived "
            "success criteria. Evaluate only against caller-supplied criteria and visible evidence refs. "
            "Returns a typed SemanticVerificationReceipt; it cannot execute effects or mark completion. "
            "Not exposed to the semantic decision maker: the interaction runtime decides when a draft is "
            "verified, so the model can neither skip verification nor author the criteria it is judged by."
        ),
        args_schema=VerifyInteractionDraftArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            risk_level="low",
            side_effects=("none",),
            permission_scope="interaction:verify",
            timeout_seconds=60,
            max_retries=0,
            rate_limit_per_minute=20,
            emits_verified_artifact=True,
        ),
    )
    def verify_interaction_draft(
        draft: str,
        success_criteria: tuple[str, ...],
        evidence_refs: tuple[str, ...] = (),
    ):
        messages = [{
            "role": "system",
            "content": _VERIFICATION_INSTRUCTION,
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
        reported_criteria = tuple(
            result.criterion for result in report.criterion_results
        )
        if (
            len(reported_criteria) != len(success_criteria)
            or set(reported_criteria) != set(success_criteria)
        ):
            raise ValueError(
                "semantic verifier must return exactly one result for every criterion"
            )
        statuses = tuple(result.status for result in report.criterion_results)
        if "not_satisfied" in statuses:
            verdict = "needs_revision"
        elif "insufficient_evidence" in statuses:
            verdict = "insufficient_evidence"
        else:
            verdict = "passed"
        if verdict == "needs_revision" and not report.revision_feedback.strip():
            raise ValueError(
                "semantic verifier must provide revision feedback for unmet criteria"
            )
        criteria_payload = json.dumps(
            success_criteria,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        normalized_draft = draft.strip()
        draft_digest = sha256(normalized_draft.encode("utf-8")).hexdigest()
        receipt = SemanticVerificationReceipt(
            **report.model_dump(mode="python"),
            verdict=verdict,
            receipt_id=f"svr_{draft_digest[:20]}",
            verified_draft=normalized_draft,
            draft_digest=draft_digest,
            success_criteria=tuple(success_criteria),
            criteria_digest=sha256(criteria_payload.encode("utf-8")).hexdigest(),
        )
        return tool_response(tool_success(receipt.model_dump(mode="json")))

    return verify_interaction_draft


__all__ = [
    "SemanticVerificationReceipt", "SemanticVerificationReport",
    "VerifyInteractionDraftArgs", "build_verify_interaction_draft_tool",
]
