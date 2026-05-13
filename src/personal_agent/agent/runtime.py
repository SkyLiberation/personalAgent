from __future__ import annotations

from datetime import datetime
import logging
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from openai import OpenAI
from pydantic import BaseModel, Field

from ..core.config import Settings
from ..core.logging_utils import log_event, trace_span
from ..core.models import AgentState, AskHistoryRecord, Citation, EntryInput, EntryIntent, KnowledgeNote, PendingAction, RawIngestItem, ReviewCard
from ..graphiti.store import GraphAskResult, GraphCaptureResult, GraphCitationHit, GraphitiStore
from ..storage.ask_history_store import AskHistoryStore
from ..storage.cross_session_store import CrossSessionStore
from ..memory import MemoryFacade
from ..storage.memory_store import LocalMemoryStore
from ..storage.pending_action_store import PendingActionStore
from ..tools import CaptureTextTool, CaptureUploadTool, CaptureUrlTool, DeleteNoteTool, GraphSearchTool, ToolRegistry
from .entry_nodes import (
    EntryNodeDeps,
    ask_entry_branch_node,
    capture_entry_branch_node,
    direct_answer_entry_branch_node,
    route_entry_intent_node,
    summarize_entry_branch_node,
    unknown_entry_branch_node,
)
from .graph import build_ask_graph, build_capture_graph, build_entry_graph
from .nodes import digest_node
from .plan_executor import PlanExecutor, ProgressCallback
from .planner import DefaultTaskPlanner
from .plan_validator import PlanValidator
from .replanner import Replanner
from .router import DefaultIntentRouter, RouterDecision
from .verifier import AnswerVerifier, VerificationResult

if TYPE_CHECKING:
    from ..capture import CaptureService

logger = logging.getLogger(__name__)


class CaptureResult(BaseModel):
    note: KnowledgeNote
    related_notes: list[KnowledgeNote] = Field(default_factory=list)
    review_card: ReviewCard | None = None
    graph_enabled: bool = False


