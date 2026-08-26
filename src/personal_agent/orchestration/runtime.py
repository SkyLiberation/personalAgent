from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING

from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal
from personal_agent.kernel.langsmith_tracing import configure_langsmith_environment
from personal_agent.kernel.models import (
    KnowledgeNote,
    NoteBody,
    NoteSource,
    ReviewCard,
)
from personal_agent.kernel.observability import set_policy_decision_sink
from personal_agent.infra.structured_model import build_structured_model_client
from personal_agent.memory.graphiti.store import GraphitiStore
from personal_agent.memory import MemoryFacade
from personal_agent.application.knowledge import KnowledgeConsolidationUseCase
from personal_agent.application.insight import KnowledgeGapAnalyzer, KnowledgeGapUseCase
from personal_agent.governance.policy import PolicyEngine, PolicyRules
from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
from personal_agent.infra.storage.postgres_research_store import PostgresResearchStore
from personal_agent.infra.storage.postgres_tool_governance_store import (
    PostgresToolGovernanceStore,
)
from personal_agent.infra.storage.postgres_worker_queue_store import (
    PostgresWorkerQueueStore,
)
from personal_agent.infra.storage.postgres_knowledge_store import PostgresKnowledgeStore
from personal_agent.infra.storage.postgres_knowledge_lifecycle_store import (
    PostgresKnowledgeLifecycleStore,
)
from personal_agent.infra.storage.postgres_procedure_definition_store import (
    PostgresProcedureDefinitionStore,
)
from personal_agent.infra.storage.postgres_agent_trace_store import (
    PostgresAgentTraceStore,
)
from personal_agent.infra.storage.postgres_execution_replay_store import (
    PostgresExecutionReplayStore,
)
from personal_agent.infra.storage.postgres_investigation_project import (
    PostgresInvestigationProjectStore,
)
from personal_agent.infra.storage.postgres_agent_run_store import PostgresAgentRunStore
from personal_agent.memory.structural_retriever import StructuralRetrieverStore
from personal_agent.governance import ToolExecutor
from personal_agent.tools import (
    build_capture_text_tool,
    build_capture_upload_tool,
    build_capture_url_tool,
    build_consolidate_knowledge_tool,
    build_enterprise_knowledge_search_tool,
    build_graph_search_tool,
    build_inspect_artifact_tool,
    build_inspect_knowledge_gaps_tool,
    build_verify_interaction_draft_tool,
    build_list_recent_notes_tool,
    build_get_note_tool,
    build_find_similar_notes_tool,
    build_update_note_tool,
    build_supersede_note_tool,
    build_mark_note_deprecated_tool,
    build_mark_notes_conflicted_tool,
    build_mcp_tools,
    build_raw_wiki_search_tools,
    build_inspect_worker_queue_tool,
    build_retry_worker_task_tool,
    build_review_digest_tool,
    build_create_research_subscription_tool,
    build_research_initialize_state_tool,
    build_research_prepare_run_tool,
    build_research_run_loop_tool,
    build_research_synthesize_digest_tool,
    build_research_verify_digest_tool,
    build_list_research_subscriptions_tool,
    build_update_research_subscription_tool,
    build_pause_research_subscription_tool,
    build_resume_research_subscription_tool,
    build_run_research_subscription_now_tool,
    build_list_research_runs_tool,
    build_get_research_digest_tool,
    build_submit_research_feedback_tool,
    build_save_research_event_tool,
    build_web_search_tool,
)
from personal_agent.agents import AgentGateway, GPTResearcherA2AAdapter
from personal_agent.planning.step_projection_validator import StepProjectionValidator
from personal_agent.runtime.procedure_runtime import (
    PROCEDURE_CATALOG,
    ProcedureMaterializer,
    ProcedureRuntime,
)
from personal_agent.capabilities.inventory import (
    A2AAssemblyDefinition,
)
from personal_agent.application.artifacts import ArtifactService
from personal_agent.application.investigation_project import (
    CreateInvestigationProject,
    InvestigationProjectService,
    QueryInvestigationProject,
    SteerInvestigationProject,
    StructuredExecutionProposer,
    StructuredInvestigationPlanner,
    StructuredProjectSynthesis,
    StructuredProjectVerifier,
    UnavailableInvestigationModelPorts,
)
from personal_agent.orchestration.investigation_project_adapters import (
    DurableProjectAgentAdapter,
    PolicyEngineDelegationAdapter,
    RuntimeCapabilitySnapshot,
    ScopeBoundDisclosureManifest,
    ToolExecutorProjectAdapter,
)
from personal_agent.application.capture.ingestion_pipeline import IngestionPipeline
from personal_agent.application.conversation import (
    ConversationService,
    FileInteractionJournal,
    LoopBudgetPolicy,
)
from personal_agent.application.conversation.models import (
    ConversationProjectSnapshot,
    InvestigationRequirementProgress,
    InvestigationSubgoalProgress,
    ProjectReference,
    StartDurableInvestigationArguments,
    SteerInvestigationProjectArguments,
    PersonalKnowledgeCandidate,
    PersonalKnowledgeEvidenceCitation,
    PersonalKnowledgeEvidenceSnapshot,
)
from personal_agent.domain.investigation_project import UserRequirement
from personal_agent.orchestration.runtime_admin import _protected_eval_graph_group_ids
from personal_agent.orchestration.capability_inventory import (
    build_runtime_capability_inventory,
)
from personal_agent.orchestration.runtime_helpers import (
    _annotate_answer,
    _evidence_content,
    _extract_question_keywords,
    _format_graph_relation,
    _graph_episode_uuids,
    _graph_fact_lines,
    _graph_facts_by_episode,
    _merge_citations,
    _merge_notes,
    _split_sentences,
    _tokenize_for_overlap,
    _top_sentences,
)
from personal_agent.infra.runtime_llm import LlmClient
from personal_agent.application.runtime_results import (
    CaptureResult,
    DigestResult,
    ResetResult,
)
from personal_agent.application.review import DigestFormatter, ReviewDigestUseCase
from personal_agent.application.knowledge_lifecycle import KnowledgeLifecycleService
from personal_agent.application.research import (
    ResearchLimits,
    ResearchFeedback,
    ResearchService,
    ResearchSubscriptionRecord,
)
from personal_agent.application.knowledge import (
    IngestKnowledgeResult,
    LLMClaimGroundingJudge,
    LLMClaimRelationJudge,
    LLMSemanticClaimExtractor,
    LLMSemanticEvidenceExtractor,
    KnowledgeService,
)
from personal_agent.application.research.extraction import (
    StructuredResearchEventExtractor,
)
from personal_agent.infra.storage.postgres_debug_reset_store import (
    PostgresDebugResetStore,
    clear_upload_files,
)
from personal_agent.application.verifier import create_answer_verifier

