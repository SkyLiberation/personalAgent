from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.adapters.web.routes._shared import (
    resolve_requested_principal,
)
from personal_agent.application.knowledge import (
    Artifact,
    Claim,
    ClaimCorrectionResult,
    ConversationMessage,
    ConversationSolidifyResult,
    DecisionCard,
    GraphProjectionResult,
    IngestKnowledgeResult,
    KnowledgeGap,
    KnowledgeItem,
    KnowledgeRelation,
    KnowledgeStateEvent,
    ResearchEvent,
    ResearchIngestResult,
    ReviewItem,
    ReviewPlanResult,
    KnowledgeService,
)
from personal_agent.application.artifacts import ArtifactService
from personal_agent.application.capture import CaptureService
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.config import Settings


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IngestTextRequest(_StrictRequest):
    text: str
    user_id: str | None = None
    source_type: str = "text"
    source_ref: str | None = None
    raw_location: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class SolidifyConversationRequest(_StrictRequest):
    messages: list[ConversationMessage]
    user_id: str | None = None


class CorrectClaimRequest(_StrictRequest):
    corrected_statement: str
    user_id: str | None = None


class ResearchEventRequest(_StrictRequest):
    topic: str
    title: str
    summary: str
    user_id: str | None = None
    source_ref: str | None = None


class ResearchFeedbackRequest(_StrictRequest):
    negative_feedback_reason: str


class ReviewPlanRequest(_StrictRequest):
    user_id: str | None = None
    limit: int = 10


class GraphProjectionRequest(_StrictRequest):
    user_id: str | None = None
    limit: int = 100


class IngestUrlRequest(_StrictRequest):
    url: str
    user_id: str | None = None


class CapturedResourceResult(BaseModel):
    resource_ref: ResourceRef | None = None
    ingest_result: IngestKnowledgeResult


