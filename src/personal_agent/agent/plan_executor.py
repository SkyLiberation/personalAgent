from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from ..core.models import AgentState, KnowledgeNote
from ..memory import MemoryFacade
from .planner import PlanStep
from .react_runner import ReActStepRunner
from .replanner import MAX_RETRIES, RETRY_DELAY_SECONDS, Replanner

logger = logging.getLogger(__name__)

# Callback for emitting SSE progress events: (event_name, payload_dict)
ProgressCallback = Callable[[str, dict[str, object]], None] | None


@dataclass(slots=True)
class ExecutionProgress:
    total: int
    completed: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def running_count(self) -> int:
        return self.total - self.completed - self.failed - self.skipped


def _topological_sort(steps: list[PlanStep]) -> list[PlanStep]:
    """Sort steps so that dependencies come before dependents."""
    if len(steps) <= 1:
        return list(steps)
    step_ids = {s.step_id for s in steps}
    indeg: dict[str, int] = {s.step_id: 0 for s in steps}
    adj: dict[str, list[int]] = {s.step_id: [] for s in steps}
    idx_map: dict[str, int] = {s.step_id: i for i, s in enumerate(steps)}
    for i, s in enumerate(steps):
        for dep_id in s.depends_on:
            if dep_id in step_ids and dep_id in adj:
                indeg[s.step_id] += 1
                adj[dep_id].append(i)
    q: deque[str] = deque(sid for sid, d in indeg.items() if d == 0)
    result: list[PlanStep] = []
    while q:
        sid = q.popleft()
        result.append(steps[idx_map[sid]])
        for ni in adj[sid]:
            neighbor_id = steps[ni].step_id
            indeg[neighbor_id] -= 1
            if indeg[neighbor_id] == 0:
                q.append(neighbor_id)
    return result


