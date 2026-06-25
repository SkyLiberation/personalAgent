from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.kernel.evidence import EvidenceItem
from personal_agent.memory.graphiti.store import GraphitiStore
from personal_agent.tools.base import ToolError, governance_extras, tool_response, tool_success

logger = logging.getLogger(__name__)


class GraphSearchArgs(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        description="要在个人知识图谱中检索的问题、实体、关系或候选对象描述。",
    )
    user_id: str = Field(default="default", description="个人知识库归属用户 ID。")


def build_graph_search_tool(graph_store: GraphitiStore) -> BaseTool:
    @tool(
        "graph_search",
        description=(
            "在个人长期知识图谱中搜索相关实体、关系、事实和笔记。"
            "只读本地知识，不访问外网、不写入数据；适合问答、候选定位和删除前目标解析。"
            "返回 artifact.data.answer/entity_names/relation_facts/node_refs/edge_refs/fact_refs，并附带 evidence。"
        ),
        args_schema=GraphSearchArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="public_agent",
            risk_level="low",
            side_effects=("read_local",),
            permission_scope="memory:read",
            timeout_seconds=15.0,
            max_retries=0,
            rate_limit_per_minute=60,
        ),
    )
    def graph_search(question: str, user_id: str = "default"):
        if not graph_store.configured():
            raise ToolError("图谱未配置或未启用。", kind="permission")
        result = graph_store.ask(question, user_id)
        if not result.enabled:
            raise ToolError(result.error or "图谱检索不可用。", kind="permission")
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

    return graph_search
