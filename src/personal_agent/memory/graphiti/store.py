from __future__ import annotations

import asyncio
import logging
import socket
from urllib.parse import urlparse

from graphiti_core.embedder.openai import OpenAIEmbedderConfig
from graphiti_core.graphiti import Graphiti
from graphiti_core.nodes import EpisodeType, EpisodicNode
from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF
from neo4j import AsyncGraphDatabase

from personal_agent.kernel.config import Settings
from personal_agent.kernel.graph_results import GraphAskResult, GraphCaptureResult
from personal_agent.kernel.logging_utils import log_event, trace_span
from personal_agent.kernel.models import (
    KnowledgeNote,
    GraphNodeRef,
    GraphEdgeRef,
    GraphFactRef,
)
from personal_agent.kernel.projections import graph_ingest_document_from_note
from personal_agent.memory.graphiti.dashscope_compatible_embedder import DashScopeCompatibleEmbedder
from personal_agent.memory.graphiti.documents import (
    dedupe as _dedupe,
    episode_uuids_from_search_result as _episode_uuids_from_search_result,
    graphiti_episode_body as _graphiti_episode_body,
    graphiti_safe_episode_body as _graphiti_safe_episode_body,
    looks_like_content_filter_error as _looks_like_content_filter_error,
    related_episode_ids_from_edges as _related_episode_ids_from_edges,
)
from personal_agent.memory.graphiti.llm_strategies import build_graphiti_llm_client
from personal_agent.memory.graphiti.ontology import CUSTOM_EXTRACTION_INSTRUCTIONS, ENTITY_TYPES
from personal_agent.memory.graphiti.search_strategies import (
    GraphSearchStrategy,
    apply_search_config_overrides,
    get_graph_search_strategy,
)

logger = logging.getLogger(__name__)


class GraphitiStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._indices_ready = False
        self.search_strategy: GraphSearchStrategy = apply_search_config_overrides(
            get_graph_search_strategy(settings.graphiti.search_strategy),
            max_hops=settings.graphiti.search_max_hops,
            limit=settings.graphiti.search_limit,
            citation_limit=settings.graphiti.search_citation_limit,
            min_score=settings.graphiti.search_min_score,
        )

    def configured(self) -> bool:
        return bool(
            self.settings.graphiti.uri
            and self.settings.graphiti.user
            and self.settings.graphiti.password
            and (self.settings.graphiti.llm_api_key or self.settings.openai.api_key)
            and (self.settings.graphiti.llm_base_url or self.settings.openai.base_url)
            and (self.settings.graphiti.llm_model or self.settings.openai.model)
            and (self.settings.openai.embedding_api_key or self.settings.openai.api_key)
            and (self.settings.openai.embedding_base_url or self.settings.openai.base_url)
            and self.settings.openai.embedding_model
        )

    def status(self) -> dict[str, str | bool]:
        return {
            "configured": self.configured(),
            "base_url": self.settings.graphiti.llm_base_url
            or self.settings.openai.base_url
            or "",
            "model": self.settings.graphiti.llm_model or self.settings.openai.model,
            "embedding_base_url": self.settings.openai.embedding_base_url
            or self.settings.openai.base_url
            or "",
            "embedding_model": self.settings.openai.embedding_model,
            "search_strategy": self.search_strategy.name,
        }

    def ingest_note(
        self,
        note: KnowledgeNote,
        trace_id: str | None = None,
        attempt: int | None = None,
    ) -> GraphCaptureResult:
        if not self.configured():
            return GraphCaptureResult(
                enabled=False, error="Graphiti is not configured."
            )
        if not self._neo4j_reachable():
            return GraphCaptureResult(enabled=False, error="Neo4j is not reachable.")
        try:
            return asyncio.run(
                self._ingest_note(note, trace_id=trace_id, attempt=attempt)
            )
        except Exception as exc:
            logger.exception("Graphiti ingest failed for note %s", note.id)
            return GraphCaptureResult(
                enabled=False, error=str(exc)[:500] or exc.__class__.__name__
            )

    def ingest_notes(
        self,
        notes: list[KnowledgeNote],
        *,
        trace_id: str | None = None,
        max_workers: int | None = None,
    ) -> dict[str, GraphCaptureResult]:
        if not notes:
            return {}
        if not self.configured():
            return {
                note.id: GraphCaptureResult(enabled=False, error="Graphiti is not configured.")
                for note in notes
            }
        if not self._neo4j_reachable():
            return {
                note.id: GraphCaptureResult(enabled=False, error="Neo4j is not reachable.")
                for note in notes
            }
        worker_count = max(1, max_workers or self.settings.graphiti.sync_max_workers)
        try:
            return asyncio.run(
                self._ingest_notes(notes, trace_id=trace_id, max_workers=worker_count)
            )
        except Exception as exc:
            logger.exception("Graphiti batch ingest failed notes=%s", len(notes))
            return {
                note.id: GraphCaptureResult(
                    enabled=False, error=str(exc)[:500] or exc.__class__.__name__
                )
                for note in notes
            }

    def ask(
        self, question: str, user_id: str, trace_id: str | None = None
    ) -> GraphAskResult:
        if not self.configured():
            return GraphAskResult(enabled=False, error="Graphiti is not configured.")
        if not self._neo4j_reachable():
            return GraphAskResult(enabled=False, error="Neo4j is not reachable.")
        try:
            return asyncio.run(self._ask(question, user_id, trace_id=trace_id))
        except Exception as exc:
            logger.exception("Graphiti ask failed for user %s", user_id)
            return GraphAskResult(
                enabled=False, error=str(exc)[:500] or exc.__class__.__name__
            )

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

    def clear_all_data(self, preserve_group_ids: list[str] | None = None) -> int:
        if not (
            self.settings.graphiti.uri
            and self.settings.graphiti.user
            and self.settings.graphiti.password
        ):
            return 0
        if not self._neo4j_reachable():
            return 0
        try:
            return asyncio.run(
                self._clear_all_data(preserve_group_ids=preserve_group_ids)
            )
        except Exception:
            logger.exception("Graphiti database reset failed")
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
            logger.exception(
                "Graphiti episode deletion failed for episode %s", episode_uuid
            )
            return False

    def _neo4j_reachable(self, timeout_seconds: float = 0.5) -> bool:
        uri = self.settings.graphiti.uri
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
        self,
        note: KnowledgeNote,
        trace_id: str | None = None,
        attempt: int | None = None,
    ) -> GraphCaptureResult:
        document = graph_ingest_document_from_note(note)
        with trace_span(
            logger,
            "graphiti.ingest_note",
            trace_id=trace_id,
            note_id=document.id,
            user_id=document.user_id,
            attempt=attempt,
            model=self.settings.graphiti.llm_model or self.settings.openai.model,
            embedding_model=self.settings.openai.embedding_model,
        ) as span:
            graphiti = await self._build_client(trace_id=span["trace_id"])
            trace_id = span["trace_id"]
            try:
                with trace_span(
                    logger,
                    "graphiti.add_episode",
                    trace_id=trace_id,
                    note_id=note.id,
                    attempt=attempt,
                ):
                    try:
                        add_result = await asyncio.wait_for(
                            graphiti.add_episode(
                                name=document.title,
                                episode_body=_graphiti_episode_body(
                                    document,
                                    max_chars=self.settings.graphiti.episode_max_chars,
                                ),
                                source_description=f"Personal note {document.id}",
                                reference_time=document.created_at,
                                source=EpisodeType.text,
                                group_id=self._group_id(document.user_id),
                                entity_types=ENTITY_TYPES,
                                custom_extraction_instructions=CUSTOM_EXTRACTION_INSTRUCTIONS,
                            ),
                            timeout=self.settings.graphiti.add_episode_timeout_seconds,
                        )
                    except Exception as exc:
                        if (
                            not self.settings.graphiti.content_filter_fallback
                            or not _looks_like_content_filter_error(exc)
                        ):
                            raise
                        logger.warning(
                            "Graphiti add_episode hit content filter; retrying with safe fallback body note=%s",
                            document.id,
                        )
                        add_result = await asyncio.wait_for(
                            graphiti.add_episode(
                                name=document.title,
                                episode_body=_graphiti_safe_episode_body(document),
                                source_description=f"Personal note {document.id} (content-filter fallback)",
                                reference_time=document.created_at,
                                source=EpisodeType.text,
                                group_id=self._group_id(document.user_id),
                                entity_types=ENTITY_TYPES,
                                custom_extraction_instructions=CUSTOM_EXTRACTION_INSTRUCTIONS,
                            ),
                            timeout=self.settings.graphiti.add_episode_timeout_seconds,
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
                                query=document.summary,
                                config=COMBINED_HYBRID_SEARCH_RRF,
                                group_ids=[self._group_id(document.user_id)],
                            ),
                            timeout=self.settings.graphiti.search_timeout_seconds,
                        )
                    related_episode_uuids = _related_episode_ids_from_edges(
                        [edge.episodes for edge in search_result.edges],
                        exclude={add_result.episode.uuid},
                    )
                except Exception:
                    logger.warning(
                        "search_after_ingest failed for note=%s, continuing without related episodes",
                        document.id,
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
                        source_node_name=node_names_by_uuid.get(
                            edge.source_node_uuid, ""
                        ),
                        target_node_name=node_names_by_uuid.get(
                            edge.target_node_uuid, ""
                        ),
                        episodes=list(edge.episodes),
                    )
                    for edge in add_result.edges
                ]
                fact_refs = [
                    GraphFactRef(
                        fact=edge.fact,
                        edge_uuid=edge.uuid,
                        source_node_name=node_names_by_uuid.get(
                            edge.source_node_uuid, ""
                        ),
                        target_node_name=node_names_by_uuid.get(
                            edge.target_node_uuid, ""
                        ),
                        episode_uuids=list(edge.episodes),
                    )
                    for edge in add_result.edges
                ]

                log_event(
                    logger,
                    logging.INFO,
                    "graphiti.ingest_note.completed",
                    trace_id=trace_id,
                    note_id=document.id,
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
                await self._close_client(graphiti)

    async def _ingest_notes(
        self,
        notes: list[KnowledgeNote],
        *,
        trace_id: str | None,
        max_workers: int,
    ) -> dict[str, GraphCaptureResult]:
        semaphore = asyncio.Semaphore(max(1, max_workers))

        async def _limited(note: KnowledgeNote, index: int) -> tuple[str, GraphCaptureResult]:
            async with semaphore:
                result = await self._ingest_note(
                    note,
                    trace_id=f"{trace_id or 'graph-batch'}-{index}",
                )
                return note.id, result

        tasks = [_limited(note, index + 1) for index, note in enumerate(notes)]
        pairs = await asyncio.gather(*tasks)
        return dict(pairs)

    async def _ask(
        self, question: str, user_id: str, trace_id: str | None = None
    ) -> GraphAskResult:
        with trace_span(
            logger,
            "graphiti.ask",
            trace_id=trace_id,
            user_id=user_id,
            model=self.settings.graphiti.llm_model or self.settings.openai.model,
            embedding_model=self.settings.openai.embedding_model,
        ) as span:
            graphiti = await self._build_client(trace_id=span["trace_id"])
            trace_id = span["trace_id"]
            try:
                with trace_span(
                    logger,
                    "graphiti.search_for_ask",
                    trace_id=trace_id,
                    user_id=user_id,
                ):
                    search_result = await asyncio.wait_for(
                        graphiti.search_(
                            query=question,
                            config=self.search_strategy.search_config,
                            group_ids=[self._group_id(user_id)],
                        ),
                        timeout=self.settings.graphiti.search_timeout_seconds,
                    )

                node_names_by_uuid = {
                    node.uuid: node.name for node in search_result.nodes
                }
                ranked_hits = self.search_strategy.citation_hits(
                    question, search_result.edges, node_names_by_uuid
                )
                entity_names = _dedupe([node.name for node in search_result.nodes])
                relation_facts = _dedupe([hit.relation_fact for hit in ranked_hits])
                related_episode_uuids = _dedupe([
                    *[hit.episode_uuid for hit in ranked_hits],
                    *_episode_uuids_from_search_result(search_result),
                ])

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
                        source_node_name=node_names_by_uuid.get(
                            edge.source_node_uuid, ""
                        ),
                        target_node_name=node_names_by_uuid.get(
                            edge.target_node_uuid, ""
                        ),
                        episodes=list(edge.episodes),
                    )
                    for edge in search_result.edges
                ]
                ask_fact_refs = [
                    GraphFactRef(
                        fact=edge.fact,
                        edge_uuid=edge.uuid,
                        source_node_name=node_names_by_uuid.get(
                            edge.source_node_uuid, ""
                        ),
                        target_node_name=node_names_by_uuid.get(
                            edge.target_node_uuid, ""
                        ),
                        episode_uuids=list(edge.episodes),
                    )
                    for edge in search_result.edges
                ]

                answer = None
                if relation_facts:
                    top_entities = (
                        "、".join(entity_names[:5]) if entity_names else "暂无实体摘要"
                    )
                    fact_lines = "\n".join(f"- {fact}" for fact in relation_facts[:5])
                    answer = (
                        f"图谱里最相关的实体：{top_entities}\n关联事实：\n{fact_lines}"
                    )

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
                await self._close_client(graphiti)

    async def _clear_user_group(self, user_id: str) -> int:
        graphiti = await self._build_client()
        deleted_count = 0
        try:
            group_id = self._group_id(user_id)
            while True:
                episodes = await EpisodicNode.get_by_group_ids(
                    graphiti.driver, [group_id], limit=100
                )
                if not episodes:
                    break
                for episode in episodes:
                    await graphiti.remove_episode(episode.uuid)
                    deleted_count += 1
            logger.info(
                "Cleared graph group data user=%s group_id=%s deleted_episodes=%s",
                user_id,
                group_id,
                deleted_count,
            )
            return deleted_count
        finally:
            await self._close_client(graphiti)

    async def _clear_all_data(self, preserve_group_ids: list[str] | None = None) -> int:
        driver = AsyncGraphDatabase.driver(
            self.settings.graphiti.uri,
            auth=(self.settings.graphiti.user, self.settings.graphiti.password),
        )
        protected_group_ids = sorted(set(preserve_group_ids or []))
        try:
            async with driver.session() as session:
                if protected_group_ids:
                    count_result = await session.run(
                        """
                        MATCH (n)
                        WHERE coalesce(n.group_id, '') NOT IN $protected_group_ids
                        RETURN count(n) AS total
                        """,
                        protected_group_ids=protected_group_ids,
                    )
                    record = await count_result.single()
                    deleted_count = int(record["total"]) if record else 0
                    rel_result = await session.run(
                        """
                        MATCH (a)-[r]->(b)
                        WHERE coalesce(r.group_id, '') NOT IN $protected_group_ids
                          AND NOT (
                            coalesce(a.group_id, '') IN $protected_group_ids
                            AND coalesce(b.group_id, '') IN $protected_group_ids
                          )
                        DELETE r
                        """,
                        protected_group_ids=protected_group_ids,
                    )
                    await rel_result.consume()
                    node_result = await session.run(
                        """
                        MATCH (n)
                        WHERE coalesce(n.group_id, '') NOT IN $protected_group_ids
                        DETACH DELETE n
                        """,
                        protected_group_ids=protected_group_ids,
                    )
                    await node_result.consume()
                    logger.info(
                        "Cleared Neo4j database except protected groups nodes=%s protected_groups=%s",
                        deleted_count,
                        protected_group_ids,
                    )
                    return deleted_count

                count_result = await session.run("MATCH (n) RETURN count(n) AS total")
                record = await count_result.single()
                deleted_count = int(record["total"]) if record else 0
                result = await session.run("MATCH (n) DETACH DELETE n")
                await result.consume()
            logger.info("Cleared configured Neo4j database nodes=%s", deleted_count)
            return deleted_count
        finally:
            await driver.close()

    async def _delete_episode(self, episode_uuid: str) -> bool:
        graphiti = await self._build_client()
        try:
            await graphiti.remove_episode(episode_uuid)
            logger.info("Deleted graph episode episode_uuid=%s", episode_uuid)
            return True
        finally:
            await self._close_client(graphiti)

    async def _build_client(self, trace_id: str | None = None) -> Graphiti:
        llm_client = build_graphiti_llm_client(self.settings)
        embedder = DashScopeCompatibleEmbedder(
            config=OpenAIEmbedderConfig(
                api_key=self.settings.openai.embedding_api_key or self.settings.openai.api_key,
                base_url=self.settings.openai.embedding_base_url
                or self.settings.openai.base_url,
                embedding_model=self.settings.openai.embedding_model,
            )
        )
        graphiti = Graphiti(
            uri=self.settings.graphiti.uri,
            user=self.settings.graphiti.user,
            password=self.settings.graphiti.password,
            llm_client=llm_client,
            embedder=embedder,
        )
        if not self._indices_ready:
            with trace_span(
                logger,
                "graphiti.build_indices",
                trace_id=trace_id,
                graphiti_uri=self.settings.graphiti.uri,
            ):
                await asyncio.wait_for(
                    graphiti.build_indices_and_constraints(), timeout=45
                )
            self._indices_ready = True
            log_event(
                logger,
                logging.INFO,
                "graphiti.indices.ready",
                trace_id=trace_id,
                graphiti_uri=self.settings.graphiti.uri,
            )
        return graphiti

    @staticmethod
    async def _close_client(graphiti: Graphiti) -> None:
        """Close Graphiti plus its OpenAI-compatible async HTTP clients.

        graphiti-core currently closes only the graph driver. Its LLM/embedder
        clients otherwise reach garbage collection after ``asyncio.run`` has
        closed the loop, producing ``Event loop is closed`` warnings.
        """
        for component in (
            getattr(graphiti, "llm_client", None),
            getattr(graphiti, "embedder", None),
            getattr(graphiti, "cross_encoder", None),
        ):
            client = getattr(component, "client", None)
            close = getattr(client, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.debug("Could not close Graphiti HTTP client", exc_info=True)
        await graphiti.close()

    def _group_id(self, user_id: str) -> str:
        raw = f"{self.settings.graphiti.group_prefix}-{user_id}"
        normalized = []
        for char in raw:
            if char.isalnum() or char in {"-", "_"}:
                normalized.append(char)
            else:
                normalized.append("_")
        return "".join(normalized)

    def group_id_for_user(self, user_id: str) -> str:
        return self._group_id(user_id)

    def get_topology(self, user_id: str | None = None) -> dict:
        """Query Neo4j for all entity nodes and edges, return force-graph format."""
        if not self._neo4j_reachable():
            return {"nodes": [], "links": [], "error": "Neo4j is not reachable."}
        try:
            return asyncio.run(self._get_topology(user_id))
        except Exception as exc:
            logger.warning("get_topology failed: %s", exc)
            return {"nodes": [], "links": [], "error": str(exc)[:200]}

    async def _get_topology(self, user_id: str | None = None) -> dict:
        driver = AsyncGraphDatabase.driver(
            self.settings.graphiti.uri,
            auth=(self.settings.graphiti.user, self.settings.graphiti.password),
        )
        # Scope to a single user's group when a user_id is given, otherwise
        # return the whole graph (admin/topology view). Graphiti stamps every
        # node and edge with the same group_id used at ingest time.
        group_id = self._group_id(user_id) if user_id else None
        try:
            async with driver.session() as session:
                if group_id is not None:
                    node_query = (
                        "MATCH (n:Entity) WHERE n.group_id = $group_id "
                        "RETURN n.uuid AS id, n.name AS name, labels(n) AS labels, n.summary AS summary"
                    )
                    result = await session.run(node_query, group_id=group_id)
                else:
                    node_query = "MATCH (n:Entity) RETURN n.uuid AS id, n.name AS name, labels(n) AS labels, n.summary AS summary"
                    result = await session.run(node_query)
                records = await result.data()
                nodes = [
                    {
                        "id": r["id"],
                        "name": r["name"] or "",
                        "labels": [
                            label for label in (r["labels"] or []) if label != "Entity"
                        ],
                        "summary": r.get("summary") or "",
                    }
                    for r in records
                    if r.get("id")
                ]

                if group_id is not None:
                    edge_query = (
                        "MATCH (a:Entity)-[r]->(b:Entity) "
                        "WHERE a.group_id = $group_id AND b.group_id = $group_id "
                        "RETURN a.uuid AS source, b.uuid AS target, "
                        "r.fact AS fact, r.uuid AS uuid"
                    )
                    result = await session.run(edge_query, group_id=group_id)
                else:
                    edge_query = (
                        "MATCH (a:Entity)-[r]->(b:Entity) "
                        "RETURN a.uuid AS source, b.uuid AS target, "
                        "r.fact AS fact, r.uuid AS uuid"
                    )
                    result = await session.run(edge_query)
                records = await result.data()
                links = [
                    {
                        "source": r["source"],
                        "target": r["target"],
                        "fact": r.get("fact") or "",
                        "uuid": r.get("uuid") or "",
                    }
                    for r in records
                    if r.get("source") and r.get("target")
                ]

            return {"nodes": nodes, "links": links}
        finally:
            await driver.close()


