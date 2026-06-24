from __future__ import annotations

import logging
from uuid import uuid4

from personal_agent.kernel.evidence import (
    EvidenceItem,
    graph_result_to_evidence,
    notes_to_evidence,
)
from personal_agent.kernel.models import AgentState, Citation, KnowledgeNote
from personal_agent.kernel.prompts import get_prompt, render_prompt
from personal_agent.kernel.projections import MatchRef
from personal_agent.kernel.query_understanding import RetrievalFilters
from personal_agent.memory.graphiti.store import GraphAskResult
from personal_agent.agent.ask import AskRunContext
from personal_agent.agent.ask.evidence_ops import (
    graph_matches_to_evidence as _graph_matches_to_evidence,
    match_refs as _match_refs,
    selected_citations as _selected_citations,
    selected_matches as _selected_matches,
)
from personal_agent.agent.ask.prompts import AskPromptMixin
from personal_agent.agent.ask.stages import GenerationStage, RetrievalStage, VerificationStage
from personal_agent.agent.ask_pipeline_factory import AskPipelineComponents, AskPipelineFactory
from personal_agent.agent.query_planner import plan_retrieval
from personal_agent.agent.runtime_helpers import (
    _best_snippet,
    _graph_episode_uuids,
    _graph_fact_lines,
    _graph_facts_by_episode,
    _merge_citations,
    _merge_notes,
)
from personal_agent.agent.runtime_results import AskResult, RetryResult
from personal_agent.agent.verifier import VerificationResult

logger = logging.getLogger(__name__)

def _conversation_messages_text(messages: list[dict[str, str]]) -> str:
    # 入参通常已由短期记忆策略窗口化；此处统一渲染为「用户/助手」文本。
    from personal_agent.memory.short_term_context import render_as_text

    return render_as_text(messages)