class AskResult(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    matches: list[KnowledgeNote] = Field(default_factory=list)
    graph_enabled: bool = False
    session_id: str = "default"


class DigestResult(BaseModel):
    message: str
    recent_notes: list[KnowledgeNote] = Field(default_factory=list)
    due_reviews: list[ReviewCard] = Field(default_factory=list)


class EntryResult(BaseModel):
    intent: EntryIntent
    reason: str
    reply_text: str
    capture_result: CaptureResult | None = None
    ask_result: AskResult | None = None
    plan_steps: list[dict[str, object]] = Field(default_factory=list)


class ResetResult(BaseModel):
    user_id: str
    deleted_notes: int = 0
    deleted_reviews: int = 0
    deleted_conversations: int = 0
    deleted_upload_files: int = 0
    deleted_ask_history: int = 0
    deleted_graph_episodes: int = 0


class AgentRuntime:
    """Unified execution runtime for capture / ask / digest / entry operations.

    Extracted from AgentService to provide a single execution entry point.
    Owns the tool registry, memory facade, verifier, and graph execution.
    """

    def __init__(
        self,
        settings: Settings,
        store: LocalMemoryStore,
        graph_store: GraphitiStore,
        ask_history_store: AskHistoryStore,
        capture_service: "CaptureService | None" = None,
        pending_action_store: PendingActionStore | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.graph_store = graph_store
        self.ask_history_store = ask_history_store
        self.pending_action_store = pending_action_store or PendingActionStore(settings.data_dir)
        self.capture_service = capture_service
        self._intent_router = DefaultIntentRouter(settings)
        self._tool_registry = ToolRegistry()
        self._register_tools()
        self._planner = DefaultTaskPlanner(settings, tool_registry=self._tool_registry)
        self._cross_session = CrossSessionStore(settings.data_dir)
        self.memory = MemoryFacade(store, ask_history_store, cross_session_store=self._cross_session)
        self._verifier = AnswerVerifier()
        self._plan_validator = PlanValidator(tool_registry=self._tool_registry)
        self._replanner = Replanner(settings)

    def _register_tools(self) -> None:
        if self.capture_service is not None:
            self._tool_registry.register(CaptureUrlTool(self.capture_service))
            self._tool_registry.register(
                CaptureUploadTool(self.capture_service, self.settings.data_dir / "uploads")
            )
        self._tool_registry.register(GraphSearchTool(self.graph_store))
        self._tool_registry.register(CaptureTextTool(self))
        self._tool_registry.register(DeleteNoteTool(self.store, self.graph_store, self.pending_action_store))

    def list_tools(self) -> list:
        return self._tool_registry.list_tools()

    def execute_tool(self, name: str, **kwargs: object):
        return self._tool_registry.execute(name, **kwargs)

    def execute_capture(
        self,
        text: str,
        source_type: str = "text",
        user_id: str | None = None,
        source_ref: str | None = None,
        attempt_graph: bool = True,
    ) -> CaptureResult:
        normalized_user = user_id or self.settings.default_user
        logger.info("Starting capture user=%s source_type=%s", normalized_user, source_type)
        self.memory.working.set_goal(f"采集知识: {text[:80]}")
        graph = build_capture_graph(self.store)
        state = AgentState(
            mode="capture",
            user_id=normalized_user,
            raw_item=RawIngestItem(
                content=text,
                source_type=source_type,
                source_ref=source_ref,
                user_id=normalized_user,
            ),
        )
        result = AgentState.model_validate(graph.invoke(state))
        if result.note is None:
            raise ValueError("Capture flow did not produce a note.")

        if not attempt_graph:
            result.note.graph_sync_status = "pending" if self.graph_store.configured() else "idle"
            result.note.graph_sync_error = None
            self.store.update_note(result.note)
            logger.info(
                "Capture stored without immediate graph sync user=%s note_id=%s graph_sync_status=%s",
                normalized_user, result.note.id, result.note.graph_sync_status,
            )
            return CaptureResult(
                note=result.note,
                related_notes=result.matches,
                review_card=result.review_card,
                graph_enabled=False,
            )

        graph_result = self.graph_store.ingest_note(result.note)
        related_notes = result.matches
        if graph_result.enabled:
            updated_note = self._merge_graph_capture(result.note, graph_result)
            self.store.update_note(updated_note)
            result.note = updated_note
            graph_related_notes = self.store.find_notes_by_graph_episode_uuids(
                normalized_user, graph_result.related_episode_uuids
            )
            related_notes = _merge_notes(graph_related_notes, related_notes)
            updated_note.related_note_ids = [n.id for n in related_notes if n.id != updated_note.id]
            updated_note.updated_at = datetime.utcnow()
            self.store.update_note(updated_note)
            result.note = updated_note
        elif self.graph_store.configured():
            result.note.graph_sync_status = "failed"
            result.note.graph_sync_error = graph_result.error or "Graphiti ingest returned disabled result."
            result.note.updated_at = datetime.utcnow()
            self.store.update_note(result.note)

        logger.info(
            "Capture finished user=%s note_id=%s graph_enabled=%s related_notes=%s",
            normalized_user, result.note.id, graph_result.enabled, len(related_notes),
        )
        return CaptureResult(
            note=result.note,
            related_notes=related_notes,
            review_card=result.review_card,
            graph_enabled=graph_result.enabled,
        )

    def execute_ask(
        self, question: str, user_id: str | None = None, session_id: str | None = None
    ) -> AskResult:
        normalized_user = user_id or self.settings.default_user
        normalized_session = session_id or "default"
        logger.info("Starting ask user=%s question=%s", normalized_user, question[:120])
        self.memory.bind_session(normalized_user, normalized_session)
        self.memory.working.set_goal(f"回答用户问题: {question[:80]}")
        self.memory.refresh_conversation_summary(normalized_user, normalized_session)
        working_context = self.memory.working.context_snapshot()
        trace_id = uuid4().hex[:12]

        graph_result = self.graph_store.ask(question, normalized_user, trace_id=trace_id)
        if graph_result.enabled:
            matches, citations = self._graph_matches_and_citations(normalized_user, question, graph_result)
            answer = self._compose_graph_answer(question, graph_result, matches, citations, working_context)
            verification = self._verifier.verify(question, answer, citations, matches, graph_enabled=True)
            answer = self._retry_if_needed(question, answer, citations, matches, verification, graph_enabled=True)
            verification = self._verifier.verify(question, answer, citations, matches, graph_enabled=True)
            if not verification.ok or not verification.sufficient:
                answer = _annotate_answer(answer, verification)
            self.memory.working.add_step(f"Verifier: score={verification.evidence_score:.2f} ok={verification.ok}")
            ask_result = AskResult(
                answer=answer,
                citations=citations,
                matches=matches,
                graph_enabled=True,
                session_id=normalized_session,
            )
            self.memory.record_turn(
                normalized_user, normalized_session, question, answer,
                citations=citations, graph_enabled=True,
            )
            logger.info(
                "Ask resolved from graph user=%s matches=%s citations=%s verify=%.2f",
                normalized_user, len(matches), len(citations), verification.evidence_score,
            )
            return ask_result

        graph = build_ask_graph(self.store)
        state = AgentState(mode="ask", question=question, user_id=normalized_user)
        result = AgentState.model_validate(graph.invoke(state))
        answer = self._compose_local_answer(question, result.matches, result.citations, working_context)
        final_answer = answer or result.answer or "暂时没有生成答案。"
        verification = self._verifier.verify(question, final_answer, result.citations, result.matches, graph_enabled=False)
        final_answer = self._retry_if_needed(question, final_answer, result.citations, result.matches, verification, graph_enabled=False)
        verification = self._verifier.verify(question, final_answer, result.citations, result.matches, graph_enabled=False)
        if not verification.ok or not verification.sufficient:
            final_answer = _annotate_answer(final_answer, verification)
        self.memory.working.add_step(f"Verifier: score={verification.evidence_score:.2f} ok={verification.ok}")
        ask_result = AskResult(
            answer=final_answer,
            citations=result.citations,
            matches=result.matches,
            graph_enabled=False,
            session_id=normalized_session,
        )
        self.memory.record_turn(
            normalized_user, normalized_session, question, final_answer,
            citations=result.citations, graph_enabled=False,
        )
        logger.info(
            "Ask resolved locally user=%s matches=%s citations=%s verify=%.2f",
            normalized_user, len(result.matches), len(result.citations), verification.evidence_score,
        )
        return ask_result

    def execute_digest(self, user_id: str | None = None) -> DigestResult:
        normalized_user = user_id or self.settings.default_user
        logger.info("Generating digest user=%s", normalized_user)
        return DigestResult(
            message=digest_node(self.store, normalized_user),
            recent_notes=self.store.list_notes(normalized_user)[-5:],
            due_reviews=self.store.due_reviews(normalized_user),
        )

    def execute_entry(self, entry_input: EntryInput, on_progress: ProgressCallback = None) -> EntryResult:
        normalized_user = entry_input.user_id or self.settings.default_user
        normalized_session = entry_input.session_id or "default"
        self.memory.bind_session(normalized_user, normalized_session)
        self.memory.refresh_conversation_summary(normalized_user, normalized_session)
        decision = self._intent_router.classify(entry_input)
        self.memory.working.set_goal(f"入口任务[{decision.route}]: {entry_input.text[:60]}")
        steps = self._planner.plan(decision.route, entry_input.text)
        validation = self._plan_validator.validate(steps, decision)
        if validation.blocking:
            logger.warning(
                "Plan validation blocked: %d issues, %d warnings. Issues: %s",
                len(validation.issues), len(validation.warnings), validation.issues,
            )
            if validation.corrected_steps:
                validated_steps = validation.corrected_steps
            else:
                # Fall back to heuristic planner for a known-safe plan
                logger.info("Replanning with heuristic due to validation blocking issues")
                validated_steps = self._planner.fallback_plan(decision.route)
                revalidation = self._plan_validator.validate(validated_steps, decision)
                if revalidation.blocking:
                    logger.error("Heuristic plan also blocked: %s. Falling back to direct_answer.", revalidation.issues)
                    decision = RouterDecision(
                        route="unknown",
                        confidence=0.1,
                        risk_level="low",
                        user_visible_message=f"计划校验失败: {'; '.join(revalidation.issues[:3])}",
                    )
                    validated_steps = self._planner.fallback_plan("unknown")
        else:
            validated_steps = validation.corrected_steps or steps
            if not validation.ok:
                logger.warning(
                    "Plan validation found %d non-blocking issues: %s",
                    len(validation.issues), validation.issues,
                )
        self.memory.working.plan_steps = [
            {
                "step_id": s.step_id, "action_type": s.action_type,
                "description": s.description, "tool_name": s.tool_name,
                "tool_input": s.tool_input, "depends_on": s.depends_on,
                "expected_output": s.expected_output,
                "success_criteria": s.success_criteria,
                "risk_level": s.risk_level,
                "requires_confirmation": s.requires_confirmation,
                "on_failure": s.on_failure, "status": s.status,
                "retry_count": s.retry_count,
            }
            for s in validated_steps
        ]
        log_event(logger, logging.INFO, "entry.planned",
            user_id=normalized_user, session_id=normalized_session,
            route=decision.route, confidence=decision.confidence,
            risk_level=decision.risk_level,
            requires_confirmation=decision.requires_confirmation,
            plan_step_count=len(self.memory.working.plan_steps),
            plan_steps=self.memory.working.plan_steps,
        )

        if decision.requires_planning and validated_steps:
            # Plan-driven execution: delete_knowledge, solidify_conversation
            logger.info("Using PlanExecutor for intent=%s steps=%d", decision.route, len(validated_steps))
            executor = PlanExecutor(self, self.memory, replanner=self._replanner)
            state = AgentState(
                mode="entry",
                user_id=normalized_user,
                intent=decision.route,
                entry_input=entry_input.model_copy(update={"user_id": normalized_user, "session_id": normalized_session}),
            )
            result = executor.execute(validated_steps, state, on_progress=on_progress)
            reply_text = result.answer or "计划执行完成。"
            # Update plan_steps with execution status
            self.memory.working.plan_steps = [
                {
                    "step_id": s.step_id, "action_type": s.action_type,
                    "description": s.description, "tool_name": s.tool_name,
                    "tool_input": s.tool_input, "depends_on": s.depends_on,
                    "expected_output": s.expected_output,
                    "success_criteria": s.success_criteria,
                    "risk_level": s.risk_level,
                    "requires_confirmation": s.requires_confirmation,
                    "on_failure": s.on_failure, "status": s.status,
                    "retry_count": s.retry_count,
                }
                for s in validated_steps
            ]
            return EntryResult(
                intent=decision.route,
                reason=decision.user_visible_message,
                reply_text=reply_text,
                plan_steps=self.memory.working.plan_steps,
            )

        # Existing graph path for capture/ask/summarize/direct_answer/unknown
        entry_node_deps = EntryNodeDeps(
            classify_intent=self._intent_router.classify,
            capture=self.execute_capture,
            ask=self.execute_ask,
            capture_service=self.capture_service,
            summarize_thread=self._summarize_thread,
            llm_configured=bool(
                self.settings.openai_api_key
                and self.settings.openai_base_url
                and self.settings.openai_small_model
            ),
            settings=self.settings,
        )
        graph = build_entry_graph(
            lambda state: route_entry_intent_node(state, entry_node_deps),
            lambda state: capture_entry_branch_node(state, entry_node_deps),
            lambda state: ask_entry_branch_node(state, entry_node_deps),
            lambda state: summarize_entry_branch_node(state, entry_node_deps),
            unknown_entry_branch_node,
            direct_answer_branch_node=lambda state: direct_answer_entry_branch_node(state, entry_node_deps),
        )
        state = AgentState(
            mode="entry",
            user_id=normalized_user,
            entry_input=entry_input.model_copy(update={"user_id": normalized_user, "session_id": normalized_session}),
        )
        result = AgentState.model_validate(graph.invoke(state))
        reply_text = result.answer or "暂时没有可执行的结果。"

        capture_result = None
        ask_result = None
        if result.note is not None:
            capture_result = CaptureResult(
                note=result.note,
                related_notes=result.matches,
                review_card=result.review_card,
                graph_enabled=result.note.graph_sync_status == "synced",
            )
        elif result.question:
            ask_result = AskResult(
                answer=reply_text,
                citations=result.citations,
                matches=result.matches,
                graph_enabled=bool(result.citations or result.matches),
                session_id=normalized_session,
            )

        return EntryResult(
            intent=result.intent,
            reason=result.intent_reason or "未提供路由说明。",
            reply_text=reply_text,
            capture_result=capture_result,
            ask_result=ask_result,
            plan_steps=self.memory.working.plan_steps,
        )

    def sync_note_to_graph(self, note_id: str) -> bool:
        note = self.store.get_note(note_id)
        if note is None:
            logger.warning("Graph sync skipped because note_id=%s was not found", note_id)
            return False
        if not self.graph_store.configured():
            logger.info("Graph sync skipped because graph is not configured note_id=%s", note_id)
            note.graph_sync_status = "idle"
            note.graph_sync_error = None
            note.updated_at = datetime.utcnow()
            self.store.update_note(note)
            return False

        trace_id = uuid4().hex[:12]
        max_attempts = max(1, self.settings.graph_sync_max_attempts)
        logger.info("Starting background graph sync note_id=%s trace_id=%s", note_id, trace_id)
        note.graph_sync_status = "pending"
        note.graph_sync_error = None
        note.updated_at = datetime.utcnow()
        self.store.update_note(note)

        last_error: str | None = None
        with trace_span(
            logger, "agent.sync_note_to_graph",
            trace_id=trace_id, note_id=note_id, user_id=note.user_id, max_attempts=max_attempts,
        ):
            for attempt in range(1, max_attempts + 1):
                note = self.store.get_note(note_id) or note
                note.graph_sync_status = "pending"
                note.updated_at = datetime.utcnow()
                self.store.update_note(note)

                log_event(logger, logging.INFO, "graph_sync.attempt.started",
                    trace_id=trace_id, note_id=note_id, user_id=note.user_id,
                    attempt=attempt, max_attempts=max_attempts)

                graph_result = self.graph_store.ingest_note(note, trace_id=trace_id, attempt=attempt)
                if graph_result.enabled:
                    updated_note = self._merge_graph_capture(note, graph_result)
                    related_notes = self.store.find_notes_by_graph_episode_uuids(
                        note.user_id, graph_result.related_episode_uuids
                    )
                    updated_note.related_note_ids = [item.id for item in related_notes if item.id != updated_note.id]
                    updated_note.updated_at = datetime.utcnow()
                    self.store.update_note(updated_note)
                    log_event(logger, logging.INFO, "graph_sync.completed",
                        trace_id=trace_id, note_id=note_id, user_id=note.user_id, attempt=attempt,
                        episode_uuid=updated_note.graph_episode_uuid,
                        entity_count=len(updated_note.entity_names),
                        relation_count=len(updated_note.relation_facts))
                    logger.info(
                        "Background graph sync succeeded note_id=%s episode_uuid=%s entities=%s relations=%s",
                        note_id, updated_note.graph_episode_uuid,
                        len(updated_note.entity_names), len(updated_note.relation_facts),
                    )
                    return True

                last_error = graph_result.error or "Graphiti ingest returned disabled result."
                retryable = self._is_retryable_graph_error(last_error)
                log_event(logger, logging.WARNING, "graph_sync.attempt.failed",
                    trace_id=trace_id, note_id=note_id, user_id=note.user_id,
                    attempt=attempt, max_attempts=max_attempts, retryable=retryable, error=last_error)
                if retryable and attempt < max_attempts:
                    backoff_seconds = self._graph_retry_backoff_seconds(attempt)
                    log_event(logger, logging.INFO, "graph_sync.retry.scheduled",
                        trace_id=trace_id, note_id=note_id, user_id=note.user_id,
                        attempt=attempt, next_attempt=attempt + 1, sleep_seconds=backoff_seconds)
                    time.sleep(backoff_seconds)
                    continue
                break

        note = self.store.get_note(note_id) or note
        note.graph_sync_status = "failed"
        note.graph_sync_error = last_error or "Graph sync failed."
        note.updated_at = datetime.utcnow()
        self.store.update_note(note)
        logger.warning("Background graph sync failed note_id=%s error=%s", note_id, note.graph_sync_error)
        return False

    def _summarize_thread(self, messages_text: str, _user_id: str) -> str:
        if not messages_text.strip():
            return "没有可总结的消息内容。"
        prompt = (
            "你是个人知识库助手。请用自然中文总结以下群聊对话的核心要点。"
            "按主题分点列出讨论的关键事项、达成的结论和待办事项。"
            "保持简洁，每个要点一句话。如果对话内容较少或主题分散，直接概括即可。\n\n"
            f"群聊消息：\n{messages_text}"
        )
        generated = self._generate_answer(prompt)
        if generated:
            return generated
        return "暂时无法生成群聊总结，请稍后重试。"

    def _generate_answer(self, prompt: str) -> str | None:
        if not (self.settings.openai_api_key and self.settings.openai_base_url and self.settings.openai_model):
            return None
        try:
            client = OpenAI(api_key=self.settings.openai_api_key, base_url=self.settings.openai_base_url)
            response = client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": "你是一个严谨、善于归纳总结的个人知识库问答助手。你的首要任务不是复述检索片段，而是把证据整理成简洁、可信、可读的答案。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=600,
            )
            return (response.choices[0].message.content or "").strip() or None
        except Exception:
            logger.exception("Failed to generate answer from LLM")
            return None

    def _generate_answer_stream(self, prompt: str):
        """Stream tokens from the LLM in real time via SSE-compatible chunks.

        Yields (event_type, payload) tuples suitable for SSE streaming.
        Completes with ('answer_complete', {'answer': full_text}).
        On failure, yields ('answer_error', {'error': message}) and stops.
        """
        if not (self.settings.openai_api_key and self.settings.openai_base_url and self.settings.openai_model):
            yield ("answer_error", {"error": "LLM not configured"})
            return
        try:
            client = OpenAI(api_key=self.settings.openai_api_key, base_url=self.settings.openai_base_url)
            stream = client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": "你是一个严谨、善于归纳总结的个人知识库问答助手。你的首要任务不是复述检索片段，而是把证据整理成简洁、可信、可读的答案。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=600,
                stream=True,
            )
            full_text = ""
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else ""
                if delta:
                    full_text += delta
                    yield ("answer_delta", {"delta": delta, "answer": full_text})
            if full_text.strip():
                yield ("answer_complete", {"answer": full_text.strip()})
            else:
                yield ("answer_error", {"error": "LLM returned empty response"})
        except Exception:
            logger.exception("Failed to stream answer from LLM")
            yield ("answer_error", {"error": "LLM streaming failed"})

    def _merge_graph_capture(self, note: KnowledgeNote, graph_result: GraphCaptureResult) -> KnowledgeNote:
        note.graph_episode_uuid = graph_result.episode_uuid
        note.entity_names = graph_result.entity_names
        note.relation_facts = graph_result.relation_facts[:8]
        note.graph_sync_status = "synced"
        note.graph_sync_error = None
        note.updated_at = datetime.utcnow()
        return note

    def _is_retryable_graph_error(self, error: str | None) -> bool:
        if not error:
            return False
        normalized = error.lower()
        retryable_signals = (
            "timed out", "timeout", "503", "service unavailable",
            "service is too busy", "rate limit", "temporarily unavailable",
            "connection reset", "connection aborted", "readtimeout", "apitimeouterror",
        )
        return any(signal in normalized for signal in retryable_signals)

    def _graph_retry_backoff_seconds(self, attempt: int) -> float:
        initial = max(0.0, self.settings.graph_sync_initial_backoff_seconds)
        multiplier = max(1.0, self.settings.graph_sync_backoff_multiplier)
        maximum = max(initial, self.settings.graph_sync_max_backoff_seconds)
        delay = initial * (multiplier ** max(0, attempt - 1))
        return min(delay, maximum)

    def _graph_citations(self, matches: list[KnowledgeNote], graph_result: GraphAskResult) -> list[Citation]:
        citations: list[Citation] = []
        facts = graph_result.relation_facts
        for index, note in enumerate(matches[:5]):
            citations.append(Citation(
                note_id=note.id, title=note.title,
                snippet=note.summary[:120],
                relation_fact=facts[index] if index < len(facts) else None,
            ))
        return citations

    def _graph_matches_and_citations(
        self, user_id: str, question: str, graph_result: GraphAskResult
    ) -> tuple[list[KnowledgeNote], list[Citation]]:
        matches = self.store.find_notes_by_graph_episode_uuids(user_id, graph_result.related_episode_uuids)
        if not graph_result.citation_hits:
            return matches, self._graph_citations(matches, graph_result)

        notes_by_episode_uuid = {n.graph_episode_uuid: n for n in matches if n.graph_episode_uuid is not None}
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
                    note_id=note.id, title=note.title,
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

    def _build_graph_answer_prompt(
        self, question: str, graph_result: GraphAskResult,
        matches: list[KnowledgeNote], citations: list[Citation], working_context: str,
    ) -> str:
        """Build the LLM prompt for composing a graph-backed answer.

        Separated from generation so streaming callers can reuse the prompt.
        """
        focus_entities = "、".join(graph_result.entity_names[:6]) if graph_result.entity_names else "暂无"
        evidence_blocks = self._build_note_evidence_blocks(matches, citations)
        anchored_lines: list[str] = []
        for c in citations[:5]:
            label = f"{c.title}"
            if c.relation_fact:
                label += f"  [事实: {c.relation_fact}]"
            if c.snippet:
                label += f"  [证据: {c.snippet[:100]}]"
            anchored_lines.append(f"- {label}")
        context_block = working_context or "无"
        notes_block = "\n\n".join(evidence_blocks) if evidence_blocks else "无"
        anchored_block = "\n".join(anchored_lines) if anchored_lines else "无"

        return (
            "你是个人知识库助手。请基于给定的对话上下文、图谱事实和笔记内容证据，"
            "先总结结论，再解释原因，生成一段自然、直接、连续的中文回答。"
            "如果上下文里存在代词或省略，请结合最近几轮对话补全指代。"
            "不要先输出「最相关实体」「关联事实」「根据检索结果」之类栏目标题，不要机械列点，不要把原始片段逐条照搬。"
            "你的任务是整合证据、压缩冗余、形成更像人写的总结。"
            "如果证据不足，要明确指出不确定点。"
            "回答尽量先给出一句直接结论，再补充展开说明。\n\n"
            f"当前问题：{question}\n\n"
            f"最近对话与任务上下文：\n{context_block}\n\n"
            f"图谱实体：{focus_entities}\n\n"
            f"事实与证据锚点（每条包含关系事实和对应原文片段）：\n{anchored_block}\n\n"
            f"笔记全文证据：\n{notes_block}"
        )

    def _compose_graph_answer(
        self, question: str, graph_result: GraphAskResult,
        matches: list[KnowledgeNote], citations: list[Citation], working_context: str,
    ) -> str:
        prompt = self._build_graph_answer_prompt(
            question, graph_result, matches, citations, working_context,
        )
        generated = self._generate_answer(prompt)
        if generated:
            return generated
        if citations:
            facts = [c.relation_fact for c in citations if c.relation_fact]
            if facts:
                return "结合你已有的笔记和图谱信息，" + "；".join(facts[:4]) + "。"
        return graph_result.answer or "暂时没有生成答案。"

    def _compose_local_answer(
        self, question: str, matches: list[KnowledgeNote],
        citations: list[Citation], working_context: str,
    ) -> str:
        evidence_blocks = self._build_note_evidence_blocks(matches, citations)
        context_block = working_context or "无"
        notes_block = "\n\n".join(evidence_blocks) if evidence_blocks else "无"
        prompt = (
            "你是个人知识库助手。请基于最近几轮对话和当前匹配到的笔记内容证据，"
            "用自然中文总结并回答用户问题。优先回答用户真正想问的内容，必要时承认信息不足。"
            "不要把答案写成检索结果罗列，也不要简单重复原始片段。"
            "回答尽量先给出一句直接结论，再补充必要解释。\n\n"
            f"当前问题：{question}\n\n"
            f"最近对话与任务上下文：\n{context_block}\n\n"
            f"相关内容证据：\n{notes_block}"
        )
        generated = self._generate_answer(prompt)
        if generated:
            return generated
        if matches:
            return f"结合你前面的提问和当前笔记内容，我更倾向于认为：{matches[0].summary}"
        return "我暂时无法从你的个人知识库中找到足够依据来回答这个问题。"

    def _build_note_evidence_blocks(
        self, matches: list[KnowledgeNote], citations: list[Citation], limit: int = 5,
    ) -> list[str]:
        citation_map: dict[str, list[Citation]] = {}
        for citation in citations:
            citation_map.setdefault(citation.note_id, []).append(citation)

        blocks: list[str] = []
        for note in matches[:limit]:
            candidate_snippets = [item.snippet for item in citation_map.get(note.id, []) if item.snippet]
            if not candidate_snippets:
                candidate_snippets = _top_sentences(note.content, 3)
            excerpt = "\n".join(f"- {s}" for s in candidate_snippets[:3] if s.strip())
            if not excerpt:
                excerpt = f"- {note.summary}"
            blocks.append(f"[笔记] {note.title}\n摘要：{note.summary}\n证据片段：\n{excerpt}")
        return blocks

    def _retry_if_needed(
        self,
        question: str,
        answer: str,
        citations: list[Citation],
        matches: list[KnowledgeNote],
        verification: VerificationResult,
        graph_enabled: bool = False,
    ) -> str:
        max_retries = max(0, self.settings.max_verify_retries)
        current_answer = answer
        for attempt in range(max_retries):
            if verification.ok and verification.sufficient:
                break
            correction_prompt = self._build_correction_prompt(question, current_answer, verification)
            regenerated = self._generate_answer(correction_prompt)
            if regenerated:
                current_answer = regenerated
                verification = self._verifier.verify(question, current_answer, citations, matches, graph_enabled=graph_enabled)
                self.memory.working.add_step(
                    f"Retry {attempt + 1}: score={verification.evidence_score:.2f} ok={verification.ok}"
                )
            else:
                break
        return current_answer

    def _build_correction_prompt(
        self, question: str, answer: str, verification: VerificationResult
    ) -> str:
        issues_text = "\n".join(f"- {i}" for i in verification.issues) if verification.issues else "无"
        warnings_text = "\n".join(f"- {w}" for w in verification.warnings) if verification.warnings else "无"
        return (
            "你是个人知识库助手。你刚才的回答存在以下问题，请根据反馈重新生成更准确、更有据可查的回答。\n\n"
            f"用户问题：{question}\n\n"
            f"你刚才的回答：\n{answer}\n\n"
            f"校验发现的问题：\n{issues_text}\n\n"
            f"校验提示：\n{warnings_text}\n\n"
            "请重新生成回答。要求：\n"
            "1. 直接给出结论，不要列标题\n"
            "2. 如果证据不足，明确指出\n"
            "3. 确保每个观点都有相应依据\n"
        )

    def list_notes(self, user_id: str | None = None) -> list[KnowledgeNote]:
        normalized_user = user_id or self.settings.default_user
        return list(reversed(self.store.list_notes(normalized_user)))

    def list_ask_history(
        self, user_id: str | None = None, limit: int = 20, session_id: str | None = None
    ) -> list[AskHistoryRecord]:
        normalized_user = user_id or self.settings.default_user
        normalized_session = session_id or None
        if self.ask_history_store.configured():
            return self.ask_history_store.list_history(normalized_user, limit, normalized_session)
        local_records = self.store.list_conversation_turns(normalized_user, normalized_session or "default", limit)
        return [AskHistoryRecord.model_validate(item) for item in reversed(local_records)]

    def search_ask_history(
        self, user_id: str | None = None, query: str = "", limit: int = 20, session_id: str | None = None
    ) -> list[AskHistoryRecord]:
        normalized_user = user_id or self.settings.default_user
        if self.ask_history_store.configured():
            return self.ask_history_store.search_history(normalized_user, query, limit, session_id)
        local_records = self.store.list_conversation_turns(normalized_user, session_id or "default", limit)
        if not query.strip():
            return [AskHistoryRecord.model_validate(item) for item in reversed(local_records)]
        query_lower = query.strip().lower()
        filtered = [
            r for r in local_records
            if query_lower in r.get("question", "").lower() or query_lower in r.get("answer", "").lower()
        ]
        return [AskHistoryRecord.model_validate(item) for item in reversed(filtered)]

    def delete_ask_record(self, user_id: str | None, record_id: str) -> bool:
        normalized_user = user_id or self.settings.default_user
        if self.ask_history_store.configured():
            return self.ask_history_store.delete_record(normalized_user, record_id)
        return self.store.delete_conversation_turn(normalized_user, record_id)

    def delete_ask_session(self, user_id: str | None, session_id: str) -> int:
        normalized_user = user_id or self.settings.default_user
        if self.ask_history_store.configured():
            return self.ask_history_store.delete_session(normalized_user, session_id)
        return self.store.delete_session_turns(normalized_user, session_id)

    def list_pending_actions(
        self, user_id: str | None = None, status: str | None = None
    ) -> list[PendingAction]:
        return self.pending_action_store.list_by_user(user_id or self.settings.default_user, status)

    def confirm_pending_action(self, action_id: str, token: str, user_id: str | None = None) -> PendingAction | None:
        normalized_user = user_id or self.settings.default_user
        action = self.pending_action_store.confirm(action_id, token, normalized_user)
        if action is None:
            return None
        if action.action_type == "delete_note":
            graph_episode_uuid = action.payload.get("graph_episode_uuid")
            self.store.delete_note(action.target_id, normalized_user)
            if self.graph_store.configured() and graph_episode_uuid:
                try:
                    self.graph_store.delete_episode(str(graph_episode_uuid))
                except Exception:
                    logger.exception("Graph episode deletion failed for pending action %s", action_id)
            action = self.pending_action_store.mark_executed(action_id, normalized_user) or action
        return action

    def reject_pending_action(
        self, action_id: str, user_id: str | None = None, reason: str = ""
    ) -> PendingAction | None:
        return self.pending_action_store.reject(action_id, user_id or self.settings.default_user, reason)

    def health(self) -> dict[str, object]:
        graph_status = self.graph_store.status()
        return {
            "status": "ok",
            "graphiti": graph_status,
            "ask_history": {"configured": self.ask_history_store.configured()},
        }

    def reset_user_data(self, user_id: str | None = None) -> ResetResult:
        normalized_user = user_id or self.settings.default_user
        logger.warning("Resetting user data for user=%s", normalized_user)
        deleted_graph_episodes = 0
        if self.graph_store.configured():
            deleted_graph_episodes = self.graph_store.clear_user_group(normalized_user)
        local_result = self.store.clear_user_data(normalized_user, remove_uploaded_files=True)
        self._cross_session.clear_user(normalized_user)
        deleted_ask_history = 0
        if self.ask_history_store.configured():
            try:
                deleted_ask_history = self.ask_history_store.delete_history(normalized_user)
            except Exception:
                logger.exception("Failed to delete ask history for user=%s", normalized_user)
        return ResetResult(
            user_id=normalized_user,
            deleted_notes=local_result["notes"],
            deleted_reviews=local_result["reviews"],
            deleted_conversations=local_result["conversations"],
            deleted_upload_files=local_result["uploads"],
            deleted_ask_history=deleted_ask_history,
            deleted_graph_episodes=deleted_graph_episodes,
        )


