from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.config import Settings
from ..graphiti.store import GraphitiStore
from ..ms_graphrag import MicrosoftGraphRagStore
from ..storage.postgres_memory_store import PostgresMemoryStore
from .runtime import AgentRuntime

if TYPE_CHECKING:
    from ..capture import CaptureService


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
    def intent_router(self):
        return self.runtime.intent_router

    @property
    def tool_executor(self):
        return self.runtime.tool_executor

    @property
    def step_projector(self):
        return self.runtime.step_projector

    @property
    def step_projection_validator(self):
        return self.runtime.step_projection_validator

    def health(self):
        return self.runtime.health()

    def list_tools(self):
        return self.runtime.list_tools()

    def execute_tool(self, name: str, **kwargs: object):
        return self.runtime.execute_tool(name, **kwargs)

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

    def sync_note_to_graph(self, note_id: str) -> bool:
        return self.runtime.sync_note_to_graph(note_id)

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

    def set_thread_message_loader(self, loader):
        self.runtime.set_thread_message_loader(loader)

    def load_thread_messages(self, *args, **kwargs):
        return self.runtime.load_thread_messages(*args, **kwargs)

    def execute_entry(self, *args, **kwargs):
        return self.runtime.execute_entry(*args, **kwargs)

    def resume_entry(self, *args, **kwargs):
        return self.runtime.resume_entry(*args, **kwargs)

    def get_run_snapshot(self, run_id: str):
        return self.runtime.get_run_snapshot(run_id)

    def list_run_snapshots(self, user_id: str | None = None, limit: int = 50):
        return self.runtime.list_run_snapshots(user_id=user_id, limit=limit)

    def list_run_history(self, run_id: str, limit: int = 100):
        return self.runtime.list_run_history(run_id, limit=limit)

    def replay_from_checkpoint(self, **kwargs):
        return self.runtime.replay_from_checkpoint(**kwargs)

    def execute_digest(self, user_id: str | None = None):
        return self.runtime.execute_digest(user_id=user_id)

    def reset_debug_data(self):
        return self.runtime.reset_debug_data()

    def digest(self, user_id: str | None = None):
        return self.runtime.digest(user_id=user_id)

    def entry(self, *args, **kwargs):
        return self.runtime.entry(*args, **kwargs)