class PlanExecutor:
    """Execute validated plan steps in dependency order.

    Dispatches each step to the appropriate handler based on action_type.
    Tracks status lifecycle: planned → running → completed / failed / skipped.
    Emits progress events through an optional callback for SSE streaming.
    """

    def __init__(
        self,
        runtime,
        memory: MemoryFacade,
        replanner: Replanner | None = None,
        react_runner: ReActStepRunner | None = None,
    ) -> None:
        self._runtime = runtime
        self._memory = memory
        self._replanner = replanner
        self._react_runner = react_runner

    def execute(
        self,
        steps: list[PlanStep],
        state: AgentState,
        on_progress: ProgressCallback = None,
    ) -> AgentState:
        if not steps:
            logger.info("PlanExecutor: no steps to execute")
            return state

        sorted_steps = _topological_sort(steps)
        progress = ExecutionProgress(total=len(sorted_steps))
        results: dict[str, object] = {}

        for step in sorted_steps:
            if step.status == "skipped":
                continue
            step.status = "running"
            self._emit(on_progress, "plan_step_started", {
                "step_id": step.step_id,
                "action_type": step.action_type,
                "description": step.description,
            })
            self._memory.working.add_step(
                f"执行中: [{step.step_id}] {step.action_type} {step.description}"
            )

            try:
                self._dispatch_step(step, state, results, on_progress)
            except Exception as exc:
                err_msg = f"{type(exc).__name__}: {exc}"
                logger.warning("Plan step %s failed: %s", step.step_id, err_msg)
                step.status = "failed"
                step.retry_count = 1

                if step.on_failure == "retry":
                    self._emit(on_progress, "plan_step_retry", {
                        "step_id": step.step_id,
                        "attempt": 1,
                        "max_retries": MAX_RETRIES,
                        "error": err_msg,
                    })
                    for attempt in range(1, MAX_RETRIES):
                        time.sleep(RETRY_DELAY_SECONDS)
                        try:
                            self._dispatch_step(step, state, results, on_progress)
                            step.retry_count = attempt + 1
                            self._emit(on_progress, "plan_step_completed", {
                                "step_id": step.step_id,
                                "result_summary": f"重试 {attempt + 1} 次后成功",
                            })
                            break
                        except Exception as retry_exc:
                            step.retry_count = attempt + 1
                            logger.warning(
                                "Plan step %s retry %d/%d failed: %s",
                                step.step_id, attempt + 1, MAX_RETRIES, retry_exc,
                            )

                    if step.status == "failed" and self._replanner is not None:
                        # All retries exhausted, attempt replanning
                        self._emit(on_progress, "plan_replan_attempt", {
                            "step_id": step.step_id,
                            "reason": "重试耗尽，尝试重新规划",
                        })
                        try:
                            intent = state.intent if state.intent else "unknown"
                            revised = self._replanner.replan(
                                sorted_steps, step, err_msg, results, intent,
                            )
                            if revised:
                                self._emit(on_progress, "plan_replanned", {
                                    "step_id": step.step_id,
                                    "revised_step_count": len(revised),
                                })
                                self._memory.working.add_step(
                                    f"重新规划: 生成 {len(revised)} 个新步骤替代失败步骤 {step.step_id}"
                                )
                                # Skip dependents of the failed step before replacing
                                self._skip_dependents(step, sorted_steps, on_progress, progress)
                                # Mark failed step as skipped (replaced by revised)
                                step.status = "skipped"
                                progress.skipped += 1
                                # Append revised steps and re-sort
                                sorted_steps.extend(revised)
                                sorted_steps = _topological_sort(sorted_steps)
                                progress.total = len(sorted_steps)
                                continue
                            else:
                                self._emit(on_progress, "plan_replan_failed", {
                                    "step_id": step.step_id,
                                    "reason": "Replanner 无法生成替代步骤",
                                })
                        except Exception as replan_exc:
                            logger.exception("Replanner failed for step %s: %s", step.step_id, replan_exc)
                            self._emit(on_progress, "plan_replan_failed", {
                                "step_id": step.step_id,
                                "reason": f"Replanner 异常: {replan_exc}",
                            })

                if step.status == "failed":
                    self._emit(on_progress, "plan_step_failed", {
                        "step_id": step.step_id,
                        "error": err_msg,
                        "on_failure": step.on_failure,
                        "retry_count": step.retry_count,
                    })
                    if step.on_failure == "abort":
                        state.answer = state.answer or f"执行中断于步骤 {step.step_id}。"
                        break

            if step.status == "completed":
                progress.completed += 1
                # After resolve step, inject resolved note_id into dependent tool_call steps
                if step.action_type == "resolve" and step.step_id in results:
                    resolved_data = results[step.step_id]
                    if isinstance(resolved_data, dict) and resolved_data.get("note_id"):
                        self._inject_note_id(step.step_id, resolved_data["note_id"], sorted_steps)
                # After compose step, inject draft text into dependent capture_text steps
                if step.action_type == "compose" and step.step_id in results:
                    draft = results[step.step_id]
                    if isinstance(draft, dict) and draft.get("answer"):
                        self._inject_draft_text(step.step_id, str(draft["answer"]), sorted_steps)
                # After capture_text tool_call, mark upstream compose drafts as solidified
                if step.action_type == "tool_call" and step.tool_name == "capture_text":
                    self._mark_upstream_drafts_solidified(step, results, state.user_id)
            elif step.status == "failed":
                progress.failed += 1
                if step.on_failure in ("skip", "retry"):
                    self._skip_dependents(step, sorted_steps, on_progress, progress)

            self._memory.working.add_step(
                f"完成: [{step.step_id}] status={step.status}"
            )

        if not state.answer:
            state.answer = self._default_answer(sorted_steps)

        self._emit(on_progress, "plan_execution_complete", {
            "total": progress.total,
            "completed": progress.completed,
            "failed": progress.failed,
            "skipped": progress.skipped,
            "final_answer": state.answer,
        })

        return state

    # ---- step dispatch ----

    def _dispatch_step(
        self,
        step: PlanStep,
        state: AgentState,
        results: dict[str, object],
        on_progress: ProgressCallback,
    ) -> None:
        """Execute a single step by action_type. Raises on failure."""
        # ReAct branch: step requests dynamic Thought/Action/Observation loop
        if getattr(step, "execution_mode", "deterministic") == "react":
            if self._react_runner is not None:
                result_data = self._react_runner.run(step, state, results, on_progress)
                results[step.step_id] = result_data
                step.status = "completed"
                self._emit(on_progress, "plan_step_completed", {
                    "step_id": step.step_id,
                    "result_summary": _summarize(result_data),
                    "execution_mode": "react",
                })
                return
            logger.warning(
                "Step %s requests ReAct but no runner configured, falling back to deterministic",
                step.step_id,
            )

        if step.action_type == "retrieve":
            result_data = self._execute_retrieve(step, state)
            results[step.step_id] = result_data
            step.status = "completed"
            self._emit(on_progress, "plan_step_completed", {
                "step_id": step.step_id,
                "result_summary": _summarize(result_data),
            })
        elif step.action_type == "tool_call":
            result_data = self._execute_tool_call(step)
            results[step.step_id] = result_data
            step.status = "completed"
            # Emit pending_action_created if tool result contains HITL confirmation data
            if isinstance(result_data, dict) and result_data.get("pending_confirmation"):
                self._emit(on_progress, "pending_action_created", {
                    "step_id": step.step_id,
                    "action_id": result_data.get("action_id"),
                    "token": result_data.get("token"),
                    "action_type": "delete_note",
                    "note_id": result_data.get("note_id"),
                    "title": result_data.get("title"),
                    "summary": result_data.get("summary"),
                    "expires_at": result_data.get("expires_at"),
                    "message": result_data.get("message"),
                })
            self._emit(on_progress, "plan_step_completed", {
                "step_id": step.step_id,
                "result_summary": _summarize(result_data),
            })
        elif step.action_type == "resolve":
            result_data = self._execute_resolve(step, state, results)
            results[step.step_id] = result_data
            step.status = "completed"
            self._emit(on_progress, "plan_step_completed", {
                "step_id": step.step_id,
                "result_summary": _summarize(result_data),
            })
        elif step.action_type == "compose":
            answer = self._execute_compose(step, state, results)
            state.answer = answer
            results[step.step_id] = {"answer": answer, "draft": True}
            step.status = "completed"
            self._emit(on_progress, "plan_step_completed", {
                "step_id": step.step_id,
                "result_summary": answer[:120] if answer else "",
            })
            # Emit draft_ready event if this is a solidify draft compose step
            if answer:
                self._emit(on_progress, "draft_ready", {
                    "step_id": step.step_id,
                    "draft_text": answer,
                })
        elif step.action_type == "verify":
            self._execute_verify(step, state)
            step.status = "completed"
            self._emit(on_progress, "plan_step_completed", {
                "step_id": step.step_id,
                "result_summary": "校验通过",
            })
        else:
            step.status = "failed"
            self._emit(on_progress, "plan_step_failed", {
                "step_id": step.step_id,
                "error": f"未知的 action_type: {step.action_type}",
                "on_failure": step.on_failure,
            })
            raise ValueError(f"未知的 action_type: {step.action_type}")

    # ---- step handlers ----

    def _execute_retrieve(self, step: PlanStep, state: AgentState) -> object:
        user_id = state.user_id
        question = step.tool_input.get("question") if step.tool_input else step.description
        try:
            result = self._runtime.graph_store.ask(str(question), user_id)
            if result.enabled and result.answer:
                return {
                    "answer": result.answer,
                    "entity_names": result.entity_names,
                    "relation_facts": result.relation_facts,
                    "related_episode_uuids": result.related_episode_uuids,
                }
            return {"answer": "", "entity_names": [], "relation_facts": [], "hint": "graph disabled or empty"}
        except Exception:
            logger.exception("Graph search failed in retrieve step %s", step.step_id)
            raise

    def _execute_resolve(
        self,
        step: PlanStep,
        state: AgentState,
        results: dict[str, object],
    ) -> object:
        """Resolve a fuzzy delete target to concrete note_id(s).

        Uses graph episode UUIDs from retrieve results to find matching local notes,
        then falls back to local similarity search against the user's original query.
        """
        user_id = state.user_id
        original_query = ""
        if state.entry_input:
            original_query = state.entry_input.text or ""

        candidates: list[dict[str, object]] = []

        # 1. Try to map graph episode UUIDs to local notes
        for sid, data in results.items():
            if not isinstance(data, dict):
                continue
            episode_uuids = data.get("related_episode_uuids")
            if isinstance(episode_uuids, list) and episode_uuids:
                str_uuids = [str(u) for u in episode_uuids if u]
                if str_uuids:
                    try:
                        matched = self._runtime.store.find_notes_by_graph_episode_uuids(
                            user_id, str_uuids
                        )
                        for note in matched:
                            candidates.append(self._build_candidate(note, "graph_episode"))
                    except Exception:
                        logger.exception("Episode UUID lookup failed in resolve step")

        # 2. Fall back to local similarity search via the original query
        if not candidates and original_query:
            try:
                similar = self._runtime.store.find_similar_notes(
                    user_id, original_query, limit=5
                )
                for note in similar:
                    candidates.append(self._build_candidate(note, "text_similarity"))
            except Exception:
                logger.exception("Similarity search failed in resolve step")

        # 3. Last resort: list recent notes and match by keyword
        if not candidates:
            try:
                all_notes = self._runtime.store.list_notes(user_id)
                query_lower = original_query.lower()
                keyword_matches = []
                for note in all_notes:
                    title_lower = note.title.lower()
                    content_lower = note.content.lower() if note.content else ""
                    if query_lower and (query_lower in title_lower or query_lower in content_lower):
                        keyword_matches.append(note)
                for note in keyword_matches[:5]:
                    candidates.append(self._build_candidate(note, "keyword_match"))
            except Exception:
                logger.exception("Keyword fallback failed in resolve step")

        # 4. Cross-session citations: recently cited notes from ask responses
        if not candidates:
            try:
                recent_cited = self._memory.recent_citations(user_id, limit=10)
                for cited in recent_cited:
                    cited_note_id = str(cited["note_id"])
                    note = self._runtime.store.get_note(cited_note_id)
                    if note is not None:
                        candidates.append(self._build_candidate(note, "recent_citation"))
                    else:
                        candidates.append({
                            "note_id": cited_note_id,
                            "title": cited["title"],
                            "summary": cited.get("snippet", ""),
                            "source": "recent_citation",
                            "parent_note_id": None,
                            "parent_title": None,
                        })
                if candidates:
                    self._memory.working.add_step(
                        f"通过最近引用记录找到 {len(candidates)} 个候选笔记"
                    )
            except Exception:
                logger.exception("Cross-session citation lookup failed in resolve step")

        if not candidates:
            return {"note_id": None, "candidates": [], "error": "未找到匹配的笔记。请提供更具体的笔记标题或内容描述。"}

        # Best candidate is the first one; all candidates are returned for UI display
        best = candidates[0]
        self._memory.working.add_step(
            f"解析删除目标: {best.get('title')} ({best.get('note_id')}) "
            f"来源={best.get('source')}，共 {len(candidates)} 个候选项"
        )
        return {
            "note_id": best["note_id"],
            "title": best["title"],
            "summary": best.get("summary"),
            "source": best["source"],
            "candidates": candidates,
        }

    def _build_candidate(self, note: KnowledgeNote, source: str) -> dict[str, object]:
        parent = self._runtime.store.get_parent_note(note.id) if hasattr(self._runtime.store, "get_parent_note") else None
        return {
            "note_id": note.id,
            "title": note.title,
            "summary": note.summary,
            "source": source,
            "parent_note_id": note.parent_note_id or (parent.id if parent else None),
            "parent_title": parent.title if parent else None,
        }

    def _inject_note_id(
        self,
        resolve_step_id: str,
        note_id: object,
        sorted_steps: list[PlanStep],
    ) -> None:
        """Inject a resolved note_id into dependent delete_note tool_call steps."""
        for s in sorted_steps:
            if s.status != "planned":
                continue
            if resolve_step_id in s.depends_on and s.action_type == "tool_call" and s.tool_name == "delete_note":
                if not s.tool_input:
                    s.tool_input = {}
                s.tool_input["note_id"] = str(note_id)
                logger.info("Injected note_id=%s into step %s via resolve step %s", note_id, s.step_id, resolve_step_id)

    def _inject_draft_text(
        self,
        compose_step_id: str,
        text: str,
        sorted_steps: list[PlanStep],
    ) -> None:
        """Inject composed draft text into dependent capture_text tool_call steps."""
        for s in sorted_steps:
            if s.status != "planned":
                continue
            if compose_step_id in s.depends_on and s.action_type == "tool_call" and s.tool_name == "capture_text":
                if not s.tool_input:
                    s.tool_input = {}
                s.tool_input["text"] = text
                logger.info("Injected draft text (%d chars) into step %s via compose step %s", len(text), s.step_id, compose_step_id)

    def _execute_tool_call(self, step: PlanStep) -> object:
        if not step.tool_name:
            raise ValueError("tool_call step missing tool_name")
        result = self._runtime._tool_registry.execute(
            step.tool_name, **(step.tool_input or {})
        )
        if result is not None and hasattr(result, "ok") and not result.ok:
            raise RuntimeError(result.error or f"Tool {step.tool_name} returned failure")
        return result.data if hasattr(result, "data") and result.data is not None else {"ok": True}

    def _execute_compose(
        self,
        step: PlanStep,
        state: AgentState,
        results: dict[str, object],
    ) -> str:
        """Generate a natural-language answer from collected results."""
        intent = state.intent or (state.entry_input.source_type if state.entry_input else "text")

        # Collect retrieved results for context
        context_parts: list[str] = []
        for sid, data in results.items():
            if isinstance(data, dict):
                if data.get("answer"):
                    context_parts.append(str(data["answer"]))
                if data.get("entity_names"):
                    context_parts.append("实体: " + ", ".join(
                        str(n) for n in data["entity_names"] if n
                    ))

        context = "\n".join(context_parts) if context_parts else "暂无检索结果。"
        description = step.description or "根据已有信息生成回答"

        # For ask intent, delegate to execute_ask
        if step.tool_input and step.tool_input.get("question"):
            question = str(step.tool_input["question"])
        else:
            question = description

        try:
            ask_result = self._runtime.execute_ask(question, state.user_id)
            answer = ask_result.answer
        except Exception:
            logger.exception("Compose step %s failed, generating simple answer", step.step_id)
            answer = f"根据已有信息：{context[:500]}"

        # Save solidify_conversation drafts to cross-session store
        if intent == "solidify_conversation" and answer:
            try:
                draft_context = context[:500]
                draft_id = self._memory.save_draft(
                    state.user_id, answer, source_context=draft_context,
                )
                if draft_id:
                    self._memory.working.add_step(
                        f"固化草稿已保存: {draft_id} ({len(answer)} 字符)"
                    )
                    # Store draft_id in results so downstream capture_text can mark it solidified
                    if step.step_id in results and isinstance(results[step.step_id], dict):
                        results[step.step_id]["draft_id"] = draft_id
                    # Extract candidate conclusions from the solidify draft
                    conclusions = _extract_conclusions(answer)
                    for conclusion_text in conclusions:
                        conclusion_id = self._memory.add_conclusion(
                            state.user_id, conclusion_text,
                            session_id=state.entry_input.session_id if state.entry_input else "",
                        )
                        if conclusion_id:
                            results[step.step_id].setdefault("conclusion_ids", []).append(conclusion_id)
                    if conclusions:
                        self._memory.working.add_step(
                            f"从固化草稿提取 {len(conclusions)} 条候选结论"
                        )
            except Exception:
                logger.exception("Failed to save solidify draft to cross_session store")

        return answer

    def _execute_verify(self, step: PlanStep, state: AgentState) -> None:
        if not state.answer:
            logger.info("Verify step %s: no answer to verify, skipping", step.step_id)
            return
        try:
            verification = self._runtime._verifier.verify(
                question=state.entry_input.text if state.entry_input else "",
                answer=state.answer,
                citations=state.citations,
                matches=state.matches,
            )
            self._memory.working.add_step(
                f"校验: score={verification.evidence_score:.2f} ok={verification.ok}"
            )
            if verification.issues:
                logger.warning("Verify step %s found issues: %s", step.step_id, verification.issues)
        except Exception:
            logger.exception("Verify step %s error", step.step_id)

    # ---- helpers ----

    def _skip_dependents(
        self,
        failed_step: PlanStep,
        all_steps: list[PlanStep],
        on_progress: ProgressCallback,
        progress: ExecutionProgress,
    ) -> None:
        for s in all_steps:
            if s.status != "planned":
                continue
            if failed_step.step_id in s.depends_on:
                s.status = "skipped"
                progress.skipped += 1
                self._emit(on_progress, "plan_step_skipped", {
                    "step_id": s.step_id,
                    "reason": f"依赖步骤 {failed_step.step_id} 失败",
                })
                self._memory.working.add_step(
                    f"跳过: [{s.step_id}] 依赖步骤 {failed_step.step_id} 失败"
                )
                # Recursively skip steps depending on this one
                self._skip_dependents(s, all_steps, on_progress, progress)

    def _mark_upstream_drafts_solidified(
        self, step: PlanStep, results: dict[str, object], user_id: str,
    ) -> None:
        """Mark compose drafts as solidified after capture_text stores the note."""
        for dep_id in step.depends_on:
            dep_result = results.get(dep_id)
            if isinstance(dep_result, dict):
                draft_id = dep_result.get("draft_id")
                if draft_id:
                    try:
                        self._memory.mark_draft_solidified(user_id, str(draft_id))
                        self._memory.working.add_step(f"草稿已固化: {draft_id}")
                    except Exception:
                        logger.exception("Failed to mark draft as solidified: %s", draft_id)
                # Also mark linked candidate conclusions as solidified
                conclusion_ids = dep_result.get("conclusion_ids", [])
                if isinstance(conclusion_ids, list):
                    for cid in conclusion_ids:
                        try:
                            self._memory.mark_conclusion_solidified(user_id, str(cid))
                        except Exception:
                            logger.exception("Failed to mark conclusion as solidified: %s", cid)

    def _default_answer(self, steps: list[PlanStep]) -> str:
        completed = sum(1 for s in steps if s.status == "completed")
        failed = sum(1 for s in steps if s.status == "failed")
        skipped = sum(1 for s in steps if s.status == "skipped")
        return f"计划执行完成：{completed} 步成功" + (
            f"，{failed} 步失败" if failed else ""
        ) + (
            f"，{skipped} 步跳过" if skipped else ""
        ) + "。"

    def _emit(
        self,
        on_progress: ProgressCallback,
        event: str,
        payload: dict[str, object],
    ) -> None:
        if on_progress is not None:
            try:
                on_progress(event, payload)
            except Exception:
                logger.exception("Progress callback failed for event=%s", event)


def _summarize(data: object) -> str:
    if data is None:
        return "无结果"
    if isinstance(data, dict):
        answer = data.get("answer", "")
        if answer:
            return str(answer)[:100]
        entity_names = data.get("entity_names", [])
        if entity_names:
            return f"命中 {len(entity_names)} 个实体"
        return "已获取结果"
    if isinstance(data, str):
        return data[:100]
    return str(data)[:100]


def _extract_conclusions(answer: str) -> list[str]:
    """Extract candidate conclusions from a composed solidify answer.

    Splits the answer on sentence boundaries and identifies sentences
    that look like factual conclusions (containing markers like
    '是', '包括', '需要', '应该', etc.).
    """
    sentences = _split_answer_sentences(answer)
    conclusions: list[str] = []
    indicators = ("是", "包括", "需要", "应该", "已", "通过", "基于", "根据", "确认", "决定", "结论")
    for sentence in sentences:
        text = sentence.strip()
        if len(text) < 15:
            continue
        if any(ind in text for ind in indicators):
            conclusions.append(text[:300])
    return conclusions[:5]


def _split_answer_sentences(text: str) -> list[str]:
    """Split text into sentence-level parts using common delimiters."""
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
