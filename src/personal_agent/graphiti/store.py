from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from graphiti_core.embedder.openai import OpenAIEmbedderConfig
from graphiti_core.graphiti import Graphiti
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.nodes import EpisodeType, EpisodicNode
from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF

from ..core.config import Settings
from ..core.models import Citation, KnowledgeNote
from .dashscope_compatible_embedder import DashScopeCompatibleEmbedder
from .deepseek_compatible_client import DeepSeekCompatibleClient
from .ontology import CUSTOM_EXTRACTION_INSTRUCTIONS, ENTITY_TYPES

logger = logging.getLogger(__name__)


class GraphCaptureResult(BaseModel):
    enabled: bool = False
    episode_uuid: str | None = None
    entity_names: list[str] = Field(default_factory=list)
    relation_facts: list[str] = Field(default_factory=list)
    related_episode_uuids: list[str] = Field(default_factory=list)


class GraphAskResult(BaseModel):
    enabled: bool = False
    answer: str | None = None
    entity_names: list[str] = Field(default_factory=list)
    relation_facts: list[str] = Field(default_factory=list)
    related_episode_uuids: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    citation_hits: list["GraphCitationHit"] = Field(default_factory=list)


class GraphCitationHit(BaseModel):
    episode_uuid: str
    relation_fact: str
    endpoint_names: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    entity_overlap_count: int = 0
    score: int = 0


class GraphitiStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def configured(self) -> bool:
        return bool(
            self.settings.graphiti_enabled
            and self.settings.graphiti_uri
            and self.settings.graphiti_user
            and self.settings.graphiti_password
            and self.settings.openai_api_key
            and self.settings.openai_base_url
            and self.settings.openai_model
            and (self.settings.embedding_api_key or self.settings.openai_api_key)
            and (self.settings.embedding_base_url or self.settings.openai_base_url)
            and self.settings.openai_embedding_model
        )

    def status(self) -> dict[str, str | bool]:
        return {
            "enabled": self.settings.graphiti_enabled,
            "configured": self.configured(),
            "base_url": self.settings.openai_base_url or "",
            "model": self.settings.openai_model,
            "embedding_base_url": self.settings.embedding_base_url
            or self.settings.openai_base_url
            or "",
            "embedding_model": self.settings.openai_embedding_model,
        }

    def ingest_note(self, note: KnowledgeNote) -> GraphCaptureResult:
        if not self.configured():
            return GraphCaptureResult(enabled=False)
        try:
            return asyncio.run(self._ingest_note(note))
        except Exception:
            logger.exception("Graphiti ingest failed for note %s", note.id)
            return GraphCaptureResult(enabled=False)

    def ask(self, question: str, user_id: str) -> GraphAskResult:
        if not self.configured():
            return GraphAskResult(enabled=False)
        try:
            return asyncio.run(self._ask(question, user_id))
        except Exception:
            logger.exception("Graphiti ask failed for user %s", user_id)
            return GraphAskResult(enabled=False)

    def clear_user_group(self, user_id: str) -> int:
        if not self.configured():
            return 0
        try:
            return asyncio.run(self._clear_user_group(user_id))
        except Exception:
            logger.exception("Graphiti group reset failed for user %s", user_id)
            return 0

    async def _ingest_note(self, note: KnowledgeNote) -> GraphCaptureResult:
        graphiti = await self._build_client()
        try:
            add_result = await graphiti.add_episode(
                name=note.title,
                episode_body=note.content,
                source_description=f"Personal note {note.id}",
                reference_time=note.created_at,
                source=EpisodeType.text,
                group_id=self._group_id(note.user_id),
                entity_types=ENTITY_TYPES,
                custom_extraction_instructions=CUSTOM_EXTRACTION_INSTRUCTIONS,
            )

            search_result = await graphiti.search_(
                query=note.summary,
                config=COMBINED_HYBRID_SEARCH_RRF,
                group_ids=[self._group_id(note.user_id)],
            )
            related_episode_uuids = _related_episode_ids_from_edges(
                [edge.episodes for edge in search_result.edges],
                exclude={add_result.episode.uuid},
            )

            return GraphCaptureResult(
                enabled=True,
                episode_uuid=add_result.episode.uuid,
                entity_names=_dedupe([node.name for node in add_result.nodes]),
                relation_facts=_dedupe([edge.fact for edge in add_result.edges]),
                related_episode_uuids=related_episode_uuids,
            )
        finally:
            await graphiti.close()

    async def _ask(self, question: str, user_id: str) -> GraphAskResult:
        graphiti = await self._build_client()
        try:
            search_result = await graphiti.search_(
                query=question,
                config=COMBINED_HYBRID_SEARCH_RRF,
                group_ids=[self._group_id(user_id)],
            )

            node_names_by_uuid = {node.uuid: node.name for node in search_result.nodes}
            ranked_hits = _select_focus_hits(question, _rank_graph_hits(question, search_result.edges, node_names_by_uuid))
            entity_names = _dedupe([node.name for node in search_result.nodes])
            relation_facts = _dedupe([hit.relation_fact for hit in ranked_hits])
            related_episode_uuids = _dedupe([hit.episode_uuid for hit in ranked_hits])

            answer = None
            if relation_facts:
                top_entities = "、".join(entity_names[:5]) if entity_names else "暂无实体摘要"
                fact_lines = "\n".join(f"- {fact}" for fact in relation_facts[:5])
                answer = f"图谱里最相关的实体：{top_entities}\n关联事实：\n{fact_lines}"

            return GraphAskResult(
                enabled=True,
                answer=answer,
                entity_names=entity_names,
                relation_facts=relation_facts,
                related_episode_uuids=related_episode_uuids,
                citation_hits=ranked_hits[:12],
            )
        finally:
            await graphiti.close()

    async def _clear_user_group(self, user_id: str) -> int:
        graphiti = await self._build_client()
        deleted_count = 0
        try:
            group_id = self._group_id(user_id)
            while True:
                episodes = await EpisodicNode.get_by_group_ids(graphiti.driver, [group_id], limit=100)
                if not episodes:
                    break
                for episode in episodes:
                    await graphiti.remove_episode(episode.uuid)
                    deleted_count += 1
            logger.info("Cleared graph group data user=%s group_id=%s deleted_episodes=%s", user_id, group_id, deleted_count)
            return deleted_count
        finally:
            await graphiti.close()

    async def _build_client(self) -> Graphiti:
        llm_client = DeepSeekCompatibleClient(
            config=LLMConfig(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
                model=self.settings.openai_model,
                small_model=self.settings.openai_small_model,
            )
        )
        embedder = DashScopeCompatibleEmbedder(
            config=OpenAIEmbedderConfig(
                api_key=self.settings.embedding_api_key or self.settings.openai_api_key,
                base_url=self.settings.embedding_base_url or self.settings.openai_base_url,
                embedding_model=self.settings.openai_embedding_model,
            )
        )
        graphiti = Graphiti(
            uri=self.settings.graphiti_uri,
            user=self.settings.graphiti_user,
            password=self.settings.graphiti_password,
            llm_client=llm_client,
            embedder=embedder,
        )
        await graphiti.build_indices_and_constraints()
        return graphiti

    def _group_id(self, user_id: str) -> str:
        raw = f"{self.settings.graphiti_group_prefix}-{user_id}"
        normalized = []
        for char in raw:
            if char.isalnum() or char in {"-", "_"}:
                normalized.append(char)
            else:
                normalized.append("_")
        return "".join(normalized)