if TYPE_CHECKING:
    from personal_agent.application.capture import CaptureService

logger = logging.getLogger(__name__)


class _KnowledgeJsonResult:
    def __init__(
        self, payload: dict[str, object], *, ok: bool = True, error: str = ""
    ) -> None:
        self.ok = ok
        self.error = error
        self._payload = payload

    def model_dump(self, mode: str = "python") -> dict[str, object]:
        return dict(self._payload)


class _KnowledgeConsolidationAdapter:
    def __init__(self, runtime: "AgentRuntime") -> None:
        self._runtime = runtime

    def execute(self, *, topic: str, user_id: str = "default") -> _KnowledgeJsonResult:
        return _KnowledgeJsonResult(
            self._runtime.execute_consolidate(topic=topic, user_id=user_id)
        )


class _KnowledgeGapReport:
    def __init__(self, *, text: str, gaps: list[dict[str, object]]) -> None:
        self.text = text
        self.gaps = gaps


class _KnowledgeGapAdapter:
    def __init__(self, runtime: "AgentRuntime") -> None:
        self._runtime = runtime

    def inspect(self, user_id: str) -> _KnowledgeGapReport:
        result = self._runtime.knowledge_service.plan_review_and_gaps(
            owner_id=self._runtime._owner_id(user_id),
            limit=self._runtime.settings.knowledge_gap.max_gaps_per_run,
        )
        gaps = [gap.model_dump(mode="json") for gap in result.knowledge_gaps]
        if gaps:
            text = "\n".join(f"- {gap['question']}" for gap in gaps)
        else:
            text = "当前个人知识库 没有发现需要立即处理的知识缺口。"
        return _KnowledgeGapReport(text=text, gaps=gaps)


class _KnowledgeDigest:
    def __init__(
        self,
        *,
        text: str,
        recent_notes: list[KnowledgeNote],
        due_cards: list[ReviewCard],
        sections: list[dict[str, object]],
    ) -> None:
        self.text = text
        self.recent_notes = recent_notes
        self.due_cards = due_cards
        self.sections = sections


class _KnowledgeReviewDigestAdapter:
    formatter: "_KnowledgeReviewDigestAdapter"

    def __init__(self, runtime: "AgentRuntime") -> None:
        self._runtime = runtime
        self.formatter = self

    def generate(self, user_id: str) -> _KnowledgeDigest:
        return self._runtime._knowledge_digest(user_id)

    def to_text(self, digest: _KnowledgeDigest) -> str:
        return digest.text


class _ConversationKnowledgeReadAdapter:
    def __init__(self, knowledge_service: KnowledgeService) -> None:
        self._knowledge_service = knowledge_service

    def list_personal_knowledge(
        self,
        *,
        owner_id: str,
        user_id: str,
        limit: int,
    ) -> tuple[PersonalKnowledgeCandidate, ...]:
        items = self._knowledge_service.store.list_knowledge_items(
            owner_id,
            limit=500,
        )
        visible = tuple(
            PersonalKnowledgeCandidate(
                knowledge_item_id=item.knowledge_item_id,
                title=item.title,
                summary=item.summary,
                state=item.state,
            )
            for item in items
            if item.user_id == user_id and item.state not in {"deleted", "deprecated"}
        )
        return visible[:limit]

    def select_personal_evidence(
        self,
        *,
        question: str,
        owner_id: str,
        user_id: str,
        limit: int,
    ) -> PersonalKnowledgeEvidenceSnapshot:
        selection = self._knowledge_service.select_evidence(
            question,
            owner_id=owner_id,
            limit=limit,
        )
        return PersonalKnowledgeEvidenceSnapshot(
            question=selection.question,
            citations=tuple(
                PersonalKnowledgeEvidenceCitation(
                    evidence_span_id=item.evidence_span_id,
                    quote=item.quote,
                    locator=item.locator,
                    claim_ids=tuple(item.claim_ids),
                )
                for item in selection.citations
            ),
            claim_summaries=tuple(
                item.statement for item in selection.selected_claims
            ),
            conflicted_claim_ids=tuple(selection.conflicted_claim_ids),
            potential_conflicted_claim_ids=tuple(
                selection.potential_conflicted_claim_ids
            ),
            reason=selection.reason,
        )