def _annotate_answer(answer: str, verification: VerificationResult) -> str:
    if verification.ok and verification.sufficient:
        return answer
    notes: list[str] = []
    if verification.issues:
        notes.append("(校验提示: " + "; ".join(verification.issues) + ")")
    if verification.warnings:
        notes.append("(注意: " + "; ".join(verification.warnings[:2]) + ")")
    if not notes:
        return answer
    return answer + "\n\n---\n" + "\n".join(notes)


def _merge_notes(primary: list[KnowledgeNote], secondary: list[KnowledgeNote]) -> list[KnowledgeNote]:
    merged: list[KnowledgeNote] = []
    seen: set[str] = set()
    for note in [*primary, *secondary]:
        if note.id in seen:
            continue
        seen.add(note.id)
        merged.append(note)
    return merged


def _best_snippet(note: KnowledgeNote, hit: GraphCitationHit, question: str) -> str:
    """Select the sentence from note content that best anchors the graph relation_fact.

    Uses word-overlap scoring between the relation_fact and each sentence,
    weighted by entity name matches and question keyword relevance.
    Falls back to note summary when no sentence reaches the minimum score.
    """
    best_part = ""
    best_score = -1
    question_keywords = _extract_question_keywords(question)
    fact_tokens = _tokenize_for_overlap(hit.relation_fact)
    entity_names = [n for n in (hit.endpoint_names or note.entity_names or []) if len(n) >= 2]

    for part in _split_sentences(note.content):
        if len(part) < 10:
            continue
        score = 0
        # Word overlap between relation_fact and this sentence (primary anchor)
        if fact_tokens:
            part_tokens = _tokenize_for_overlap(part)
            if part_tokens:
                overlap = len(fact_tokens & part_tokens)
                score += min(overlap * 5, 30)  # cap at 30 points for overlap
        # Legacy exact match bonus
        if hit.relation_fact and hit.relation_fact in part:
            score += 10
        # Entity name matches (strong signal)
        for entity_name in entity_names:
            if entity_name in part:
                score += 5
        # Question keyword relevance
        for keyword in question_keywords:
            if keyword in part:
                score += 2
        if score > best_score:
            best_part = part
            best_score = score

    if best_part and best_score >= 3:
        return best_part[:160]
    # Weak anchoring: return summary with a marker
    if best_part:
        return best_part[:160]
    return note.summary[:160]


