from __future__ import annotations

import logging
from typing import Any

from ..core.evidence import EvidenceItem
from ..graphiti.store import GraphitiStore
from .base import BaseTool, ToolResult, ToolSpec

logger = logging.getLogger(__name__)


class GraphSearchTool(BaseTool):
    def __init__(self, graph_store: GraphitiStore) -> None:
        self._graph_store = graph_store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="graph_search",
            description="在个人知识图谱中搜索与问题相关的实体、关系和笔记，返回结构化的图谱检索结果。",
            input_schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "要查询的问题"},
                    "user_id": {"type": "string", "description": "用户标识，默认 'default'"},
                },
                "required": ["question"],
            },
            risk_level="low",
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        question = kwargs.get("question")
        user_id = kwargs.get("user_id", "default")
        if not question or not isinstance(question, str):
            return ToolResult(ok=False, error="缺少有效的 question 参数。")

        if not self._graph_store.configured():
            return ToolResult(ok=False, error="图谱未配置或未启用。")

        try:
            result = self._graph_store.ask(question, user_id)
            if not result.enabled:
                return ToolResult(ok=False, error=result.error or "图谱检索不可用。")
            # Build unified evidence from graph refs
            evidence: list[EvidenceItem] = []
            seen_facts: set[str] = set()
            for fact_ref in result.fact_refs:
                fact = fact_ref.fact.strip()
                if not fact or fact in seen_facts:
                    continue
                seen_facts.add(fact)
                evidence.append(EvidenceItem(
                    source_type="graph_fact",
                    source_id=fact_ref.edge_uuid,
                    fact=fact,
                    metadata={
                        "source_node_name": fact_ref.source_node_name,
                        "target_node_name": fact_ref.target_node_name,
                        "episode_uuids": fact_ref.episode_uuids,
                    },
                ))
            for edge_ref in result.edge_refs:
                fact = edge_ref.fact.strip()
                if not fact or fact in seen_facts:
                    continue
                seen_facts.add(fact)
                evidence.append(EvidenceItem(
                    source_type="graph_fact",
                    source_id=edge_ref.uuid,
                    fact=fact,
                    metadata={
                        "source_node_name": edge_ref.source_node_name,
                        "target_node_name": edge_ref.target_node_name,
                        "episodes": edge_ref.episodes,
                    },
                ))
            for hit in result.citation_hits:
                evidence.append(EvidenceItem(
                    source_type="graph_fact",
                    source_id=hit.episode_uuid,
                    fact=hit.relation_fact,
                    score=float(hit.score),
                    metadata={
                        "episode_uuid": hit.episode_uuid,
                        "endpoint_names": hit.endpoint_names,
                        "matched_terms": hit.matched_terms,
                        "entity_overlap_count": hit.entity_overlap_count,
                    },
                ))

            return ToolResult(
                ok=True,
                data={
                    "answer": result.answer,
                    "entity_names": result.entity_names,
                    "relation_facts": result.relation_facts,
                    "related_episode_uuids": result.related_episode_uuids,
                    "node_refs": [r.model_dump(mode="json") for r in result.node_refs],
                    "edge_refs": [r.model_dump(mode="json") for r in result.edge_refs],
                    "fact_refs": [r.model_dump(mode="json") for r in result.fact_refs],
                },
                evidence=evidence,
            )
        except Exception as exc:
            logger.exception("GraphSearchTool failed for question=%s", question[:80])
            return ToolResult(ok=False, error=str(exc)[:500])