def _dedupe(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def _related_episode_ids_from_edges(
    edge_episode_lists: list[list[str]], exclude: set[str] | None = None
) -> list[str]:
    seen: list[str] = []
    blocked = exclude or set()
    for episode_ids in edge_episode_lists:
        for episode_id in episode_ids:
            if episode_id in blocked or episode_id in seen:
                continue
            seen.append(episode_id)
    return seen


def _rank_graph_hits(question: str, edges: list, node_names_by_uuid: dict[str, str]) -> list[GraphCitationHit]:
    scored_hits: list[GraphCitationHit] = []
    query_bigrams = _character_bigrams(question)
    normalized_question = _normalize_text(question)
    query_keywords = _extract_keywords(question)

    for edge in edges:
        relation_fact = edge.fact.strip()
        if not relation_fact:
            continue

        endpoint_names = [
            node_names_by_uuid.get(edge.source_node_uuid, ""),
            node_names_by_uuid.get(edge.target_node_uuid, ""),
        ]
        relation_score, matched_terms, entity_overlap_count = _score_relation_fact(
            normalized_question,
            query_bigrams,
            query_keywords,
            relation_fact,
            endpoint_names,
        )

        for episode_uuid in edge.episodes:
            scored_hits.append(
                GraphCitationHit(
                    episode_uuid=episode_uuid,
                    relation_fact=relation_fact,
                    endpoint_names=[name for name in endpoint_names if name],
                    matched_terms=matched_terms,
                    entity_overlap_count=entity_overlap_count,
                    score=relation_score,
                )
            )

    scored_hits.sort(
        key=lambda hit: (
            hit.entity_overlap_count,
            len(hit.matched_terms),
            hit.score,
            len(hit.relation_fact),
        ),
        reverse=True,
    )
    return _dedupe_citation_hits(scored_hits)


def _score_relation_fact(
    normalized_question: str,
    query_bigrams: set[str],
    query_keywords: list[str],
    relation_fact: str,
    endpoint_names: list[str],
) -> tuple[int, list[str], int]:
    normalized_fact = _normalize_text(relation_fact)
    fact_bigrams = _character_bigrams(relation_fact)
    overlap_score = len(query_bigrams & fact_bigrams)
    direct_match_score = 4 if normalized_question and (
        normalized_question in normalized_fact or normalized_fact in normalized_question
    ) else 0

    endpoint_score = 0
    entity_overlap_count = 0
    for name in endpoint_names:
        normalized_name = _normalize_text(name)
        if len(normalized_name) >= 2 and normalized_name in normalized_question:
            endpoint_score += 6
            entity_overlap_count += 1

    matched_terms: list[str] = []
    keyword_score = 0
    for keyword in query_keywords:
        if keyword in relation_fact and keyword not in matched_terms:
            matched_terms.append(keyword)
            keyword_score += 5 if len(keyword) >= 4 else 3

    relation_bonus = _relation_phrase_score(query_keywords, relation_fact)
    total_score = endpoint_score + direct_match_score + overlap_score + keyword_score + relation_bonus
    return total_score, matched_terms, entity_overlap_count


def _dedupe_citation_hits(hits: list[GraphCitationHit]) -> list[GraphCitationHit]:
    deduped: list[GraphCitationHit] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit.episode_uuid, hit.relation_fact)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return deduped