class AskService(AskPromptMixin):
    """Ask pipeline as an explicit collaborator.

    Previously ``RuntimeAskMixin`` mixed into ``AgentRuntime`` and reached
    sibling methods (``_generate_answer``) and fields via a shared ``self``.
    It now receives its dependencies explicitly, including a shared
    ``LlmClient``.
    """

    def __init__(
        self,
        *,
        settings,
        graph_store,
        ms_graphrag_store,
        structural_retriever,
        memory,
        tool_executor,
        verifier,
        llm,
    ) -> None:
        self.settings = settings
        self.graph_store = graph_store
        self.ms_graphrag_store = ms_graphrag_store
        self.structural_retriever = structural_retriever
        self.memory = memory
        self._tool_executor = tool_executor
        self._verifier = verifier
        self._llm = llm
        self.dialogue_context_policy = get_prompt("answer.dialogue_context_policy").template

    @property
    def _web_search_available(self) -> bool:
        return bool(self.settings.web_search.api_key)

    @staticmethod
    def _match_refs(matches: list[KnowledgeNote]) -> list[MatchRef]:
        return _match_refs(matches)

    @property
    def _ask_components(self) -> "AskPipelineComponents":
        """Assembled enricher + reranker + budget for this run.

        Built per access (cheap) so settings swapped on the service after
        construction take effect, matching the runtime's per-call build style.
        """
        return AskPipelineFactory(self.settings).create()

    def _plan_retrieval(self, question: str, structured_context: str):
        """Indirection so tests monkeypatching ``runtime_ask.plan_retrieval``
        still take effect when the stage calls through the service."""
        return plan_retrieval(question, structured_context, self.settings)

    def build_run_context(
        self,
        question: str,
        user_id: str | None = None,
        session_id: str | None = None,
        conversation_messages: list[dict[str, str]] | None = None,
    ) -> AskRunContext:
        normalized_user = user_id or self.settings.default_user
        normalized_session = session_id or "default"
        logger.info("Starting ask user=%s question=%s", normalized_user, question[:120])
        self.memory.bind_session(normalized_user, normalized_session)
        structured_context = _conversation_messages_text(conversation_messages or [])
        has_dialogue_context = bool(structured_context)
        context_parts = [f"当前任务目标：回答用户问题: {question[:80]}"]
        if has_dialogue_context:
            context_parts.append(
                "当前会话对话线索（仅用于理解追问和更正，不作为事实证据）：\n"
                f"{structured_context}"
            )
        return AskRunContext(
            question=question,
            user_id=normalized_user,
            session_id=normalized_session,
            working_context="\n\n".join(context_parts),
            structured_context=structured_context,
            has_dialogue_context=has_dialogue_context,
            trace_id=uuid4().hex[:12],
        )

    # --- Staged entrypoints (one per ask-* workflow step) ---

    def run_retrieval_stage(self, ctx: AskRunContext) -> None:
        """ask-retrieve: query understanding + multi-source recall + assembly."""
        RetrievalStage(self).run(ctx)

    def run_generation_stage(self, ctx: AskRunContext) -> None:
        """ask-compose: pure generation from the assembled ContextPack."""
        GenerationStage(self).run(ctx)

    def run_verification_stage(self, ctx: AskRunContext) -> None:
        """ask-verify: verify + retry + web fallback + annotate."""
        VerificationStage(self, RetrievalStage(self)).run(ctx)

    def context_to_result(self, ctx: AskRunContext) -> AskResult:
        ordered_matches = _selected_matches(ctx.combined_matches, ctx.context_pack.evidence)
        result_citations = _selected_citations(ctx.combined_citations, ctx.context_pack.evidence)
        ask_result = AskResult(
            answer=ctx.answer,
            citations=result_citations,
            matches=ordered_matches,
            match_refs=_match_refs(ordered_matches),
            evidence=ctx.context_pack.evidence,
            session_id=ctx.session_id,
        )
        verification = ctx.verification
        logger.info(
            "Ask resolved from unified evidence user=%s matches=%s citations=%s evidence=%s verify=%.2f",
            ctx.user_id,
            len(ordered_matches),
            len(result_citations),
            len(ctx.context_pack.evidence),
            verification.evidence_score if verification else 0.0,
        )
        return ask_result

    def execute_ask(
        self,
        question: str,
        user_id: str | None = None,
        session_id: str | None = None,
        conversation_messages: list[dict[str, str]] | None = None,
    ) -> AskResult:
        """Thin orchestration over the three stages.

        Kept as the whole-pipeline entrypoint for evals (``current_runtime_ask``)
        and unit tests. The orchestration graph instead drives the three stages
        individually via the ask-retrieve / ask-compose / ask-verify steps so the
        step panel reflects each phase honestly.
        """
        ctx = self.build_run_context(question, user_id, session_id, conversation_messages)
        self.run_retrieval_stage(ctx)
        self.run_generation_stage(ctx)
        self.run_verification_stage(ctx)
        return self.context_to_result(ctx)

    @staticmethod
    def _graph_has_evidence(
        graph_result: GraphAskResult,
        matches: list[KnowledgeNote],
        citations: list[Citation],
    ) -> bool:
        return bool(
            graph_result.answer
            or graph_result.relation_facts
            or graph_result.node_refs
            or graph_result.edge_refs
            or graph_result.fact_refs
            or matches
            or citations
        )

    def _run_graph_retrieval(
        self,
        provider: str,
        question: str,
        user_id: str,
        trace_id: str,
        filters: RetrievalFilters | None = None,
    ) -> GraphAskResult | AgentState | None:
        if provider == "structural":
            return self._run_structural_retrieval(question, user_id, filters)
        if provider in {"ms_graphrag", "microsoft_graphrag", "graphrag"}:
            if not self.ms_graphrag_store.configured():
                return None
            return self.ms_graphrag_store.ask(question, user_id, trace_id=trace_id)
        if provider == "hybrid":
            structural_state = self._run_structural_retrieval(question, user_id, filters)
            if not self.graph_store.configured():
                return structural_state
            graph_result = self.graph_store.ask(question, user_id, trace_id=trace_id)
            if not graph_result.enabled:
                return structural_state
            graph_matches, graph_citations = self._graph_matches_and_citations(
                user_id, question, graph_result, filters
            )
            graph_evidence: list[EvidenceItem] = []
            if not (filters and filters.active() and not graph_matches and not graph_citations):
                notes_by_episode = {
                    note.graph.episode_uuid: note
                    for note in graph_matches
                    if note.graph.episode_uuid is not None
                }
                if self._graph_has_evidence(graph_result, graph_matches, graph_citations):
                    graph_evidence.extend(
                        graph_result_to_evidence(graph_result, notes_by_episode, question)
                    )
                    graph_evidence.extend(
                        _graph_matches_to_evidence(
                            question,
                            graph_matches,
                            graph_citations,
                            mode=self.settings.ask.graph_note_evidence_mode,
                            min_overlap=self.settings.ask.graph_note_evidence_min_overlap,
                        )
                    )
            return AgentState(
                mode="ask",
                question=question,
                user_id=user_id,
                matches=_merge_notes(structural_state.matches, graph_matches),
                citations=_merge_citations(structural_state.citations, graph_citations),
                evidence=[*structural_state.evidence, *graph_evidence],
                answer=structural_state.answer or graph_result.answer,
            )
        if provider != "graphiti":
            logger.warning("Unknown graph provider=%s; falling back to graphiti", provider)
        if not self.graph_store.configured():
            return None
        return self.graph_store.ask(question, user_id, trace_id=trace_id)

    def _run_structural_retrieval(
        self,
        question: str,
        user_id: str,
        filters: RetrievalFilters | None = None,
    ) -> AgentState:
        matches, citations = self.structural_retriever.ask(
            question,
            user_id,
            limit=self.settings.graphiti.search_limit,
            filters=filters,
        )
        evidence = [
            item.model_copy(
                update={
                    "score": max(item.score, 0.58),
                    "metadata": {
                        **item.metadata,
                        "retrieved_by": "structural",
                    },
                }
            )
            for item in notes_to_evidence(matches)
        ]
        return AgentState(
            mode="ask",
            question=question,
            user_id=user_id,
            matches=matches,
            citations=citations,
            evidence=evidence,
            answer=matches[0].body.summary if matches else None,
        )

    def _run_local_retrieval(
        self,
        question: str,
        user_id: str,
        filters: RetrievalFilters | None = None,
    ) -> AgentState:
        """Run local note retrieval and return an ask-shaped state."""
        matches = self.memory.search_memory(user_id, question, filters=filters)
        citations = [
            Citation(note_id=note.id, title=note.body.title, snippet=note.body.summary[:80])
            for note in matches
        ]
        answer = None
        if matches:
            answer = f"根据你已有的笔记，最相关的结论是：{matches[0].body.summary}"
        return AgentState(
            mode="ask",
            question=question,
            user_id=user_id,
            matches=matches,
            citations=citations,
            answer=answer,
        )

    def _execute_web_search(self, question: str) -> tuple[list[dict], list[Citation]]:
        """Run web search and convert results to Citation list.

        Returns (raw_results, citations). Both empty if unavailable or failed.
        """
        if not self._web_search_available:
            return [], []
        try:
            tool = self._tool_executor.get("web_search")
            if tool is None:
                return [], []
            result = self._tool_executor.invoke_direct("web_search", query=question, limit=5)
            if not result.get("ok") or not result.get("data"):
                return [], []
            raw_results = result["data"].get("results", [])
            if not isinstance(raw_results, list):
                return [], []
            citations: list[Citation] = []
            for r in raw_results[:5]:
                if not isinstance(r, dict):
                    continue
                citations.append(Citation(
                    note_id="",
                    title=str(r.get("title", "")),
                    snippet=str(r.get("snippet", "")),
                    url=str(r.get("url", "")),
                    source_type="web",
                ))
            return raw_results, citations
        except Exception:
            logger.exception("Web search failed for question=%s", question[:80])
            return [], []

    def _graph_citations(self, matches: list[KnowledgeNote], graph_result: GraphAskResult) -> list[Citation]:
        citations: list[Citation] = []
        facts_by_episode = _graph_facts_by_episode(graph_result)
        fallback_facts = _graph_fact_lines(graph_result, limit=8)
        for index, note in enumerate(matches[:5]):
            relation_fact = None
            if note.graph.episode_uuid:
                episode_facts = facts_by_episode.get(note.graph.episode_uuid, [])
                if episode_facts:
                    relation_fact = episode_facts[0]
            if relation_fact is None and index < len(fallback_facts):
                relation_fact = fallback_facts[index]
            citations.append(Citation(
                note_id=note.id, title=note.body.title,
                snippet=note.body.summary[:120],
                relation_fact=relation_fact,
            ))
        return citations

    def _graph_matches_and_citations(
        self,
        user_id: str,
        question: str,
        graph_result: GraphAskResult,
        filters: RetrievalFilters | None = None,
    ) -> tuple[list[KnowledgeNote], list[Citation]]:
        episode_uuids = _graph_episode_uuids(graph_result)
        matches = self.memory.find_by_graph_episodes(user_id, episode_uuids, filters=filters)
        if not graph_result.citation_hits:
            return matches, self._graph_citations(matches, graph_result)

        notes_by_episode_uuid = {n.graph.episode_uuid: n for n in matches if n.graph.episode_uuid is not None}
        citations: list[Citation] = []
        matched_notes: list[KnowledgeNote] = []
        seen_note_ids: set[str] = set()
        seen_citation_keys: set[tuple[str, str]] = set()

        for hit in graph_result.citation_hits:
            note = notes_by_episode_uuid.get(hit.episode_uuid)
            if note is None:
                continue
            citation_key = (note.id, hit.relation_fact)
            if citation_key not in seen_citation_keys:
                citations.append(Citation(
                    note_id=note.id, title=note.body.title,
                    snippet=_best_snippet(note, hit, question),
                    relation_fact=hit.relation_fact,
                ))
                seen_citation_keys.add(citation_key)
            if note.id not in seen_note_ids:
                matched_notes.append(note)
                seen_note_ids.add(note.id)
            if len(citations) >= 5:
                break

        for note in matches:
            if note.id not in seen_note_ids:
                matched_notes.append(note)
                seen_note_ids.add(note.id)
        return matched_notes, citations

    def _retry_if_needed(
        self,
        question: str,
        answer: str,
        citations: list[Citation],
        matches: list[KnowledgeNote],
        verification: VerificationResult,
        web_enabled: bool = False,
        evidence: list[EvidenceItem] | None = None,
    ) -> RetryResult:
        max_retries = max(0, self.settings.max_verify_retries)
        current_answer = answer
        current_verification = verification
        attempts = 0
        for attempt in range(max_retries):
            if current_verification.ok and current_verification.sufficient:
                break
            correction_prompt = self._build_correction_prompt(
                question,
                current_answer,
                current_verification,
                evidence=evidence,
            )
            prompt_spec = get_prompt("ask.correction.user")
            regenerated = self._llm.generate_answer(
                correction_prompt,
                prompt_name="ask_correction",
                prompt_version=prompt_spec.version,
            )
            if regenerated:
                current_answer = regenerated
                current_verification = self._verifier.verify(
                    question, current_answer, citations, _match_refs(matches),
                    web_enabled=web_enabled,
                    evidence=evidence,
                )
                attempts = attempt + 1
                logger.debug(
                    "ask retry %d score=%.2f ok=%s",
                    attempt + 1,
                    current_verification.evidence_score,
                    current_verification.ok,
                )
            else:
                break
        return RetryResult(answer=current_answer, verification=current_verification, attempts=attempts)

    def _build_correction_prompt(
        self,
        question: str,
        answer: str,
        verification: VerificationResult,
        evidence: list[EvidenceItem] | None = None,
    ) -> str:
        issues_text = "\n".join(f"- {i}" for i in verification.issues) if verification.issues else "无"
        warnings_text = "\n".join(f"- {w}" for w in verification.warnings) if verification.warnings else "无"
        claim_lines: list[str] = []
        for item in verification.claim_checks:
            if item.status == "supported":
                continue
            evidence_ids = ", ".join(item.supporting_evidence_ids) if item.supporting_evidence_ids else "无"
            claim_lines.append(
                f"- [{item.status}] {item.claim} | evidence_ids={evidence_ids} | {item.reason}"
            )
        claims_text = "\n".join(claim_lines) if claim_lines else "无"

        evidence_lines: list[str] = []
        for index, item in enumerate((evidence or [])[:8], 1):
            content = item.fact or item.snippet or item.title
            evidence_lines.append(
                f"- E{index}/{item.evidence_id} {item.source_type} {item.title}: {content[:220]}"
            )
        evidence_text = "\n".join(evidence_lines) if evidence_lines else "无"
        return render_prompt(
            "ask.correction.user",
            question=question,
            answer=answer,
            issues_text=issues_text,
            warnings_text=warnings_text,
            claims_text=claims_text,
            evidence_text=evidence_text,
        )
