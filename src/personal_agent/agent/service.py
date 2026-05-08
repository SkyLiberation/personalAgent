from __future__ import annotations

from datetime import datetime
import logging

from openai import OpenAI
from pydantic import BaseModel, Field

from ..core.config import Settings
from ..core.models import AgentState, AskHistoryRecord, Citation, KnowledgeNote, RawIngestItem, ReviewCard
from ..graphiti.store import GraphAskResult, GraphCaptureResult, GraphCitationHit, GraphitiStore
from ..storage.ask_history_store import AskHistoryStore
from ..storage.memory_store import LocalMemoryStore
from .graph import build_ask_graph, build_capture_graph
from .nodes import digest_node

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


class ResetResult(BaseModel):
    user_id: str
    deleted_notes: int = 0
    deleted_reviews: int = 0
    deleted_conversations: int = 0
    deleted_upload_files: int = 0
    deleted_ask_history: int = 0
    deleted_graph_episodes: int = 0


class AgentService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.store = LocalMemoryStore(self.settings.data_dir)
        self.graph_store = GraphitiStore(self.settings)
        self.ask_history_store = AskHistoryStore(self.settings.postgres_url)

    def capture(
        self,
        text: str,
        source_type: str = "text",
        user_id: str | None = None,
        source_ref: str | None = None,
        attempt_graph: bool = True,
    ) -> CaptureResult:
        normalized_user = user_id or self.settings.default_user
        logger.info("Starting capture user=%s source_type=%s", normalized_user, source_type)
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
                normalized_user,
                result.note.id,
                result.note.graph_sync_status,
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
            updated_note.related_note_ids = [note.id for note in related_notes if note.id != updated_note.id]
            updated_note.updated_at = datetime.utcnow()
            self.store.update_note(updated_note)
            result.note = updated_note
        elif self.graph_store.configured():
            result.note.graph_sync_status = "failed"
            result.note.graph_sync_error = "Graphiti ingest returned disabled result."
            result.note.updated_at = datetime.utcnow()
            self.store.update_note(result.note)

        logger.info(
            "Capture finished user=%s note_id=%s graph_enabled=%s related_notes=%s",
            normalized_user,
            result.note.id,
            graph_result.enabled,
            len(related_notes),
        )

        return CaptureResult(
            note=result.note,
            related_notes=related_notes,
            review_card=result.review_card,
            graph_enabled=graph_result.enabled,
        )

    def ask(self, question: str, user_id: str | None = None, session_id: str | None = None) -> AskResult:
        normalized_user = user_id or self.settings.default_user
        normalized_session = session_id or "default"
        logger.info("Starting ask user=%s question=%s", normalized_user, question[:120])
        conversation_context = self._conversation_context(normalized_user, normalized_session)

        graph_result = self.graph_store.ask(question, normalized_user)
        if graph_result.enabled:
            matches, citations = self._graph_matches_and_citations(normalized_user, question, graph_result)
            answer = self._compose_graph_answer(question, graph_result, matches, citations, conversation_context)
            ask_result = AskResult(
                answer=answer,
                citations=citations,
                matches=matches,
                graph_enabled=True,
                session_id=normalized_session,
            )
            self._record_ask_history(normalized_user, normalized_session, question, ask_result)
            logger.info(
                "Ask resolved from graph user=%s matches=%s citations=%s",
                normalized_user,
                len(matches),
                len(citations),
            )
            return ask_result

        graph = build_ask_graph(self.store)
        state = AgentState(mode="ask", question=question, user_id=normalized_user)
        result = AgentState.model_validate(graph.invoke(state))
        answer = self._compose_local_answer(question, result.matches, result.citations, conversation_context)
        ask_result = AskResult(
            answer=answer or result.answer or "暂时没有生成答案。",
            citations=result.citations,
            matches=result.matches,
            graph_enabled=False,
            session_id=normalized_session,
        )
        self._record_ask_history(normalized_user, normalized_session, question, ask_result)
        logger.info(
            "Ask resolved locally user=%s matches=%s citations=%s",
            normalized_user,
            len(result.matches),
            len(result.citations),
        )
        return ask_result

    def digest(self, user_id: str | None = None) -> DigestResult:
        normalized_user = user_id or self.settings.default_user
        logger.info("Generating digest user=%s", normalized_user)
        return DigestResult(
            message=digest_node(self.store, normalized_user),
            recent_notes=self.store.list_notes(normalized_user)[-5:],
            due_reviews=self.store.due_reviews(normalized_user),
        )

    def list_notes(self, user_id: str | None = None) -> list[KnowledgeNote]:
        normalized_user = user_id or self.settings.default_user
        logger.info("Loading notes user=%s", normalized_user)
        return list(reversed(self.store.list_notes(normalized_user)))

    def health(self) -> dict[str, object]:
        graph_status = self.graph_store.status()
        return {
            "status": "ok",
            "graphiti": graph_status,
            "ask_history": {
                "configured": self.ask_history_store.configured(),
            },
        }

    def list_ask_history(
        self, user_id: str | None = None, limit: int = 20, session_id: str | None = None
    ) -> list[AskHistoryRecord]:
        normalized_user = user_id or self.settings.default_user
        normalized_session = session_id or None
        logger.info("Loading ask history user=%s session=%s limit=%s", normalized_user, normalized_session, limit)
        if self.ask_history_store.configured():
            return self.ask_history_store.list_history(normalized_user, limit, normalized_session)

        local_records = self.store.list_conversation_turns(normalized_user, normalized_session or "default", limit)
        return [AskHistoryRecord.model_validate(item) for item in reversed(local_records)]

    def reset_user_data(self, user_id: str | None = None) -> ResetResult:
        normalized_user = user_id or self.settings.default_user
        logger.warning("Resetting user data for user=%s", normalized_user)
        deleted_graph_episodes = 0
        if self.graph_store.configured():
            deleted_graph_episodes = self.graph_store.clear_user_group(normalized_user)
        local_result = self.store.clear_user_data(normalized_user, remove_uploaded_files=True)
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

    def _merge_graph_capture(
        self, note: KnowledgeNote, graph_result: GraphCaptureResult
    ) -> KnowledgeNote:
        note.graph_episode_uuid = graph_result.episode_uuid
        note.entity_names = graph_result.entity_names
        note.relation_facts = graph_result.relation_facts[:8]
        note.graph_sync_status = "synced"
        note.graph_sync_error = None
        note.updated_at = datetime.utcnow()
        return note

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

        logger.info("Starting background graph sync note_id=%s", note_id)
        note.graph_sync_status = "pending"
        note.graph_sync_error = None
        note.updated_at = datetime.utcnow()
        self.store.update_note(note)

        try:
            graph_result = self.graph_store.ingest_note(note)
            if not graph_result.enabled:
                note.graph_sync_status = "failed"
                note.graph_sync_error = "Graphiti ingest returned disabled result."
                note.updated_at = datetime.utcnow()
                self.store.update_note(note)
                logger.warning("Background graph sync failed note_id=%s", note_id)
                return False

            updated_note = self._merge_graph_capture(note, graph_result)
            related_notes = self.store.find_notes_by_graph_episode_uuids(
                note.user_id, graph_result.related_episode_uuids
            )
            updated_note.related_note_ids = [item.id for item in related_notes if item.id != updated_note.id]
            updated_note.updated_at = datetime.utcnow()
            self.store.update_note(updated_note)
            logger.info(
                "Background graph sync succeeded note_id=%s episode_uuid=%s entities=%s relations=%s",
                note_id,
                updated_note.graph_episode_uuid,
                len(updated_note.entity_names),
                len(updated_note.relation_facts),
            )
            return True
        except Exception as exc:
            note.graph_sync_status = "failed"
            note.graph_sync_error = str(exc)[:500]
            note.updated_at = datetime.utcnow()
            self.store.update_note(note)
            logger.exception("Background graph sync raised exception note_id=%s", note_id)
            return False

    def _graph_citations(
        self, matches: list[KnowledgeNote], graph_result: GraphAskResult
    ) -> list[Citation]:
        citations: list[Citation] = []
        facts = graph_result.relation_facts
        for index, note in enumerate(matches[:5]):
            citations.append(
                Citation(
                    note_id=note.id,
                    title=note.title,
                    snippet=note.summary[:120],
                    relation_fact=facts[index] if index < len(facts) else None,
                )
            )
        return citations

    def _graph_matches_and_citations(
        self, user_id: str, question: str, graph_result: GraphAskResult
    ) -> tuple[list[KnowledgeNote], list[Citation]]:
        matches = self.store.find_notes_by_graph_episode_uuids(
            user_id, graph_result.related_episode_uuids
        )
        if not graph_result.citation_hits:
            return matches, self._graph_citations(matches, graph_result)

        notes_by_episode_uuid = {
            note.graph_episode_uuid: note for note in matches if note.graph_episode_uuid is not None
        }
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
                citations.append(
                    Citation(
                        note_id=note.id,
                        title=note.title,
                        snippet=_best_snippet(note, hit, question),
                        relation_fact=hit.relation_fact,
                    )
                )
                seen_citation_keys.add(citation_key)
            if note.id not in seen_note_ids:
                matched_notes.append(note)
                seen_note_ids.add(note.id)
            if len(citations) >= 5:
                break

        for note in matches:
            if note.id in seen_note_ids:
                continue
            matched_notes.append(note)
            seen_note_ids.add(note.id)

        return matched_notes, citations

    def _compose_graph_answer(
        self,
        question: str,
        graph_result: GraphAskResult,
        matches: list[KnowledgeNote],
        citations: list[Citation],
        conversation_context: list[AskHistoryRecord],
    ) -> str:
        focus_entities = "、".join(graph_result.entity_names[:6]) if graph_result.entity_names else "暂无"
        relation_facts = graph_result.relation_facts[:8]
        context_lines = [f"Q: {item.question}\nA: {item.answer}" for item in conversation_context[-4:]]
        evidence_blocks = self._build_note_evidence_blocks(matches, citations)
        citation_lines = [f"- {citation.title}: {citation.relation_fact or citation.snippet}" for citation in citations[:5]]
        fact_lines = [f"- {fact}" for fact in relation_facts]
        context_block = "\n".join(context_lines) if context_lines else "无"
        notes_block = "\n\n".join(evidence_blocks) if evidence_blocks else "无"
        citations_block = "\n".join(citation_lines) if citation_lines else "无"
        facts_block = "\n".join(fact_lines) if fact_lines else "无"

        prompt = (
            "你是个人知识库助手。请基于给定的对话上下文、图谱事实和笔记内容证据，"
            "先总结结论，再解释原因，生成一段自然、直接、连续的中文回答。"
            "如果上下文里存在代词或省略，请结合最近几轮对话补全指代。"
            "不要先输出“最相关实体”“关联事实”“根据检索结果”之类栏目标题，不要机械列点，不要把原始片段逐条照搬。"
            "你的任务是整合证据、压缩冗余、形成更像人写的总结。"
            "如果证据不足，要明确指出不确定点。"
            "回答尽量先给出一句直接结论，再补充展开说明。\n\n"
            f"当前问题：{question}\n\n"
            f"最近对话：\n{context_block}\n\n"
            f"图谱实体：{focus_entities}\n\n"
            f"图谱事实：\n{facts_block}\n\n"
            f"相关内容证据：\n{notes_block}\n\n"
            f"引用锚点：\n{citations_block}"
        )
        generated = self._generate_answer(prompt)
        if generated:
            return generated
        if relation_facts:
            return "结合你已有的笔记和图谱信息，" + "；".join(relation_facts[:4]) + "。"
        return graph_result.answer or "暂时没有生成答案。"

    def _compose_local_answer(
        self,
        question: str,
        matches: list[KnowledgeNote],
        citations: list[Citation],
        conversation_context: list[AskHistoryRecord],
    ) -> str:
        context_lines = [f"Q: {item.question}\nA: {item.answer}" for item in conversation_context[-4:]]
        evidence_blocks = self._build_note_evidence_blocks(matches, citations)
        context_block = "\n".join(context_lines) if context_lines else "无"
        notes_block = "\n\n".join(evidence_blocks) if evidence_blocks else "无"
        prompt = (
            "你是个人知识库助手。请基于最近几轮对话和当前匹配到的笔记内容证据，"
            "用自然中文总结并回答用户问题。优先回答用户真正想问的内容，必要时承认信息不足。"
            "不要把答案写成检索结果罗列，也不要简单重复原始片段。"
            "回答尽量先给出一句直接结论，再补充必要解释。\n\n"
            f"当前问题：{question}\n\n"
            f"最近对话：\n{context_block}\n\n"
            f"相关内容证据：\n{notes_block}"
        )
        generated = self._generate_answer(prompt)
        if generated:
            return generated
        if matches:
            return f"结合你前面的提问和当前笔记内容，我更倾向于认为：{matches[0].summary}"
        return "我暂时无法从你的个人知识库中找到足够依据来回答这个问题。"

    def _record_ask_history(self, user_id: str, session_id: str, question: str, result: AskResult) -> None:
        record = AskHistoryRecord(
            user_id=user_id,
            session_id=session_id,
            question=question,
            answer=result.answer,
            citations=result.citations,
            graph_enabled=result.graph_enabled,
        )
        self.store.append_conversation_turn(record.model_dump(mode="json"))
        try:
            if self.ask_history_store.configured():
                self.ask_history_store.append(record)
        except Exception:
            logger.exception("Failed to persist ask history user=%s", user_id)

    def _conversation_context(self, user_id: str, session_id: str, limit: int = 6) -> list[AskHistoryRecord]:
        if self.ask_history_store.configured():
            try:
                records = self.ask_history_store.list_history(user_id, limit, session_id)
                return list(reversed(records))
            except Exception:
                logger.exception("Failed to load persisted conversation context user=%s session=%s", user_id, session_id)

        local_records = self.store.list_conversation_turns(user_id, session_id, limit)
        return [AskHistoryRecord.model_validate(item) for item in local_records]

    def _generate_answer(self, prompt: str) -> str | None:
        if not (self.settings.openai_api_key and self.settings.openai_base_url and self.settings.openai_model):
            return None
        try:
            client = OpenAI(api_key=self.settings.openai_api_key, base_url=self.settings.openai_base_url)
            response = client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个严谨、善于归纳总结的个人知识库问答助手。"
                            "你的首要任务不是复述检索片段，而是把证据整理成简洁、可信、可读的答案。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=600,
            )
            return (response.choices[0].message.content or "").strip() or None
        except Exception:
            logger.exception("Failed to generate answer from LLM")
            return None

    def _build_note_evidence_blocks(
        self, matches: list[KnowledgeNote], citations: list[Citation], limit: int = 5
    ) -> list[str]:
        citation_map: dict[str, list[Citation]] = {}
        for citation in citations:
            citation_map.setdefault(citation.note_id, []).append(citation)

        blocks: list[str] = []
        for note in matches[:limit]:
            candidate_snippets = [item.snippet for item in citation_map.get(note.id, []) if item.snippet]
            if not candidate_snippets:
                candidate_snippets = _top_sentences(note.content, 3)
            excerpt = "\n".join(f"- {snippet}" for snippet in candidate_snippets[:3] if snippet.strip())
            if not excerpt:
                excerpt = f"- {note.summary}"
            blocks.append(
                f"[笔记] {note.title}\n"
                f"摘要：{note.summary}\n"
                f"证据片段：\n{excerpt}"
            )
        return blocks


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
    best_part = ""
    best_score = -1
    question_keywords = _extract_question_keywords(question)

    for part in _split_sentences(note.content):
        score = 0
        if hit.relation_fact in part:
            score += 10
        for entity_name in hit.endpoint_names or note.entity_names:
            if len(entity_name) >= 2 and entity_name in part:
                score += 4
        for keyword in question_keywords:
            if keyword in part:
                score += 2
        if score > best_score:
            best_part = part
            best_score = score

    if best_part:
        return best_part[:160]
    return note.summary[:160]


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