class _ConversationProjectAdapter:
    def __init__(self, project_service: InvestigationProjectService) -> None:
        self._project_service = project_service

    def start(
        self,
        *,
        principal,
        owner,
        request: StartDurableInvestigationArguments,
        idempotency_key: str,
    ) -> ProjectReference:
        view = self._project_service.create(
            CreateInvestigationProject(
                principal=principal,
                title=request.title,
                goal=request.goal,
                requirements=tuple(
                    UserRequirement(
                        requirement_id=f"req-{index}",
                        statement=requirement.statement,
                        acceptance_contract=requirement.acceptance_contract,
                    )
                    for index, requirement in enumerate(request.requirements, start=1)
                ),
                idempotency_key=idempotency_key,
            )
        )
        return ProjectReference(
            project_id=view.definition.project_id,
            tenant_id=view.definition.principal.tenant_id,
            user_id=view.definition.principal.user_id,
            state=view.state,
            title=view.definition.title,
            goal=view.definition.goal,
        )

    def get(self, *, principal, reference) -> ConversationProjectSnapshot:
        view = self._project_service.get(QueryInvestigationProject(
            principal=principal,
            project_id=reference.project_id,
        ))
        return self._snapshot(view)

    def steer(
        self,
        *,
        principal,
        reference,
        request: SteerInvestigationProjectArguments,
        idempotency_key: str,
    ) -> ConversationProjectSnapshot:
        current = self._project_service.get(QueryInvestigationProject(
            principal=principal,
            project_id=reference.project_id,
        ))
        if current.accepted_plan is None:
            raise ValueError("durable investigation has no accepted plan yet")
        updated = self._project_service.steer(SteerInvestigationProject(
            principal=principal,
            project_id=reference.project_id,
            expected_plan_version=current.accepted_plan.plan_version,
            statement=request.statement,
            waived_requirement_ids=request.waived_requirement_ids,
            added_requirements=tuple(
                UserRequirement(
                    requirement_id=(
                        "req-conversation-"
                        f"{idempotency_key[:10]}-{index}"
                    ),
                    statement=item.statement,
                    acceptance_contract=item.acceptance_contract,
                )
                for index, item in enumerate(request.added_requirements, start=1)
            ),
            idempotency_key=idempotency_key,
        ))
        return self._snapshot(updated)

    @staticmethod
    def _snapshot(view) -> ConversationProjectSnapshot:
        completed = {item.logical_subgoal_id for item in view.outcomes}
        plan = view.accepted_plan
        return ConversationProjectSnapshot(
            project_id=view.definition.project_id,
            state=view.state,
            title=view.definition.title,
            goal=view.definition.goal,
            plan_version=plan.plan_version if plan is not None else None,
            requirements=tuple(
                InvestigationRequirementProgress(
                    requirement_id=item.requirement_id,
                    statement=item.statement,
                    acceptance_contract=item.acceptance_contract,
                    status=item.status,
                )
                for item in view.user_requirements.requirements
            ),
            subgoals=tuple(
                InvestigationSubgoalProgress(
                    logical_subgoal_id=item.logical_subgoal_id,
                    objective=item.objective,
                    status=(
                        "completed"
                        if item.logical_subgoal_id in completed
                        else "pending"
                    ),
                )
                for item in (plan.proposal.subgoals if plan is not None else ())
            ),
            waiting_reasons=tuple(
                f"{item.logical_subgoal_id}:{item.reason}"
                for item in view.waiting_reasons
            ),
        )


def _policy_rules_from_settings(settings: Settings) -> PolicyRules:
    """Build the policy override rule set from configured allow/deny lists."""
    cfg = settings.policy
    return PolicyRules(
        deny_users=frozenset(cfg.deny_users),
        allow_users=frozenset(cfg.allow_users),
        deny_sources=frozenset(cfg.deny_sources),
        allow_sources=frozenset(cfg.allow_sources),
        deny_tools=frozenset(cfg.deny_tools),
        deny_scopes=frozenset(cfg.deny_scopes),
        require_confirmation_for_high_risk=cfg.require_confirmation_for_high_risk,
    )


