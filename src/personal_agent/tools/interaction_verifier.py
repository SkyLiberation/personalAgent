from __future__ import annotations

from hashlib import sha256
import json

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent.capabilities.contracts.model import (
    StructuredModelClient,
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.capabilities.contracts.research import ResearchBasis, ResearchFinalReport
from personal_agent.capabilities.contracts.verification import (
    ConversationAnswerSegment,
    CitedDraftUnit,
    CitedSupportRejection,
    OverreachReport,
    SemanticVerificationReceipt,
    SemanticVerificationReport,
    SourceReadingState,
)
from personal_agent.kernel.prompts import get_prompt
from personal_agent.tools.base import ToolArtifact, governance_extras, tool_response, tool_success


class VerifyInteractionDraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: str = Field(min_length=1, max_length=20_000)
    success_criteria: tuple[str, ...] = Field(min_length=1)
    cited_units: tuple[CitedDraftUnit, ...] = ()
    source_reading_state: tuple[SourceReadingState, ...] = ()
    research_basis: ResearchBasis | None = None
    research_segments: tuple[ConversationAnswerSegment, ...] = ()

    @model_validator(mode="after")
    def check_draft_coverage(self):
        if self.research_basis is not None:
            if not self.research_segments or self.cited_units or self.source_reading_state:
                raise ValueError("research final verification requires only claim-bound segments")
            if "".join(segment.text for segment in self.research_segments) != self.draft:
                raise ValueError("research segments must preserve the entire exact draft")
        elif self.research_segments:
            raise ValueError("research segments require a verified research basis")
        if self.cited_units and "".join(unit.draft for unit in self.cited_units) != self.draft:
            raise ValueError("cited units must preserve the entire exact draft in order")
        for unit in self.cited_units:
            ids = [evidence.id for evidence in unit.execution_evidence]
            if len(ids) != len(set(ids)):
                raise ValueError("cited evidence ids must be unique within their unit")
        return self


def build_verify_interaction_draft_tool(model_client: StructuredModelClient) -> BaseTool:
    @tool(
        "verify_interaction_draft",
        description=(
            "Runtime-invoked semantic verification of an interaction draft against runtime-derived "
            "success criteria plus a mandatory source-support criterion, using visible evidence. "
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
            timeout_seconds=480,
            max_retries=0,
            rate_limit_per_minute=20,
            emits_verified_artifact=True,
        ),
    )
    def verify_interaction_draft(
        draft: str,
        success_criteria: tuple[str, ...],
        cited_units: tuple[CitedDraftUnit, ...] = (),
        source_reading_state: tuple[SourceReadingState, ...] = (),
        research_basis: ResearchBasis | None = None,
        research_segments: tuple[ConversationAnswerSegment, ...] = (),
    ):
        prompt = get_prompt("conversation.research.final_verification" if research_basis is not None
                            else "interaction_verification.system")
        support_prompt = get_prompt("conversation.research.faithfulness" if research_basis is not None
                                    else "interaction_verification.source_support")
        verification_criteria = tuple(dict.fromkeys((
            *success_criteria, support_prompt.template,
        )))
        verification_input = VerifyInteractionDraftArgs(
            draft=draft,
            success_criteria=verification_criteria,
            cited_units=cited_units,
            source_reading_state=source_reading_state,
            research_basis=research_basis,
            research_segments=research_segments,
        )
        units = verification_input.cited_units or (CitedDraftUnit(draft=draft),)
        # Only writer-submitted evidence reaches either semantic consumer.
        verification_payload = {
            "draft": draft,
            "success_criteria": list(verification_criteria),
            "execution_evidence": [
                evidence.model_dump(mode="json", exclude={"id"})
                for unit in units for evidence in unit.execution_evidence
            ],
            "source_reading_state": [
                state.model_dump(mode="json") for state in verification_input.source_reading_state
            ],
        }
        if verification_input.research_basis is not None:
            verification_payload = {
                "draft": draft,
                "success_criteria": list(verification_criteria),
                "research_basis": verification_input.research_basis.model_dump(mode="json"),
                "segments": [segment.model_dump(mode="json") for segment in verification_input.research_segments],
            }
        cited_prompt = get_prompt("interaction_verification.cited_support")
        for unit in units if verification_input.research_basis is None else ():
            if not unit.draft.strip():
                continue
            cited_messages = [
                {"role": "system", "content": cited_prompt.template},
                {"role": "user", "content": unit.model_dump_json()},
            ]
            support = model_client.generate(StructuredModelRequest(
                operation="interaction_cited_support",
                version=cited_prompt.version,
                messages=cited_messages,
                output_type=OverreachReport,
                context_projection_ref=sealed_context_projection_ref(
                    purpose="interaction_cited_support", messages=cited_messages,
                ),
                max_tokens=32_768,
                temperature=0,
                metadata={"component": "interaction_verifier"},
            )).value
            valid_ids = {evidence.id for evidence in unit.execution_evidence}
            for finding in support.findings:
                if len(set(finding.evidence_ids)) != len(finding.evidence_ids) or not set(finding.evidence_ids).issubset(valid_ids):
                    raise ValueError("support finding must reference only submitted evidence")
            if support.findings:
                rejection = CitedSupportRejection(
                    rejected_draft=draft, checked_draft=unit.draft, findings=support.findings,
                )
                return tool_response(ToolArtifact(
                    ok=False, data=rejection.model_dump(mode="json"),
                    error=rejection.explanation, error_kind="unrecoverable",
                ))
        messages = [{
            "role": "system",
            "content": prompt.template,
        }, {
            "role": "user",
            "content": json.dumps(verification_payload, ensure_ascii=False),
        }]
        response = model_client.generate(StructuredModelRequest(
            operation="interaction_semantic_verification",
            version=prompt.version,
            messages=messages,
            output_type=ResearchFinalReport if verification_input.research_basis is not None else SemanticVerificationReport,
            context_projection_ref=sealed_context_projection_ref(
                purpose="interaction_semantic_verification", messages=messages,
            ),
            max_tokens=32_768,
            temperature=0,
            metadata={
                "component": "interaction_verifier",
                "source_support_prompt_version": support_prompt.version,
            },
        ))
        report = response.value
        reported_criteria = tuple(
            result.criterion for result in report.criterion_results
        )
        if (
            len(reported_criteria) != len(verification_criteria)
            or set(reported_criteria) != set(verification_criteria)
        ):
            raise ValueError(
                "semantic verifier must return exactly one result for every criterion"
            )
        statuses = tuple(result.status for result in report.criterion_results)
        verdict = (
            "passed"
            if all(status == "satisfied" for status in statuses)
            else "failed"
        )
        if verdict == "failed" and not report.revision_feedback.strip():
            derived_feedback = "\n".join(
                f"{result.criterion}: {result.feedback.strip()}"
                for result in report.criterion_results
                if result.status != "satisfied" and result.feedback.strip()
            )
            if not derived_feedback:
                raise ValueError(
                    "semantic verifier must provide feedback for failed criteria"
                )
            report = report.model_copy(update={
                "revision_feedback": derived_feedback,
            })
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
            research_ref=(verification_input.research_basis.claims.resource_ref
                          if verification_input.research_basis is not None else None),
        )
        return tool_response(tool_success(receipt.model_dump(mode="json")))

    return verify_interaction_draft


__all__ = [
    "SemanticVerificationReceipt", "SemanticVerificationReport",
    "VerifyInteractionDraftArgs", "build_verify_interaction_draft_tool",
]
