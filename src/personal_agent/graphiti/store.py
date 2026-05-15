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
from .reranker import GraphCitationHit
from .search_strategies import GraphSearchStrategy, get_graph_search_strategy

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


class GraphitiStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._indices_ready = False
        self.search_strategy: GraphSearchStrategy = get_graph_search_strategy(settings.graph_search_strategy)

    def configured(self) -> bool:
        return bool(
            self.settings.graphiti_uri
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
            "configured": self.configured(),
            "base_url": self.settings.openai_base_url or "",
            "model": self.settings.openai_model,
            "embedding_base_url": self.settings.embedding_base_url
            or self.settings.openai_base_url
            or "",
            "embedding_model": self.settings.openai_embedding_model,
            "search_strategy": self.search_strategy.name,
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
                            config=self.search_strategy.search_config,
                            group_ids=[self._group_id(user_id)],
                        ),
                        timeout=45,
                    )

                node_names_by_uuid = {node.uuid: node.name for node in search_result.nodes}
                ranked_hits = self.search_strategy.citation_hits(
                    question, search_result.edges, node_names_by_uuid
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
                    search_strategy=self.search_strategy.name,
                )
                return GraphAskResult(
                    enabled=True,
                    answer=answer,
                    entity_names=entity_names,
                    relation_facts=relation_facts,
                    related_episode_uuids=related_episode_uuids,
                    citation_hits=ranked_hits,
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