class AgentRuntime:
    """Composition root for conversation and domain application services."""

    def __init__(
        self,
        settings: Settings,
        store: PostgresMemoryStore,
        graph_store: GraphitiStore,
        capture_service: "CaptureService | None" = None,
    ) -> None:
        if not settings.postgres_url:
            raise ValueError(
                "PERSONAL_AGENT_POSTGRES_URL is required for business persistence."
            )
        self.settings = settings
        configure_langsmith_environment(settings.langsmith)
        self.store = store
        self.graph_store = graph_store
        self._policy_engine = PolicyEngine(_policy_rules_from_settings(settings))
        self.tool_governance_store = PostgresToolGovernanceStore(settings.postgres_url)
        self.procedure_definition_store = PostgresProcedureDefinitionStore(
            settings.postgres_url
        )
        self.agent_trace_store = PostgresAgentTraceStore(settings.postgres_url)
        self.execution_replay_store = PostgresExecutionReplayStore(
            settings.postgres_url
        )
        self.worker_queue_store = PostgresWorkerQueueStore(settings.postgres_url)
        self.research_store = PostgresResearchStore(
            settings.postgres_url,
            worker_queue=self.worker_queue_store,
        )
        self.knowledge_service = KnowledgeService(
            PostgresKnowledgeStore(settings.postgres_url, settings.data_dir)
        )
        self.knowledge_lifecycle_service = KnowledgeLifecycleService(
            PostgresKnowledgeLifecycleStore(settings.postgres_url)
        )
        # 让 gateway 与 facade 两条策略路径的决策都落库，调用点无需改签名。
        set_policy_decision_sink(self.tool_governance_store.record_policy_decision)
        self.memory = MemoryFacade(
            store, graph_store, policy_engine=self._policy_engine
        )
        self.structural_retriever = StructuralRetrieverStore(self.memory)
        self.capture_service = capture_service
        self.artifact_service = ArtifactService(settings, logger)
        self._structured_client = build_structured_model_client(
            settings.structured,
            settings.langsmith,
        )
        # Unified LLM ports: every application caller depends on these instead of
        # ``OpenAI`` / ``traced_chat_completion``. ``model_client`` serves
        # tool_calling + free-form text; ``structured_client`` serves every
        # JSON-schema / Pydantic structured-output call.
        from personal_agent.infra.structured_model import (
            build_chat_model_client,
            build_streaming_model_client,
        )

        self._model_client = build_chat_model_client(
            settings.openai,
            settings.langsmith,
        )
        if self._structured_client is not None:
            self.knowledge_service.relation_judge = LLMClaimRelationJudge(
                self._structured_client
            )
            self.knowledge_service.semantic_evidence_extractor = (
                LLMSemanticEvidenceExtractor(self._structured_client)
            )
            self.knowledge_service.semantic_claim_extractor = LLMSemanticClaimExtractor(
                self._structured_client
            )
            self.knowledge_service.claim_grounding_judge = LLMClaimGroundingJudge(
                self._structured_client
            )
        self._streaming_client = build_streaming_model_client(
            settings.openai,
            settings.langsmith,
        )
        self._research_event_client = self._structured_client
        self._planner_client = self._structured_client
        self._tool_executor = ToolExecutor(
            audit_sink=self.tool_governance_store,
            idempotency_store=self.tool_governance_store,
            policy_engine=self._policy_engine,
        )
        self.agent_run_store = PostgresAgentRunStore(settings.postgres_url)
        self._agent_gateway = AgentGateway(
            policy_engine=self._policy_engine,
            store=self.agent_run_store,
        )
        if self.settings.gpt_researcher_a2a.enabled:
            self._agent_gateway.register(
                GPTResearcherA2AAdapter(
                    self.settings.gpt_researcher_a2a,
                    self.artifact_service,
                )
            )
        self._llm = LlmClient(
            settings,
            model_client=self._model_client,
            streaming_client=self._streaming_client,
        )
        self._digest_formatter = DigestFormatter()
        self._review_digest_use_case = ReviewDigestUseCase(
            self.memory,
            formatter=self._digest_formatter,
            graph_store=self.graph_store,
        )
        self._knowledge_gap_use_case = KnowledgeGapUseCase(
            KnowledgeGapAnalyzer(
                self.memory,
                graph_store=self.graph_store,
                min_degree=settings.knowledge_gap.min_entity_degree,
                max_gaps=settings.knowledge_gap.max_gaps_per_run,
                recent_note_limit=settings.knowledge_gap.recent_note_limit,
                question_llm=self._rewrite_gap_question,
            )
        )
        self._knowledge_consolidation_use_case = KnowledgeConsolidationUseCase(
            self.memory,
            capture=lambda **kwargs: self.execute_capture(**kwargs),
            generate_draft=lambda prompt: self._llm.generate_answer(
                prompt,
                prompt_name="note_consolidation",
            ),
        )
        self._research_service = ResearchService(
            self.research_store,
            self._tool_executor,
            generate_text=lambda prompt, name: self._llm.generate_answer(
                prompt,
                prompt_name=name,
            ),
            save_note=lambda **kwargs: self.execute_capture(**kwargs),
            event_extractor=StructuredResearchEventExtractor(
                settings.langextract,
                model_client=self._research_event_client,
            ),
            default_limits=ResearchLimits(
                max_queries=settings.research.max_queries,
                max_exploration_queries=settings.research.max_exploration_queries,
                max_verification_queries=settings.research.max_verification_queries,
                max_satisfaction_model_calls=settings.research.max_satisfaction_model_calls,
                max_search_results=settings.research.max_search_results,
                max_fulltext_fetches=settings.research.max_fulltext_fetches,
                max_tool_calls=settings.research.max_tool_calls,
            ),
        )
        self._tool_executor.register(
            build_create_research_subscription_tool(self._research_service)
        )
        self._tool_executor.register(
            build_research_prepare_run_tool(self._research_service)
        )
        self._tool_executor.register(
            build_research_initialize_state_tool(self._research_service)
        )
        self._tool_executor.register(
            build_research_run_loop_tool(self._research_service)
        )
        self._tool_executor.register(
            build_research_synthesize_digest_tool(self._research_service)
        )
        self._tool_executor.register(
            build_research_verify_digest_tool(self._research_service)
        )
        self._register_tools()
        if self._structured_client is not None:
            investigation_planner = StructuredInvestigationPlanner(
                self._structured_client
            )
            investigation_execution_proposer = StructuredExecutionProposer(
                self._structured_client
            )
            investigation_verifier = StructuredProjectVerifier(self._structured_client)
            investigation_synthesis = StructuredProjectSynthesis(
                self._structured_client
            )
        else:
            unavailable_investigation_model = UnavailableInvestigationModelPorts()
            investigation_planner = unavailable_investigation_model
            investigation_execution_proposer = unavailable_investigation_model
            investigation_verifier = unavailable_investigation_model
            investigation_synthesis = unavailable_investigation_model
        self.investigation_project_store = PostgresInvestigationProjectStore(
            settings.postgres_url
        )
        self.investigation_project_service = InvestigationProjectService(
            store=self.investigation_project_store,
            queue=self.worker_queue_store,
            clock=lambda: datetime.now(UTC),
            capabilities=RuntimeCapabilitySnapshot(self.capability_inventory),
            planner=investigation_planner,
            execution_proposer=investigation_execution_proposer,
            tool_port=ToolExecutorProjectAdapter(
                self._tool_executor,
                self.artifact_service,
            ),
            agent_port=DurableProjectAgentAdapter(
                self._agent_gateway,
                self.artifact_service,
            ),
            synthesis_port=investigation_synthesis,
            verifier=investigation_verifier,
            artifact_writer=self.artifact_service,
            delegation_policy=PolicyEngineDelegationAdapter(
                self._policy_engine,
                self._agent_gateway.profile,
            ),
            disclosure_manifest=ScopeBoundDisclosureManifest(),
        )
        self._conversation_service = ConversationService(
            self._structured_client,
            tool_port=self._tool_executor,
            agent_port=self._agent_gateway,
            artifact_port=self.artifact_service,
            knowledge_writer=self.knowledge_service,
            knowledge_reader=_ConversationKnowledgeReadAdapter(self.knowledge_service),
            knowledge_lifecycle=self.knowledge_lifecycle_service,
            project_port=_ConversationProjectAdapter(
                self.investigation_project_service
            ),
            budget_policy=LoopBudgetPolicy(
                **self.settings.interaction_loop.model_dump()
            ),
            journal=FileInteractionJournal(self.settings.data_dir / "interaction_runs"),
        )
        self._sync_procedure_definitions()
        self._procedure_runtime = ProcedureRuntime(
            ProcedureMaterializer(PROCEDURE_CATALOG),
        )
        self._verifier = create_answer_verifier(settings)
        self._step_projection_validator = StepProjectionValidator(
            tool_executor=self._tool_executor
        )

    @property
    def agent_gateway(self) -> AgentGateway:
        return self._agent_gateway

    @property
    def review_digest_use_case(self) -> ReviewDigestUseCase:
        return self._review_digest_use_case

    @property
    def knowledge_gap_use_case(self) -> KnowledgeGapUseCase:
        return self._knowledge_gap_use_case

    @property
    def research_service(self) -> ResearchService:
        return self._research_service

    def create_research_subscription(
        self, subscription: ResearchSubscriptionRecord
    ) -> ResearchSubscriptionRecord:
        return self._research_service.create_subscription(subscription)

    def run_research_once(
        self,
        *,
        user_id: str,
        topic: str,
        instructions: str = "",
        max_items: int = 5,
        lookback_hours: int = 24,
        **_: object,
    ):
        """Execute the mandatory one-shot ResearchRun procedure.

        Decision Ownership Taxonomy: deterministic mandatory route.  The
        accepted HTTP command owns topic, instructions, limits, and user
        scope; the versioned Research procedure uniquely fixes the transaction
        order.  This code introduces no intent or replacement payload.
        """
        run = self._research_service.prepare_run(
            user_id=user_id,
            topic=topic,
            instructions=instructions,
            max_items=max_items,
            lookback_hours=lookback_hours,
        )
        try:
            return self._research_service.execute_run(run.id, max_items=max_items)
        except Exception:
            logger.exception("One-shot ResearchRun failed run_id=%s", run.id)
            return self.research_store.get_run(run.id) or run

    def enqueue_research_subscription(self, subscription_id: str):
        subscription = self.research_store.get_subscription(subscription_id)
        if subscription is None:
            return None
        return self._research_service.enqueue_subscription_run(
            subscription,
            trigger_type="manual",
        )

    def submit_research_feedback(self, feedback: ResearchFeedback):
        return self._research_service.feedback(feedback)

    def save_research_event(self, event_id: str, *, user_id: str):
        return self._research_service.save_event(event_id, user_id=user_id)

    def _sync_procedure_definitions(self) -> None:
        try:
            self.procedure_definition_store.sync_registry(PROCEDURE_CATALOG)
        except Exception:
            logger.exception("Failed to sync procedure definitions")

    # ---- tool registry (capture / search / delete tools) ----

    def _register_tools(self) -> None:
        if self.capture_service is not None:
            self._tool_executor.register(build_capture_url_tool(self.capture_service))
            self._tool_executor.register(
                build_capture_upload_tool(self.capture_service, self.artifact_service)
            )
        self._tool_executor.register(build_inspect_artifact_tool(self.artifact_service))
        if self._structured_client is not None:
            self._tool_executor.register(
                build_verify_interaction_draft_tool(self._structured_client)
            )
        self._tool_executor.register(
            build_graph_search_tool(self._active_graph_store())
        )
        self._tool_executor.register(
            build_capture_text_tool(
                lambda text, source_type="text", user_id="default": (
                    self.execute_capture(
                        text=text,
                        source_type=source_type,
                        user_id=user_id,
                    )
                )
            )
        )
        self._tool_executor.register(build_list_recent_notes_tool(self.memory))
        self._tool_executor.register(build_get_note_tool(self.memory))
        self._tool_executor.register(build_find_similar_notes_tool(self.memory))
        self._tool_executor.register(build_update_note_tool(self.memory))
        self._tool_executor.register(build_supersede_note_tool(self.memory))
        self._tool_executor.register(build_mark_note_deprecated_tool(self.memory))
        self._tool_executor.register(build_mark_notes_conflicted_tool(self.memory))
        self._tool_executor.register(
            build_consolidate_knowledge_tool(self._knowledge_consolidation_use_case)
        )
        self._tool_executor.register(
            build_review_digest_tool(self._review_digest_use_case)
        )
        self._tool_executor.register(
            build_inspect_knowledge_gaps_tool(self._knowledge_gap_use_case)
        )
        self._tool_executor.register(
            build_list_research_subscriptions_tool(self._research_service)
        )
        self._tool_executor.register(
            build_update_research_subscription_tool(self._research_service)
        )
        self._tool_executor.register(
            build_pause_research_subscription_tool(self._research_service)
        )
        self._tool_executor.register(
            build_resume_research_subscription_tool(self._research_service)
        )
        self._tool_executor.register(
            build_run_research_subscription_now_tool(self._research_service)
        )
        self._tool_executor.register(
            build_list_research_runs_tool(self._research_service)
        )
        self._tool_executor.register(
            build_get_research_digest_tool(self._research_service)
        )
        self._tool_executor.register(
            build_submit_research_feedback_tool(self._research_service)
        )
        self._tool_executor.register(
            build_save_research_event_tool(self._research_service)
        )
        self._tool_executor.register(build_inspect_worker_queue_tool(self))
        self._tool_executor.register(build_retry_worker_task_tool(self))
        if self.settings.web_search_available:
            from personal_agent.application.capture.providers.web_search import (
                build_web_search_provider,
            )

            web_provider = build_web_search_provider(self.settings)
            self._tool_executor.register(
                build_web_search_tool(self.settings, web_provider, self.capture_service)
            )
        for mcp_tool in build_mcp_tools(self.settings.mcp):
            self._tool_executor.register(mcp_tool)
        for raw_wiki_tool in build_raw_wiki_search_tools(
            self.settings.enterprise_knowledge
        ):
            self._tool_executor.register(raw_wiki_tool)
        self._tool_executor.register(
            build_enterprise_knowledge_search_tool(self._tool_executor)
        )

    @property
    def _web_search_available(self) -> bool:
        return self.settings.web_search_available

    def list_tools(self, *, include_internal: bool = False) -> list:
        if include_internal:
            return self._tool_executor.list_tools()
        return self._tool_executor.list_tools(
            exposures={"public_agent", "scoped_agent", "admin"}
        )

    def capability_inventory(self):
        return build_runtime_capability_inventory(
            tools=self._tool_executor.list_tools(),
            mcp_config=self.settings.mcp,
            agent_profiles=self._agent_gateway.profiles(),
            a2a_assembly=(
                A2AAssemblyDefinition(
                    agent_id="gpt_researcher",
                    implementation_present=True,
                    configuration_state=(
                        "enabled"
                        if self.settings.gpt_researcher_a2a.enabled
                        else "disabled"
                    ),
                ),
            ),
        )

    def execute_tool(self, name: str, *, execution_scope, **kwargs: object):
        return self._tool_executor.invoke_direct(
            name,
            execution_scope=execution_scope,
            **kwargs,
        )

    # ---- tool audit query API (P1) ----

    def query_tool_audit(self, **filters):
        return self.tool_governance_store.query_audit_events(**filters)

    def query_policy_decisions(self, **filters):
        return self.tool_governance_store.query_policy_decisions(**filters)

    def trace_tool_call(self, idempotency_key: str, *, reveal: bool = False):
        return self.tool_governance_store.trace_idempotency(
            idempotency_key, reveal=reveal
        )

    def audit_metrics(self, *, window_hours: int = 24):
        return self.tool_governance_store.audit_metrics(window_hours=window_hours)

    def _generate_answer(self, prompt: str) -> str | None:
        return self._llm.generate_answer(prompt)

    def _generate_answer_stream(self, prompt: str):
        return self._llm.generate_answer_stream(prompt)

    # ---- ingestion pipeline (capture → graph) ----

    def _ingestion(self) -> IngestionPipeline:
        """Build a pipeline bound to current settings/store/graph_store.

        Built per-call so test doubles that swap ``self.graph_store`` after
        construction (a common fixture pattern) take effect immediately.
        """
        return IngestionPipeline(
            settings=self.settings,
            memory=self.memory,
            graph_store=self._active_graph_store(),
            worker_queue=self.worker_queue_store,
        )

    def _active_graph_store(self):
        return self.graph_store

    def _bind_active_graph_store_to_memory(self) -> None:
        self.memory.graph = self._active_graph_store()

    def execute_capture(
        self,
        text: str,
        source_type: str = "text",
        user_id: str | None = None,
        source_ref: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> "CaptureResult":
        result = self._ingestion().ingest(
            text=text,
            source_type=source_type,
            user_id=user_id,
            source_ref=source_ref,
            metadata=metadata,
        )
        normalized_user = user_id or self.settings.default_user
        try:
            self.knowledge_service.ingest_text(
                text=text,
                source_type=source_type,
                user_id=normalized_user,
                owner_id=self._owner_id(normalized_user),
                source_ref=source_ref,
                raw_location=source_ref or "",
                created_by="user",
            )
        except Exception:
            logger.exception(
                "Knowledge projection write failed during capture user=%s",
                normalized_user,
            )
        return result

    def execute_consolidate(
        self,
        *,
        topic: str,
        user_id: str = "default",
    ) -> dict:
        return self._knowledge_consolidation_use_case.execute(
            topic=topic,
            user_id=user_id,
        ).model_dump(mode="json")

    def inspect_knowledge_gaps(self, user_id: str):
        return self.knowledge_service.plan_review_and_gaps(
            owner_id=self._owner_id(user_id),
            limit=self.settings.knowledge_gap.max_gaps_per_run,
        )

    def _knowledge_digest(self, user_id: str) -> _KnowledgeDigest:
        owner_id = self._owner_id(user_id)
        plan = self.knowledge_service.plan_review_and_gaps(
            owner_id=owner_id,
            limit=self.settings.knowledge_gap.max_gaps_per_run,
        )
        items = self.knowledge_service.store.list_knowledge_items(
            owner_id,
            state="active",
            limit=20,
        )
        claims_by_id = {
            claim.claim_id: claim
            for claim in self.knowledge_service.store.list_claims(owner_id, limit=500)
        }
        recent_notes = [
            KnowledgeNote(
                id=item.knowledge_item_id,
                user_id=item.user_id,
                source=NoteSource(
                    type="knowledge_item",
                    metadata={
                        "owner_id": owner_id,
                        "claim_ids": list(item.claim_ids),
                        "evidence_span_ids": list(item.evidence_span_ids),
                    },
                ),
                body=NoteBody(
                    title=item.title,
                    content=item.summary,
                    summary=item.summary,
                ),
            )
            for item in items
        ]
        due_cards = [
            ReviewCard(
                note_id=item.claim_id,
                prompt=item.prompt,
                answer_hint=claims_by_id.get(item.claim_id).statement
                if item.claim_id in claims_by_id
                else item.prompt,
                due_at=item.due_at,
            )
            for item in plan.review_items
        ]
        claim_lines = [f"- {item.summary}" for item in items[:8]]
        gap_lines = [f"- {gap.question}" for gap in plan.knowledge_gaps[:8]]
        text = "\n".join(
            [
                "个人知识简报",
                "",
                "活跃知识：",
                *(claim_lines or ["- 暂无 active claim。"]),
                "",
                "待处理缺口：",
                *(gap_lines or ["- 暂无高优先级缺口。"]),
            ]
        )
        return _KnowledgeDigest(
            text=text,
            recent_notes=recent_notes,
            due_cards=due_cards,
            sections=[
                {"title": "active_claims", "count": len(items)},
                {"title": "review_items", "count": len(plan.review_items)},
                {"title": "knowledge_gaps", "count": len(plan.knowledge_gaps)},
            ],
        )

    def _owner_id(self, user_id: str | None) -> str:
        return AuthenticatedPrincipal(
            tenant_id="personal-agent",
            user_id=user_id or self.settings.default_user or "default",
        ).principal_id

    def _knowledge_capture_result(
        self,
        ingest: IngestKnowledgeResult,
        *,
        metadata: dict[str, str] | None = None,
    ) -> CaptureResult:
        artifact = ingest.artifact
        active_claims = [
            claim
            for claim in ingest.claims
            if claim.state in {"active", "verified", "grounded", "conflicted"}
        ]
        title = (
            ingest.knowledge_items[0].title
            if ingest.knowledge_items
            else (
                active_claims[0].statement[:48]
                if active_claims
                else "Knowledge artifact"
            )
        )
        summary = (
            ingest.knowledge_items[0].summary
            if ingest.knowledge_items
            else (active_claims[0].statement if active_claims else artifact.text[:240])
        )
        note = KnowledgeNote(
            id=ingest.knowledge_items[0].knowledge_item_id
            if ingest.knowledge_items
            else artifact.artifact_id,
            user_id=artifact.user_id,
            source=NoteSource(
                type=artifact.source_type,
                ref=artifact.source_ref,
                fingerprint=artifact.content_hash,
                metadata={
                    **(metadata or {}),
                    "owner_id": artifact.owner_id,
                    "artifact_id": artifact.artifact_id,
                    "extraction_run_id": ingest.extraction_run.extraction_run_id,
                    "claim_ids": [claim.claim_id for claim in ingest.claims],
                    "evidence_span_ids": [
                        span.evidence_span_id for span in ingest.evidence_spans
                    ],
                    "admission_results": [
                        decision.admission_result
                        for decision in ingest.admission_decisions
                    ],
                },
            ),
            body=NoteBody(
                title=title,
                content=artifact.text,
                summary=summary,
            ),
        )
        note.version.content_hash = artifact.content_hash
        note.version.source_fingerprint = artifact.content_hash
        note.version.chunking_version = "knowledge:evidence-block-v1"
        note.version.graph_extraction_version = "knowledge:claim-v1"
        chunk_notes = [
            KnowledgeNote(
                id=block.evidence_block_id,
                user_id=artifact.user_id,
                source=NoteSource(
                    type=f"{artifact.source_type}_chunk",
                    ref=artifact.source_ref,
                    fingerprint=artifact.content_hash,
                    metadata={
                        "owner_id": artifact.owner_id,
                        "artifact_id": artifact.artifact_id,
                        "evidence_block_id": block.evidence_block_id,
                    },
                ),
                body=NoteBody(
                    title=f"{title} · {block.locator}",
                    content=block.full_context,
                    summary=block.full_context[:240],
                ),
            )
            for block in ingest.evidence_blocks
            if len(ingest.evidence_blocks) > 1
        ]
        for chunk in chunk_notes:
            chunk.version.content_hash = artifact.content_hash
            chunk.version.source_fingerprint = artifact.content_hash
            chunk.version.chunking_version = "knowledge:evidence-block-v1"
            chunk.version.graph_extraction_version = "knowledge:claim-v1"
        review_card = None
        if active_claims:
            review_card = ReviewCard(
                note_id=note.id,
                prompt=f"复习：{active_claims[0].statement}",
                answer_hint=active_claims[0].statement,
            )
        return CaptureResult(
            note=note,
            chunk_notes=chunk_notes,
            related_notes=[],
            review_card=review_card,
        )

    def _rewrite_gap_question(self, gap) -> str | None:
        if not self.settings.openai.api_key or not self.settings.openai.base_url:
            return None
        prompt = (
            "把下面的个人知识库缺口改写成一句自然、友好、简洁的中文提问。"
            "只输出问题本身。\n"
            f"缺口类型：{gap.gap_type}\n相关实体：{', '.join(gap.entities) or '无'}\n"
            f"默认问法：{gap.question}"
        )
        return self._llm.generate_answer(prompt, prompt_name="knowledge_gap_question")

    def sync_note_to_graph(self, note_id: str) -> bool:
        return self._ingestion().sync_note_to_graph(note_id)

    def enqueue_graph_sync(
        self, note_id: str, *, user_id: str | None = None
    ) -> str | None:
        note = self.memory.get_note(note_id)
        if note is None:
            return None
        if user_id is not None and note.user_id != user_id:
            return None
        task = self.worker_queue_store.enqueue(
            queue="graph",
            task_type="graph_sync_note",
            payload={
                "note_id": note.id,
                "user_id": note.user_id,
                "title": note.body.title,
            },
            idempotency_key=f"graph_sync_note:{note.id}",
            max_attempts=1,
        )
        return task.task_id

    def drain_worker_queue(
        self,
        queue: str = "graph",
        *,
        limit: int = 10,
        worker_id: str = "runtime-worker",
    ) -> dict[str, int]:
        """Synchronously drain queued worker tasks.

        This is the Phase 3 bridge before a separate worker process exists.
        It exercises the same durable queue/lease/complete/fail path that a
        future background worker will use.
        """
        from personal_agent.orchestration.worker import WorkflowWorker

        worker = WorkflowWorker(
            self,
            queue=queue,
            worker_id=worker_id,
            max_running_per_user=1,
        )
        total = {"leased": 0, "completed": 0, "failed": 0, "unsupported": 0}
        for _ in range(max(0, limit)):
            current = worker.run_once()
            for key in total:
                total[key] += getattr(current, key)
            if current.leased == 0:
                break
        return total

    def worker_queue_stats(self, queue: str | None = None) -> dict[str, int]:
        return self.worker_queue_store.queue_stats(queue)

    def retry_dead_worker_task(self, task_id: str) -> bool:
        return self.worker_queue_store.retry_dead(task_id)

    def sync_notes_to_graph(self, note_ids: list[str]) -> dict[str, bool]:
        return self._ingestion().sync_notes_to_graph(note_ids)

    def reconcile_graph_sync(
        self,
        user_id: str,
        *,
        graph_episode_uuids: list[str] | None = None,
        retry_statuses: list[str] | None = None,
        clean_orphans: bool = False,
    ):
        self._bind_active_graph_store_to_memory()
        return self.memory.reconcile_graph_sync(
            user_id,
            graph_episode_uuids=graph_episode_uuids,
            retry_statuses=retry_statuses,
            clean_orphans=clean_orphans,
            sync_note=self.sync_note_to_graph,
        )

    # ---- public properties (delegate to private fields so test mocks are visible) ----

    @property
    def tool_executor(self):
        return self._tool_executor

    @property
    def procedure_runtime(self):
        return self._procedure_runtime

    @property
    def step_projection_validator(self):
        return self._step_projection_validator

    def converse(self, *args, **kwargs):
        return self._conversation_service.respond(*args, **kwargs)

    def conversation_trace(self, interaction_run_ref: str, *, principal):
        return self._conversation_service.trace(
            interaction_run_ref,
            principal=principal,
        )

    def decide_conversation_knowledge_save(self, **kwargs):
        return self._conversation_service.decide_knowledge_save(**kwargs)

    def list_procedure_definitions(self):
        return self.procedure_definition_store.list_definitions()

    def set_procedure_deployment(self, procedure_id: str, **kwargs):
        return self.procedure_definition_store.set_deployment(procedure_id, **kwargs)

    def get_procedure_deployment(self, procedure_id: str, environment: str = "default"):
        return self.procedure_definition_store.get_deployment(
            procedure_id,
            environment=environment,
        )

    def record_procedure_eval_run(self, procedure_id: str, version: str, **kwargs):
        return self.procedure_definition_store.record_eval_run(
            procedure_id=procedure_id,
            version=version,
            **kwargs,
        )

    def get_procedure_eval_gate_status(
        self,
        procedure_id: str,
        version: str,
        *,
        suite: str = "default",
    ) -> dict[str, object]:
        return self.procedure_definition_store.get_eval_gate_status(
            procedure_id,
            version,
            suite=suite,
        )

    def set_procedure_eval_policy(self, procedure_id: str, **kwargs):
        return self.procedure_definition_store.set_eval_policy(procedure_id, **kwargs)

    def evaluate_procedure_deployment_gate(
        self,
        procedure_id: str,
        version: str,
        **kwargs,
    ) -> dict[str, object]:
        return self.procedure_definition_store.evaluate_deployment_gate(
            procedure_id,
            version,
            **kwargs,
        )

    def dry_run_procedure(
        self,
        *,
        procedure_id: str,
        routing_key: str = "dry-run",
        spec_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Validate and project a governed procedure without executing effects."""
        from dataclasses import asdict

        from personal_agent.capabilities.contracts.procedure import ProcedureDefinition
        from personal_agent.runtime.procedure_runtime import ProcedureSpecValidator

        spec = (
            ProcedureDefinition.from_definition_payload(spec_payload)
            if spec_payload is not None
            else self.procedure_definition_store.select_active_spec(
                procedure_id,
                registry=PROCEDURE_CATALOG,
                routing_key=routing_key,
            )
        )
        if spec is None:
            return {
                "valid": False,
                "issues": ["procedure deployment is disabled"],
                "steps": [],
            }
        issues = []
        try:
            ProcedureSpecValidator().validate(spec)
        except ValueError as exc:
            issues.append(str(exc))
        steps = spec.project("dry-run")
        step_validation = (
            self.step_projection_validator.validate(steps) if steps else None
        )
        return {
            "valid": not issues and (step_validation is None or step_validation.valid),
            "procedure_id": spec.procedure_id,
            "procedure_version": spec.version,
            "issues": [
                *issues,
                *(step_validation.issues if step_validation else []),
            ],
            "warnings": [
                *(step_validation.warnings if step_validation else []),
            ],
            "steps": [asdict(step) for step in steps],
            "eval_gate": self.procedure_definition_store.evaluate_deployment_gate(
                spec.procedure_id,
                spec.version,
            ),
        }

    def list_execution_artifacts(
        self,
        run_id: str,
        *,
        kind: str | None = None,
        step_id: str | None = None,
        limit: int = 50,
    ):
        return self.execution_replay_store.list_artifacts(
            run_id,
            kind=kind,
            step_id=step_id,
            limit=limit,
        )

    def get_execution_artifact(self, artifact_id: str):
        return self.execution_replay_store.get_artifact(artifact_id)

    def redact_execution_artifact(
        self, artifact_id: str, *, keys: set[str] | None = None
    ):
        return self.execution_replay_store.redact_artifact(artifact_id, keys=keys)

    def purge_expired_execution_artifacts(self, *, limit: int = 1000) -> int:
        return self.execution_replay_store.purge_expired_artifacts(limit=limit)

    def list_replay_runs(self, run_id: str, limit: int = 50):
        return self.execution_replay_store.list_replay_runs(run_id, limit=limit)

    # ---- digest / intent (formerly RuntimeEntryMixin) ----

    def execute_digest(self, user_id: str | None = None) -> DigestResult:
        normalized_user = user_id or self.settings.default_user
        logger.info("Generating digest user=%s", normalized_user)
        digest = self._review_digest_use_case.generate(normalized_user)
        return DigestResult(
            message=self._digest_formatter.to_text(digest),
            recent_notes=digest.recent_notes,
            due_reviews=digest.due_cards,
        )

    # ---- admin / maintenance (formerly RuntimeAdminMixin) ----

    def health(self) -> dict[str, object]:
        graph_status = self.graph_store.status()
        return {
            "status": "ok",
            "graphiti": graph_status,
        }

    def reset_debug_data(self) -> ResetResult:
        logger.warning("Resetting all development data stores")
        protected_eval_groups = _protected_eval_graph_group_ids(
            self.settings,
            graph_store=self.graph_store,
        )
        deleted_graph_nodes = self.graph_store.clear_all_data(
            preserve_group_ids=protected_eval_groups
        )
        self.memory.ensure_schema()
        counts = PostgresDebugResetStore(self.settings.postgres_url).clear_all_data()
        deleted_upload_files = clear_upload_files(self.settings.data_dir)
        return ResetResult(
            deleted_notes=counts["notes"],
            deleted_reviews=counts["reviews"],
            deleted_upload_files=deleted_upload_files,
            deleted_graph_nodes=deleted_graph_nodes,
            deleted_checkpoints=counts["checkpoints"],
            deleted_checkpoint_blobs=counts["checkpoint_blobs"],
            deleted_checkpoint_writes=counts["checkpoint_writes"],
            deleted_checkpoint_migrations=counts["checkpoint_migrations"],
            truncated_postgres_tables=counts["postgres_tables"],
            deleted_postgres_rows=counts["postgres_rows"],
        )

    # ---- short aliases ----

    def digest(self, user_id: str | None = None) -> DigestResult:
        return self.execute_digest(user_id=user_id)


__all__ = [
    "AgentRuntime",
    "CaptureResult",
    "DigestResult",
    "ResetResult",
    "_annotate_answer",
    "_evidence_content",
    "_extract_question_keywords",
    "_format_graph_relation",
    "_graph_episode_uuids",
    "_graph_fact_lines",
    "_graph_facts_by_episode",
    "_merge_citations",
    "_merge_notes",
    "_split_sentences",
    "_tokenize_for_overlap",
    "_top_sentences",
]
