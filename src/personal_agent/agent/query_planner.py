"""Query planner: produces a QueryUnderstanding + RetrievalPlan from LLM.

Uses the LangExtract-compatible structured-output model by default. This keeps
planner JSON parsing stable without changing the other small-model paths
(router, task planner, replanner).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import timedelta

from openai import OpenAI

from ..core.config import Settings
from ..core.models import local_now
from ..core.query_understanding import QueryUnderstanding, RetrievalFilters, RetrievalPlan

logger = logging.getLogger(__name__)

_PLANNER_SYSTEM = """\
You are a retrieval planner for a personal knowledge management system.
Given a user question (and optional conversation context), produce a JSON object with these fields:

- needs_freshness (bool): true if the question asks about latest/current/recent/today information
- needs_personal_memory (bool): true if the question references personal notes, prior knowledge, or things the user previously captured
- needs_graph_reasoning (bool): true if the question requires multi-hop entity relationship reasoning (e.g. "how does A relate to B", "what connects X and Y")
- query_rewrite (string): rewrite the question into a concise, keyword-rich retrieval query. Remove filler words, resolve pronouns from context, expand abbreviations. If the question is already retrieval-friendly, return it unchanged.
- sub_queries (string[]): if the question is compound or multi-hop, decompose into 2-3 independent sub-queries. Otherwise empty array.
- filters (object): structured metadata filters. Use only when the user explicitly asks for a time/source/tag/file constraint.
  - source_types: array of source types, e.g. ["link"], ["file"], ["text"], ["note"], ["pdf"]
  - source_ref_contains: filename, URL/domain, or source reference substring
  - tags: tag names
  - created_after / created_before: ISO datetime bounds when the user asks for today/yesterday/last week/recent saved notes
  - metadata_contains: author/title/file metadata substring
  - parent_note_id: note id only when explicitly provided
- answer_policy (string): one of "must_cite", "allow_web", "refuse_if_insufficient"
  - "must_cite": default, answer only from personal knowledge
  - "allow_web": when freshness is needed or personal KB is unlikely to have the answer
  - "refuse_if_insufficient": when the user explicitly asks about their own data and nothing else

Respond ONLY with valid JSON, no markdown fences."""

_PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "needs_freshness": {"type": "boolean"},
        "needs_personal_memory": {"type": "boolean"},
        "needs_graph_reasoning": {"type": "boolean"},
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
) -> tuple[QueryUnderstanding, RetrievalPlan]:
    """Run LLM-based query understanding and produce a retrieval plan.

    Falls back to a sensible default plan if the LLM call fails.
    """
    try:
        understanding = _call_planner_llm(question, conversation_context, settings)
    except Exception as exc:
        logger.warning("Query planner failed, using default plan: %s", exc)
        understanding = QueryUnderstanding(
            needs_personal_memory=True,
            query_rewrite=question,
            filters=_heuristic_filters(question),
        )

    plan = _derive_plan(question, understanding)
    return understanding, plan


def _call_planner_llm(
    question: str,
    conversation_context: str,
    settings: Settings,
) -> QueryUnderstanding:
    """Call the planner model with strict structured output."""
    api_key, base_url, model = _planner_llm_config(settings)
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=15.0,
    )

    user_content = f"Current datetime: {local_now().isoformat()}\nQuestion: {question}"
    if conversation_context:
        char_budget = getattr(
            getattr(settings, "short_term", None), "char_budget", 800
        )
        user_content += f"\n\nConversation context:\n{conversation_context[:char_budget]}"

    start = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=500,
        response_format=_planner_response_format(),
    )
    duration_ms = (time.monotonic() - start) * 1000
    logger.info("Query planner completed in %.0fms model=%s", duration_ms, model)

    raw = response.choices[0].message.content or "{}"
    if raw.rstrip()[-1:] not in ("}", "]"):
        raw = _repair_truncated_json(raw)
    data = json.loads(raw)
    return QueryUnderstanding(**data)


def _planner_llm_config(settings: Settings) -> tuple[str | None, str | None, str]:
    """Prefer LangExtract's qwen/json_schema endpoint for planner calls."""
    if settings.langextract.api_key:
        return (
            settings.langextract.api_key,
            settings.langextract.base_url,
            settings.langextract.model_id,
        )
    return (
        settings.openai.api_key,
        settings.openai.base_url,
        settings.openai.small_model or settings.openai.model,
    )


def _planner_response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "query_understanding",
            "strict": True,
            "schema": _PLANNER_SCHEMA,
        },
    }


def _repair_truncated_json(raw: str) -> str:
    """Attempt to repair JSON truncated by max_tokens."""
    stripped = raw.rstrip()
    open_braces = stripped.count("{") - stripped.count("}")
    open_brackets = stripped.count("[") - stripped.count("]")
    in_string = False
    escape_next = False
    for ch in stripped:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
    if in_string:
        stripped += '"'
    stripped += "]" * open_brackets
    stripped += "}" * open_braces
    return stripped


def _derive_plan(question: str, understanding: QueryUnderstanding) -> RetrievalPlan:
    """Derive a RetrievalPlan from QueryUnderstanding."""
    sources: list[str] = []

    if understanding.needs_personal_memory or understanding.needs_graph_reasoning:
        sources.append("graph")
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