def _select_focus_hits(question: str, hits: list[GraphCitationHit]) -> list[GraphCitationHit]:
    if not hits:
        return []
    question_keywords = _extract_keywords(question)
    entity_hits = [hit for hit in hits if hit.entity_overlap_count > 0]
    if entity_hits:
        hits = entity_hits
    keyword_hits = [
        hit
        for hit in hits
        if any(_normalize_text(keyword) in _normalize_text(hit.relation_fact) for keyword in question_keywords)
    ]
    if keyword_hits:
        hits = keyword_hits
    top_score = hits[0].score
    if top_score <= 0:
        return hits
    threshold = max(1, top_score - 3)
    focused_hits = [hit for hit in hits if hit.score >= threshold]
    return focused_hits or hits


def _character_bigrams(text: str) -> set[str]:
    normalized = _normalize_text(text)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def _normalize_text(text: str) -> str:
    return "".join(char.lower() for char in text if char.isalnum())


def _extract_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    ascii_buffer = ""
    cjk_buffer = ""
    for char in text:
        if char.isascii() and (char.isalnum() or char in {"_", "-"}):
            if cjk_buffer:
                _append_keyword(keywords, cjk_buffer)
                cjk_buffer = ""
            ascii_buffer += char.lower()
            continue
        if ascii_buffer:
            _append_keyword(keywords, ascii_buffer)
            ascii_buffer = ""
        if _is_cjk(char):
            cjk_buffer += char
            continue
        if cjk_buffer:
            _append_keyword(keywords, cjk_buffer)
            cjk_buffer = ""
    if ascii_buffer:
        _append_keyword(keywords, ascii_buffer)
    if cjk_buffer:
        _append_keyword(keywords, cjk_buffer)
    return keywords


def _keep_keyword(token: str) -> bool:
    if len(token) >= 2 and not token.isascii():
        return True
    if len(token) < 2:
        return False
    return token not in {
        "什么",
        "哪些",
        "哪个",
        "这个",
        "那个",
        "一下",
        "一下子",
        "about",
        "from",
        "into",
        "that",
        "this",
        "with",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "how",
        "the",
        "and",
        "for",
        "are",
        "was",
        "were",
        "is",
    }


def _relation_phrase_score(query_keywords: list[str], relation_fact: str) -> int:
    score = 0
    normalized_fact = _normalize_text(relation_fact)
    for left, right in zip(query_keywords, query_keywords[1:]):
        if len(left) < 2 or len(right) < 2:
            continue
        compact_pair = _normalize_text(left + right)
        if compact_pair and compact_pair in normalized_fact:
            score += 4
    return score


def _append_keyword(target: list[str], token: str) -> None:
    normalized = token.strip().lower()
    if _keep_keyword(normalized) and normalized not in target:
        target.append(normalized)


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"
