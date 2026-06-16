"""Run-scoped context for the staged ask pipeline.

The ask flow is split into three bounded stages (retrieval, generation,
verification) that map 1:1 onto the ``ask-retrieve`` / ``ask-compose`` /
``ask-verify`` workflow steps. ``AskRunContext`` is the mutable carrier that
threads intermediate state between those stages within a single run.

The large retrieval payload (evidence pool, context pack, scored matches) is
intentionally kept here, by reference, rather than on the checkpointed
``AgentGraphState`` — mirroring the long-standing "summary form to avoid
checkpoint bloat" design. ``AskRunContextStore`` gives that payload an explicit
lifecycle (put / get / clear) instead of a module-global dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...core.evidence import ContextPack, EvidenceItem
from ...core.models import Citation, KnowledgeNote
from ...core.query_understanding import QueryUnderstanding, RetrievalPlan


@dataclass
class AskRunContext:
    """Mutable per-run carrier threaded across the three ask stages."""

    question: str
    user_id: str
    session_id: str
    working_context: str
    structured_context: str = ""
    has_dialogue_context: bool = False
    trace_id: str = ""

    # Query understanding (filled by RetrievalStage)
    understanding: QueryUnderstanding | None = None
    retrieval_plan: RetrievalPlan | None = None
    effective_query: str = ""

    # Evidence pool + accumulated candidates (filled by RetrievalStage / web fallback)
    evidence_pool: list[EvidenceItem] = field(default_factory=list)
    combined_matches: list[KnowledgeNote] = field(default_factory=list)
    combined_citations: list[Citation] = field(default_factory=list)
    web_tried: bool = False

    # Context assembly output
    context_pack: ContextPack | None = None
    selected_matches: list[KnowledgeNote] = field(default_factory=list)
    selected_citations: list[Citation] = field(default_factory=list)

    # Generation + verification output
    answer: str = ""
    verification: object | None = None

    # Human-readable trace breadcrumbs (parity with the old add_trace_step)
    trace_steps: list[str] = field(default_factory=list)

    def add_trace(self, message: str) -> None:
        self.trace_steps.append(message)

    @property
    def web_search_enabled_for_selected(self) -> bool:
        return any(c.source_type == "web" for c in self.selected_citations)

    @property
    def thread_key(self) -> str:
        return f"{self.user_id}:{self.session_id}"


class AskRunContextStore:
    """Run-scoped store for :class:`AskRunContext`, keyed by ``run_id``.

    Replaces the former module-global ``_ASK_RUN_CACHE``. Injected through
    ``OrchestrationDeps`` so the retrieve step can stash the context and the
    compose / verify steps can read it back, with an explicit ``clear`` at
    finalize time to avoid leaks.
    """

    def __init__(self) -> None:
        self._by_run: dict[str, AskRunContext] = {}

    def put(self, run_id: str, ctx: AskRunContext) -> None:
        if run_id:
            self._by_run[run_id] = ctx

    def get(self, run_id: str) -> AskRunContext | None:
        return self._by_run.get(run_id)

    def clear(self, run_id: str) -> None:
        self._by_run.pop(run_id, None)