def register_knowledge_routes(
    app: FastAPI,
    *,
    settings: Settings,
    knowledge_service: KnowledgeService,
    artifact_service: ArtifactService,
    capture_service: CaptureService,
) -> None:
    @app.post("/api/knowledge/ingest-text", response_model=IngestKnowledgeResult)
    def ingest_text(body: IngestTextRequest, request: Request) -> IngestKnowledgeResult:
        principal = resolve_requested_principal(request, settings, body.user_id)
        return knowledge_service.ingest_text(
            body.text,
            user_id=principal.user_id,
            owner_id=principal.principal_id,
            source_type=body.source_type,
            source_ref=body.source_ref,
            raw_location=body.raw_location,
        )

    @app.post("/api/knowledge/ingest-upload", response_model=CapturedResourceResult)
    def ingest_upload(
        request: Request,
        file: UploadFile = File(...),
        user_id: str = Form("default"),
    ) -> CapturedResourceResult:
        principal = resolve_requested_principal(
            request,
            settings,
            None if user_id == "default" else user_id,
        )
        file_bytes = file.file.read()
        resource_ref = artifact_service.save_upload(
            filename=file.filename or "upload",
            content_type=file.content_type,
            file_bytes=file_bytes,
            uploads_dir=settings.data_dir / "uploads",
            principal=principal,
            owner=principal,
        )
        source_type = capture_service.source_type_from_upload(
            file.filename or "upload",
            file.content_type,
        )
        text = capture_service.capture_text_from_upload(
            file.filename or "upload",
            file.content_type,
            file_bytes,
            source_type,
        )
        ingest = knowledge_service.ingest_text(
            text,
            user_id=principal.user_id,
            owner_id=principal.principal_id,
            source_type=source_type,
            source_ref=resource_ref.resource_id,
            artifact_id=resource_ref.resource_id,
            artifact_metadata={
                "filename": file.filename or "upload",
                "content_type": file.content_type or "",
            },
        )
        return CapturedResourceResult(resource_ref=resource_ref, ingest_result=ingest)

    @app.post("/api/knowledge/ingest-url", response_model=CapturedResourceResult)
    def ingest_url(body: IngestUrlRequest, request: Request) -> CapturedResourceResult:
        principal = resolve_requested_principal(request, settings, body.user_id)
        text = capture_service.capture_text_from_url(body.url)
        ingest = knowledge_service.ingest_text(
            text,
            user_id=principal.user_id,
            owner_id=principal.principal_id,
            source_type="link",
            source_ref=body.url,
        )
        return CapturedResourceResult(ingest_result=ingest)

    @app.post("/api/knowledge/solidify-conversation", response_model=ConversationSolidifyResult)
    def solidify_conversation(
        body: SolidifyConversationRequest,
        request: Request,
    ) -> ConversationSolidifyResult:
        principal = resolve_requested_principal(request, settings, body.user_id)
        return knowledge_service.solidify_conversation(
            body.messages,
            user_id=principal.user_id,
            owner_id=principal.principal_id,
        )

    @app.post("/api/knowledge/claims/{claim_id}/correct", response_model=ClaimCorrectionResult)
    def correct_claim(
        claim_id: str,
        body: CorrectClaimRequest,
        request: Request,
    ) -> ClaimCorrectionResult:
        principal = resolve_requested_principal(request, settings, body.user_id)
        try:
            return knowledge_service.correct_claim(
                claim_id,
                body.corrected_statement,
                owner_id=principal.principal_id,
                user_id=principal.user_id,
            )
        except (KeyError, PermissionError):
            raise HTTPException(status_code=404, detail="Resource not found.") from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/knowledge/claims", response_model=list[Claim])
    def list_claims(
        request: Request,
        state: str | None = None,
        user_id: str | None = None,
    ) -> list[Claim]:
        principal = resolve_requested_principal(request, settings, user_id)
        return knowledge_service.store.list_claims(
            principal.principal_id,
            state=state,
            limit=200,
        )

    @app.get("/api/knowledge/relations", response_model=list[KnowledgeRelation])
    def list_relations(
        request: Request,
        source_id: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        user_id: str | None = None,
    ) -> list[KnowledgeRelation]:
        principal = resolve_requested_principal(request, settings, user_id)
        return knowledge_service.store.list_knowledge_relations(
            principal.principal_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            limit=200,
        )

    @app.get("/api/knowledge/state-events", response_model=list[KnowledgeStateEvent])
    def list_state_events(
        request: Request,
        target_id: str | None = None,
        user_id: str | None = None,
    ) -> list[KnowledgeStateEvent]:
        principal = resolve_requested_principal(request, settings, user_id)
        return knowledge_service.store.list_knowledge_state_events(
            principal.principal_id,
            target_id=target_id,
            limit=200,
        )

    @app.get("/api/knowledge/knowledge-items", response_model=list[KnowledgeItem])
    def list_knowledge_items(
        request: Request,
        state: str | None = None,
        user_id: str | None = None,
    ) -> list[KnowledgeItem]:
        principal = resolve_requested_principal(request, settings, user_id)
        return knowledge_service.store.list_knowledge_items(
            principal.principal_id,
            state=state,
            limit=200,
        )

    @app.get("/api/knowledge/artifacts", response_model=list[Artifact])
    def list_artifacts(
        request: Request,
        source_type: str | None = None,
        user_id: str | None = None,
    ) -> list[Artifact]:
        principal = resolve_requested_principal(request, settings, user_id)
        return knowledge_service.store.list_artifacts(
            principal.principal_id,
            source_type=source_type,
            limit=200,
        )

    @app.get("/api/knowledge/decisions", response_model=list[DecisionCard])
    def list_decisions(
        request: Request,
        status: str | None = None,
        user_id: str | None = None,
    ) -> list[DecisionCard]:
        principal = resolve_requested_principal(request, settings, user_id)
        return knowledge_service.store.list_decisions(
            principal.principal_id,
            status=status,
            limit=200,
        )

    @app.post("/api/knowledge/research-events", response_model=ResearchIngestResult)
    def ingest_research_event(
        body: ResearchEventRequest,
        request: Request,
    ) -> ResearchIngestResult:
        principal = resolve_requested_principal(request, settings, body.user_id)
        return knowledge_service.ingest_research_event(
            topic=body.topic,
            title=body.title,
            summary=body.summary,
            user_id=principal.user_id,
            owner_id=principal.principal_id,
            source_ref=body.source_ref,
        )

    @app.post("/api/knowledge/research-events/{research_event_id}/feedback", response_model=ResearchEvent)
    def submit_research_feedback(
        research_event_id: str,
        body: ResearchFeedbackRequest,
    ) -> ResearchEvent:
        return knowledge_service.submit_research_feedback(
            research_event_id,
            negative_feedback_reason=body.negative_feedback_reason,
        )

    @app.get("/api/knowledge/research-events", response_model=list[ResearchEvent])
    def list_research_events(
        request: Request,
        user_id: str | None = None,
    ) -> list[ResearchEvent]:
        principal = resolve_requested_principal(request, settings, user_id)
        return knowledge_service.store.list_research_events(principal.principal_id, limit=200)

    @app.post("/api/knowledge/review-plan", response_model=ReviewPlanResult)
    def plan_review_and_gaps(body: ReviewPlanRequest, request: Request) -> ReviewPlanResult:
        principal = resolve_requested_principal(request, settings, body.user_id)
        return knowledge_service.plan_review_and_gaps(
            owner_id=principal.principal_id,
            limit=body.limit,
        )

    @app.get("/api/knowledge/review-items", response_model=list[ReviewItem])
    def list_review_items(
        request: Request,
        state: str | None = None,
        user_id: str | None = None,
    ) -> list[ReviewItem]:
        principal = resolve_requested_principal(request, settings, user_id)
        return knowledge_service.store.list_review_items(
            principal.principal_id,
            state=state,
            limit=200,
        )

    @app.get("/api/knowledge/knowledge-gaps", response_model=list[KnowledgeGap])
    def list_knowledge_gaps(
        request: Request,
        state: str | None = None,
        user_id: str | None = None,
    ) -> list[KnowledgeGap]:
        principal = resolve_requested_principal(request, settings, user_id)
        return knowledge_service.store.list_knowledge_gaps(
            principal.principal_id,
            state=state,
            limit=200,
        )

    @app.post("/api/knowledge/graph-projections", response_model=GraphProjectionResult)
    def project_knowledge_graph(
        body: GraphProjectionRequest,
        request: Request,
    ) -> GraphProjectionResult:
        principal = resolve_requested_principal(request, settings, body.user_id)
        return knowledge_service.project_knowledge_graph(
            owner_id=principal.principal_id,
            limit=body.limit,
        )
