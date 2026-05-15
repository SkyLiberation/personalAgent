from __future__ import annotations

import logging
from uuid import uuid4

from ..core.evidence import (
    EvidenceItem,
    graph_result_to_evidence,
    notes_to_evidence,
    web_results_to_evidence,
)
from ..core.models import AgentState, Citation, KnowledgeNote
from ..graphiti.store import GraphAskResult
from .graph import build_ask_graph
from .runtime_helpers import (
    _annotate_answer,
    _best_snippet,
    _evidence_content,
    _format_graph_relation,
    _graph_episode_uuids,
    _graph_fact_lines,
    _graph_facts_by_episode,
    _merge_citations,
    _merge_notes,
    _top_sentences,
)
from .runtime_results import AskResult, RetryResult
from .verifier import VerificationResult

logger = logging.getLogger(__name__)


class RuntimeAskMixin:
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
        graph_fallback_answer: str | None = None
        graph_fallback_citations: list[Citation] = []
        graph_fallback_matches: list[KnowledgeNote] = []
        all_evidence: list[EvidenceItem] = []

        graph_result = self.graph_store.ask(question, normalized_user, trace_id=trace_id)
        if graph_result.enabled is True:
            matches, citations = self._graph_matches_and_citations(normalized_user, question, graph_result)
            # Build graph evidence from result + episode-to-note mapping
            notes_by_episode = {n.graph_episode_uuid: n for n in matches if n.graph_episode_uuid is not None}
            graph_evidence = graph_result_to_evidence(graph_result, notes_by_episode, question)
            all_evidence.extend(graph_evidence)
            answer = self._compose_graph_answer(question, graph_result, matches, citations, working_context)
            verification = self._verifier.verify(question, answer, citations, matches, evidence=all_evidence)
            retry_result = self._retry_if_needed(question, answer, citations, matches, verification)
            answer = retry_result.answer
            verification = retry_result.verification
            self.memory.working.add_step(f"Verifier: score={verification.evidence_score:.2f} ok={verification.ok}")
            if verification.ok and verification.sufficient:
                ask_result = AskResult(
                    answer=answer,
                    citations=citations,
                    matches=matches,
                    evidence=all_evidence,
                    session_id=normalized_session,
                )
                self.memory.record_turn(
                    normalized_user, normalized_session, question, answer,
                    citations=citations,
                )
                logger.info(
                    "Ask resolved from graph user=%s matches=%s citations=%s verify=%.2f",
                    normalized_user, len(matches), len(citations), verification.evidence_score,
                )
                return ask_result
            graph_fallback_answer = answer
            graph_fallback_citations = citations
            graph_fallback_matches = matches
            self.memory.working.add_step("图谱语义结果证据不足，继续合并本地检索兜底")

        graph = build_ask_graph(self.store)
        state = AgentState(mode="ask", question=question, user_id=normalized_user)
        result = AgentState.model_validate(graph.invoke(state))
        local_matches = _merge_notes(graph_fallback_matches, result.matches)
        local_citations = _merge_citations(graph_fallback_citations, result.citations)
        # Accumulate local evidence
        all_evidence.extend(notes_to_evidence(local_matches))
        answer = self._compose_local_answer(question, local_matches, local_citations, working_context)
        final_answer = answer or result.answer or "暂时没有生成答案。"
        verification = self._verifier.verify(
            question, final_answer, local_citations, local_matches, evidence=all_evidence
        )
        retry_result = self._retry_if_needed(
            question, final_answer, local_citations, local_matches, verification,
        )
        final_answer = retry_result.answer
        verification = retry_result.verification
        if not verification.ok or not verification.sufficient:
            final_answer = _annotate_answer(graph_fallback_answer or final_answer, verification)
        self.memory.working.add_step(f"Verifier: score={verification.evidence_score:.2f} ok={verification.ok}")

        # Third tier: web search fallback when local evidence is insufficient
        if not verification.sufficient and self._web_search_available:
            web_results, web_citations = self._execute_web_search(question)
            if web_citations:
                all_evidence.extend(web_results_to_evidence(web_results))
                self.memory.working.add_step(f"知识库证据不足，尝试网络搜索: {len(web_citations)} 条结果")
                web_answer = self._compose_web_answer(question, web_results, web_citations, working_context)
                web_verification = self._verifier.verify(
                    question, web_answer, web_citations, [], web_enabled=True, evidence=all_evidence,
                )
                retry_result = self._retry_if_needed(
                    question, web_answer, web_citations, [], web_verification, web_enabled=True,
                )
                web_answer = retry_result.answer
                web_verification = retry_result.verification
                if not web_verification.ok or not web_verification.sufficient:
                    web_answer = _annotate_answer(web_answer, web_verification)
                self.memory.working.add_step(
                    f"网络搜索完成: score={web_verification.evidence_score:.2f} ok={web_verification.ok}"
                )
                self.memory.record_turn(
                    normalized_user, normalized_session, question, web_answer,
                    citations=web_citations,
                )
                logger.info(
                    "Ask resolved from web user=%s citations=%s verify=%.2f",
                    normalized_user, len(web_citations), web_verification.evidence_score,
                )
                return AskResult(
                    answer=web_answer,
                    citations=web_citations,
                    matches=[],
                    evidence=all_evidence,
                    session_id=normalized_session,
                )

        ask_result = AskResult(
            answer=final_answer,
            citations=local_citations,
            matches=local_matches,
            evidence=all_evidence,
            session_id=normalized_session,
        )
        self.memory.record_turn(
            normalized_user, normalized_session, question, final_answer,
            citations=local_citations,
        )
        logger.info(
            "Ask resolved locally user=%s matches=%s citations=%s verify=%.2f",
            normalized_user, len(local_matches), len(local_citations), verification.evidence_score,
        )
        return ask_result

    def _execute_web_search(self, question: str) -> tuple[list[dict], list[Citation]]:
        """Run web search and convert results to Citation list.

        Returns (raw_results, citations). Both empty if unavailable or failed.
        """
        if not self._web_search_available:
            return [], []
        try:
            tool = self._tool_registry.get("web_search")
            if tool is None:
                return [], []
            result = tool.execute(query=question, limit=5)
            if not result.ok or not result.data:
                return [], []
            raw_results = result.data.get("results", [])
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

    def _build_web_answer_prompt(
        self, question: str, web_results: list[dict], web_citations: list[Citation],
        working_context: str,
    ) -> str:
        context_block = working_context or "无"
        web_blocks: list[str] = []
        for i, citation in enumerate(web_citations[:5], 1):
            web_blocks.append(
                f"[来源{i}] {citation.title}\n"
                f"URL: {citation.url}\n"
                f"摘要: {citation.snippet[:200]}"
            )
        web_block = "\n\n".join(web_blocks) if web_blocks else "无"
        return (
            "你是个人知识库助手。你的个人知识库中未能找到足够依据来回答这个问题，"
            "因此进行了一次网络搜索。请基于以下网络搜索结果，用自然中文回答问题。\n"
            "重要：你必须明确指出信息来源于网络搜索，并标注每个要点的来源编号（如 [来源1]）。"
            "如果搜索结果之间存在矛盾，请如实指出。"
            "如果搜索结果仍不足以完整回答问题，请说明现有信息的局限。\n\n"
            f"当前问题：{question}\n\n"
            f"最近对话与任务上下文：\n{context_block}\n\n"
            f"网络搜索结果：\n{web_block}"
        )

    def _compose_web_answer(
        self, question: str, web_results: list[dict], web_citations: list[Citation],
        working_context: str,
    ) -> str:
        prompt = self._build_web_answer_prompt(question, web_results, web_citations, working_context)
        generated = self._generate_answer(prompt)
        if generated:
            return generated
        if web_citations:
            sources = "；".join(
                f"[{c.title}]({c.url})" for c in web_citations[:3] if c.url
            )
            return f"根据网络搜索，相关来源包括：{sources}。"
        return "网络搜索未返回足够信息来回答这个问题。"
    def execute_ask_stream(self, question: str, user_id: str | None = None, session_id: str | None = None):
        """Public streaming ask API — search, prompt, and stream tokens.

        Yields SSE-compatible ``(event_type, payload)`` tuples:
        ``status``, ``metadata``, ``answer_delta``, ``answer_complete``,
        ``answer_error``, ``done``.

        The caller should wrap each tuple into an SSE frame and send it
        to the client.  This method handles session binding, graph/local
        search, prompt building, token streaming, and recording the turn.
        """
        normalized_user = user_id or self.settings.default_user
        normalized_session = session_id or "default"
        self.memory.bind_session(normalized_user, normalized_session)
        self.memory.working.set_goal(f"回答用户问题: {question[:80]}")
        self.memory.refresh_conversation_summary(normalized_user, normalized_session)
        working_context = self.memory.working.context_snapshot()
        trace_id = uuid4().hex[:12]

        yield ("status", {"message": "Searching your knowledge graph and local memory..."})

        graph_result = self.graph_store.ask(question, normalized_user, trace_id=trace_id)
        if graph_result.enabled is True:
            matches, citations = self._graph_matches_and_citations(normalized_user, question, graph_result)
            yield ("metadata", {
                "citations": [c.model_dump(mode="json") for c in citations],
                "matches": [n.model_dump(mode="json") for n in matches],
                "session_id": normalized_session,
            })
            prompt = self._build_graph_answer_prompt(
                question, graph_result, matches, citations, working_context,
            )
            full_answer = ""
            for event_type, payload in self._generate_answer_stream(prompt):
                if event_type == "answer_delta":
                    full_answer = str(payload.get("answer", ""))
                yield (event_type, payload)
            if full_answer:
                self.memory.record_turn(
                    normalized_user, normalized_session, question, full_answer,
                    citations=citations,
                )
                yield ("done", {
                    "answer": full_answer,
                    "citations": [c.model_dump(mode="json") for c in citations],
                    "matches": [n.model_dump(mode="json") for n in matches],
                    "session_id": normalized_session,
                })
            return

        # Local fallback
        graph = build_ask_graph(self.store)
        state = AgentState(mode="ask", question=question, user_id=normalized_user)
        result = AgentState.model_validate(graph.invoke(state))
        matches = result.matches
        citations = result.citations

        yield ("metadata", {
            "citations": [c.model_dump(mode="json") for c in citations],
            "matches": [n.model_dump(mode="json") for n in matches],
            "session_id": normalized_session,
        })

        prompt = self._build_local_answer_prompt(question, matches, citations, working_context)
        full_answer = ""
        for event_type, payload in self._generate_answer_stream(prompt):
            if event_type == "answer_delta":
                full_answer = str(payload.get("answer", ""))
            yield (event_type, payload)

        final_answer = full_answer or "我暂时无法从你的个人知识库中找到足够依据来回答这个问题。"

        # Web search fallback when local evidence is insufficient
        if (not full_answer or len(full_answer) < 20) and self._web_search_available:
            yield ("status", {"message": "个人知识库未找到足够依据，正在搜索网络..."})
            web_results, web_citations = self._execute_web_search(question)
            if web_citations:
                yield ("metadata", {
                    "citations": [c.model_dump(mode="json") for c in web_citations],
                    "web_enabled": True,
                    "session_id": normalized_session,
                })
                web_prompt = self._build_web_answer_prompt(
                    question, web_results, web_citations, working_context,
                )
                full_answer = ""
                for event_type, payload in self._generate_answer_stream(web_prompt):
                    if event_type == "answer_delta":
                        full_answer = str(payload.get("answer", ""))
                    yield (event_type, payload)
                final_answer = full_answer or "网络搜索未返回足够信息来回答这个问题。"
                self.memory.record_turn(
                    normalized_user, normalized_session, question, final_answer,
                    citations=web_citations,
                )
                yield ("done", {
                    "answer": final_answer,
                    "citations": [c.model_dump(mode="json") for c in web_citations],
                    "web_enabled": True,
                    "session_id": normalized_session,
                })
                return

        self.memory.record_turn(
            normalized_user, normalized_session, question, final_answer,
            citations=citations,
        )
        yield ("done", {
            "answer": final_answer,
            "citations": [c.model_dump(mode="json") for c in citations],
            "matches": [n.model_dump(mode="json") for n in matches],
            "session_id": normalized_session,
        })

    def _graph_citations(self, matches: list[KnowledgeNote], graph_result: GraphAskResult) -> list[Citation]:
        citations: list[Citation] = []
        facts_by_episode = _graph_facts_by_episode(graph_result)
        fallback_facts = _graph_fact_lines(graph_result, limit=8)
        for index, note in enumerate(matches[:5]):
            relation_fact = None
            if note.graph_episode_uuid:
                episode_facts = facts_by_episode.get(note.graph_episode_uuid, [])
                if episode_facts:
                    relation_fact = episode_facts[0]
            if relation_fact is None and index < len(fallback_facts):
                relation_fact = fallback_facts[index]
            citations.append(Citation(
                note_id=note.id, title=note.title,
                snippet=note.summary[:120],
                relation_fact=relation_fact,
            ))
        return citations

    def _graph_matches_and_citations(
        self, user_id: str, question: str, graph_result: GraphAskResult
    ) -> tuple[list[KnowledgeNote], list[Citation]]:
        episode_uuids = _graph_episode_uuids(graph_result)
        matches = self.store.find_notes_by_graph_episode_uuids(user_id, episode_uuids)
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
        if graph_result.node_refs:
            entity_lines = []
            for ref in graph_result.node_refs[:6]:
                line = ref.name
                if ref.summary:
                    line += f"（{ref.summary[:60]}）"
                entity_lines.append(line)
            focus_entities = "、".join(entity_lines) if entity_lines else "暂无"
        else:
            focus_entities = "、".join(graph_result.entity_names[:6]) if graph_result.entity_names else "暂无"
        graph_fact_blocks = self._build_graph_fact_blocks(graph_result, citations)
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
        graph_fact_block = "\n".join(graph_fact_blocks) if graph_fact_blocks else "无"
        notes_block = "\n\n".join(evidence_blocks) if evidence_blocks else "无"
        anchored_block = "\n".join(anchored_lines) if anchored_lines else "无"

        return (
            "你是个人知识库助手。请基于给定的对话上下文、图谱事实网络和原文证据，"
            "先总结结论，再解释原因，生成一段自然、直接、连续的中文回答。"
            "如果上下文里存在代词或省略，请结合最近几轮对话补全指代。"
            "不要先输出「最相关实体」「关联事实」「根据检索结果」之类栏目标题，不要机械列点，不要把原始片段逐条照搬。"
            "你的主要推理材料是图谱事实网络中的实体、关系边和事实；"
            "笔记片段只用于核对出处、补充限定条件和引用定位。"
            "如果证据不足，要明确指出不确定点。"
            "回答尽量先给出一句直接结论，再补充展开说明。\n\n"
            f"当前问题：{question}\n\n"
            f"最近对话与任务上下文：\n{context_block}\n\n"
            f"图谱实体：{focus_entities}\n\n"
            f"图谱事实网络（优先基于这些实体关系和事实推理）：\n{graph_fact_block}\n\n"
            f"原文证据锚点（用于校验和引用定位）：\n{anchored_block}\n\n"
            f"原文证据片段：\n{notes_block}"
        )

    def _build_graph_fact_blocks(
        self, graph_result: GraphAskResult, citations: list[Citation], limit: int = 8
    ) -> list[str]:
        citation_snippets: dict[str, str] = {}
        for citation in citations:
            if citation.relation_fact and citation.snippet:
                citation_snippets.setdefault(citation.relation_fact, citation.snippet)

        blocks: list[str] = []
        seen: set[str] = set()

        for fact_ref in graph_result.fact_refs:
            fact = fact_ref.fact.strip()
            if not fact or fact in seen:
                continue
            relation = _format_graph_relation(
                fact,
                fact_ref.source_node_name,
                fact_ref.target_node_name,
                citation_snippets.get(fact),
            )
            blocks.append(relation)
            seen.add(fact)
            if len(blocks) >= limit:
                return blocks

        for edge_ref in graph_result.edge_refs:
            fact = edge_ref.fact.strip()
            if not fact or fact in seen:
                continue
            relation = _format_graph_relation(
                fact,
                edge_ref.source_node_name,
                edge_ref.target_node_name,
                citation_snippets.get(fact),
            )
            blocks.append(relation)
            seen.add(fact)
            if len(blocks) >= limit:
                return blocks

        for hit in graph_result.citation_hits:
            fact = hit.relation_fact.strip()
            if not fact or fact in seen:
                continue
            source = hit.endpoint_names[0] if hit.endpoint_names else ""
            target = hit.endpoint_names[1] if len(hit.endpoint_names) > 1 else ""
            relation = _format_graph_relation(fact, source, target, citation_snippets.get(fact))
            if hit.score:
                relation += f" [score={hit.score}]"
            blocks.append(relation)
            seen.add(fact)
            if len(blocks) >= limit:
                return blocks

        for fact in graph_result.relation_facts:
            normalized = fact.strip()
            if not normalized or normalized in seen:
                continue
            blocks.append(f"- {normalized}")
            seen.add(normalized)
            if len(blocks) >= limit:
                return blocks
        return blocks

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

    def _build_local_answer_prompt(
        self, question: str, matches: list[KnowledgeNote],
        citations: list[Citation], working_context: str,
    ) -> str:
        """Build the LLM prompt for composing a local-store answer."""
        evidence_blocks = self._build_note_evidence_blocks(matches, citations)
        context_block = working_context or "无"
        notes_block = "\n\n".join(evidence_blocks) if evidence_blocks else "无"
        return (
            "你是个人知识库助手。请基于最近几轮对话和当前匹配到的笔记内容证据，"
            "用自然中文总结并回答用户问题。优先回答用户真正想问的内容，必要时承认信息不足。"
            "不要把答案写成检索结果罗列，也不要简单重复原始片段。"
            "回答尽量先给出一句直接结论，再补充必要解释。\n\n"
            f"当前问题：{question}\n\n"
            f"最近对话与任务上下文：\n{context_block}\n\n"
            f"相关内容证据：\n{notes_block}"
        )

    def _compose_local_answer(
        self, question: str, matches: list[KnowledgeNote],
        citations: list[Citation], working_context: str,
    ) -> str:
        prompt = self._build_local_answer_prompt(question, matches, citations, working_context)
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
                candidate_snippets = _top_sentences(_evidence_content(note), 3)
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
        web_enabled: bool = False,
    ) -> RetryResult:
        max_retries = max(0, self.settings.max_verify_retries)
        current_answer = answer
        current_verification = verification
        attempts = 0
        for attempt in range(max_retries):
            if current_verification.ok and current_verification.sufficient:
                break
            correction_prompt = self._build_correction_prompt(question, current_answer, current_verification)
            regenerated = self._generate_answer(correction_prompt)
            if regenerated:
                current_answer = regenerated
                current_verification = self._verifier.verify(
                    question, current_answer, citations, matches,
                    web_enabled=web_enabled,
                )
                attempts = attempt + 1
                self.memory.working.add_step(
                    f"Retry {attempt + 1}: score={current_verification.evidence_score:.2f} ok={current_verification.ok}"
                )
            else:
                break
        return RetryResult(answer=current_answer, verification=current_verification, attempts=attempts)

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

