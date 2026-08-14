"""Research request classification and deterministic query planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from personal_agent.kernel.contracts.research import (
    ResearchPolicy,
    ResearchQuery,
)


@dataclass(frozen=True)
class ResearchRequestUnderstanding:
    topic: str
    instructions: str
    max_items: int
    window_start: datetime
    window_end: datetime
    policy: ResearchPolicy = field(default_factory=ResearchPolicy)
    queries: list[ResearchQuery] = field(default_factory=list)


class ResearchPolicyResolver:
    _DEFAULTS = {
        "technical_product_update": {
            "source_preference": ["official", "docs", "github", "paper", "media"],
            "evidence_requirement": "official_or_multi_source",
            "ranking_objective": "confidence_first",
            "verification_strictness": "medium_high",
        },
        "academic_research": {
            "source_preference": ["paper", "github", "official", "docs", "media"],
            "evidence_requirement": "paper_or_primary_source",
            "ranking_objective": "confidence_first",
            "verification_strictness": "high",
        },
        "company_financials": {
            "source_preference": ["filing", "investor_relations", "transcript", "media"],
            "evidence_requirement": "primary_financial_source_required",
            "ranking_objective": "confidence_first",
            "verification_strictness": "high",
        },
        "general_news": {
            "source_preference": ["official", "paper", "media"],
            "evidence_requirement": "official_or_multi_source",
            "ranking_objective": "confidence_first",
            "verification_strictness": "medium_high",
        },
    }

    @classmethod
    def resolve(
        cls,
        raw_policy: object,
        *,
        topic: str,
        instructions: str,
    ) -> ResearchPolicy:
        raw = raw_policy if isinstance(raw_policy, dict) else {}
        inferred_type = str(raw.get("research_type") or "").strip()
        heuristic_type = cls._infer_type(topic, instructions)
        if inferred_type not in cls._DEFAULTS:
            inferred_type = heuristic_type
        elif inferred_type == "general_news" and heuristic_type != "general_news":
            inferred_type = heuristic_type
        data = {"research_type": inferred_type, **cls._DEFAULTS[inferred_type]}
        if not raw.get("ranking_objective") and any(
            token in f"{topic} {instructions}".lower()
            for token in ("personal", "个人", "知识库", "相关")
        ):
            data["ranking_objective"] = "personal_relevance_first"
        for key in (
            "evidence_requirement",
            "ranking_objective",
            "verification_strictness",
        ):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                data[key] = value.strip()
        preferences = raw.get("source_preference")
        if isinstance(preferences, list):
            data["source_preference"] = [
                str(item).strip() for item in preferences if str(item).strip()
            ] or data["source_preference"]
        try:
            return ResearchPolicy.model_validate(cls._enforce_type_requirements(data))
        except Exception:
            return ResearchPolicy.model_validate(
                {"research_type": inferred_type, **cls._DEFAULTS[inferred_type]}
            )

    @classmethod
    def _enforce_type_requirements(cls, data: dict[str, object]) -> dict[str, object]:
        research_type = str(data.get("research_type") or "general_news")
        if research_type == "company_financials":
            data["evidence_requirement"] = "primary_financial_source_required"
        elif research_type == "academic_research":
            data["evidence_requirement"] = "paper_or_primary_source"
        return data

    @classmethod
    def _infer_type(cls, topic: str, instructions: str) -> str:
        text = f"{topic} {instructions}".lower()
        if any(
            token in text
            for token in ("earnings", "10-k", "10-q", "sec", "财报", "营收", "财务")
        ):
            return "company_financials"
        if any(
            token in text
            for token in ("paper", "arxiv", "论文", "学术", "research paper")
        ):
            return "academic_research"
        if any(
            token in text
            for token in ("sdk", "api", "github", "release", "runtime", "开源", "发布")
        ):
            return "technical_product_update"
        return "general_news"


class QueryPlanner:
    _FALLBACKS = {
        "technical_product_update": [
            ("latest", "{topic} latest news", 0.96),
            ("official", "{topic} official announcement", 0.9),
            ("docs", "{topic} documentation release notes", 0.86),
            ("repo", "{topic} GitHub release", 0.82),
            ("technical", "{topic} technical report", 0.72),
        ],
        "academic_research": [
            ("paper", "{topic} paper arXiv", 0.95),
            ("repo", "{topic} GitHub code", 0.7),
            ("media", "{topic} latest research news", 0.45),
        ],
        "company_financials": [
            ("financial_filing", "{topic} SEC filing 10-Q 10-K", 0.95),
            ("transcript", "{topic} earnings call transcript", 0.82),
            ("official", "{topic} investor relations earnings release", 0.8),
            ("media", "{topic} financial results news", 0.45),
        ],
        "general_news": [
            ("latest", "{topic} latest news", 0.8),
            ("official", "{topic} official announcement", 0.7),
            ("media", "{topic} independent coverage", 0.45),
        ],
    }

    @classmethod
    def build(
        cls,
        *,
        topic: str,
        policy: ResearchPolicy,
        raw_queries: object,
        seed_queries: list[str],
        max_queries: int,
    ) -> list[ResearchQuery]:
        unique: dict[str, ResearchQuery] = {}
        for candidate in cls._parse_raw_queries(raw_queries):
            cls._add_query(unique, candidate, replace_with_higher_priority=True)
        for index, query in enumerate(seed_queries):
            cls._add_query(
                unique,
                ResearchQuery(
                    query=query,
                    intent="latest",
                    priority=max(0.2, 0.6 - index * 0.05),
                ),
                replace_with_higher_priority=False,
            )
        fallbacks = cls._FALLBACKS.get(
            policy.research_type,
            cls._FALLBACKS["general_news"],
        )
        for intent, template, priority in fallbacks:
            cls._add_query(
                unique,
                ResearchQuery(
                    query=template.format(topic=topic),
                    intent=intent,
                    priority=priority,
                ),
                replace_with_higher_priority=False,
            )
        return sorted(
            unique.values(),
            key=lambda item: item.priority,
            reverse=True,
        )[:max_queries]

    @staticmethod
    def _add_query(
        unique: dict[str, ResearchQuery],
        candidate: ResearchQuery,
        *,
        replace_with_higher_priority: bool,
    ) -> None:
        query = " ".join(candidate.query.split())
        if not query:
            return
        key = query.lower()
        current = unique.get(key)
        normalized = candidate.model_copy(update={"query": query})
        if current is None or (
            replace_with_higher_priority and normalized.priority > current.priority
        ):
            unique[key] = normalized

    @staticmethod
    def _parse_raw_queries(raw_queries: object) -> list[ResearchQuery]:
        if not isinstance(raw_queries, list):
            return []
        parsed: list[ResearchQuery] = []
        for item in raw_queries:
            if isinstance(item, str):
                query = item.strip()
                if query:
                    parsed.append(
                        ResearchQuery(
                            query=query,
                            intent=query_intent(query),
                            priority=0.7,
                        )
                    )
            elif isinstance(item, dict):
                query = str(item.get("query") or "").strip()
                if not query:
                    continue
                try:
                    parsed.append(
                        ResearchQuery.model_validate(
                            {
                                "query": query,
                                "intent": item.get("intent") or query_intent(query),
                                "priority": item.get("priority", 0.7),
                            }
                        )
                    )
                except Exception:
                    parsed.append(
                        ResearchQuery(
                            query=query,
                            intent=query_intent(query),
                            priority=0.7,
                        )
                    )
        return parsed


def query_intent(query: str) -> str:
    lowered = query.lower()
    if any(token in lowered for token in ("sec", "10-k", "10-q", "filing")):
        return "financial_filing"
    if "transcript" in lowered:
        return "transcript"
    if any(token in lowered for token in ("github", "repo", "open source")):
        return "repo"
    if any(token in lowered for token in ("docs", "documentation", "release notes")):
        return "docs"
    if any(token in lowered for token in ("paper", "arxiv", "technical report")):
        return "paper"
    if "official" in lowered:
        return "official"
    if any(token in lowered for token in ("news", "coverage", "report")):
        return "media"
    return "latest"


__all__ = [
    "QueryPlanner",
    "ResearchPolicyResolver",
    "ResearchRequestUnderstanding",
    "query_intent",
]