def _tokenize_for_overlap(text: str) -> set[str]:
    """Tokenize text into lowercased meaningful words for overlap scoring."""
    if not text:
        return set()
    # Simple tokenization: split on non-alphanumeric, filter short tokens
    tokens: set[str] = set()
    for token in text.lower().split():
        # Strip punctuation from each token
        cleaned = "".join(c for c in token if c.isalnum())
        if len(cleaned) >= 2:
            tokens.add(cleaned)
    return tokens


def _split_sentences(text: str) -> list[str]:
    normalized = text.replace("\r", "\n")
    parts: list[str] = []
    current = ""
    for char in normalized:
        current += char
        if char in {"。", "！", "？", ".", "!", "?", "\n"}:
            stripped = current.strip()
            if stripped:
                parts.append(stripped)
            current = ""
    if current.strip():
        parts.append(current.strip())
    return parts


def _extract_question_keywords(question: str) -> list[str]:
    keywords: list[str] = []
    buffer = ""
    for char in question:
        if char.isascii() and (char.isalnum() or char in {"_", "-"}):
            buffer += char.lower()
            continue
        if buffer:
            if len(buffer) >= 2 and buffer not in keywords:
                keywords.append(buffer)
            buffer = ""
    if buffer and len(buffer) >= 2 and buffer not in keywords:
        keywords.append(buffer)
    compact = question.replace("？", " ").replace("。", " ").replace("，", " ").replace(",", " ")
    for chunk in compact.split():
        normalized = chunk.strip()
        if len(normalized) >= 2 and not normalized.isascii() and normalized not in keywords:
            keywords.append(normalized)
    return keywords[:8]


def _top_sentences(text: str, limit: int = 3) -> list[str]:
    sentences = _split_sentences(text)
    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        compact = sentence.strip()
        if not compact:
            continue
        score = len(compact)
        if any(token in compact for token in ["是", "包括", "通过", "用于", "因为", "所以", "导致", "机制", "原理"]):
            score += 20
        scored.append((score, compact))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [sentence[:180] for _, sentence in scored[:limit]]
