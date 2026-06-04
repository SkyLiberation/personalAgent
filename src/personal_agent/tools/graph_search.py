from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool

from ..core.evidence import EvidenceItem
from ..graphiti.store import GraphitiStore
from .base import governance_extras, tool_failure, tool_response, tool_success

logger = logging.getLogger(__name__)


def build_graph_search_tool(graph_store: GraphitiStore) -> BaseTool:
    @tool(
        "graph_search",
        description="在个人知识图谱中搜索与问题相关的实体、关系和笔记，返回结构化检索结果。只读本地长期知识，不产生写入副作用。",
        response_format="content_and_artifact",
        extras=governance_extras(
            risk_level="low",
            side_effects=("read_local",),
            permission_scope="memory:read",
        ),
    )
    def graph_search(question: str, user_id: str = "default"):
        if not graph_store.configured():
            return tool_response(tool_failure("图谱未配置或未启用。"))
        try:
            result = graph_store.ask(question, user_id)
            if not result.enabled:
                return tool_response(tool_failure(result.error or "图谱检索不可用。"))
            evidence: list[EvidenceItem] = []
            seen_facts: set[str] = set()
            for fact_ref in result.fact_refs:
                fact = fact_ref.fact.strip()
                if fact and fact not in seen_facts:
                    seen_facts.add(fact)
                    evidence.append(EvidenceItem(
                        source_type="graph_fact", source_id=fact_ref.edge_uuid, fact=fact,
                        metadata={"source_node_name": fact_ref.source_node_name, "target_node_name": fact_ref.target_node_name, "episode_uuids": fact_ref.episode_uuids},
                    ))
            for edge_ref in result.edge_refs:
                fact = edge_ref.fact.strip()
                if fact and fact not in seen_facts:
                    seen_facts.add(fact)
                    evidence.append(EvidenceItem(
                        source_type="graph_fact", source_id=edge_ref.uuid, fact=fact,
                        metadata={"source_node_name": edge_ref.source_node_name, "target_node_name": edge_ref.target_node_name, "episodes": edge_ref.episodes},
                    ))
            for hit in result.citation_hits:
                evidence.append(EvidenceItem(
                    source_type="graph_fact", source_id=hit.episode_uuid, fact=hit.relation_fact, score=float(hit.score),
                    metadata={"episode_uuid": hit.episode_uuid, "endpoint_names": hit.endpoint_names, "matched_terms": hit.matched_terms, "entity_overlap_count": hit.entity_overlap_count},
                ))
            return tool_response(tool_success({
                "answer": result.answer,
                "entity_names": result.entity_names,
                "relation_facts": result.relation_facts,
                "related_episode_uuids": result.related_episode_uuids,
                "node_refs": [r.model_dump(mode="json") for r in result.node_refs],
                "edge_refs": [r.model_dump(mode="json") for r in result.edge_refs],
                "fact_refs": [r.model_dump(mode="json") for r in result.fact_refs],
            }, evidence))
        except Exception as exc:
            logger.exception("graph_search failed for question=%s", question[:80])
            return tool_response(tool_failure(str(exc)[:500]))

    return graph_search
