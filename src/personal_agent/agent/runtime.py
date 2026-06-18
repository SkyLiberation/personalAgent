from __future__ import annotations

import logging
from typing import Callable, TYPE_CHECKING

from ..core.config import Settings
from ..core.langsmith_tracing import configure_langsmith_environment
from ..core.models import EntryInput
from ..core.observability import set_policy_decision_sink
from ..graphiti.store import GraphitiStore
from ..memory import MemoryFacade
from ..ms_graphrag import MicrosoftGraphRagStore
from ..policy import PolicyEngine, PolicyRules
from ..storage.postgres_memory_store import PostgresMemoryStore
from ..storage.postgres_tool_governance_store import PostgresToolGovernanceStore
from ..storage.postgres_worker_queue_store import PostgresWorkerQueueStore
from ..storage.postgres_workflow_definition_store import PostgresWorkflowDefinitionStore
from ..storage.postgres_workflow_event_store import PostgresWorkflowEventStore
from ..storage.postgres_workflow_replay_store import PostgresWorkflowReplayStore
from ..structural_retriever import StructuralRetrieverStore
from ..tools import (
    ToolExecutor,
    build_capture_text_tool,
    build_capture_upload_tool,
    build_capture_url_tool,
    build_delete_note_tool,
    build_restore_note_tool,
    build_graph_search_tool,
    build_web_search_tool,
)
from .entry_orchestrator import EntryOrchestrator
from .episodic_memory import record_entry_episode
from .step_projector import WorkflowStepProjector
from .step_projection_validator import StepProjectionValidator
from .replanner import Replanner
from .router import DefaultIntentRouter
from .ingestion_pipeline import IngestionPipeline
from .runtime_admin import _protected_eval_graph_group_ids
from .runtime_ask import AskService
from .runtime_helpers import (
    _annotate_answer,
    _best_snippet,
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
from .runtime_llm import LlmClient
from .thread_summarizer import ThreadSummarizer
from .runtime_results import (
    AskResult,
    CaptureResult,
    DigestResult,
    EntryResult,
    ResetResult,
    RetryResult,
)
from ..review import DigestFormatter, ReviewDigestUseCase
from ..storage.postgres_debug_reset_store import PostgresDebugResetStore, clear_upload_files
from .verifier import AnswerVerifier

if TYPE_CHECKING:
    from ..capture import CaptureService

logger = logging.getLogger(__name__)


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
    """Composition root for capture / ask / digest / entry operations.

    Owns the stores and wires explicit collaborators — ``LlmClient``,
    ``ThreadSummarizer``, ``AskService`` (answering) and ``EntryOrchestrator``
    (LangGraph entry flow) — and exposes thin delegating methods. No behavior
    is inherited via mixins; everything here is either local glue over the
    shared stores or a one-line delegation to a collaborator.
    """

    def __init__(
        self,
        settings: Settings,
        store: PostgresMemoryStore,
        graph_store: GraphitiStore,
        ms_graphrag_store: MicrosoftGraphRagStore | None = None,
        capture_service: "CaptureService | None" = None,
    ) -> None:
        if not settings.postgres_url:
            raise ValueError("PERSONAL_AGENT_POSTGRES_URL is required for business persistence.")
        self.settings = settings
        configure_langsmith_environment(settings.langsmith)
        self.store = store
        self.graph_store = graph_store
        self.ms_graphrag_store = ms_graphrag_store or MicrosoftGraphRagStore(settings)
        self._policy_engine = PolicyEngine(_policy_rules_from_settings(settings))
        self.tool_governance_store = PostgresToolGovernanceStore(settings.postgres_url)
        self.workflow_definition_store = PostgresWorkflowDefinitionStore(settings.postgres_url)
        self.workflow_event_store = PostgresWorkflowEventStore(settings.postgres_url)
        self.workflow_replay_store = PostgresWorkflowReplayStore(settings.postgres_url)
        self.worker_queue_store = PostgresWorkerQueueStore(settings.postgres_url)
        # 让 gateway 与 facade 两条策略路径的决策都落库，调用点无需改签名。
        set_policy_decision_sink(self.tool_governance_store.record_policy_decision)
        self.memory = MemoryFacade(store, graph_store, policy_engine=self._policy_engine)
        self.structural_retriever = StructuralRetrieverStore(self.memory)
        self.capture_service = capture_service
        self._intent_router = DefaultIntentRouter(settings)
        self._tool_executor = ToolExecutor(
            audit_sink=self.tool_governance_store,
            idempotency_store=self.tool_governance_store,
            policy_engine=self._policy_engine,
        )
        self._register_tools()
        self._sync_workflow_definitions()
        self._step_projector = WorkflowStepProjector(
            settings,
            tool_executor=self._tool_executor,
            workflow_definition_store=self.workflow_definition_store,
        )
        self._verifier = AnswerVerifier()
        self._step_projection_validator = StepProjectionValidator(tool_executor=self._tool_executor)
        self._replanner = Replanner(settings)
        self._digest_formatter = DigestFormatter()
        # Explicit collaborators.
        self._llm = LlmClient(settings)
        self._summarizer = ThreadSummarizer(self._llm)
        self._entry = EntryOrchestrator(self)
        self._thread_message_loader: (
            Callable[[EntryInput, int], list[dict[str, str]]] | None
        ) = None

    def _sync_workflow_definitions(self) -> None:
        try:
            from .workflow import WORKFLOW_REGISTRY

            self.workflow_definition_store.sync_registry(WORKFLOW_REGISTRY)
        except Exception:
            logger.exception("Failed to sync workflow definitions")

    # ---- tool registry (capture / search / delete tools) ----

    def _register_tools(self) -> None:
        if self.capture_service is not None:
            self._tool_executor.register(build_capture_url_tool(self.capture_service))
            self._tool_executor.register(
                build_capture_upload_tool(self.capture_service, self.settings.data_dir / "uploads")
            )
        self._tool_executor.register(build_graph_search_tool(self._active_graph_store()))
        self._tool_executor.register(build_capture_text_tool(
            lambda text, source_type="text", user_id="default": self.execute_capture(
                text=text, source_type=source_type, user_id=user_id,
            )
        ))
        self._tool_executor.register(build_delete_note_tool(self.memory))
        self._tool_executor.register(build_restore_note_tool(self.memory))
        if self.settings.web_search.api_key:
            from ..capture.providers.web_search import build_web_search_provider
            web_provider = build_web_search_provider(self.settings)
            self._tool_executor.register(build_web_search_tool(self.settings, web_provider, self.capture_service))

    @property
    def _web_search_available(self) -> bool:
        return bool(self.settings.web_search.api_key)

    def list_tools(self) -> list:
        return self._tool_executor.list_tools()

    def execute_tool(self, name: str, **kwargs: object):
        return self._tool_executor.invoke_direct(name, **kwargs)

    # ---- tool audit query API (P1) ----

    def query_tool_audit(self, **filters):
        return self.tool_governance_store.query_audit_events(**filters)

    def query_policy_decisions(self, **filters):
        return self.tool_governance_store.query_policy_decisions(**filters)

    def trace_tool_call(self, idempotency_key: str, *, reveal: bool = False):
        return self.tool_governance_store.trace_idempotency(idempotency_key, reveal=reveal)

    def audit_metrics(self, *, window_hours: int = 24):
        return self.tool_governance_store.audit_metrics(window_hours=window_hours)


    # ---- delegation to explicit collaborators ----

    def _ask_service(self) -> AskService:
        """Build an ask service bound to current settings/stores.

        Built per-call (mirroring ``_ingestion()``) so test doubles that swap
        ``self.settings`` / ``self.graph_store`` after construction take effect.
        The shared ``LlmClient`` / verifier are reused so cooldown state and
        test mocks remain visible.
        """
        return AskService(
            settings=self.settings,
            graph_store=self.graph_store,
            ms_graphrag_store=self.ms_graphrag_store,
            structural_retriever=self.structural_retriever,
            memory=self.memory,
            tool_executor=self._tool_executor,
            verifier=self._verifier,
            llm=self._llm,
        )

    def execute_ask(self, *args, **kwargs) -> "AskResult":
        return self._ask_service().execute_ask(*args, **kwargs)

    def _generate_answer(self, prompt: str) -> str | None:
        return self._llm.generate_answer(prompt)

    def _generate_answer_stream(self, prompt: str):
        return self._llm.generate_answer_stream(prompt)

    def summarize_chat(self, messages_text: str, user_id: str = "default") -> str:
        return self._summarizer.summarize_chat(messages_text, user_id)

    def compress_context(self, messages_text: str, user_id: str = "default") -> str:
        return self._summarizer.compress_context(messages_text, user_id)

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
        provider = self.settings.ask.graph_provider.strip().lower()
        if provider in {"ms_graphrag", "microsoft_graphrag", "graphrag"}:
            return self.ms_graphrag_store
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
        return self._ingestion().ingest(
            text=text,
            source_type=source_type,
            user_id=user_id,
            source_ref=source_ref,
            metadata=metadata,
        )

    def sync_note_to_graph(self, note_id: str) -> bool:
        return self._ingestion().sync_note_to_graph(note_id)

    def enqueue_graph_sync(self, note_id: str, *, user_id: str | None = None) -> str | None:
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
        from .worker import WorkflowWorker

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
    def intent_router(self):
        return self._intent_router

    @property
    def tool_executor(self):
        return self._tool_executor

    @property
    def step_projector(self):
        return self._step_projector

    @property
    def step_projection_validator(self):
        return self._step_projection_validator

    def set_thread_message_loader(
        self, loader: Callable[[EntryInput, int], list[dict[str, str]]] | None
    ) -> None:
        """Register a platform adapter used only after the graph selects summary."""
        self._thread_message_loader = loader

    def load_thread_messages(
        self, entry_input: EntryInput, limit: int = 20
    ) -> list[dict[str, str]]:
        if self._thread_message_loader is None:
            return []
        return self._thread_message_loader(entry_input, limit)

    # ---- entry orchestration (delegated to EntryOrchestrator) ----

    def execute_entry(self, entry_input: EntryInput, on_progress=None) -> EntryResult:
        result = self._entry.execute_entry(entry_input, on_progress=on_progress)
        record_entry_episode(self.memory, result, entry_input, settings=self.settings)
        return result

    def resume_entry(
        self, run_id: str, thread_id: str, decision: str, user_id: str,
        text: str | None = None, option_id: str | None = None,
    ) -> EntryResult:
        result = self._entry.resume_entry(
            run_id, thread_id, decision, user_id, text=text, option_id=option_id,
        )
        record_entry_episode(self.memory, result, settings=self.settings)
        return result

    def get_run_snapshot(self, run_id: str):
        return self._entry.get_run_snapshot(run_id)

    def list_run_snapshots(self, user_id: str | None = None, limit: int = 50):
        return self._entry.list_run_snapshots(user_id=user_id, limit=limit)

    def list_run_history(self, run_id: str, limit: int = 100):
        return self._entry.list_run_history(run_id, limit=limit)

    def list_workflow_definitions(self):
        return self.workflow_definition_store.list_definitions()

    def set_workflow_deployment(self, workflow_id: str, **kwargs):
        return self.workflow_definition_store.set_deployment(workflow_id, **kwargs)

    def get_workflow_deployment(self, workflow_id: str, environment: str = "default"):
        return self.workflow_definition_store.get_deployment(
            workflow_id,
            environment=environment,
        )

    def record_workflow_eval_run(self, workflow_id: str, version: str, **kwargs):
        return self.workflow_definition_store.record_eval_run(
            workflow_id=workflow_id,
            version=version,
            **kwargs,
        )

    def get_workflow_eval_gate_status(
        self,
        workflow_id: str,
        version: str,
        *,
        suite: str = "default",
    ) -> dict[str, object]:
        return self.workflow_definition_store.get_eval_gate_status(
            workflow_id,
            version,
            suite=suite,
        )

    def set_workflow_eval_policy(self, workflow_id: str, **kwargs):
        return self.workflow_definition_store.set_eval_policy(workflow_id, **kwargs)

    def evaluate_workflow_deployment_gate(
        self,
        workflow_id: str,
        version: str,
        **kwargs,
    ) -> dict[str, object]:
        return self.workflow_definition_store.evaluate_deployment_gate(
            workflow_id,
            version,
            **kwargs,
        )

    def dry_run_workflow(
        self,
        *,
        intent: str,
        routing_key: str = "dry-run",
        spec_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Validate and project a workflow definition without executing effects."""
        from dataclasses import asdict

        from .router import _default_router_decision
        from .workflow import WORKFLOW_REGISTRY, WorkflowSpec
        from .workflow_validator import WorkflowSpecValidator

        spec = (
            WorkflowSpec.from_definition_payload(spec_payload)
            if spec_payload is not None
            else self.workflow_definition_store.select_active_spec(
                intent,
                registry=WORKFLOW_REGISTRY,
                routing_key=routing_key,
            )
        )
        if spec is None:
            return {"valid": False, "issues": ["workflow deployment is disabled"], "steps": []}
        spec_validation = WorkflowSpecValidator().validate_spec(spec)
        steps = spec.project()
        step_validation = self.step_projection_validator.validate(
            steps,
            _default_router_decision(spec.intent),
        ) if steps else None
        return {
            "valid": spec_validation.valid and (step_validation is None or step_validation.valid),
            "workflow_id": spec.workflow_id,
            "workflow_version": spec.version,
            "issues": [
                *spec_validation.issues,
                *(step_validation.issues if step_validation else []),
            ],
            "warnings": [
                *spec_validation.warnings,
                *(step_validation.warnings if step_validation else []),
            ],
            "steps": [asdict(step) for step in steps],
            "eval_gate": self.workflow_definition_store.evaluate_deployment_gate(
                spec.workflow_id,
                spec.version,
            ),
        }

    def list_workflow_artifacts(
        self,
        run_id: str,
        *,
        kind: str | None = None,
        limit: int = 50,
    ):
        return self.workflow_replay_store.list_artifacts(run_id, kind=kind, limit=limit)

    def get_workflow_artifact(self, artifact_id: str):
        return self.workflow_replay_store.get_artifact(artifact_id)

    def redact_workflow_artifact(self, artifact_id: str, *, keys: set[str] | None = None):
        return self.workflow_replay_store.redact_artifact(artifact_id, keys=keys)

    def purge_expired_workflow_artifacts(self, *, limit: int = 1000) -> int:
        return self.workflow_replay_store.purge_expired_artifacts(limit=limit)

    def list_replay_runs(self, run_id: str, limit: int = 50):
        return self.workflow_replay_store.list_replay_runs(run_id, limit=limit)

    def rebuild_workflow_projection(self, run_id: str):
        from .workflow_event_projection import project_workflow_events

        return project_workflow_events(
            run_id,
            self.workflow_event_store.list_events(run_id),
        )

    def build_workflow_debug_bundle(self, run_id: str) -> dict[str, object]:
        events = [
            event.model_dump(mode="json")
            for event in self.workflow_event_store.list_events(run_id)
        ]
        history = self.list_run_history(run_id, limit=100)
        return self.workflow_replay_store.build_debug_bundle(
            run_id=run_id,
            events=events,
            history=history,
            projection=self.rebuild_workflow_projection(run_id).model_dump(mode="json"),
        )

    def replay_from_checkpoint(
        self,
        *,
        thread_id: str,
        checkpoint_id: str,
        updates: dict[str, object],
        checkpoint_ns: str | None = None,
        as_node: str | None = None,
    ) -> EntryResult:
        result = self._entry.replay_from_checkpoint(
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            updates=updates,
            checkpoint_ns=checkpoint_ns,
            as_node=as_node,
        )
        record_entry_episode(self.memory, result, settings=self.settings)
        return result

    def fork_from_checkpoint(
        self,
        *,
        thread_id: str,
        checkpoint_id: str,
        updates: dict[str, object] | None = None,
        checkpoint_ns: str | None = None,
        as_node: str | None = None,
    ) -> EntryResult:
        result = self._entry.fork_from_checkpoint(
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            updates=updates or {},
            checkpoint_ns=checkpoint_ns,
            as_node=as_node,
        )
        record_entry_episode(self.memory, result, settings=self.settings)
        return result

    def fork_from_step(
        self,
        *,
        run_id: str,
        step_id: str,
        updates: dict[str, object] | None = None,
    ) -> EntryResult:
        result = self._entry.fork_from_step(
            run_id=run_id,
            step_id=step_id,
            updates=updates,
        )
        record_entry_episode(self.memory, result, settings=self.settings)
        return result

    def set_workflow_state_migration(self, workflow_id: str, **kwargs):
        return self.workflow_definition_store.set_state_migration(workflow_id, **kwargs)

    def preview_workflow_state_migration(
        self,
        *,
        run_id: str,
        to_version: str,
    ):
        from .workflow_state_migration import migrate_step_execution

        source_state = self._entry.get_run_state(run_id)
        if source_state is None:
            raise ValueError(f"Workflow run not found: {run_id}")
        target = self.workflow_definition_store.get_definition(
            source_state.workflow_id,
            to_version,
        )
        if target is None:
            raise ValueError(
                f"Workflow definition not found: {source_state.workflow_id}@{to_version}"
            )
        migration = self.workflow_definition_store.get_state_migration(
            source_state.workflow_id,
            from_version=source_state.workflow_version,
            to_version=to_version,
        )
        return migrate_step_execution(
            source_state.step_execution,
            target,
            step_mapping=dict((migration or {}).get("step_mapping") or {}),
        )

    # ---- digest / intent (formerly RuntimeEntryMixin) ----

    def execute_digest(self, user_id: str | None = None) -> DigestResult:
        normalized_user = user_id or self.settings.default_user
        logger.info("Generating digest user=%s", normalized_user)
        digest = ReviewDigestUseCase(
            self.memory,
            formatter=self._digest_formatter,
        ).generate(normalized_user)
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
        checkpointer = self._entry._get_orch_graph().checkpointer
        counts = PostgresDebugResetStore(self.settings.postgres_url).clear_all_data()
        checkpointer.setup()
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

    def entry(self, entry_input: EntryInput, on_progress=None) -> EntryResult:
        return self.execute_entry(entry_input, on_progress=on_progress)


__all__ = [
    "AgentRuntime",
    "AskResult",
    "CaptureResult",
    "DigestResult",
    "EntryResult",
    "ResetResult",
    "RetryResult",
    "_annotate_answer",
    "_best_snippet",
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
