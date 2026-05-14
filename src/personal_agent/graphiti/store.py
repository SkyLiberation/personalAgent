from __future__ import annotations

import asyncio
import logging
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from graphiti_core.embedder.openai import OpenAIEmbedderConfig
from graphiti_core.graphiti import Graphiti
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.nodes import EpisodeType, EpisodicNode
from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF

from ..core.config import Settings
from ..core.logging_utils import log_event, trace_span
from ..core.models import Citation, KnowledgeNote, GraphNodeRef, GraphEdgeRef, GraphFactRef
from .dashscope_compatible_embedder import DashScopeCompatibleEmbedder
from .deepseek_compatible_client import DeepSeekCompatibleClient
from .ontology import CUSTOM_EXTRACTION_INSTRUCTIONS, ENTITY_TYPES

logger = logging.getLogger(__name__)
MARKDOWN_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
MARKDOWN_TABLE_RULE_RE = re.compile(r"^\s*\|?[\s:\-]+(?:\|[\s:\-]+)+\|?\s*$")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
MARKDOWN_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_|`)")
MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
BLOCKQUOTE_RE = re.compile(r"^\s*>\s?")


class GraphCaptureResult(BaseModel):
    enabled: bool = False
    error: str | None = None
    episode_uuid: str | None = None
    entity_names: list[str] = Field(default_factory=list)
    relation_facts: list[str] = Field(default_factory=list)
    related_episode_uuids: list[str] = Field(default_factory=list)
    node_refs: list[GraphNodeRef] = Field(default_factory=list)
    edge_refs: list[GraphEdgeRef] = Field(default_factory=list)
    fact_refs: list[GraphFactRef] = Field(default_factory=list)


class GraphAskResult(BaseModel):
    enabled: bool = False
    error: str | None = None
    answer: str | None = None
    entity_names: list[str] = Field(default_factory=list)
    relation_facts: list[str] = Field(default_factory=list)
    related_episode_uuids: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    citation_hits: list["GraphCitationHit"] = Field(default_factory=list)
    node_refs: list[GraphNodeRef] = Field(default_factory=list)
    edge_refs: list[GraphEdgeRef] = Field(default_factory=list)
    fact_refs: list[GraphFactRef] = Field(default_factory=list)


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
        self._indices_ready = False

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

    def ingest_note(
        self, note: KnowledgeNote, trace_id: str | None = None, attempt: int | None = None
    ) -> GraphCaptureResult:
        if not self.configured():
            return GraphCaptureResult(enabled=False, error="Graphiti is not configured.")
        if not self._neo4j_reachable():
            return GraphCaptureResult(enabled=False, error="Neo4j is not reachable.")
        try:
            return asyncio.run(self._ingest_note(note, trace_id=trace_id, attempt=attempt))
        except Exception as exc:
            logger.exception("Graphiti ingest failed for note %s", note.id)
            return GraphCaptureResult(enabled=False, error=str(exc)[:500] or exc.__class__.__name__)

    def ask(self, question: str, user_id: str, trace_id: str | None = None) -> GraphAskResult:
        if not self.configured():
            return GraphAskResult(enabled=False, error="Graphiti is not configured.")
        if not self._neo4j_reachable():
            return GraphAskResult(enabled=False, error="Neo4j is not reachable.")
        try:
            return asyncio.run(self._ask(question, user_id, trace_id=trace_id))
        except Exception as exc:
            logger.exception("Graphiti ask failed for user %s", user_id)
            return GraphAskResult(enabled=False, error=str(exc)[:500] or exc.__class__.__name__)

    def clear_user_group(self, user_id: str) -> int:
        if not self.configured():
            return 0
        if not self._neo4j_reachable():
            return 0
        try:
            return asyncio.run(self._clear_user_group(user_id))
        except Exception:
            logger.exception("Graphiti group reset failed for user %s", user_id)
            return 0

    def delete_episode(self, episode_uuid: str) -> bool:
        """Delete a single episode from the graph by its UUID."""
        if not self.configured():
            return False
        if not self._neo4j_reachable():
            return False
        try:
            return asyncio.run(self._delete_episode(episode_uuid))
        except Exception:
            logger.exception("Graphiti episode deletion failed for episode %s", episode_uuid)
            return False

    def _neo4j_reachable(self, timeout_seconds: float = 0.5) -> bool:
        uri = self.settings.graphiti_uri
        if not uri:
            return False

        parsed = urlparse(uri)
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            return False

        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                return True
        except OSError:
            logger.warning("Neo4j is unreachable host=%s port=%s", host, port)
            return False

    async def _ingest_note(
        self, note: KnowledgeNote, trace_id: str | None = None, attempt: int | None = None
    ) -> GraphCaptureResult:
        with trace_span(
            logger,
            "graphiti.ingest_note",
            trace_id=trace_id,
            note_id=note.id,
            user_id=note.user_id,
            attempt=attempt,
            model=self.settings.openai_model,
            embedding_model=self.settings.openai_embedding_model,
        ) as span:
            graphiti = await self._build_client(trace_id=span["trace_id"])
            trace_id = span["trace_id"]
            try:
                with trace_span(logger, "graphiti.add_episode", trace_id=trace_id, note_id=note.id, attempt=attempt):
                    add_result = await asyncio.wait_for(
                        graphiti.add_episode(
                            name=note.title,
                            episode_body=_graphiti_episode_body(note),
                            source_description=f"Personal note {note.id}",
                            reference_time=note.created_at,
                            source=EpisodeType.text,
                            group_id=self._group_id(note.user_id),
                            entity_types=ENTITY_TYPES,
                            custom_extraction_instructions=CUSTOM_EXTRACTION_INSTRUCTIONS,
                        ),
                        timeout=480,
                    )

                related_episode_uuids: list[str] = []
                try:
                    with trace_span(
                        logger,
                        "graphiti.search_after_ingest",
                        trace_id=trace_id,
                        note_id=note.id,
                        attempt=attempt,
                    ):
                        search_result = await asyncio.wait_for(
                            graphiti.search_(
                                query=note.summary,
                                config=COMBINED_HYBRID_SEARCH_RRF,
                                group_ids=[self._group_id(note.user_id)],
                            ),
                            timeout=45,
                        )
                    related_episode_uuids = _related_episode_ids_from_edges(
                        [edge.episodes for edge in search_result.edges],
                        exclude={add_result.episode.uuid},
                    )
                except Exception:
                    logger.warning(
                        "search_after_ingest failed for note=%s, continuing without related episodes",
                        note.id,
                    )

                node_names_by_uuid = {node.uuid: node.name for node in add_result.nodes}
                node_refs = [
                    GraphNodeRef(
                        uuid=node.uuid,
                        name=node.name,
                        labels=list(node.labels),
                        summary=getattr(node, "summary", "") or "",
                    )
                    for node in add_result.nodes
                ]
                edge_refs = [
                    GraphEdgeRef(
                        uuid=edge.uuid,
                        fact=edge.fact,
                        source_node_uuid=edge.source_node_uuid,
                        target_node_uuid=edge.target_node_uuid,
                        source_node_name=node_names_by_uuid.get(edge.source_node_uuid, ""),
                        target_node_name=node_names_by_uuid.get(edge.target_node_uuid, ""),
                        episodes=list(edge.episodes),
                    )
                    for edge in add_result.edges
                ]
                fact_refs = [
                    GraphFactRef(
                        fact=edge.fact,
                        edge_uuid=edge.uuid,
                        source_node_name=node_names_by_uuid.get(edge.source_node_uuid, ""),
                        target_node_name=node_names_by_uuid.get(edge.target_node_uuid, ""),
                        episode_uuids=list(edge.episodes),
                    )
                    for edge in add_result.edges
                ]

                log_event(
                    logger,
                    logging.INFO,
                    "graphiti.ingest_note.completed",
                    trace_id=trace_id,
                    note_id=note.id,
                    attempt=attempt,
                    episode_uuid=add_result.episode.uuid,
                    entity_count=len(add_result.nodes),
                    relation_count=len(add_result.edges),
                    related_episode_count=len(related_episode_uuids),
                )
                return GraphCaptureResult(
                    enabled=True,
                    episode_uuid=add_result.episode.uuid,
                    entity_names=_dedupe([node.name for node in add_result.nodes]),
                    relation_facts=_dedupe([edge.fact for edge in add_result.edges]),
                    related_episode_uuids=related_episode_uuids,
                    node_refs=node_refs,
                    edge_refs=edge_refs,
                    fact_refs=fact_refs,
                )
            finally:
                await graphiti.close()

    async def _ask(self, question: str, user_id: str, trace_id: str | None = None) -> GraphAskResult:
        with trace_span(
            logger,
            "graphiti.ask",
            trace_id=trace_id,
            user_id=user_id,
            model=self.settings.openai_model,
            embedding_model=self.settings.openai_embedding_model,
        ) as span:
            graphiti = await self._build_client(trace_id=span["trace_id"])
            trace_id = span["trace_id"]
            try:
                with trace_span(logger, "graphiti.search_for_ask", trace_id=trace_id, user_id=user_id):
                    search_result = await asyncio.wait_for(
                        graphiti.search_(
                            query=question,
                            config=COMBINED_HYBRID_SEARCH_RRF,
                            group_ids=[self._group_id(user_id)],
                        ),
                        timeout=45,
                    )

                node_names_by_uuid = {node.uuid: node.name for node in search_result.nodes}
                ranked_hits = _select_focus_hits(
                    question, _rank_graph_hits(question, search_result.edges, node_names_by_uuid)
                )
                entity_names = _dedupe([node.name for node in search_result.nodes])
                relation_facts = _dedupe([hit.relation_fact for hit in ranked_hits])
                related_episode_uuids = _dedupe([hit.episode_uuid for hit in ranked_hits])

                ask_node_refs = [
                    GraphNodeRef(
                        uuid=node.uuid,
                        name=node.name,
                        labels=list(node.labels),
                        summary=getattr(node, "summary", "") or "",
                    )
                    for node in search_result.nodes
                ]
                ask_edge_refs = [
                    GraphEdgeRef(
                        uuid=edge.uuid,
                        fact=edge.fact,
                        source_node_uuid=edge.source_node_uuid,
                        target_node_uuid=edge.target_node_uuid,
                        source_node_name=node_names_by_uuid.get(edge.source_node_uuid, ""),
                        target_node_name=node_names_by_uuid.get(edge.target_node_uuid, ""),
                        episodes=list(edge.episodes),
                    )
                    for edge in search_result.edges
                ]
                ask_fact_refs = [
                    GraphFactRef(
                        fact=edge.fact,
                        edge_uuid=edge.uuid,
                        source_node_name=node_names_by_uuid.get(edge.source_node_uuid, ""),
                        target_node_name=node_names_by_uuid.get(edge.target_node_uuid, ""),
                        episode_uuids=list(edge.episodes),
                    )
                    for edge in search_result.edges
                ]

                answer = None
                if relation_facts:
                    top_entities = "、".join(entity_names[:5]) if entity_names else "暂无实体摘要"
                    fact_lines = "\n".join(f"- {fact}" for fact in relation_facts[:5])
                    answer = f"图谱里最相关的实体：{top_entities}\n关联事实：\n{fact_lines}"

                log_event(
                    logger,
                    logging.INFO,
                    "graphiti.ask.completed",
                    trace_id=trace_id,
                    user_id=user_id,
                    entity_count=len(entity_names),
                    relation_count=len(relation_facts),
                    related_episode_count=len(related_episode_uuids),
                )
                return GraphAskResult(
                    enabled=True,
                    answer=answer,
                    entity_names=entity_names,
                    relation_facts=relation_facts,
                    related_episode_uuids=related_episode_uuids,
                    citation_hits=ranked_hits[:12],
                    node_refs=ask_node_refs,
                    edge_refs=ask_edge_refs,
                    fact_refs=ask_fact_refs,
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

    async def _delete_episode(self, episode_uuid: str) -> bool:
        graphiti = await self._build_client()
        try:
            await graphiti.remove_episode(episode_uuid)
            logger.info("Deleted graph episode episode_uuid=%s", episode_uuid)
            return True
        finally:
            await graphiti.close()

    async def _build_client(self, trace_id: str | None = None) -> Graphiti:
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
        if not self._indices_ready:
            with trace_span(
                logger,
                "graphiti.build_indices",
                trace_id=trace_id,
                graphiti_uri=self.settings.graphiti_uri,
            ):
                await asyncio.wait_for(graphiti.build_indices_and_constraints(), timeout=45)
            self._indices_ready = True
            log_event(
                logger,
                logging.INFO,
                "graphiti.indices.ready",
                trace_id=trace_id,
                graphiti_uri=self.settings.graphiti_uri,
            )
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


def _graphiti_episode_body(note: KnowledgeNote) -> str:
    content = note.content.strip()
    if not content:
        return content

    lines = content.replace("\r", "").split("\n")
    if lines and lines[0].startswith("Uploaded file: "):
        lines = lines[2:] if len(lines) > 1 and not lines[1].strip() else lines[1:]

    is_markdown = note.source_type == "note" and Path(note.source_ref).suffix.lower() in {".md", ".markdown"}
    if not is_markdown:
        return content[:8000]

    cleaned_lines: list[str] = []
    pending_table: list[list[str]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if pending_table:
                cleaned_lines.extend(_flatten_markdown_table(pending_table))
                pending_table = []
            continue
        if MARKDOWN_TABLE_RULE_RE.match(line):
            continue
        if MARKDOWN_TABLE_ROW_RE.match(line):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if any(cells):
                pending_table.append(cells)
            continue
        if pending_table:
            cleaned_lines.extend(_flatten_markdown_table(pending_table))
            pending_table = []

        line = MARKDOWN_HEADING_RE.sub("", line)
        line = BLOCKQUOTE_RE.sub("", line)
        line = MARKDOWN_LINK_RE.sub(r"\1", line)
        line = MARKDOWN_EMPHASIS_RE.sub("", line)
        line = line.replace("→", "->")
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        cleaned_lines.append(line)

    if pending_table:
        cleaned_lines.extend(_flatten_markdown_table(pending_table))

    compact = "\n".join(line for line in cleaned_lines if line).strip()
    return compact[:8000]


def _flatten_markdown_table(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    header = rows[0]
    if len(rows) == 1:
        return [" | ".join(cell for cell in header if cell)]

    flattened: list[str] = []
    for row in rows[1:]:
        pairs = []
        for index, cell in enumerate(row):
            label = header[index] if index < len(header) else f"col{index + 1}"
            if cell:
                pairs.append(f"{label}: {cell}")
        if pairs:
            flattened.append("; ".join(pairs))
    return flattened


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
