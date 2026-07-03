from __future__ import annotations

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from personal_agent.adapters.web.routes._shared import resolve_user_id
from personal_agent.application.workspace import (
    Claim,
    ClaimCorrectionResult,
    ConversationMessage,
    ConversationSolidifyResult,
    DecisionCard,
    EvidenceGroundedAnswer,
    GraphProjectionResult,
    IngestKnowledgeResult,
    KnowledgeGap,
    KnowledgeItem,
    KnowledgeRelation,
    ResearchEvent,
    ResearchIngestResult,
    ReviewItem,
    ReviewPlanResult,
    WorkspaceService,
)
from personal_agent.kernel.config import Settings


class IngestTextRequest(BaseModel):
    text: str
    user_id: str | None = None
    workspace_id: str = "default"
    source_type: str = "text"
    source_ref: str | None = None
    raw_location: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class AskWorkspaceRequest(BaseModel):
    question: str
    workspace_id: str = "default"
    limit: int = 5


class SolidifyConversationRequest(BaseModel):
    messages: list[ConversationMessage]
    user_id: str | None = None
    workspace_id: str = "default"


class CorrectClaimRequest(BaseModel):
    corrected_statement: str
    user_id: str | None = None


class ResearchEventRequest(BaseModel):
    topic: str
    title: str
    summary: str
    user_id: str | None = None
    workspace_id: str = "default"
    source_ref: str | None = None


class ResearchFeedbackRequest(BaseModel):
    negative_feedback_reason: str


class ReviewPlanRequest(BaseModel):
    workspace_id: str = "default"
    limit: int = 10


class GraphProjectionRequest(BaseModel):
    workspace_id: str = "default"
    limit: int = 100


def register_workspace_routes(
    app: FastAPI,
    *,
    settings: Settings,
    workspace_service: WorkspaceService,
) -> None:
    @app.post("/api/workspace/ingest-text", response_model=IngestKnowledgeResult)
    def ingest_text(body: IngestTextRequest, request: Request) -> IngestKnowledgeResult:
        user_id = body.user_id or resolve_user_id(request, settings)
        return workspace_service.ingest_text(
            body.text,
            user_id=user_id,
            workspace_id=body.workspace_id,
            source_type=body.source_type,
            source_ref=body.source_ref,
            raw_location=body.raw_location,
        )

    @app.post("/api/workspace/ask", response_model=EvidenceGroundedAnswer)
    def ask_workspace(body: AskWorkspaceRequest) -> EvidenceGroundedAnswer:
        return workspace_service.answer_with_evidence(
            body.question,
            workspace_id=body.workspace_id,
            limit=body.limit,
        )

    @app.post("/api/workspace/solidify-conversation", response_model=ConversationSolidifyResult)
    def solidify_conversation(
        body: SolidifyConversationRequest,
        request: Request,
    ) -> ConversationSolidifyResult:
        user_id = body.user_id or resolve_user_id(request, settings)
        return workspace_service.solidify_conversation(
            body.messages,
            user_id=user_id,
            workspace_id=body.workspace_id,
        )

    @app.post("/api/workspace/claims/{claim_id}/correct", response_model=ClaimCorrectionResult)
    def correct_claim(
        claim_id: str,
        body: CorrectClaimRequest,
        request: Request,
    ) -> ClaimCorrectionResult:
        user_id = body.user_id or resolve_user_id(request, settings)
        return workspace_service.correct_claim(
            claim_id,
            body.corrected_statement,
            user_id=user_id,
        )

    @app.get("/api/workspace/claims", response_model=list[Claim])
    def list_claims(workspace_id: str = "default", state: str | None = None) -> list[Claim]:
        return workspace_service.store.list_claims(workspace_id, state=state, limit=200)

    @app.get("/api/workspace/relations", response_model=list[KnowledgeRelation])
    def list_relations(
        workspace_id: str = "default",
        source_id: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
    ) -> list[KnowledgeRelation]:
        return workspace_service.store.list_knowledge_relations(
            workspace_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            limit=200,
        )

    @app.get("/api/workspace/knowledge-items", response_model=list[KnowledgeItem])
    def list_knowledge_items(workspace_id: str = "default", state: str | None = None) -> list[KnowledgeItem]:
        return workspace_service.store.list_knowledge_items(workspace_id, state=state, limit=200)

    @app.get("/api/workspace/decisions", response_model=list[DecisionCard])
    def list_decisions(workspace_id: str = "default", status: str | None = None) -> list[DecisionCard]:
        return workspace_service.store.list_decisions(workspace_id, status=status, limit=200)

    @app.post("/api/workspace/research-events", response_model=ResearchIngestResult)
    def ingest_research_event(
        body: ResearchEventRequest,
        request: Request,
    ) -> ResearchIngestResult:
        user_id = body.user_id or resolve_user_id(request, settings)
        return workspace_service.ingest_research_event(
            topic=body.topic,
            title=body.title,
            summary=body.summary,
            user_id=user_id,
            workspace_id=body.workspace_id,
            source_ref=body.source_ref,
        )

    @app.post("/api/workspace/research-events/{research_event_id}/feedback", response_model=ResearchEvent)
    def submit_research_feedback(
        research_event_id: str,
        body: ResearchFeedbackRequest,
    ) -> ResearchEvent:
        return workspace_service.submit_research_feedback(
            research_event_id,
            negative_feedback_reason=body.negative_feedback_reason,
        )

    @app.get("/api/workspace/research-events", response_model=list[ResearchEvent])
    def list_research_events(workspace_id: str = "default") -> list[ResearchEvent]:
        return workspace_service.store.list_research_events(workspace_id, limit=200)

    @app.post("/api/workspace/review-plan", response_model=ReviewPlanResult)
    def plan_review_and_gaps(body: ReviewPlanRequest) -> ReviewPlanResult:
        return workspace_service.plan_review_and_gaps(
            workspace_id=body.workspace_id,
            limit=body.limit,
        )

    @app.get("/api/workspace/review-items", response_model=list[ReviewItem])
    def list_review_items(workspace_id: str = "default", state: str | None = None) -> list[ReviewItem]:
        return workspace_service.store.list_review_items(workspace_id, state=state, limit=200)

    @app.get("/api/workspace/knowledge-gaps", response_model=list[KnowledgeGap])
    def list_knowledge_gaps(workspace_id: str = "default", state: str | None = None) -> list[KnowledgeGap]:
        return workspace_service.store.list_knowledge_gaps(workspace_id, state=state, limit=200)

    @app.post("/api/workspace/graph-projections", response_model=GraphProjectionResult)
    def project_knowledge_graph(body: GraphProjectionRequest) -> GraphProjectionResult:
        return workspace_service.project_knowledge_graph(
            workspace_id=body.workspace_id,
            limit=body.limit,
        )
