from __future__ import annotations

import logging
from typing import Any

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
            )
        except Exception as exc:
            logger.exception("GraphSearchTool failed for question=%s", question[:80])
            return ToolResult(ok=False, error=str(exc)[:500])
