from __future__ import annotations

from typing import TYPE_CHECKING

from personal_agent.kernel.config import Settings
from personal_agent.memory.graphiti.store import GraphitiStore
from personal_agent.memory.ms_graphrag import MicrosoftGraphRagStore
from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
from personal_agent.orchestration.runtime import AgentRuntime

if TYPE_CHECKING:
    from personal_agent.application.capture import CaptureService


class AgentService:
    """Application service facade that owns the concrete runtime.

    ``AgentService`` is the boundary used by CLI, Web and Feishu adapters. It
    wires durable stores, then delegates use cases to an explicit
    ``AgentRuntime`` instance instead of inheriting runtime internals.
    """

    def __init__(
        self, settings: Settings | None = None, capture_service: "CaptureService | None" = None
    ) -> None:
        resolved_settings = settings or Settings.from_env()
        if not resolved_settings.postgres_url:
            raise ValueError("PERSONAL_AGENT_POSTGRES_URL is required for business persistence.")
        store = PostgresMemoryStore(
            resolved_settings.data_dir,
            resolved_settings.postgres_url,
            embedding_provider=resolved_settings.embedding_provider,
            embedding_model=resolved_settings.openai.embedding_model,
            embedding_api_key=resolved_settings.openai.embedding_api_key
            or resolved_settings.openai.api_key,
            embedding_base_url=resolved_settings.openai.embedding_base_url
            or resolved_settings.openai.base_url,
            langsmith_config=resolved_settings.langsmith,
        )
        self.runtime = AgentRuntime(
            settings=resolved_settings,
            store=store,
            graph_store=GraphitiStore(resolved_settings),
            ms_graphrag_store=MicrosoftGraphRagStore(resolved_settings),
            capture_service=capture_service,
        )

    @property
    def settings(self):
        return self.runtime.settings

    @settings.setter
    def settings(self, value):
        self.runtime.settings = value

    @property
    def store(self):
        return self.runtime.store

    @property
    def memory(self):
        return self.runtime.memory

    @property
    def workspace_service(self):
        return self.runtime.workspace_service

    @property
    def knowledge_lifecycle_service(self):
        return self.runtime.knowledge_lifecycle_service

    @property
    def graph_store(self):
        return self.runtime.graph_store

    @graph_store.setter
    def graph_store(self, value):
        self.runtime.graph_store = value

    @property
    def ms_graphrag_store(self):
        return self.runtime.ms_graphrag_store

    @property
    def tool_governance_store(self):
        return self.runtime.tool_governance_store

    @property
    def tool_executor(self):
        return self.runtime.tool_executor

    @property
    def agent_gateway(self):
        return self.runtime.agent_gateway

    @property
    def artifact_service(self):
        return self.runtime.artifact_service

    def health(self):
        return self.runtime.health()

    def list_tools(self, *, include_internal: bool = False):
        return self.runtime.list_tools(include_internal=include_internal)

    def capability_inventory(self):
        return self.runtime.capability_inventory()

    @property
    def investigation_project_service(self):
        return self.runtime.investigation_project_service

    def create_investigation_project(self, command):
        return self.runtime.investigation_project_service.create(command)

    def get_investigation_project(self, query):
        return self.runtime.investigation_project_service.get(query)

    def get_investigation_report(self, query):
        return self.runtime.investigation_project_service.get_report(query)

    def process_investigation_project(self, command):
        return self.runtime.investigation_project_service.process(command)

    def steer_investigation_project(self, command):
        return self.runtime.investigation_project_service.steer(command)

    def approve_investigation_command(self, command):
        return self.runtime.investigation_project_service.approve(command)

    def cancel_investigation_project(self, command):
        return self.runtime.investigation_project_service.cancel(command)

    def pause_investigation_project(self, command):
        return self.runtime.investigation_project_service.pause(command)

    def resume_investigation_project(self, command):
        return self.runtime.investigation_project_service.resume(command)

    def execute_tool(self, name: str, *, execution_scope, **kwargs: object):
        return self.runtime.execute_tool(
            name,
            execution_scope=execution_scope,
            **kwargs,
        )

    def query_tool_audit(self, **filters):
        return self.runtime.query_tool_audit(**filters)

    def query_policy_decisions(self, **filters):
        return self.runtime.query_policy_decisions(**filters)

    def trace_tool_call(self, idempotency_key: str, *, reveal: bool = False):
        return self.runtime.trace_tool_call(idempotency_key, reveal=reveal)

    def audit_metrics(self, *, window_hours: int = 24):
        return self.runtime.audit_metrics(window_hours=window_hours)

    def execute_capture(self, *args, **kwargs):
        return self.runtime.execute_capture(*args, **kwargs)

    def execute_consolidate(self, *args, **kwargs):
        return self.runtime.execute_consolidate(*args, **kwargs)

    @property
    def review_digest_use_case(self):
        return self.runtime.review_digest_use_case

    @property
    def knowledge_gap_use_case(self):
        return self.runtime.knowledge_gap_use_case

    @property
    def research_service(self):
        return self.runtime.research_service

    @property
    def research_store(self):
        return self.runtime.research_store

    def create_research_subscription(self, subscription):
        return self.runtime.create_research_subscription(subscription)

    def run_research_once(self, **kwargs):
        return self.runtime.run_research_once(**kwargs)

    def enqueue_research_subscription(self, subscription_id: str):
        return self.runtime.enqueue_research_subscription(subscription_id)

    def submit_research_feedback(self, feedback):
        return self.runtime.submit_research_feedback(feedback)

    def save_research_event(self, event_id: str, *, user_id: str):
        return self.runtime.save_research_event(event_id, user_id=user_id)

    def inspect_knowledge_gaps(self, user_id: str):
        return self.runtime.inspect_knowledge_gaps(user_id)

    def sync_note_to_graph(self, note_id: str) -> bool:
        return self.runtime.sync_note_to_graph(note_id)

    def enqueue_graph_sync(self, note_id: str, *, user_id: str | None = None) -> str | None:
        return self.runtime.enqueue_graph_sync(note_id, user_id=user_id)

    def drain_worker_queue(self, *args, **kwargs):
        return self.runtime.drain_worker_queue(*args, **kwargs)

    def worker_queue_stats(self, queue: str | None = None):
        return self.runtime.worker_queue_stats(queue)

    def retry_dead_worker_task(self, task_id: str) -> bool:
        return self.runtime.retry_dead_worker_task(task_id)

    def sync_notes_to_graph(self, note_ids: list[str]) -> dict[str, bool]:
        return self.runtime.sync_notes_to_graph(note_ids)

    def reconcile_graph_sync(self, *args, **kwargs):
        return self.runtime.reconcile_graph_sync(*args, **kwargs)

    def execute_ask(self, *args, **kwargs):
        return self.runtime.execute_ask(*args, **kwargs)

    def summarize_chat(self, messages_text: str, user_id: str = "default") -> str:
        return self.runtime.summarize_chat(messages_text, user_id)

    def compress_context(self, messages_text: str, user_id: str = "default") -> str:
        return self.runtime.compress_context(messages_text, user_id)

    def converse(self, *args, **kwargs):
        return self.runtime.converse(*args, **kwargs)

    def conversation_trace(self, *args, **kwargs):
        return self.runtime.conversation_trace(*args, **kwargs)

    def decide_conversation_knowledge_save(self, **kwargs):
        return self.runtime.decide_conversation_knowledge_save(**kwargs)

    def list_procedure_definitions(self):
        return self.runtime.list_procedure_definitions()

    def set_procedure_deployment(self, procedure_id: str, **kwargs):
        return self.runtime.set_procedure_deployment(procedure_id, **kwargs)

    def get_procedure_deployment(self, procedure_id: str, environment: str = "default"):
        return self.runtime.get_procedure_deployment(procedure_id, environment=environment)

    def record_procedure_eval_run(self, procedure_id: str, version: str, **kwargs):
        return self.runtime.record_procedure_eval_run(procedure_id, version, **kwargs)

    def get_procedure_eval_gate_status(self, procedure_id: str, version: str, **kwargs):
        return self.runtime.get_procedure_eval_gate_status(procedure_id, version, **kwargs)

    def set_procedure_eval_policy(self, procedure_id: str, **kwargs):
        return self.runtime.set_procedure_eval_policy(procedure_id, **kwargs)

    def evaluate_procedure_deployment_gate(self, procedure_id: str, version: str, **kwargs):
        return self.runtime.evaluate_procedure_deployment_gate(
            procedure_id,
            version,
            **kwargs,
        )

    def dry_run_procedure(self, **kwargs):
        return self.runtime.dry_run_procedure(**kwargs)

    def list_execution_artifacts(self, run_id: str, **kwargs):
        return self.runtime.list_execution_artifacts(run_id, **kwargs)

    def get_execution_artifact(self, artifact_id: str):
        return self.runtime.get_execution_artifact(artifact_id)

    def redact_execution_artifact(self, artifact_id: str, **kwargs):
        return self.runtime.redact_execution_artifact(artifact_id, **kwargs)

    def purge_expired_execution_artifacts(self, **kwargs):
        return self.runtime.purge_expired_execution_artifacts(**kwargs)

    def rebuild_execution_projection(self, run_id: str):
        return self.runtime.rebuild_execution_projection(run_id)

    def list_replay_runs(self, run_id: str, limit: int = 50):
        return self.runtime.list_replay_runs(run_id, limit=limit)

    def build_execution_debug_bundle(self, run_id: str):
        return self.runtime.build_execution_debug_bundle(run_id)

    def execute_digest(self, user_id: str | None = None):
        return self.runtime.execute_digest(user_id=user_id)

    def reset_debug_data(self):
        return self.runtime.reset_debug_data()

    def digest(self, user_id: str | None = None):
        return self.runtime.digest(user_id=user_id)

