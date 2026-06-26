"""Query planner: produces a QueryUnderstanding + RetrievalPlan from LLM.

Uses a dedicated structured-output model (``settings.planner``) by default.
This keeps planner JSON parsing stable without changing the other small-model
paths (router, task planner, replanner), and is intentionally independent from
the capture-time LangExtract layer.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import TYPE_CHECKING

from personal_agent.kernel.config import Settings
from personal_agent.kernel.models import local_now
from personal_agent.kernel.prompts import get_prompt, render_prompt
from personal_agent.kernel.query_understanding import QueryUnderstanding, RetrievalFilters, RetrievalPlan
from personal_agent.infra.structured_parse import parse_structured

if TYPE_CHECKING:
    from personal_agent.infra.structured_model import StructuredModelClient

logger = logging.getLogger(__name__)

_PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "needs_freshness": {"type": "boolean"},
        "needs_personal_memory": {"type": "boolean"},
        "needs_graph_reasoning": {"type": "boolean"},
        "needs_episodic_context": {"type": "boolean"},
        "query_rewrite": {"type": "string"},
        "sub_queries": {"type": "array", "items": {"type": "string"}},
        "filters": {
            "type": "object",
            "properties": {
                "source_types": {"type": "array", "items": {"type": "string"}},
                "source_ref_contains": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "created_after": {"type": "string"},
                "created_before": {"type": "string"},
                "metadata_contains": {"type": "string"},
                "parent_note_id": {"type": "string"},
            },
            "required": [
                "source_types",
                "source_ref_contains",
                "tags",
                "created_after",
                "created_before",
                "metadata_contains",
                "parent_note_id",
            ],
            "additionalProperties": False,
        },
        "answer_policy": {
            "type": "string",
            "enum": ["must_cite", "allow_web", "refuse_if_insufficient"],
        },
    },
    "required": [
        "needs_freshness",
        "needs_personal_memory",
        "needs_graph_reasoning",
        "needs_episodic_context",
        "query_rewrite",
        "sub_queries",
        "filters",
        "answer_policy",
    ],
    "additionalProperties": False,
}


def plan_retrieval(
    question: str,
    conversation_context: str,
    settings: Settings,
    model_client: "StructuredModelClient | None" = None,
) -> tuple[QueryUnderstanding, RetrievalPlan]:
    """Run LLM-based query understanding and produce a retrieval plan.

    Falls back to a sensible default plan if the LLM call fails.
    """
    try:
        understanding = _call_planner_llm(question, conversation_context, settings, model_client)
    except Exception as exc:
        logger.warning("Query planner failed, using default plan: %s", exc)
        understanding = QueryUnderstanding(
            needs_personal_memory=True,
            needs_episodic_context=_looks_like_episodic_query(question),
            query_rewrite=question,
            filters=_heuristic_filters(question),
        )

    plan = _derive_plan(question, understanding)
    return understanding, plan


def _call_planner_llm(
    question: str,
    conversation_context: str,
    settings: Settings,
    model_client: "StructuredModelClient | None",
) -> QueryUnderstanding:
    """Call the planner model with strict structured output via the model port."""
    if model_client is None:
        raise RuntimeError("Query planner requires a configured model client")

    conversation_context_block = ""
    if conversation_context:
        char_budget = getattr(
            getattr(settings, "short_term", None), "char_budget", 800
        )
        conversation_context_block = (
            f"\n\nConversation context:\n{conversation_context[:char_budget]}"
        )
    system_prompt = get_prompt("query_planner.system")
    user_content = render_prompt(
        "query_planner.user",
        current_datetime=local_now().isoformat(),
        question=question,
        conversation_context_block=conversation_context_block,
    )

    from personal_agent.infra.structured_model import StructuredModelRequest
    from pydantic import BaseModel

    response = model_client.generate(StructuredModelRequest(
        operation="query_planner",
        version=system_prompt.version,
        messages=[
            {"role": "system", "content": system_prompt.template},
            {"role": "user", "content": user_content},
        ],
        output_type=BaseModel,
        temperature=0.0,
        max_tokens=500,
        kind="text",
        response_format=_planner_response_format(),
        metadata={
            "component": "query_planner",
            "has_conversation_context": bool(conversation_context),
        },
    ))
    logger.info("Query planner completed in %.0fms model=%s", response.latency_ms, response.model)

    parsed = parse_structured(
        response.content or "{}",
        QueryUnderstanding,
        operation="query_planner",
        version=system_prompt.version,
        model_name=response.model,
        latency_ms=response.latency_ms,
    )
    if not parsed.ok:
        raise ValueError(f"query_planner structured parse failed: {parsed.error}")
    return parsed.value


def _planner_response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "query_understanding",
            "strict": True,
            "schema": _PLANNER_SCHEMA,
        },
    }



def _derive_plan(question: str, understanding: QueryUnderstanding) -> RetrievalPlan:
    """Derive a RetrievalPlan from QueryUnderstanding."""
    sources: list[str] = []

    if understanding.needs_personal_memory or understanding.needs_graph_reasoning:
        sources.append("graph")
        sources.append("local")

    if understanding.needs_episodic_context and "local" not in sources:
        sources.append("local")

    if understanding.needs_freshness or understanding.answer_policy == "allow_web":
        sources.append("web")

    if not sources:
        sources = ["graph", "local"]

    # Always keep local as a retrieval source — it's the universal fallback
    if "local" not in sources:
        sources.append("local")

    parallel = "graph" in sources and "local" in sources

    effective_query = understanding.query_rewrite or question

    return RetrievalPlan(
        sources=sources,  # type: ignore[arg-type]
        parallel=parallel,
        query=effective_query,
        sub_queries=understanding.sub_queries,
        filters=understanding.filters,
    )


def _looks_like_episodic_query(question: str) -> bool:
    markers = (
        "上次", "之前", "刚才", "当时", "历史", "做过", "做了什么", "改了什么",
        "为什么这么", "为什么当时", "继续", "进展", "做到哪", "失败在哪里",
        "未完成", "遗留", "run", "workflow",
    )
    lowered = question.lower()
    return any(marker in question or marker in lowered for marker in markers)


def _heuristic_filters(question: str) -> RetrievalFilters:
    """Cheap fallback extraction for common personal-KB filter phrases."""
    lowered = question.lower()
    now = local_now()
    filters = RetrievalFilters()

    if any(token in question for token in ("链接", "网页", "网址", "URL")) or "url" in lowered:
        filters.source_types.append("link")
    elif any(token in question for token in ("文件", "上传", "PDF", "pdf")):
        filters.source_types.append("file")
    elif any(token in question for token in ("笔记", "手记", "记录")):
        filters.source_types.append("text")

    url_match = re.search(r"https?://[^\s，。！？]+", question)
    if url_match:
        filters.source_ref_contains = url_match.group(0).rstrip(".,;")

    file_match = re.search(r"[\w.-]+\.(?:pdf|md|txt|docx|xlsx|csv)", question, re.I)
    if file_match:
        filters.source_ref_contains = file_match.group(0).strip()
        if "file" not in filters.source_types:
            filters.source_types.append("file")

    if "今天" in question:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        filters.created_after = start.isoformat()
        filters.created_before = now.isoformat()
    elif "昨天" in question:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        filters.created_after = (today - timedelta(days=1)).isoformat()
        filters.created_before = today.isoformat()
    elif "上周" in question or "最近一周" in question:
        filters.created_after = (now - timedelta(days=7)).isoformat()
        filters.created_before = now.isoformat()
    elif "最近" in question:
        filters.created_after = (now - timedelta(days=30)).isoformat()
        filters.created_before = now.isoformat()

    return filters
